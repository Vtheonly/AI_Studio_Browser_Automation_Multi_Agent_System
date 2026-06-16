# aistudio_system/infrastructure/agents/aistudio_brain.py
import asyncio
import time
from core.interfaces.agent import IBrainAgent
from core.interfaces.browser import IBrowserManager
from core.models import AgentPrompt, AgentResponse
from core.exceptions import AuthenticationTimeoutException, ResponseExtractionException
from logger import TraceLogger
import config


class AIStudioBrain(IBrainAgent):
    def __init__(self, browser_manager: IBrowserManager):
        self.logger = TraceLogger.get_logger("AIStudioBrain")
        self.browser = browser_manager
        self.page = None

    async def setup(self) -> None:
        self.page = await self.browser.get_primary_page()
        self.logger.info(f"Navigating to AI Studio Chat endpoint: {config.AI_STUDIO_CHAT_URL}")
        await self.page.goto(config.AI_STUDIO_CHAT_URL, wait_until="domcontentloaded")
        await self._ensure_authenticated()

    async def _ensure_authenticated(self) -> None:
        self.logger.info("Validating AI Studio user session...")
        start_time = time.time()
        max_auth_wait = 180  # Provide up to 3 minutes for manual 2FA/login step

        while True:
            # Check for standard elements present only when logged in
            is_authenticated = False
            for selector in config.AI_STUDIO_INPUT_SELECTORS:
                try:
                    if await self.page.locator(selector).is_visible():
                        is_authenticated = True
                        break
                except Exception:
                    continue
            if is_authenticated:
                self.logger.info("Session verified. AI Studio Workspace is accessible.")
                break
            if time.time() - start_time > max_auth_wait:
                self.logger.error("User session verification timed out.")
                raise AuthenticationTimeoutException(
                    "User failed to authenticate inside AI Studio window."
                )
            self.logger.warning(
                "Waiting for workspace initialization... Please sign in if prompted."
            )
            await asyncio.sleep(5)

    async def process_reasoning(self, prompt: AgentPrompt) -> AgentResponse:
        self.logger.info(f"[{prompt.trace_id}] Processing reasoning pipeline...")
        start_time = time.time()

        try:
            # 1. Resolve input locator
            input_selector = await self._find_active_selector(config.AI_STUDIO_INPUT_SELECTORS)
            if not input_selector:
                raise ResponseExtractionException(
                    "No valid input container was found on the current DOM."
                )

            # 2. Focus and reset focus container
            await self.page.focus(input_selector)
            await self.page.keyboard.down("Control")
            await self.page.keyboard.press("KeyA")
            await self.page.keyboard.up("Control")
            await self.page.keyboard.press("Backspace")

            # 3. Type humanized prompt contents
            self.logger.debug(f"[{prompt.trace_id}] Populating prompt text container.")
            await self.page.type(input_selector, prompt.text, delay=config.HUMAN_TYPING_DELAY_MS)

            # 4. Fire trigger to submit interaction
            self.logger.debug(f"[{prompt.trace_id}] Triggering prompt submission.")
            await self.page.keyboard.press("Enter")

            # 5. Monitor stream stabilization
            output_text = await self._wait_for_stream_completion(prompt.trace_id)

            elapsed = time.time() - start_time
            self.logger.info(
                f"[{prompt.trace_id}] Generation completed in {elapsed:.2f} seconds."
            )
            return AgentResponse(
                text=output_text,
                trace_id=prompt.trace_id,
                success=True,
                execution_time_sec=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(f"[{prompt.trace_id}] Failed during logic reasoning flow: {e}")
            return AgentResponse(
                text="",
                trace_id=prompt.trace_id,
                success=False,
                execution_time_sec=elapsed,
                error_message=str(e),
            )

    async def _find_active_selector(self, selectors_list: list) -> str:
        """Iterates through prioritized selector fallbacks to find a visible match."""
        for selector in selectors_list:
            try:
                if await self.page.locator(selector).is_visible():
                    return selector
            except Exception:
                continue
        return ""

    async def _wait_for_stream_completion(self, trace_id: str) -> str:
        """Polls the DOM to extract the latest message content and waits for it to stabilize."""
        self.logger.debug(f"[{trace_id}] Waiting for stream generation to settle...")
        await asyncio.sleep(3.0)  # Initial latency delay

        last_extracted_text = ""
        seconds_unchanged = 0.0
        start_time = time.time()
        while True:
            # Check timeout guard rail
            if time.time() - start_time > config.MAX_GENERATION_TIMEOUT_SEC:
                self.logger.warning(
                    f"[{trace_id}] Generation reached strict timeout ceiling. Cutting process."
                )
                break

            current_text = await self._scrape_latest_bubble()

            if current_text == last_extracted_text and len(current_text) > 0:
                seconds_unchanged += config.STREAM_POLL_INTERVAL_SEC
                if seconds_unchanged >= config.STREAM_STABILITY_SEC:
                    self.logger.debug(f"[{trace_id}] Output stream has stabilized.")
                    break
            else:
                last_extracted_text = current_text
                seconds_unchanged = 0.0

            await asyncio.sleep(config.STREAM_POLL_INTERVAL_SEC)

        if not last_extracted_text:
            raise ResponseExtractionException(
                "No generated text could be parsed from the latest response bubble."
            )
        return last_extracted_text

    async def _scrape_latest_bubble(self) -> str:
        """Executes context evaluation scripts on the DOM using registered selectors."""
        selectors_json = config.AI_STUDIO_BUBBLE_SELECTORS
        try:
            extracted = await self.page.evaluate(
                """
                (selectors) => {
                    for (const sel of selectors) {
                        const items = document.querySelectorAll(sel);
                        if (items && items.length > 0) {
                            return items[items.length - 1].innerText;
                        }
                    }
                    // Generic fallback for any markdown element under the main content container
                    const chatView = document.querySelector('ms-chat-view');
                    if (chatView) {
                        const divs = chatView.querySelectorAll('.markdown');
                        if (divs && divs.length > 0) {
                            return divs[divs.length - 1].innerText;
                        }
                    }
                    return "";
                }
            """,
                selectors_json,
            )
            return extracted.strip()
        except Exception:
            return ""