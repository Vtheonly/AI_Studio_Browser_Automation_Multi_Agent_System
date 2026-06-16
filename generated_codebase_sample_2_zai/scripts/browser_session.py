"""
browser_session.py — Shared Playwright session manager.

Implements the "manual login once" pattern from the article:
  1. If session/storage_state.json exists → reuse it.
  2. Otherwise → launch a HEADED browser, navigate to AI Studio,
     wait for the user to complete Google login, then save state.

This is the #1 failure point the article describes: Google binds sessions
to browser fingerprint + device, so the saved state is the only way to
persist auth across automation runs.

Usage:
    from browser_session import SessionManager
    sm = SessionManager(headless=False)  # headless=False for login flow!
    await sm.ensure_session()
    page = await sm.new_page()
    ...
    await sm.close()

Or use the CLI helper:
    python login.py            # opens headed browser, you log in
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

# Project layout — resolves correctly whether the script is run from
# /home/z/my-project/scripts/ OR from a downloaded copy elsewhere.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SESSION_DIR = PROJECT_ROOT / "session"
STORAGE_STATE_PATH = SESSION_DIR / "storage_state.json"
SESSION_META_PATH = SESSION_DIR / "meta.json"

# AI Studio URLs
AISTUDIO_HOME = "https://aistudio.google.com/app/prompts/new_chat"
GEMINI_HOME = "https://gemini.google.com/app"

# Heuristic: a URL that contains either of these means we are still logged out.
LOGOUT_MARKERS = ("accounts.google.com", "/signin", "/v3/signin")


class SessionManager:
    """Owns one Chromium process and one persistent context for the whole app."""

    def __init__(self, headless: bool = True, debug: bool = False):
        # Default headless=True for safe server use. The login flow
        # explicitly constructs SessionManager(headless=False).
        self.headless = headless
        self.debug = debug
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()

    async def ensure_session(self, force_relogin: bool = False) -> None:
        """Make sure we have a logged-in browser context.

        - If storage_state.json exists and force_relogin is False, load it.
        - Otherwise launch a browser and wait for the user to log in manually.

        In headless mode with no saved state, we DO NOT block — we create an
        unauthenticated context so callers can try (and hit the auth wall
        themselves with a clear error). The actual login flow requires
        headless=False, which the user triggers via login.py or /api/login.
        """
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            if self._context is not None:
                return
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )

            has_state = STORAGE_STATE_PATH.exists() and not force_relogin
            if has_state:
                self._log(f"Loading saved session from {STORAGE_STATE_PATH}")
                self._context = await self._browser.new_context(
                    storage_state=str(STORAGE_STATE_PATH),
                    user_agent=self._ua(),
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                )
                # Verify session still works by hitting AI Studio and checking
                # we are NOT bounced to accounts.google.com.
                probe = await self._context.new_page()
                try:
                    await probe.goto(AISTUDIO_HOME, wait_until="domcontentloaded", timeout=20000)
                    if any(m in probe.url for m in LOGOUT_MARKERS):
                        self._log("Saved session is stale (bounced to login). Relogin needed.")
                        try:
                            await probe.close()
                        except Exception:
                            pass
                        await self._context.close()
                        self._context = None
                        # If headless, don't try to launch headed flow — fail fast.
                        if self.headless:
                            raise RuntimeError(
                                "AUTH_WALL: saved session is stale and headless mode "
                                "cannot complete manual Google login. Run "
                                "`python login.py` to refresh the session."
                            )
                        return await self.ensure_session(force_relogin=True)
                    self._log("Saved session is valid.")
                finally:
                    try:
                        await probe.close()
                    except Exception:
                        pass
            else:
                if self.headless:
                    # Cannot do manual login headless. Create a context anyway so
                    # callers can at least try (and hit the auth wall themselves).
                    self._log("No saved session and headless=True. Creating unauthenticated "
                              "context; expect chat requests to bounce to login. "
                              "Run `python login.py` to authenticate.")
                    self._context = await self._browser.new_context(
                        user_agent=self._ua(),
                        viewport={"width": 1280, "height": 900},
                        locale="en-US",
                    )
                    return
                # HEADLESS=FALSE → run the interactive login flow.
                self._log("No saved session. Launching HEADED browser for manual login.")
                self._context = await self._browser.new_context(
                    user_agent=self._ua(),
                    viewport={"width": 1280, "height": 900},
                    locale="en-US",
                )
                page = await self._context.new_page()
                await page.goto(AISTUDIO_HOME, wait_until="domcontentloaded", timeout=30000)
                await self._wait_for_login(page)
                await self._save_state()
                await page.close()

    async def _wait_for_login(self, page: Page, timeout_sec: int = 600) -> None:
        """Wait until the user completes Google login in the visible browser.

        We poll the URL once a second. As long as it contains a logout marker,
        we keep waiting. Once it returns to aistudio.google.com, we treat the
        session as authenticated.
        """
        self._log(
            "\n" + "=" * 70 + "\n"
            ">>> HEADED BROWSER OPEN\n"
            ">>> Please log into Google in the visible window.\n"
            f">>> Waiting up to {timeout_sec}s for login to complete...\n"
            ">>> (Complete email + password + 2FA / CAPTCHA / 'verify it's you' as needed.)\n"
            ">>> Once you reach the AI Studio chat UI, the session will be saved\n"
            ">>> automatically and the browser will close.\n"
            + "=" * 70
        )
        start = time.time()
        last_url = ""
        while time.time() - start < timeout_sec:
            url = page.url
            if url != last_url:
                self._log(f"  current url: {url[:100]}")
                last_url = url
            if not any(m in url for m in LOGOUT_MARKERS) and "aistudio.google.com" in url:
                self._log("Login detected! Saving session...")
                # Give the page a moment to settle and load the chat UI.
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                return
            await asyncio.sleep(1)
        raise TimeoutError(
            "Timed out waiting for manual login. Re-run and complete login within 10 minutes."
        )

    async def _save_state(self) -> None:
        state = await self._context.storage_state(path=str(STORAGE_STATE_PATH))
        meta = {
            "saved_at": int(time.time()),
            "saved_at_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "ua": self._ua(),
            "note": "Manual login persisted. Reuse across runs.",
        }
        SESSION_META_PATH.write_text(json.dumps(meta, indent=2))
        self._log(f"Session saved → {STORAGE_STATE_PATH}")

    async def new_page(self, url: Optional[str] = None) -> Page:
        """Open a fresh page on the authenticated context."""
        if self._context is None:
            await self.ensure_session()
        page = await self._context.new_page()
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return page

    @property
    def has_session(self) -> bool:
        return STORAGE_STATE_PATH.exists()

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None

    @staticmethod
    def _ua() -> str:
        return (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )

    def _log(self, msg: str) -> None:
        print(f"[session] {msg}", flush=True)


# Module-level singleton for sharing across FastAPI handlers and PoCs.
_singleton: Optional[SessionManager] = None


async def get_session_manager(headless: bool = True) -> SessionManager:
    global _singleton
    if _singleton is None:
        _singleton = SessionManager(headless=headless)
        await _singleton.ensure_session()
    return _singleton


async def shutdown_session_manager() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.close()
        _singleton = None


async def reset_session_manager() -> None:
    """Close + drop the singleton so the next call re-creates it (e.g. after
    a successful login flow that saved a fresh storage_state.json)."""
    global _singleton
    if _singleton is not None:
        await _singleton.close()
        _singleton = None
