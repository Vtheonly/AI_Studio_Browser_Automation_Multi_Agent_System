"""
cdp_gemini_agent.py — PoC #3: Drive https://gemini.google.com via CDP.

Unlike PoC #1 (which uses Playwright's own Chromium), this pattern launches
a SEPARATE Chrome instance with --remote-debugging-port and connects to it
via the Chrome DevTools Protocol. This is closer to the "Gemini Browser
Agent" pattern from the article: an external agent controls the user's
real logged-in Chrome.

Architecture:
    ┌─────────────────────────────┐
    │  Chrome (subprocess)        │
    │  --remote-debugging-port    │
    │  --user-data-dir=./chrome/  │   ← persistent profile
    │  https://gemini.google.com  │
    └──────────┬──────────────────┘
               │ CDP ws://localhost:9222
               ▼
    ┌─────────────────────────────┐
    │  cdp_gemini_agent.py        │
    │  connect_over_cdp()         │
    │  - finds prompt input       │
    │  - types + presses Enter    │
    │  - scrapes response         │
    └─────────────────────────────┘

Run as a server:
    python cdp_gemini_agent.py --port 8003

Or one-shot:
    python cdp_gemini_agent.py --prompt "hello"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

PROJECT_ROOT = Path("/home/z/my-project")
CHROME_PROFILE_DIR = PROJECT_ROOT / "session" / "chrome_profile"
CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

CDP_PORT = 9222
GEMINI_URL = "https://gemini.google.com/app"

# Try to find a Chrome/Chromium binary.
CHROME_CANDIDATES = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    # Playwright bundled Chromium (layout varies by version)
    os.path.expanduser("~/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome"),
    os.path.expanduser("~/.cache/ms-playwright/chromium-1228/chrome-linux/chrome"),
    os.path.expanduser("~/.cache/ms-playwright/chromium-1200/chrome-linux64/chrome"),
    os.path.expanduser("~/.cache/ms-playwright/chromium-1200/chrome-linux/chrome"),
    os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-1228/chrome-linux/headless_shell"),
    os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-1228/chrome-linux64/headless_shell"),
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError(
        "No Chrome binary found. Install google-chrome or chromium.\n"
        f"Tried: {CHROME_CANDIDATES}"
    )


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


async def launch_chrome_with_cdp(headless: bool = True) -> subprocess.Popen:
    """Launch Chrome with remote debugging enabled. Returns the Popen handle."""
    chrome = find_chrome()
    if _port_in_use(CDP_PORT):
        print(f"[cdp] port {CDP_PORT} already in use; assuming Chrome is already running.")
        return None  # caller should not kill it

    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={CHROME_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=Translate",
        "--no-sandbox",
    ]
    if headless:
        args.append("--headless=new")
    args.append(GEMINI_URL)
    print(f"[cdp] launching: {' '.join(args[:3])} ... {GEMINI_URL}")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Wait for CDP endpoint to come up.
    for _ in range(30):
        if _port_in_use(CDP_PORT):
            return proc
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Chrome did not open CDP port {CDP_PORT} in time.")


# ─── gemini.google.com selectors ────────────────────────────────────────────
GEMINI_PROMPT_SELECTORS = [
    "rich-textarea div.ql-editor[contenteditable='true']",
    "div.ql-editor[contenteditable='true']",
    "textarea[aria-label*='Prompt']",
    ".ql-editor[contenteditable='true']",
]

GEMINI_SEND_BUTTON_SELECTORS = [
    "button[aria-label='Send message']",
    "button.send-button",
    "button[aria-label*='Send']",
]

GEMINI_RESPONSE_SELECTORS = [
    "message-content.model-response-text",
    "model-response message-content",
    ".response-container .model-response-text",
    ".model-response-text",
    "message-content:last-of-type",
]


async def _find_first(page: Page, selectors: list[str], timeout_ms: int = 8000):
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if await loc.is_visible(timeout=500):
                    return loc
            except Exception:
                continue
        await asyncio.sleep(0.3)
    return None


async def _wait_for_gemini_response(page: Page, max_wait_sec: int = 120) -> str:
    """Wait until gemini.google.com's latest model response stops growing.

    Selectors may match MULTIPLE model-response elements (one per turn). We
    always grab the LAST visible one to avoid stale responses from earlier
    turns in the same conversation.
    """
    start = time.time()
    last_text = ""
    stable_count = 0
    while time.time() - start < max_wait_sec:
        # Try each selector; pick the one with the most matches, then use .last
        best_text = ""
        for sel in GEMINI_RESPONSE_SELECTORS:
            loc = page.locator(sel)
            try:
                cnt = await loc.count()
                if cnt == 0:
                    continue
                last_loc = loc.nth(cnt - 1)
                if not await last_loc.is_visible(timeout=500):
                    continue
                txt = (await last_loc.inner_text(timeout=2000)).strip()
                if len(txt) > len(best_text):
                    best_text = txt
            except Exception:
                continue
        current = best_text
        if current and current == last_text:
            stable_count += 1
            if stable_count >= 2:
                return current
        else:
            stable_count = 0
            last_text = current
        await asyncio.sleep(0.8)
    return last_text


async def chat_with_gemini_via_cdp(prompt: str) -> dict:
    """Connect to Chrome via CDP and drive gemini.google.com."""
    t0 = time.time()
    debug_info: dict = {"steps": []}
    chrome_proc = None
    pw = None
    try:
        # 1. Ensure Chrome is up with CDP.
        chrome_proc = await launch_chrome_with_cdp(headless=True)
        debug_info["steps"].append("chrome launched with --remote-debugging-port")

        # 2. Connect via CDP.
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        debug_info["steps"].append(f"connected over CDP; contexts={len(browser.contexts)}")

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()

        # Always open a FRESH chat (no conversation ID in URL). This avoids
        # contaminating this request with the previous conversation's responses.
        page = await ctx.new_page()
        await page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
        # Gemini has long-polling/telemetry that prevents networkidle from ever
        # firing. Just sleep briefly instead.
        await asyncio.sleep(3.0)
        debug_info["steps"].append(f"page ready: {page.url}")

        # Bounce check: Gemini bounces unauthenticated users to accounts.google.com.
        if "accounts.google.com" in page.url:
            return {
                "response": None,
                "latency_ms": int((time.time() - t0) * 1000),
                "error": "not_authenticated: gemini.google.com bounced to Google sign-in. "
                         "Open the visible Chrome window and log in once.",
                "debug": debug_info,
            }

        # 3. Find prompt input.
        try:
            await page.wait_for_selector(
                ", ".join(GEMINI_PROMPT_SELECTORS), timeout=20000
            )
        except PWTimeout:
            return {
                "response": None,
                "latency_ms": int((time.time() - t0) * 1000),
                "error": "prompt_input_not_found (gemini UI changed?)",
                "debug": debug_info,
            }

        prompt_loc = await _find_first(page, GEMINI_PROMPT_SELECTORS, timeout_ms=3000)
        await prompt_loc.click()
        # Clear any leftover text in the input first.
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.keyboard.type(prompt, delay=10)
        debug_info["steps"].append("prompt typed")
        # The Send button only appears AFTER text has been entered. Wait briefly.
        await asyncio.sleep(0.5)

        # 4. Submit (Enter or Send button).
        send_loc = await _find_first(page, GEMINI_SEND_BUTTON_SELECTORS, timeout_ms=3000)
        if send_loc:
            await send_loc.click()
            debug_info["steps"].append("clicked Send")
        else:
            await page.keyboard.press("Enter")
            debug_info["steps"].append("pressed Enter (no Send button)")

        # 5. Wait briefly for the new turn to start rendering before scraping,
        # otherwise we might grab the previous model response.
        await asyncio.sleep(2.0)

        # 6. Scrape response. Count all model-response elements and grab the LAST one.
        response_text = await _wait_for_gemini_response(page, max_wait_sec=120)
        debug_info["steps"].append(f"response captured (len={len(response_text)})")
        return {
            "response": response_text or None,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": None if response_text else "empty_response",
            "debug": debug_info,
        }
    except Exception as e:
        return {
            "response": None,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": f"{type(e).__name__}: {e}",
            "debug": debug_info,
        }
    finally:
        if pw:
            try:
                await pw.stop()
            except Exception:
                pass
        # NOTE: we intentionally leave Chrome running so its session persists
        # across requests. The user can kill it manually if needed.


# ─── HTTP layer ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    prompt: str


class ChatResponse(BaseModel):
    response: Optional[str]
    latency_ms: int
    error: Optional[str] = None
    debug: dict = {}


app = FastAPI(title="CDPGeminiAgent")


@app.get("/health")
async def health():
    return {"ok": True, "service": "cdp_gemini_agent", "cdp_port": CDP_PORT}


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    return ChatResponse(**await chat_with_gemini_via_cdp(req.prompt))


async def login_gemini_headed(timeout_sec: int = 600) -> dict:
    """Launch a HEADED Chrome so the user can log into gemini.google.com.

    After login, the Chrome user-data-dir is saved at CHROME_PROFILE_DIR and
    reused by future headless CDP runs. This is optional — PoC #3 works
    anonymously with the Flash model, but logging in unlocks Gemini Pro /
    2.5 Pro and removes per-session limits.
    """
    chrome = find_chrome()
    # Kill any existing CDP Chrome first.
    if _port_in_use(CDP_PORT):
        try:
            import subprocess as _sp
            _sp.run(["pkill", "-f", f"remote-debugging-port={CDP_PORT}"],
                    check=False)
            await asyncio.sleep(1)
        except Exception:
            pass

    args = [
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={CHROME_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        GEMINI_URL,
    ]
    print(f"[cdp_login] launching HEADED chrome: {' '.join(args[:3])} ... {GEMINI_URL}")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for CDP endpoint to come up.
    for _ in range(30):
        if _port_in_use(CDP_PORT):
            break
        await asyncio.sleep(0.5)

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        print(f"[cdp_login] waiting up to {timeout_sec}s for login...")
        logout_markers = ("accounts.google.com", "/signin", "/v3/signin")
        import time
        start = time.time()
        last_url = ""
        logged_in = False
        while time.time() - start < timeout_sec:
            url = page.url
            if url != last_url:
                print(f"[cdp_login]   url: {url[:100]}")
                last_url = url
            if "gemini.google.com" in url and not any(m in url for m in logout_markers):
                # Wait for the page to settle.
                await asyncio.sleep(3)
                logged_in = True
                break
            await asyncio.sleep(1)

        if not logged_in:
            return {"ok": False, "error": "Timed out waiting for Gemini login."}
        return {"ok": True, "msg": f"Gemini login complete. Profile saved at {CHROME_PROFILE_DIR}."}
    finally:
        try:
            await pw.stop()
        except Exception:
            pass
        # Leave Chrome running so the user sees the result. They can close it
        # manually; the profile is already saved.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--prompt", type=str, default=None)
    parser.add_argument("--login", action="store_true",
                        help="Open a HEADED Chrome window to log into gemini.google.com.")
    args = parser.parse_args()

    if args.login:
        result = asyncio.run(login_gemini_headed())
        print("\n=== LOGIN RESULT ===")
        for k, v in result.items():
            print(f"{k}: {v}")
        return

    if args.prompt:
        result = asyncio.run(chat_with_gemini_via_cdp(args.prompt))
        print("\n=== RESULT ===")
        for k, v in result.items():
            print(f"{k}: {v}")
        return

    import uvicorn
    print(f"[cdp_gemini_agent] serving on http://localhost:{args.port}")
    print(f"[cdp_gemini_agent] first time? run: python cdp_gemini_agent.py --login")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
