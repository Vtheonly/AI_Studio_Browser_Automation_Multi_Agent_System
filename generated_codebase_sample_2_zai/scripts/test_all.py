"""
test_all.py — Single-prompt E2E test runner across all three PoCs.

Runs a single, simple prompt through each backend and reports:
  - success / failure
  - latency
  - error type (matched against the article's predicted failure modes)
  - the actual response (if any)

Output is written to:
  /home/z/my-project/download/test_results.md  (human-readable)
  /home/z/my-project/download/test_results.json (machine-readable)

Usage:
    python test_all.py [--prompt "What is 2+2?"]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Make sibling modules importable.
sys.path.insert(0, str(Path(__file__).parent))

from browser_session import SessionManager, shutdown_session_manager, STORAGE_STATE_PATH
from aistudio_to_api import chat_with_aistudio
from cdp_gemini_agent import chat_with_gemini_via_cdp
from multi_agent_system import run_multi_agent

DOWNLOAD_DIR = Path("/home/z/my-project/download")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PROMPT = "What is 2+2? Reply with just the number."


def classify_error(err: str) -> str:
    """Map an error string to one of the article's named failure modes."""
    if not err:
        return "none"
    e = err.lower()
    if "accounts.google.com" in e or "session_expired" in e or "not_authenticated" in e:
        return "AUTH_WALL (article §1: Authentication & Session Breakage)"
    if "prompt_input_not_found" in e or "prompt_input_not_visible" in e or "ui changed" in e:
        return "UI_FRAGILITY (article §2: selectors break constantly)"
    if "empty_response" in e:
        return "STREAMING_ISSUE (article §3: partial/empty response)"
    if "timeout" in e:
        return "TIMING_ISSUE (article §6: sleep-based waits fail under load)"
    return "OTHER"


async def run_one(name: str, coro_factory, prompt: str) -> dict:
    print(f"\n{'='*60}\n[{name}] sending prompt: {prompt!r}\n{'='*60}", flush=True)
    t0 = time.time()
    try:
        result = await coro_factory(prompt)
        wall = int((time.time() - t0) * 1000)
        # Normalize result shape.
        # Multi-agent result has nested brain_result; flatten it for reporting.
        if "multi_agent" in name.lower() or "brain_result" in result:
            brain = result.get("brain_result") or {}
            return {
                "name": name,
                "prompt": prompt,
                "success": bool(brain.get("response")) and not brain.get("error"),
                "response": brain.get("response"),
                "error": brain.get("error"),
                "error_class": classify_error(brain.get("error") or ""),
                "latency_ms": result.get("total_latency_ms", wall),
                "wall_ms": wall,
                "web_needed": result.get("web_needed"),
                "web_matched": result.get("web_matched_keywords"),
                "trace": result.get("trace"),
                "final_prompt_excerpt": (result.get("final_prompt") or "")[:300],
                "debug_steps": (brain.get("debug") or {}).get("steps", []),
            }
        return {
            "name": name,
            "prompt": prompt,
            "success": bool(result.get("response")) and not result.get("error"),
            "response": result.get("response"),
            "error": result.get("error"),
            "error_class": classify_error(result.get("error") or ""),
            "latency_ms": result.get("latency_ms", wall),
            "wall_ms": wall,
            "debug_steps": (result.get("debug") or {}).get("steps", []),
        }
    except Exception as e:
        wall = int((time.time() - t0) * 1000)
        return {
            "name": name,
            "prompt": prompt,
            "success": False,
            "response": None,
            "error": f"{type(e).__name__}: {e}",
            "error_class": classify_error(f"{type(e).__name__}: {e}"),
            "latency_ms": wall,
            "wall_ms": wall,
        }


