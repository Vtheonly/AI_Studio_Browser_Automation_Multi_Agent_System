# aistudio_system/pipeline/orchestrator.py
import re
from core.interfaces.orchestrator import IOrchestrator
from core.interfaces.agent import IBrainAgent, IWebAgent
from core.models import OrchestratorState, AgentPrompt, AgentResponse
from pipeline.memory import PipelineMemory
from logger import TraceLogger, generate_trace_id
import config


class MultiAgentOrchestrator(IOrchestrator):
    def __init__(self, brain: IBrainAgent, web: IWebAgent):
        self.logger = TraceLogger.get_logger("Orchestrator")
        self.brain = brain
        self.web = web

    async def run_pipeline(self, goal: str) -> OrchestratorState:
        trace_id = generate_trace_id()
        self.logger.info(f"[{trace_id}] Activating orchestration pipeline for goal: '{goal}'")

        state = OrchestratorState(goal=goal, trace_id=trace_id)
        memory = PipelineMemory()
        memory.add_user_goal(goal)

        # Main agent orchestration loop
        while state.current_step <= state.max_steps:
            self.logger.info(
                f"[{trace_id}] Starting step cycle {state.current_step}/{state.max_steps}"
            )

            # 1. Compile state into a conversational prompt
            current_prompt_text = memory.export_as_formatted_prompt()
            prompt_dto = AgentPrompt(text=current_prompt_text, trace_id=trace_id)

            # 2. Query the Brain Agent
            response_dto: AgentResponse = await self.brain.process_reasoning(prompt_dto)

            if not response_dto.success:
                self.logger.error(
                    f"[{trace_id}] Step reasoning failed: {response_dto.error_message}"
                )
                state.final_output = (
                    f"Failure during execution loop step {state.current_step}."
                )
                return state

            raw_brain_text = response_dto.text
            self.logger.debug(f"[{trace_id}] Raw Brain Agent response: \n{raw_brain_text}")
            memory.add_agent_turn(raw_brain_text)

            # 3. Parse action commands
            search_match = re.search(
                r"^SEARCH:\s*(.*)$", raw_brain_text, re.IGNORECASE | re.MULTILINE
            )
            final_match = re.search(
                r"^FINAL ANSWER:\s*(.*)$", raw_brain_text, re.IGNORECASE | re.MULTILINE
            )

            if final_match:
                answer = final_match.group(1).strip()
                self.logger.info(
                    f"[{trace_id}] Final answer resolved in {state.current_step} steps."
                )
                state.completed = True
                state.final_output = answer
                break
            elif search_match:
                search_query = search_match.group(1).strip()
                self.logger.info(
                    f"[{trace_id}] Action identified: Web Search -> '{search_query}'"
                )

                # Execute web crawler search
                search_results = await self.web.execute_search(search_query)

                if search_results:
                    # Scrape top search target
                    top_url = search_results[0]["url"]
                    scrape_data = await self.web.scrape_target(top_url)

                    if scrape_data.success:
                        self.logger.info(
                            f"[{trace_id}] Search results successfully retrieved and scraped."
                        )
                        observation_log = (
                            f"Results for '{search_query}': "
                            f"Source: {scrape_data.title} ({scrape_data.url}). "
                            f"Content: {scrape_data.text_content}"
                        )
                        memory.add_environment_turn(observation_log)
                    else:
                        memory.add_environment_turn(
                            f"Query was run but target page {top_url} failed to load."
                        )
                else:
                    memory.add_environment_turn(
                        f"Search run for '{search_query}' yielded zero index results."
                    )
            else:
                self.logger.warning(
                    f"[{trace_id}] No explicit instruction format matched. "
                    "Adding default correction turn."
                )
                memory.add_environment_turn(
                    "Please structure your output using exactly either: "
                    "'SEARCH: <query>' to get more context, "
                    "or 'FINAL ANSWER: <answer>' to complete the task."
                )

            state.current_step += 1

        if not state.completed:
            self.logger.warning(
                f"[{trace_id}] Execution loop finished without resolving a final answer."
            )
            state.final_output = (
                "Orchestrator did not resolve a final answer before reaching the max step limit."
            )
        return state