"""
aistudio_to_api.py — PoC #1: Wrap Google AI Studio web UI as a /chat endpoint.

This is the pattern the article calls "AIStudioToAPI" — a Playwright-driven
robot user that types prompts into https://aistudio.google.com and scrapes
the model's response back.

Run as a server:
    python aistudio_to_api.py --port 8001

Endpoints:
    GET  /health          → {ok: true, session_ready: bool}
    POST /chat            → {prompt, model?} → {response, latency_ms, error?}
    POST /relogin         → forces manual re-login flow

Acknowledged failure modes (from the article) that this code reproduces:
  - Auth wall: if storage_state.json is missing/expired, we cannot complete
    login headlessly (Google requires 2FA + device fingerprint).
  - UI fragility: selectors are best-effort. AI Studio ships frequent UI
    updates that break them silently.
  - Streaming race: we wait for the response DOM to stabilize, but we can
    still grab a partial chunk if the page is slow.
"""
from __future__ import annotations

import argparse
import asyncio
import time
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel
from playwright.async_api import Page, TimeoutError as PWTimeout

from browser_session import get_session_manager, shutdown_session_manager

AISTUDIO_NEW_CHAT = "https://aistudio.google.com/app/prompts/new_chat"

# ─── selectors ───────────────────────────────────────────────────────────────
# Each is a list of CSS selectors tried in order. AI Studio ships frequent UI
# changes — keeping multiple fallbacks is the only way to stay alive.
PROMPT_INPUT_SELECTORS = [
    "div.ql-editor[contenteditable='true']",
    "ms-autotextarea textarea",
    ".ms-chat-prompt-input [contenteditable='true']",
    "rich-textarea [contenteditable='true']",
    "textarea[aria-label*='Type something']",
]

RUN_BUTTON_SELECTORS = [
    "button[aria-label*='Run']",
    "ms-run-button button",
    "button.run-button",
    "button:has-text('Run')",
]

STOP_BUTTON_SELECTORS = [
    "button[aria-label*='Stop']",
    "ms-stop-button button",
    "button:has-text('Stop')",
]

# A model response is any chat turn whose class list contains "model".
# AI Studio renders turns inside <ms-chat-turn-container> elements.
MODEL_RESPONSE_SELECTORS = [
    "ms-chat-turn-container.model ms-chat-turn",
    "ms-chat-turn.model",
    ".model-response-text",
    "[class*='model'] [class*='response']",
    "ms-chat-turn-container:last-of-type .response-container",
]


class ChatRequest(BaseModel):
    prompt: str
    model: Optional[str] = None  # accepted for API compat; not actively switched yet


class ChatResponse(BaseModel):
    response: Optional[str]
    latency_ms: int
    error: Optional[str] = None
    debug: dict = {}


app = FastAPI(title="AIStudioToAPI")


# ─── core driver ─────────────────────────────────────────────────────────────

async def _find_first(page: Page, selectors: list[str], timeout_ms: int = 8000):
    """Return the first locator that becomes visible, or None."""
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


async def _wait_for_response_stable(page: Page, max_wait_sec: int = 120) -> str:
    """Wait for the model's response to finish streaming and return its text.

    Heuristic:
      1. Wait until any "Stop" button disappears (means generation done).
      2. Then wait for the response container's text to stop changing
         for 2 consecutive 800ms polls (streaming done).
    """
    # Phase 1: generation in progress → wait for Stop button to vanish.
    start = time.time()
    stop_btn = await _find_first(page, STOP_BUTTON_SELECTORS, timeout_ms=2000)
    if stop_btn:
        print("[aistudio] generation in progress, waiting for Stop button to vanish", flush=True)
        while time.time() - start < max_wait_sec:
            try:
                visible = await stop_btn.is_visible(timeout=500)
            except Exception:
                visible = False
            if not visible:
                break
            await asyncio.sleep(0.5)
    else:
        # Maybe generation already finished, or never started. Give the page
        # a moment to render.
        await asyncio.sleep(1.5)

    # Phase 2: text-stability check.
    last_text = ""
    stable_count = 0
    poll_interval = 0.8
    required_stable = 2
    while time.time() - start < max_wait_sec:
        # Find the latest model-response block.
        loc = await _find_first(page, MODEL_RESPONSE_SELECTORS, timeout_ms=2000)
        if loc is None:
            await asyncio.sleep(0.5)
            continue
        try:
            current = (await loc.inner_text(timeout=2000)).strip()
        except Exception:
            current = ""
        if current and current == last_text:
            stable_count += 1
            if stable_count >= required_stable:
                return current
        else:
            stable_count = 0
            last_text = current
        await asyncio.sleep(poll_interval)
    # Fall back to whatever we last saw.
    return last_text


