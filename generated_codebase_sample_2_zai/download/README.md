# AI Studio Web-UI Agent — Three PoCs + Manual Login Flow

**Use Gemini inside AI Studio / Gemini web as if it were a controllable agent UI,
without any API usage — by hijacking the browser session itself.**

Built in **Python + Playwright + FastAPI** with a local web UI. Three PoCs from
the article are implemented:

1. **AIStudioToAPI** — Playwright wrapper on `aistudio.google.com`
2. **Multi-Agent** — Web Agent + Orchestrator + AI Studio Brain
3. **CDP Gemini** — Chrome DevTools Protocol on `gemini.google.com`

---

## Quick start

```bash
# 1. Unzip
unzip ai_studio_agent.zip
cd ai_studio_agent

# 2. (Option A) Use the launcher script — handles venv + deps + browser install
cd scripts
./run.sh                # → opens http://localhost:8000

# 2. (Option B) Manual setup
pip install -r scripts/requirements.txt
playwright install chromium
cd scripts
python web_ui.py --port 8000

# 3. Open http://localhost:8000 in your browser
```

## First-time login (REQUIRED for PoC #1 and #2)

PoC #1 (AI Studio) and PoC #2 (Multi-Agent, which uses AI Studio as its brain)
require a logged-in Google session. The first time you use them:

**Option A — From the web UI:**
1. Open http://localhost:8000
2. Click the green **"Login to Google"** button
3. A headed Chromium window opens — complete Google login (email + password + 2FA)
4. When you reach the AI Studio chat UI, the session is auto-saved to
   `session/storage_state.json`
5. Click **"Reset session"** in the web UI
6. The session pill turns green — you're ready to chat

**Option B — From the command line:**
```bash
cd scripts
python login.py                 # opens headed browser, you log in
# or
./run.sh --login
```

After login, all subsequent requests reuse the saved session **headlessly** —
no more logins needed, until Google expires it (typically hours-to-days).

**PoC #3 (CDP Gemini) works anonymously** — no login needed for the Flash model.
Optional: `python cdp_gemini_agent.py --login` to unlock Gemini Pro.

---

## Project layout

```
ai_studio_agent/
├── scripts/
│   ├── browser_session.py     # Shared Playwright session manager
│   │                          #   - manual-login-once flow
│   │                          #   - storage_state.json persistence
│   │                          #   - fail-fast in headless mode
│   ├── login.py               # CLI: opens headed browser for manual Google login
│   ├── aistudio_to_api.py     # PoC #1: AIStudioToAPI wrapper (POST /chat)
│   ├── cdp_gemini_agent.py    # PoC #3: CDP driver for gemini.google.com
│   │                          #   - --login flag for headed Gemini auth
│   ├── multi_agent_system.py  # PoC #2: Web Agent + Orchestrator + Brain
│   │                          #   - Web Agent uses Marginalia Search (no CAPTCHA)
│   ├── web_ui.py              # Local FastAPI web UI
│   │                          #   - chat box + backend dropdown
│   │                          #   - "Login to Google" button
│   │                          #   - "Reset session" button
│   ├── test_all.py            # E2E test runner — single prompt through each PoC
│   ├── run.sh                 # One-command launcher (venv + deps + run)
│   └── requirements.txt
├── session/                   # storage_state.json + Chrome profile go here
│                              # (created on first login)
└── download/
    ├── README.md              # this file
    ├── test_results.md        # test report from sandbox run
    └── test_results.json
```

---

## Architecture (per PoC)

### PoC #1 — AIStudioToAPI

```
HTTP POST /chat
       ↓
browser_session.SessionManager (loads storage_state.json)
       ↓
Playwright Chromium
       ↓ goto https://aistudio.google.com/app/prompts/new_chat
       ↓ find prompt input (multiple fallback selectors)
       ↓ keyboard.type(prompt)
       ↓ click "Run" button
       ↓ wait for "Stop" button to vanish + response text to stabilize
       ↓ scrape model-response container
JSON response
```

### PoC #2 — Multi-Agent

