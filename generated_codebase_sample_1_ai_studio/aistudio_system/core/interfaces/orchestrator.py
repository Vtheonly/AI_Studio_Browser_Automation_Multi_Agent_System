# aistudio_system/core/interfaces/orchestrator.py
from abc import ABC, abstractmethod
from core.models import OrchestratorState


class IOrchestrator(ABC):
    @abstractmethod
    async def run_pipeline(self, goal: str) -> OrchestratorState:
        """Manages step-by-step resolution cycles to fulfill the user's objective."""
        pass