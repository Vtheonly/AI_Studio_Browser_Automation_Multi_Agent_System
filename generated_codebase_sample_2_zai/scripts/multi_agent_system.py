"""
multi_agent_system.py — PoC #2: Web Agent + Orchestrator + AI Studio Brain.

Implements the architecture from the last section of the article:

    ┌──────────────────────┐
    │  Web Agent           │  deterministic: search + scrape
    │  (DuckDuckGo + PW)   │  → returns plain text snippets
    └─────────┬────────────┘
              ↓
    ┌──────────────────────┐
    │  Orchestrator        │  state machine, NOT LLM chaos
    │  (decides: web?)     │  decides what to fetch + how to prompt
    └─────────┬────────────┘
              ↓
    ┌──────────────────────┐
    │  AI Studio Brain     │  pure LLM via UI automation
    │  (reuses PoC #1)     │  never directly controls tools
    └──────────────────────┘

Three rules from the article (enforced here):
  1. AI Studio NEVER directly controls tools — it only reasons.
  2. Web Agent is deterministic only — no LLM in it.
  3. Orchestrator is the brain of the system, not AI Studio.

Run as server:
    python multi_agent_system.py --port 8002

Or one-shot:
    python multi_agent_system.py --task "What is the latest news about GPT-5?"
"""
from __future__ import annotations

import argparse
import asyncio
import re
import time
from typing import Optional
from urllib.parse import quote_plus

from fastapi import FastAPI
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

# Reuse PoC #1's chat function — single shared "brain".
from aistudio_to_api import chat_with_aistudio

# ─── Web Agent (deterministic) ──────────────────────────────────────────────
# Uses Marginalia Search (https://marginalia-search.com) — a clean, no-CAPTCHA,
# no-JS-required search engine. Bing and DuckDuckGo both 403 or CAPTCHA from
# cloud IPs; Marginalia is the only major engine that returns parseable HTML
# to sandboxed Playwright instances.

MARGINALIA_SEARCH = "https://marginalia-search.com/search"

