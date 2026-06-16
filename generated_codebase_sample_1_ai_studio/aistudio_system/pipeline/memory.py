# pipeline/memory.py
from typing import List, Dict

class PipelineMemory:
    def __init__(self):
        self._history: List[Dict[str, str]] = []

    def register_system_goal(self, goal: str) -> None:
        self._history.append({
            "role": "objective",
            "content": f"The primary goal to satisfy: {goal}"
        })

    def register_model_thought(self, response_text: str) -> None:
        self._history.append({
            "role": "thought",
            "content": response_text
        })

    def register_environment_observation(self, observation: str) -> None:
        self._history.append({
            "role": "observation",
            "content": f"LIVE OBSERVATION REPORT:\n{observation}"
        })

    def generate_context_prompt(self) -> str:
        prompt_lines = [
            "You are an advanced, context-aware web-agent running via live browser automation.",
            "Analyze the historical timeline of thoughts and observations, and determine the next step.",
            "\n=== HISTORY OF TURNS ==="
        ]
        
        for index, step in enumerate(self._history):
            role_header = step["role"].upper()
            prompt_lines.append(f"\n[Turn {index} | {role_header}]\n{step['content']}")

        prompt_lines.extend([
            "\n========================",
            "INSTRUCTIONS FOR YOUR NEXT STEP:",
            "- If you need additional data from the web, respond with a search command using this exact format:",
            "  SEARCH: <query here>",
            "- If you need to create, generate, or modify a local file on the PC, use this XML-like format:",
            "  <write_file path=\"filename.ext\">",
            "  ... file content ...",
            "  </write_file>",
            "  You can write multiple files in a single turn if needed.",
            "- If you need to execute a command on the local machine (e.g., run a Python script, test a file, compile code), use this format:",
            "  <execute_command>",
            "  ... shell command ...",
            "  </execute_command>",
            "  Commands will be executed inside the local output directory.",
            "- If you have completed the task and all requested files are written/verified, output your final response prefixed exactly with:",
            "  FINAL ANSWER: <your answer detail>",
            "Strictly follow these instruction keywords to avoid parsing errors."
        ])
        
        return "\n".join(prompt_lines)