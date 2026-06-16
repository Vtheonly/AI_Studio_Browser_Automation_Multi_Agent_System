# aistudio_system/core/interfaces/agent.py
from abc import ABC, abstractmethod
from core.models import AgentPrompt, AgentResponse, WebResult


class IBrainAgent(ABC):
    @abstractmethod
    async def setup(self) -> None:
        """Configures operational constraints and establishes visual target check."""
        pass

    @abstractmethod
    async def process_reasoning(self, prompt: AgentPrompt) -> AgentResponse:
        """Interfaces with the dynamic model page to extract structured text plans."""
        pass


class IWebAgent(ABC):
    @abstractmethod
    async def execute_search(self, query: str) -> list:
        """Queries public indexers for reference pages."""
        pass

    @abstractmethod
    async def scrape_target(self, url: str) -> WebResult:
        """Visits remote targets safely and isolates high-value textual sections."""
        pass