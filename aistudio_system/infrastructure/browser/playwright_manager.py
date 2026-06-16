# aistudio_system/infrastructure/browser/playwright_manager.py
import asyncio
from playwright.async_api import async_playwright, BrowserContext, Page
from core.interfaces.browser import IBrowserManager
from core.exceptions import BrowserAutomationException
from logger import TraceLogger
import config


class PlaywrightManager(IBrowserManager):
    def __init__(self):
        self.logger = TraceLogger.get_logger("PlaywrightManager")
        self._playwright = None
        self._context = None
        self._primary_page = None

    async def initialize(self) -> None:
        self.logger.info("Starting browser automation infrastructure...")
        try:
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=config.PROFILE_DIR,
                headless=config.HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-position=0,0",
                ],
                no_viewport=True,
                ignore_https_errors=True,
            )
            # Default fallback timeout for all page elements
            self._context.set_default_timeout(config.PAGE_TIMEOUT_MS)

            pages = self._context.pages
            if pages:
                self._primary_page = pages[0]
            else:
                self._primary_page = await self._context.new_page()

            self.logger.info("Playwright persistent browser context initialized.")
        except Exception as e:
            self.logger.error(f"Failed to initialize browser context: {e}")
            raise BrowserAutomationException(f"Initialization failure: {str(e)}")

    async def get_context(self) -> BrowserContext:
        if not self._context:
            raise BrowserAutomationException("Context queried before initialization.")
        return self._context

    async def get_primary_page(self) -> Page:
        if not self._primary_page:
            raise BrowserAutomationException("Primary page queried before initialization.")
        return self._primary_page

    async def create_secondary_page(self) -> Page:
        if not self._context:
            raise BrowserAutomationException("Cannot spawn secondary tab without active context.")
        self.logger.debug("Creating auxiliary browser tab.")
        return await self._context.new_page()

    async def terminate(self) -> None:
        self.logger.info("Terminating browser sessions...")
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
            self.logger.info("All browser connections closed cleanly.")
        except Exception as e:
            self.logger.warning(f"Error during browser termination cleanup: {e}")