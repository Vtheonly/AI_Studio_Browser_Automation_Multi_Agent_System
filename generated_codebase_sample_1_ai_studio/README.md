# AI Studio Browser-Automation Multi-Agent System

A modular Python system that drives the **Google AI Studio** web UI through Playwright
browser automation, plus an optional web-search crawler for grounding answers.

It exposes two flavors:

| Variant | Path | Use it for |
|---|---|---|
| **Standalone (single-file)** | `aistudio_agent.py` + `test_agent.py` | Quick experiments, ad-hoc prompts. |
| **Modular (multi-agent)** | `aistudio_system/` + `main.py` | Production pipeline that loops over SEARCH/FINAL ANSWER commands. |

> The modular version implements an orchestrator → brain (AI Studio) → web crawler loop.
> The standalone version implements just the brain.

## 1. Install

From the repository root (`../`):

```bash
pip install -r requirements.txt
playwright install chromium
```

Python 3.9+ recommended.
The shared virtualenv at the repo root (`../venv/`) is used by both sample codebases.
Activate it first:
```bash
source ../venv/bin/activate
```

## 2. Run the modular pipeline

```bash
python main.py
```

On the first run, a Chromium window opens. Sign in to your Google account when prompted.
Your session is then saved in `aistudio_system/aistudio_profile/` and subsequent runs can
be headless (set `HEADLESS = True` in `aistudio_system/config.py`).

## 3. Run the standalone agent

```bash
python test_agent.py
```

Once you are signed in, switch to headless by editing `test_agent.py`:

```python
agent = AIStudioAgent(headless=True)
```

## 4. Architecture

```
User Goal -> Orchestrator Loop -> PipelineMemory (history)
                                    |
                                    v
                              AI Studio Brain  (Playwright)
                                    |
                          SEARCH: <q> | FINAL ANSWER: <a>
                                    |
                                    v
                              Web Crawler (DuckDuckGo + scrape)
                                    |
                                    v
                          observations appended to PipelineMemory
```

See `aistudio_system/` for the clean separation of concerns:

- `core/` — interfaces, DTOs, custom exceptions
- `infrastructure/browser/` — Playwright session manager
- `infrastructure/agents/` — `AIStudioBrain` and `WebCrawler`
- `pipeline/` — `PipelineMemory` + `MultiAgentOrchestrator`
- `config.py` / `logger.py` — tunable knobs (selectors, timeouts, etc.)

## 5. Notes & Limitations

- Google frequently changes the AI Studio DOM. If scraping breaks, inspect the page
  and update `AI_STUDIO_BUBBLE_SELECTORS` / `AI_STUDIO_INPUT_SELECTORS` in
  `aistudio_system/config.py`.
- Headless login is intentionally not supported — you must complete the first login
  manually while the browser is visible.