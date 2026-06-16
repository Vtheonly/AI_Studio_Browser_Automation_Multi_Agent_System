# AI Studio Web-UI Agent — Test Results

**Prompt:** `What is 2+2? Reply with just the number.`  
**Saved session existed:** False  
**Timestamp:** 2026-06-16 14:46:08  

## Summary

| PoC | Success | Latency (ms) | Failure mode |
|-----|---------|--------------|--------------|
| PoC1_AIStudioToAPI |  | 1670 | AUTH_WALL (article §1: Authentication & Session Breakage) |
| PoC2_MultiAgent |  | 3710 | AUTH_WALL (article §1: Authentication & Session Breakage) |
| PoC3_CDPGemini |  | 9986 | none |

## PoC1_AIStudioToAPI

- **Success:** False
- **Latency:** 1670 ms (wall: 1683 ms)
- **Error class:** `AUTH_WALL (article §1: Authentication & Session Breakage)`
- **Error:** `session_expired: bounced to Google sign-in. Re-run --relogin.`
- **Debug steps:**
  - navigated → https://accounts.google.com/v3/signin/identifier?continue=https%3A%2F%2Faistudio.google.com%2Fapp%2Fprompts%2Fnew_chat&dsh=S-651002449%3A1781621154318081&followup=https%3A%2F%2Faistudio.google.com%2Fapp%2Fprompts%2Fnew_chat&passive=1209600&flowName=GlifWebSignIn&flowEntry=ServiceLogin&ifkv=AcDsRvyhbYwJD72mt_k0DigdgyqL64dw4jn4iWUQ5V_gRX4vgOoZ_l32vINDeuGF1hj-4BJMXv4LBA

## PoC2_MultiAgent

- **Success:** False
- **Latency:** 3710 ms (wall: 3710 ms)
- **Error class:** `AUTH_WALL (article §1: Authentication & Session Breakage)`
- **Error:** `session_expired: bounced to Google sign-in. Re-run --relogin.`
- **Debug steps:**
  - navigated → https://accounts.google.com/v3/signin/identifier?continue=https%3A%2F%2Faistudio.google.com%2Fapp%2Fprompts%2Fnew_chat&dsh=S52700820%3A1781621157976701&followup=https%3A%2F%2Faistudio.google.com%2Fapp%2Fprompts%2Fnew_chat&passive=1209600&flowName=GlifWebSignIn&flowEntry=ServiceLogin&ifkv=AcDsRvygA_NePHlE37Jax4G9YHybCmHgVAqF9U0951AUiOovoTGG9LUx_c-5ieYS7qi-3y87-UMY
- **Trace:**
  - orchestrator: web_needed=True matched=['current']
  - orchestrator: invoking WebAgent.gather_info()
  - web_agent: fetched 0 pages in 3005ms
  - orchestrator: built final prompt (len=89)
  - orchestrator: invoking AIBrainAgent.ask() (PoC #1)
  - brain: error=session_expired: bounced to Google sign-in. Re-run --relogin. latency=693ms
- **Web needed:** True (matched: ['current'])
- **Final prompt (excerpt):** `Based on current public sources, briefly answer: What is 2+2? Reply with just the number.`

## PoC3_CDPGemini

- **Success:** True
- **Latency:** 9986 ms (wall: 9992 ms)
- **Error class:** `none`
- **Response (excerpt):**
  ```
  4
  ```
- **Debug steps:**
  - chrome launched with --remote-debugging-port
  - connected over CDP; contexts=1
  - page ready: https://gemini.google.com/app
  - prompt typed
  - clicked Send
  - response captured (len=1)

## What this means

If all three PoCs failed with `AUTH_WALL`: this is exactly the #1 failure mode the article predicts. In this sandbox, no human can complete Google's 2FA/CAPTCHA login flow, so `storage_state.json` is never created and every request bounces to `accounts.google.com`.

To actually get a successful response from any of the PoCs:
1. Run `python web_ui.py --port 8000` on a machine **with a display**.
2. The first request will launch a **headed** browser window.
3. Log into Google manually inside that window.
4. The session is saved to `session/storage_state.json` and reused.
5. Subsequent requests then run **headless** against the saved session — until Google expires it (article §1).