# Skip these patterns when collecting result URLs.
SKIP_URL_PATTERNS = [
    "marginalia-search.com",
    "web.archive.org",
    "about.marginalia",
    "github.com/MarginaliaSearch",
    "chat.marginalia.nu",
]


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search Marginalia and parse result links + snippets.

    Returns: [{"title", "url", "snippet"}]
    """
    results: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = await ctx.new_page()
        try:
            await page.goto(
                f"{MARGINALIA_SEARCH}?query={quote_plus(query)}",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            # Marginalia renders results as <h2><a href="real_url">Title</a></h2>
            # followed by a URL-display link and an archive.org link. We grab h2 a
            # as the canonical title link, then filter out nav/archive links.
            title_links = page.locator("h2 a")
            n_links = await title_links.count()
            seen_urls: set[str] = set()
            for i in range(n_links):
                if len(results) >= max_results:
                    break
                try:
                    link = title_links.nth(i)
                    title = (await link.inner_text(timeout=1500)).strip()
                    href = await link.get_attribute("href")
                    if not href or not href.startswith("http"):
                        continue
                    if any(skip in href for skip in SKIP_URL_PATTERNS):
                        continue
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    # Snippet: try to find a <p> near this h2.
                    snippet = ""
                    try:
                        # Walk up to the h2's container, look for sibling <p>.
                        parent = link.locator("xpath=ancestor::*[1]/following-sibling::*//p").first
                        snippet = (await parent.inner_text(timeout=1500)).strip()
                    except Exception:
                        pass
                    if title:
                        results.append({"title": title, "url": href, "snippet": snippet})
                except Exception:
                    continue
        except Exception as e:
            print(f"[web_agent] search error: {e}", flush=True)
        finally:
            await browser.close()
    return results


async def fetch_page_text(url: str, max_chars: int = 3000) -> str:
    """Open a URL in Playwright and extract the main text content."""
    if not url or not url.startswith("http"):
        return ""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            # Wait for network to settle so JS-rendered content appears.
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            # Best-effort extraction: get visible text from <main> or <body>.
            text = await page.evaluate(
                """() => {
                    const el = document.querySelector('main') || document.querySelector('article') || document.body;
                    return el ? el.innerText : '';
                }"""
            )
            return text[:max_chars]
        except Exception as e:
            print(f"[web_agent] fetch error for {url[:80]}: {type(e).__name__}", flush=True)
            return ""
        finally:
            await browser.close()


async def gather_info(topic: str, max_pages: int = 3) -> dict:
    """Search + fetch top results. Returns the assembled context."""
    t0 = time.time()
    search_results = await web_search(topic, max_results=max_pages)
    fetched = []
    for r in search_results[:max_pages]:
        text = await fetch_page_text(r["url"], max_chars=2000)
        if text:
            fetched.append({
                "title": r["title"],
                "url": r["url"],
                "snippet": r["snippet"],
                "page_text": text,
            })
    return {
        "topic": topic,
        "search_results": search_results,
        "fetched_pages": fetched,
        "latency_ms": int((time.time() - t0) * 1000),
    }


# ─── Orchestrator (deterministic state machine) ─────────────────────────────

# Heuristic: when does the orchestrator decide to call the web agent?
WEB_TRIGGER_KEYWORDS = [
    "latest", "current", "today", "yesterday", "this week", "this month",
    "recent", "news", "now", "2024", "2025", "2026", "yesterday",
    "update", "released", "announced", "just out",
]


def needs_web(task: str) -> tuple[bool, list[str]]:
    """Decide whether the task needs fresh web info. Returns (needs, matched_keywords)."""
    task_lower = task.lower()
    matched = [k for k in WEB_TRIGGER_KEYWORDS if k in task_lower]
    return (len(matched) > 0, matched)


async def run_multi_agent(task: str) -> dict:
    """End-to-end orchestrator run."""
    t0 = time.time()
    trace: list[str] = []

    # 1. Decide whether web info is needed.
    web_needed, matched = needs_web(task)
    trace.append(f"orchestrator: web_needed={web_needed} matched={matched}")

    # 2. If needed, gather info deterministically.
    context_text = ""
    web_result = None
    if web_needed:
        trace.append("orchestrator: invoking WebAgent.gather_info()")
        web_result = await gather_info(task, max_pages=3)
        trace.append(f"web_agent: fetched {len(web_result['fetched_pages'])} pages "
                     f"in {web_result['latency_ms']}ms")
        # Build context block.
        if web_result["fetched_pages"]:
            parts = []
            for p in web_result["fetched_pages"]:
                parts.append(f"### {p['title']}\nURL: {p['url']}\n{p['page_text'][:1500]}")
            context_text = "\n\n".join(parts)

    # 3. Build the final prompt for AI Studio.
    if context_text:
        final_prompt = (
            f"You are a research assistant. Use the following web context "
            f"to answer the user's question. Cite sources by URL when relevant.\n\n"
            f"=== WEB CONTEXT ===\n{context_text}\n=== END CONTEXT ===\n\n"
            f"USER QUESTION: {task}\n\n"
            f"ANSWER:"
        )
    else:
        final_prompt = task
    trace.append(f"orchestrator: built final prompt (len={len(final_prompt)})")

    # 4. Call AI Studio brain.
    trace.append("orchestrator: invoking AIBrainAgent.ask() (PoC #1)")
    brain_result = await chat_with_aistudio(final_prompt)
    trace.append(f"brain: error={brain_result.get('error')} "
                 f"latency={brain_result.get('latency_ms')}ms")

    return {
        "task": task,
        "web_needed": web_needed,
        "web_matched_keywords": matched,
        "web_result": web_result,
        "brain_result": brain_result,
        "final_prompt": final_prompt,
        "trace": trace,
        "total_latency_ms": int((time.time() - t0) * 1000),
    }


# ─── HTTP layer ──────────────────────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str


app = FastAPI(title="MultiAgentSystem")


@app.get("/health")
async def health():
    return {"ok": True, "service": "multi_agent_system"}


@app.post("/run")
async def run_endpoint(req: TaskRequest):
    return await run_multi_agent(req.task)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--task", type=str, default=None)
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", dest="headless", action="store_false")
    args = parser.parse_args()

    if args.task:
        # Initialize session headless (will hit auth wall in sandbox).
        import browser_session
        browser_session._singleton = browser_session.SessionManager(headless=args.headless)
        result = asyncio.run(run_multi_agent(args.task))
        print("\n=== RESULT ===")
        print(json.dumps(result, indent=2, default=str))
        asyncio.run(browser_session.shutdown_session_manager())
        return

    import uvicorn
    print(f"[multi_agent_system] serving on http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    import json  # noqa
    main()