async def main_async(prompt: str, headless: bool = True) -> dict:
    # Initialize shared session (will hit auth wall in headless sandbox).
    import browser_session
    browser_session._singleton = SessionManager(headless=headless)
    try:
        await browser_session._singleton.ensure_session()
    except Exception as e:
        print(f"[test] session init failed (expected in sandbox): {e}", flush=True)

    results = []

    # PoC #1
    results.append(await run_one(
        "PoC1_AIStudioToAPI",
        chat_with_aistudio,
        prompt,
    ))

    # PoC #2 — use a web-triggering task so we exercise the Web Agent too.
    multi_task = f"Based on current public sources, briefly answer: {prompt}"
    results.append(await run_one(
        "PoC2_MultiAgent",
        run_multi_agent,
        multi_task,
    ))

    # PoC #3
    results.append(await run_one(
        "PoC3_CDPGemini",
        chat_with_gemini_via_cdp,
        prompt,
    ))

    await shutdown_session_manager()
    return {"prompt": prompt, "storage_state_existed": STORAGE_STATE_PATH.exists(),
            "results": results, "timestamp": int(time.time())}


def to_markdown(report: dict) -> str:
    lines = ["# AI Studio Web-UI Agent — Test Results", ""]
    lines.append(f"**Prompt:** `{report['prompt']}`  ")
    lines.append(f"**Saved session existed:** {report['storage_state_existed']}  ")
    lines.append(f"**Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report['timestamp']))}  ")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| PoC | Success | Latency (ms) | Failure mode |")
    lines.append("|-----|---------|--------------|--------------|")
    for r in report["results"]:
        lines.append(f"| {r['name']} | {'' if r['success'] else ''} | {r['latency_ms']} | {r['error_class']} |")
    lines.append("")

    for r in report["results"]:
        lines.append(f"## {r['name']}")
        lines.append("")
        lines.append(f"- **Success:** {r['success']}")
        lines.append(f"- **Latency:** {r['latency_ms']} ms (wall: {r['wall_ms']} ms)")
        lines.append(f"- **Error class:** `{r['error_class']}`")
        if r.get("error"):
            lines.append(f"- **Error:** `{r['error']}`")
        if r.get("response"):
            excerpt = r["response"][:500] + ("..." if len(r["response"]) > 500 else "")
            lines.append(f"- **Response (excerpt):**")
            lines.append(f"  ```")
            lines.append(f"  {excerpt}")
            lines.append(f"  ```")
        if r.get("debug_steps"):
            lines.append(f"- **Debug steps:**")
            for s in r["debug_steps"]:
                lines.append(f"  - {s}")
        if r.get("trace"):
            lines.append(f"- **Trace:**")
            for s in r["trace"]:
                lines.append(f"  - {s}")
        if r.get("web_needed") is not None:
            lines.append(f"- **Web needed:** {r['web_needed']} (matched: {r.get('web_matched')})")
        if r.get("final_prompt_excerpt"):
            lines.append(f"- **Final prompt (excerpt):** `{r['final_prompt_excerpt']}`")
        lines.append("")

    lines.append("## What this means")
    lines.append("")
    lines.append("If all three PoCs failed with `AUTH_WALL`: this is exactly the #1 failure "
                 "mode the article predicts. In this sandbox, no human can complete Google's "
                 "2FA/CAPTCHA login flow, so `storage_state.json` is never created and every "
                 "request bounces to `accounts.google.com`.")
    lines.append("")
    lines.append("To actually get a successful response from any of the PoCs:")
    lines.append("1. Run `python web_ui.py --port 8000` on a machine **with a display**.")
    lines.append("2. The first request will launch a **headed** browser window.")
    lines.append("3. Log into Google manually inside that window.")
    lines.append("4. The session is saved to `session/storage_state.json` and reused.")
    lines.append("5. Subsequent requests then run **headless** against the saved session — "
                 "until Google expires it (article §1).")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--no-headless", dest="headless", action="store_false", default=True)
    args = parser.parse_args()

    report = asyncio.run(main_async(args.prompt, headless=args.headless))

    md_path = DOWNLOAD_DIR / "test_results.md"
    json_path = DOWNLOAD_DIR / "test_results.json"
    md_path.write_text(to_markdown(report))
    json_path.write_text(json.dumps(report, indent=2, default=str))

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for r in report["results"]:
        status = " PASS" if r["success"] else " FAIL"
        print(f"  {r['name']:<25} {status}  ({r['latency_ms']}ms)  → {r['error_class']}")
    print(f"\nFull report: {md_path}")
    print(f"JSON:        {json_path}")


if __name__ == "__main__":
    main()