async def chat_with_aistudio(prompt: str, debug: bool = False) -> dict:
    """Drive AI Studio: open new chat, type, click Run, scrape response."""
    t0 = time.time()
    sm = await get_session_manager()
    page = await sm.new_page()
    debug_info: dict = {"steps": []}

    try:
        # 1. Navigate to a fresh chat.
        await page.goto(AISTUDIO_NEW_CHAT, wait_until="domcontentloaded", timeout=30000)
        debug_info["steps"].append(f"navigated → {page.url}")

        # Bounce check: if we ended up at accounts.google.com, the session is dead.
        if "accounts.google.com" in page.url:
            return {
                "response": None,
                "latency_ms": int((time.time() - t0) * 1000),
                "error": "session_expired: bounced to Google sign-in. Re-run --relogin.",
                "debug": debug_info,
            }

        # 2. Wait for prompt textarea.
        try:
            await page.wait_for_selector(
                ", ".join(PROMPT_INPUT_SELECTORS), timeout=20000
            )
        except PWTimeout:
            return {
                "response": None,
                "latency_ms": int((time.time() - t0) * 1000),
                "error": "prompt_input_not_found (UI changed?)",
                "debug": debug_info,
            }
        prompt_loc = await _find_first(page, PROMPT_INPUT_SELECTORS, timeout_ms=3000)
        if prompt_loc is None:
            return {
                "response": None,
                "latency_ms": int((time.time() - t0) * 1000),
                "error": "prompt_input_not_visible",
                "debug": debug_info,
            }

        # 3. Type the prompt. AI Studio uses a Quill editor — click + keyboard.
        await prompt_loc.click()
        await page.keyboard.type(prompt, delay=10)
        debug_info["steps"].append("prompt typed")

        # 4. Find + click Run.
        run_loc = await _find_first(page, RUN_BUTTON_SELECTORS, timeout_ms=5000)
        if run_loc is None:
            # Fallback: press Enter (works in many AI Studio versions)
            await page.keyboard.press("Enter")
            debug_info["steps"].append("no Run button, pressed Enter")
        else:
            await run_loc.click()
            debug_info["steps"].append("clicked Run")

        # 5. Wait for response to stabilize.
        response_text = await _wait_for_response_stable(page, max_wait_sec=120)
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
        try:
            await page.close()
        except Exception:
            pass


# ─── HTTP layer ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "service": "aistudio_to_api"}


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    result = await chat_with_aistudio(req.prompt)
    return ChatResponse(**result)


@app.post("/relogin")
async def relogin():
    """Force a manual re-login (requires display)."""
    await shutdown_session_manager()
    from browser_session import SessionManager
    sm = SessionManager(headless=False)
    await sm.ensure_session(force_relogin=True)
    return {"ok": True, "msg": "Relogin complete."}


@app.on_event("shutdown")
async def _shutdown():
    await shutdown_session_manager()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--headless", action="store_true", default=True,
                        help="Run browser headless (default). Use --no-headless to disable.")
    parser.add_argument("--no-headless", dest="headless", action="store_false")
    parser.add_argument("--prompt", type=str, default=None,
                        help="If given, run a single prompt and exit (no server).")
    args = parser.parse_args()

    if args.prompt:
        # CLI mode — just run one prompt and print.
        from browser_session import SessionManager, shutdown_session_manager
        global _singleton
        from browser_session import _singleton as _  # noqa
        import browser_session
        browser_session._singleton = SessionManager(headless=args.headless)
        result = asyncio.run(chat_with_aistudio(args.prompt))
        print("\n=== RESULT ===")
        for k, v in result.items():
            print(f"{k}: {v}")
        asyncio.run(shutdown_session_manager())
        return

    import uvicorn
    print(f"[aistudio_to_api] serving on http://localhost:{args.port}")
    print(f"[aistudio_to_api] try: curl -X POST http://localhost:{args.port}/chat "
          f"-H 'Content-Type: application/json' -d '{{\"prompt\":\"hi\"}}'")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
