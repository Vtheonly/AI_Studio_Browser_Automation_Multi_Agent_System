"""
login.py — Interactive Google login helper.

This is the FIRST thing you should run after downloading the project.

What it does:
  1. Launches a HEADED Chromium window (you can see it on your screen).
  2. Navigates to https://aistudio.google.com.
  3. You log into Google manually (email + password + 2FA).
  4. After you reach the AI Studio chat UI, the session is saved to
     session/storage_state.json.
  5. Subsequent runs of any PoC (or web_ui.py) will reuse that session
     headlessly — no more logins needed, until Google expires it.

Usage:
    python login.py                # login to AI Studio (for PoC #1 and #2)
    python login.py --target gemini  # login to gemini.google.com (for PoC #3, optional)
    python login.py --force        # re-login even if a saved session exists

After login succeeds, run:
    python web_ui.py --port 8000   # → http://localhost:8000
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make sibling modules importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_session import (
    SessionManager,
    STORAGE_STATE_PATH,
    SESSION_META_PATH,
    AISTUDIO_HOME,
    GEMINI_HOME,
)
from playwright.async_api import async_playwright


async def do_login(target: str, force: bool, timeout_sec: int) -> int:
    """Open a headed browser and wait for the user to log in.

    Returns 0 on success, 1 on failure.
    """
    if not force and STORAGE_STATE_PATH.exists():
        print(f"\n[login] A saved session already exists: {STORAGE_STATE_PATH}")
        # Show meta
        if SESSION_META_PATH.exists():
            print(f"[login] {SESSION_META_PATH.read_text()}")
        print("[login] Re-run with --force to discard it and log in again.")
        return 0

    target_url = AISTUDIO_HOME if target == "aistudio" else GEMINI_HOME
    target_name = "Google AI Studio" if target == "aistudio" else "Google Gemini"

    print("\n" + "=" * 70)
    print(f"  Logging into {target_name}")
    print(f"  Target URL: {target_url}")
    print("=" * 70)
    print("A browser window will open. Please complete the Google login flow.")
    print("Once you reach the chat UI, the session will be saved automatically.")
    print()

    # We don't use SessionManager here because we want a one-shot flow with
    # its own browser lifecycle, not the shared singleton.
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,  # MUST be headed for interactive login
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )

    # If we already have a saved state (e.g. logging into Gemini after AI Studio),
    # load it so we don't have to log in twice.
    if STORAGE_STATE_PATH.exists() and not force:
        print(f"[login] Loading existing session from {STORAGE_STATE_PATH}")
        await context.close()
        context = await browser.new_context(
            storage_state=str(STORAGE_STATE_PATH),
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )

    page = await context.new_page()
    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

    # Poll for login completion.
    logout_markers = ("accounts.google.com", "/signin", "/v3/signin")
    import time
    start = time.time()
    last_url = ""
    logged_in = False

    print(f"[login] Waiting up to {timeout_sec}s for login to complete...")
    print(f"[login] Current URL: {page.url[:100]}")

    while time.time() - start < timeout_sec:
        url = page.url
        if url != last_url:
            print(f"[login] Current URL: {url[:100]}")
            last_url = url
        # For aistudio: we look for the chat UI (not on accounts.google.com)
        # For gemini: same — once we're on /app without accounts.google.com, we're in.
        if not any(m in url for m in logout_markers):
            if target == "aistudio" and "aistudio.google.com" in url:
                logged_in = True
                break
            elif target == "gemini" and "gemini.google.com" in url:
                logged_in = True
                break
        await asyncio.sleep(1)

    if not logged_in:
        print("\n[login] Timed out waiting for login. Try again.")
        await browser.close()
        await pw.stop()
        return 1

    # Give the page a moment to settle.
    print(f"[login] Login detected! Waiting for page to settle...")
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        await asyncio.sleep(3)

    # Save the storage state.
    STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(STORAGE_STATE_PATH))

    import json
    meta = {
        "saved_at": int(time.time()),
        "saved_at_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "target": target,
        "target_url": target_url,
        "ua": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "note": "Manual login persisted. Reuse across runs.",
    }
    SESSION_META_PATH.write_text(json.dumps(meta, indent=2))

    print("\n" + "=" * 70)
    print(f"  LOGIN SAVED: {STORAGE_STATE_PATH}")
    print(f"  You can now run any PoC headlessly.")
    print("=" * 70)
    print("\nNext steps:")
    print("  python web_ui.py --port 8000   # → http://localhost:8000")
    print("  python test_all.py             # run the E2E test suite")
    print()

    await browser.close()
    await pw.stop()
    return 0


def main():
    parser = argparse.ArgumentParser(description="Manual Google login helper.")
    parser.add_argument(
        "--target", choices=["aistudio", "gemini"], default="aistudio",
        help="Which site to log into. Default: aistudio (for PoC #1 and #2). "
             "Use 'gemini' to also authenticate gemini.google.com (optional, "
             "PoC #3 works anonymously with the Flash model).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Discard any existing saved session and log in fresh.",
    )
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="Maximum seconds to wait for login (default 600 = 10 minutes).",
    )
    args = parser.parse_args()

    try:
        rc = asyncio.run(do_login(args.target, args.force, args.timeout))
    except KeyboardInterrupt:
        print("\n[login] Interrupted.")
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
