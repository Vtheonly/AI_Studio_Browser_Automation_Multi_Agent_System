# aistudio_system/core/interfaces/browser.py
from abc import ABC, abstractmethod
from playwright.async_api import BrowserContext, Page


class IBrowserManager(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        """Starts browser binaries and prepares session contexts."""
        pass

    @abstractmethod
    async def get_context(self) -> BrowserContext:
        """Retrieves active browser context."""
        pass

    @abstractmethod
    async def get_primary_page(self) -> Page:
        """Retrieves primary operating page."""
        pass

    @abstractmethod
    async def create_secondary_page(self) -> Page:
        """Spawns an auxiliary tab or page to prevent main workspace interference."""
        pass

    @abstractmethod
    async def terminate(self) -> None:
        """Gracefully shuts down running processes."""
        pass