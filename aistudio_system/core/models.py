# aistudio_system/core/models.py
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class AgentPrompt:
    text: str
    trace_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    text: str
    trace_id: str
    success: bool
    execution_time_sec: float
    error_message: Optional[str] = None


@dataclass
class WebResult:
    url: str
    title: str
    raw_content: str
    text_content: str
    success: bool
    error_message: Optional[str] = None


@dataclass
class OrchestratorState:
    goal: str
    trace_id: str
    history: List[Dict[str, str]] = field(default_factory=list)
    current_step: int = 1
    max_steps: int = 5
    completed: bool = False
    final_output: Optional[str] = None