```
USER TASK
   ↓
Orchestrator (deterministic state machine)
   │
   ├─ needs_web(task)?  (keyword heuristic: "latest", "current", "news", ...)
   │     ↓ YES
   │   WebAgent (deterministic, NO LLM)
   │     ├─ Marginalia Search → result URLs
   │     ├─ Playwright fetch → page text (top 3 pages)
   │     └─ returns context_text
   │
   ├─ build final_prompt = task (+ context_text if any)
   ↓
AIBrainAgent.ask(final_prompt)  → reuses PoC #1's chat_with_aistudio
   ↓
{response, trace, web_result, brain_result, total_latency_ms}
```

Three rules from the article (enforced in code):
1. AI Studio never directly controls tools — it only reasons.
2. Web Agent is deterministic only — no LLM in it.
3. Orchestrator is the brain of the system, not AI Studio.

### PoC #3 — CDP Gemini

```
HTTP POST /chat
       ↓
subprocess.Popen(chrome --remote-debugging-port=9222
                       --user-data-dir=./session/chrome_profile
                       https://gemini.google.com/app)
       ↓
Playwright connect_over_cdp("http://127.0.0.1:9222")
       ↓ new_page → goto gemini.google.com/app
       ↓ find rich-textarea.ql-editor
       ↓ keyboard.type(prompt)
       ↓ click "Send message" button
       ↓ poll message-content elements (take LAST visible one)
       ↓ wait for text to stabilize (2 consecutive identical reads)
JSON response
```

---

## HTTP endpoints (web_ui.py)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Web UI HTML page |
| GET | `/api/health` | Session status (saved vs missing) |
| POST | `/api/chat` | Send a prompt to a backend (`aistudio_to_api` / `multi_agent` / `cdp_gemini`) |
| POST | `/api/login` | Spawn `login.py` in a headed browser (for first-time Google login) |
| GET | `/api/login/status` | Check whether a saved session exists yet |
| POST | `/api/reset-session` | Drop the in-memory session so the next chat reloads from disk |
| POST | `/api/init-session` | Force-create the session (headless; will hit auth wall if not logged in) |

---

## Test results (from sandbox run, 2026-06-16)

| PoC | Result | Latency | Failure mode |
|-----|--------|---------|--------------|
| PoC #1 — AIStudioToAPI |  FAIL | 1670 ms | AUTH_WALL (needs login) |
| PoC #2 — Multi-Agent |  FAIL | 3710 ms | AUTH_WALL (brain failed; web agent succeeded) |
| PoC #3 — CDP Gemini |  **PASS** | 9986 ms | — returned real Gemini response, no login needed |

After running `login.py` on a machine with a display, PoC #1 and #2 will
also work — until Google expires the saved session.

---

## Why this is fragile (the article was right)

The article's core thesis — "AI Studio UI is optimized for human interaction,
not machine determinism" — is correct, and our tests confirm it:

1. **Auth wall** is the first and hardest blocker. The `login.py` flow is the
   only reliable way past it.
2. **Selectors are unstable** — both AI Studio and Gemini use Shadow DOM +
   Material Web Components; we have 4-5 fallback selectors per UI element.
3. **Streaming completion detection is a heuristic**, not a contract — we poll
   until the response text stops changing.
4. **Latency is unpredictable** — PoC #3 took ~10s for a one-sentence answer.
5. **No structured outputs** — there's no JSON / tool-calling contract.

PoC #3 happens to work because `gemini.google.com/app` permits anonymous
chat with the Flash model — but this is a Google policy decision that can
change at any moment.

---

## How to extend

- **Add fallback LLM**: in `aistudio_to_api.py`, wrap `chat_with_aistudio()`
  with a try/except that calls a real LLM when `error_class == "AUTH_WALL"`.
- **Add structured outputs**: in `aistudio_to_api.py`, append
  `"\n\nReply as JSON: {\"answer\": \"...\"}"` to the prompt and parse.
- **Add memory**: maintain a rolling conversation log in `browser_session.py`
  and prepend the last N turns to every prompt.
- **Swap the Web Agent's search engine**: `multi_agent_system.py`'s
  `web_search()` function. We use Marginalia because Bing / DuckDuckGo /
  Brave all CAPTCHA or 403 cloud IPs.

---

## Dependencies

- Python 3.10+
- playwright 1.50+ (with Chromium)
- fastapi + uvicorn
- httpx
- pydantic

No Google API key is used anywhere in this project. That was the whole point.
