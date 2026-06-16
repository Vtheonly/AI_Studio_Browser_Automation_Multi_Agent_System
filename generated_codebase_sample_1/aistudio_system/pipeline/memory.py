# aistudio_system/pipeline/memory.py
from typing import List, Dict


class PipelineMemory:
    def __init__(self):
        self._history: List[Dict[str, str]] = []

    def add_user_goal(self, goal: str) -> None:
        self._history.append({
            "role": "system_goal",
            "content": f"The high-level user objective is: {goal}",
        })

    def add_agent_turn(self, raw_model_response: str) -> None:
        self._history.append({
            "role": "model_reasoning",
            "content": raw_model_response,
        })

    def add_environment_turn(self, observation: str) -> None:
        self._history.append({
            "role": "environment_observation",
            "content": f"OBSERVATION / WEB DATA EXTRACED: {observation}",
        })

    def export_as_formatted_prompt(self) -> str:
        """Converts internal trace steps into a clear prompt for the Brain Agent."""
        formatted_prompt = (
            "You are an advanced, autonomous agent system operating with live web-browsing capabilities.\n"
            "Below is the current history of decisions and data observations gathered so far. "
            "Examine this log and proceed with the next logical action.\n\n"
        )

        for index, item in enumerate(self._history):
            role_header = item["role"].upper().replace("_", " ")
            formatted_prompt += f"--- STEP {index} | {role_header} ---\n{item['content']}\n\n"

        formatted_prompt += (
            "INSTRUCTIONS FOR NEXT STEP:\n"
            "If you need more information from the web to answer the goal, output a command in this EXACT format:\n"
            "SEARCH: <your query search phrase>\n"
            "Then stop. Do not write additional commentary if you request search queries.\n\n"
            "If you have gathered enough factual data to fully answer the objective, output your final result prefixed with:\n"
            "FINAL ANSWER: <your comprehensive answer>\n"
        )
        return formatted_prompt