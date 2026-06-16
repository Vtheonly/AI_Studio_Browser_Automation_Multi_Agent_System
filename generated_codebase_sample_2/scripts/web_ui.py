"""
web_ui.py — Local web UI for all three PoCs.

Single FastAPI server that:
  - Serves an HTML chat page
  - Routes /api/chat to the selected PoC:
      "aistudio_to_api" → PoC #1 (drives aistudio.google.com via Playwright)
      "multi_agent"     → PoC #2 (Web Agent + Orchestrator + AI Studio Brain)
      "cdp_gemini"      → PoC #3 (drives gemini.google.com via CDP)
  - Exposes /api/health to check session status

Run:
    python web_ui.py --port 8000

Then open: http://localhost:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# Import the three PoCs' core functions.
from aistudio_to_api import chat_with_aistudio
from cdp_gemini_agent import chat_with_gemini_via_cdp
from multi_agent_system import run_multi_agent, needs_web
from browser_session import (
    SessionManager,
    get_session_manager,
    shutdown_session_manager,
    reset_session_manager,
    STORAGE_STATE_PATH,
    SESSION_META_PATH,
)
from playwright.async_api import async_playwright
from pathlib import Path as _Path
import json as _json


class ChatRequest(BaseModel):
    backend: str  # "aistudio_to_api" | "multi_agent" | "cdp_gemini"
    prompt: str


app = FastAPI(title="AI Studio Agent — Local Web UI")

# Lazily-initialized session manager (created on first chat request).
_session_ready: bool = False


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AI Studio Agent — Local Web UI</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f1115; color: #e6e6e6;
  }
  header {
    background: #1a1d24; padding: 14px 22px; border-bottom: 1px solid #2a2f3a;
    display: flex; justify-content: space-between; align-items: center;
  }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .status { font-size: 12px; color: #888; }
  main { max-width: 920px; margin: 0 auto; padding: 24px 16px; }
  .row { margin-bottom: 14px; }
  label { display: block; font-size: 12px; color: #999; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }
  select, textarea, button {
    width: 100%; background: #1a1d24; color: #e6e6e6; border: 1px solid #2a2f3a;
    border-radius: 6px; padding: 10px 12px; font-family: inherit; font-size: 14px;
  }
  textarea { min-height: 110px; resize: vertical; }
  button {
    cursor: pointer; background: #4285f4; border-color: #4285f4; color: white;
    font-weight: 600; padding: 10px 18px;
  }
  button:hover { background: #3367d6; }
  button:disabled { background: #444; border-color: #444; cursor: not-allowed; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .response-box {
    background: #1a1d24; border: 1px solid #2a2f3a; border-radius: 6px; padding: 14px;
    min-height: 80px; white-space: pre-wrap; font-family: 'SF Mono', Menlo, monospace; font-size: 13px;
  }
  details { margin-top: 14px; }
  summary { cursor: pointer; color: #888; font-size: 12px; padding: 6px 0; }
  .trace {
    background: #0a0c10; border: 1px solid #2a2f3a; border-radius: 6px; padding: 10px;
    font-family: 'SF Mono', Menlo, monospace; font-size: 12px; color: #aaa;
    white-space: pre-wrap; max-height: 320px; overflow-y: auto;
  }
  .meta { color: #888; font-size: 12px; margin-top: 8px; }
  .error { color: #ff6b6b; }
  .pill {
    display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px;
    background: #2a2f3a; color: #aaa; margin-left: 8px;
  }
  .pill.ok { background: #2d4a2d; color: #7fc97f; }
  .pill.err { background: #4a2d2d; color: #ff8b8b; }
</style>
</head>
<body>
<header>
  <h1>AI Studio Agent — Local Web UI <span class="pill" id="session-pill">checking…</span></h1>
  <div class="status">Pure web-UI automation · no Gemini API · PoC #1 / #2 / #3</div>
</header>

<main>
  <div class="row">
    <label for="backend">Backend (PoC)</label>
    <select id="backend">
      <option value="aistudio_to_api">PoC #1 — AIStudioToAPI (Playwright on aistudio.google.com)</option>
      <option value="multi_agent">PoC #2 — Multi-Agent (Web + Orchestrator + AI Studio Brain)</option>
      <option value="cdp_gemini">PoC #3 — CDP Gemini (Chrome DevTools Protocol on gemini.google.com)</option>
    </select>
  </div>

  <div class="row">
    <label for="prompt">Prompt / Task</label>
    <textarea id="prompt" placeholder="Try: What is 2+2?   |   Or for multi-agent: What is the latest news about GPT-5?"></textarea>
  </div>

  <div class="row" style="display:flex; gap:10px; flex-wrap:wrap;">
    <button id="send" style="flex:1; min-width:200px;">Send</button>
    <button id="login" type="button" style="background:#34a853; border-color:#34a853; flex:0 0 auto;">Login to Google</button>
    <button id="reset" type="button" style="background:#5f6368; border-color:#5f6368; flex:0 0 auto;">Reset session</button>
  </div>

  <div id="login-msg" class="meta" style="display:none;"></div>

  <div class="row">
    <label>Response</label>
    <div class="response-box" id="response">—</div>
    <div class="meta" id="meta"></div>
  </div>

  <details>
    <summary>Trace / Debug</summary>
    <div class="trace" id="trace">—</div>
  </details>
</main>

<script>
const $ = id => document.getElementById(id);
const sendBtn = $('send');
const responseEl = $('response');
const traceEl = $('trace');
const metaEl = $('meta');

async function checkHealth() {
  try {
    const r = await fetch('/api/health');
    const j = await r.json();
    const pill = $('session-pill');
    if (j.session_ready) {
      pill.textContent = 'session: ready';
      pill.className = 'pill ok';
    } else {
      pill.textContent = 'session: missing (needs login)';
      pill.className = 'pill err';
    }
    return j;
  } catch (e) {
    console.error(e);
    return null;
  }
}
checkHealth();

// ─── Login button ────────────────────────────────────────────────────────
$('login').addEventListener('click', async () => {
  const msgEl = $('login-msg');
  msgEl.style.display = 'block';
  msgEl.style.color = '#7fc97f';
  msgEl.textContent = ' Launching headed browser for Google login... '
                     + 'Complete the login in the new window that opens.';
  try {
    const r = await fetch('/api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({target: 'aistudio', force: false})
    });
    const j = await r.json();
    if (j.ok) {
      msgEl.textContent = ' ' + j.msg + ' '
                        + 'After logging in, click "Reset session" then refresh.';
      // Start polling for session_saved.
      const poll = setInterval(async () => {
        const s = await (await fetch('/api/login/status')).json();
        if (s.session_saved) {
          clearInterval(poll);
          msgEl.style.color = '#7fc97f';
          msgEl.textContent = ' Login saved! Session is now ready. '
                            + 'Click "Reset session" so the server picks it up.';
          checkHealth();
        }
      }, 3000);
      // Stop polling after 10 minutes.
      setTimeout(() => clearInterval(poll), 600000);
    } else {
      msgEl.style.color = '#ff8b8b';
      msgEl.textContent = 'ERROR: ' + (j.error || 'unknown');
    }
  } catch (e) {
    msgEl.style.color = '#ff8b8b';
    msgEl.textContent = 'FETCH FAILED: ' + e.message;
  }
});

// ─── Reset session button ────────────────────────────────────────────────
$('reset').addEventListener('click', async () => {
  const msgEl = $('login-msg');
  msgEl.style.display = 'block';
  msgEl.style.color = '#aaa';
  msgEl.textContent = ' Resetting in-memory session...';
  try {
    const r = await fetch('/api/reset-session', {method: 'POST'});
    const j = await r.json();
    msgEl.style.color = '#7fc97f';
    msgEl.textContent = ' ' + j.msg;
    await checkHealth();
  } catch (e) {
    msgEl.style.color = '#ff8b8b';
    msgEl.textContent = 'RESET FAILED: ' + e.message;
  }
});

sendBtn.addEventListener('click', async () => {
  const backend = $('backend').value;
  const prompt = $('prompt').value.trim();
  if (!prompt) return;
  sendBtn.disabled = true;
  responseEl.textContent = ' thinking...';
  responseEl.className = 'response-box';
  traceEl.textContent = '—';
  metaEl.textContent = '';
  try {
    const t0 = performance.now();
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({backend, prompt})
    });
    const j = await r.json();
    const elapsed = Math.round(performance.now() - t0);

    if (j.error) {
      responseEl.innerHTML = `<span class="error">ERROR: ${escapeHtml(j.error)}</span>`;
    } else {
      responseEl.textContent = j.response || '(empty response)';
    }
    metaEl.textContent = `backend: ${backend} · latency: ${j.latency_ms || elapsed}ms`;

    // Trace differs per backend.
    let traceText = '';
    if (j.debug && j.debug.steps) {
      traceText = j.debug.steps.map(s => '• ' + s).join('\\n');
    }
    if (j.trace) {
      traceText += (traceText ? '\\n\\n' : '') + j.trace.map(s => '• ' + s).join('\\n');
    }
    if (j.web_result) {
      traceText += `\\n\\n[web_agent] search_results=${j.web_result.search_results?.length || 0} ` +
                   `fetched_pages=${j.web_result.fetched_pages?.length || 0} ` +
                   `latency=${j.web_result.latency_ms}ms`;
      if (j.web_result.fetched_pages?.length) {
        traceText += '\\n[web_agent] sources:\\n' +
          j.web_result.fetched_pages.map(p => '  - ' + p.title + '\\n    ' + p.url).join('\\n');
      }
    }
    if (j.brain_result?.debug?.steps) {
      traceText += '\\n\\n[brain] ' + j.brain_result.debug.steps.map(s => '• ' + s).join('\\n');
    }
    if (j.final_prompt) {
      traceText += '\\n\\n[final_prompt]\\n' + j.final_prompt.slice(0, 1200) +
                   (j.final_prompt.length > 1200 ? '...(truncated)' : '');
    }
    traceEl.textContent = traceText || '(no trace)';
  } catch (e) {
    responseEl.innerHTML = `<span class="error">FETCH FAILED: ${escapeHtml(e.message)}</span>`;
  } finally {
    sendBtn.disabled = false;
  }
});

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "session_ready": STORAGE_STATE_PATH.exists(),
        "session_path": str(STORAGE_STATE_PATH),
        "storage_state_exists": STORAGE_STATE_PATH.exists(),
    }


@app.post("/api/chat")
async def chat(req: ChatRequest):
    t0 = time.time()
    try:
        if req.backend == "aistudio_to_api":
            result = await chat_with_aistudio(req.prompt)
            return result
        elif req.backend == "multi_agent":
            result = await run_multi_agent(req.prompt)
            # Flatten for the UI: surface the brain's response + the trace.
            return {
                "response": (result.get("brain_result") or {}).get("response"),
                "error": (result.get("brain_result") or {}).get("error"),
                "latency_ms": result.get("total_latency_ms"),
                "trace": result.get("trace"),
                "web_result": result.get("web_result"),
                "brain_result": result.get("brain_result"),
                "final_prompt": result.get("final_prompt"),
                "web_needed": result.get("web_needed"),
                "web_matched_keywords": result.get("web_matched_keywords"),
                "debug": {"steps": []},
            }
        elif req.backend == "cdp_gemini":
            result = await chat_with_gemini_via_cdp(req.prompt)
            return result
        else:
            return {"response": None, "error": f"unknown backend: {req.backend}",
                    "latency_ms": int((time.time() - t0) * 1000), "debug": {}}
    except Exception as e:
        return {"response": None,
                "error": f"{type(e).__name__}: {e}",
                "latency_ms": int((time.time() - t0) * 1000),
                "debug": {}}


@app.post("/api/init-session")
async def init_session(headless: bool = True):
    """Force-create the session (will hit auth wall if no display)."""
    global _session_ready
    try:
        sm = await get_session_manager(headless=headless)
        _session_ready = True
        return {"ok": True, "session_ready": True,
                "storage_state_exists": STORAGE_STATE_PATH.exists()}
    except Exception as e:
        return {"ok": False, "error": str(e),
                "storage_state_exists": STORAGE_STATE_PATH.exists()}


# ─── Login flow ──────────────────────────────────────────────────────────────
# The login flow MUST run in a separate subprocess because it needs a HEADED
# browser, but the FastAPI server typically runs headless. We spawn login.py
# as a child process and stream its output back via SSE.

import subprocess
import shlex


@app.post("/api/login")
async def login(target: str = "aistudio", force: bool = False):
    """Trigger the manual login flow in a HEADED browser.

    This spawns `python login.py --target <target> [--force]` as a subprocess.
    The user completes Google login in the visible browser window; the session
    is then saved to session/storage_state.json.

    Returns immediately with the subprocess PID; the client polls /api/health
    to detect when the saved session appears.
    """
    here = _Path(__file__).resolve().parent
    cmd = [sys.executable, str(here / "login.py"), "--target", target]
    if force:
        cmd.append("--force")
    # Detach the subprocess so it survives the request handler returning.
    # Output goes to a log file the user can inspect.
    log_path = here.parent / "session" / "login.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "w")
    proc = subprocess.Popen(
        cmd,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        cwd=str(here),
        # Don't inherit our stdin/stdout — let it open its own X display.
        start_new_session=True,
    )
    return {
        "ok": True,
        "pid": proc.pid,
        "target": target,
        "force": force,
        "log_path": str(log_path),
        "msg": f"Login window launching (PID {proc.pid}). "
               f"Complete Google login in the visible browser. "
               f"Then refresh this page — the session pill should turn green.",
    }


@app.get("/api/login/status")
async def login_status():
    """Check whether a saved session exists yet."""
    exists = STORAGE_STATE_PATH.exists()
    meta = {}
    if SESSION_META_PATH.exists():
        try:
            meta = _json.loads(SESSION_META_PATH.read_text())
        except Exception:
            pass
    return {
        "session_saved": exists,
        "meta": meta,
    }


@app.post("/api/reset-session")
async def reset_session():
    """Drop the in-memory session so the next chat request re-creates it
    (picking up any freshly-saved storage_state.json)."""
    await reset_session_manager()
    return {"ok": True, "msg": "In-memory session dropped. Next chat request "
            "will reload from storage_state.json if present."}


import sys  # noqa — used by /api/login above


@app.on_event("shutdown")
async def _shutdown():
    await shutdown_session_manager()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    import uvicorn
    print(f"\n[web_ui] Open http://localhost:{args.port}\n")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
