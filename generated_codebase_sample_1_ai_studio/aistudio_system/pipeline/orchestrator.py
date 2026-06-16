# pipeline/orchestrator.py
import os
import re
import asyncio
import subprocess
from core.interfaces.orchestrator import IOrchestrator
from core.interfaces.agent import IBrainAgent, IWebAgent
from core.models import OrchestratorState, AgentPrompt, AgentResponse
from pipeline.memory import PipelineMemory
from logger import TraceLogger, generate_trace_id

class MultiAgentOrchestrator(IOrchestrator):
    def __init__(self, brain: IBrainAgent, web: IWebAgent):
        self.logger = TraceLogger.get_logger("Orchestrator")
        self.brain = brain
        self.web = web
        # Establish local output folder for synthesized files
        self.output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

    async def run_pipeline(self, goal: str) -> OrchestratorState:
        trace_id = generate_trace_id()
        self.logger.info(f"[{trace_id}] Executing orchestration loop for goal: '{goal}'")
        
        # Ensure output directory exists on local disk
        os.makedirs(self.output_dir, exist_ok=True)
        self.logger.info(f"[{trace_id}] Local output folder established at: {self.output_dir}")

        state = OrchestratorState(goal=goal, trace_id=trace_id)
        memory = PipelineMemory()
        memory.register_system_goal(goal)

        while state.current_step <= state.max_steps:
            self.logger.info(f"[{trace_id}] Processing turn {state.current_step}/{state.max_steps}")
            
            prompt_text = memory.generate_context_prompt()
            prompt_dto = AgentPrompt(text=prompt_text, trace_id=trace_id)

            response_dto: AgentResponse = await self.brain.process_reasoning(prompt_dto)

            if not response_dto.success:
                error_msg = response_dto.error_message or "Unknown interaction failure."
                self.logger.error(f"[{trace_id}] Step reasoning failed: {error_msg}")
                state.final_output = f"Execution paused on step {state.current_step} due to system error: {error_msg}"
                return state

            raw_output = response_dto.text
            self.logger.debug(f"[{trace_id}] Extracted response content:\n{raw_output}")
            memory.register_model_thought(raw_output)

            # Parsers for actions
            search_match = re.search(r"^SEARCH:\s*(.*)$", raw_output, re.IGNORECASE | re.MULTILINE)
            final_match = re.search(r"^FINAL ANSWER:\s*(.*)$", raw_output, re.IGNORECASE | re.MULTILINE)
            
            # File system write parser
            file_pattern = re.compile(r'<write_file\s+path=["\']([^"\']+)["\']>(.*?)</write_file>', re.DOTALL | re.IGNORECASE)
            file_writes = file_pattern.findall(raw_output)

            # Local command execution parser
            cmd_pattern = re.compile(r'<execute_command>(.*?)</execute_command>', re.DOTALL | re.IGNORECASE)
            cmd_executions = cmd_pattern.findall(raw_output)

            observation_buffer = []

            # Step A: Process written files
            if file_writes:
                for filename, file_content in file_writes:
                    filename = os.path.basename(filename.strip())
                    target_path = os.path.join(self.output_dir, filename)
                    cleaned_content = file_content.strip()
                    
                    try:
                        with open(target_path, "w", encoding="utf-8") as f:
                            f.write(cleaned_content)
                        self.logger.info(f"[{trace_id}] Wrote file to local directory: {target_path}")
                        observation_buffer.append(f"System: Successfully wrote file: '{filename}' ({len(cleaned_content)} chars)")
                    except Exception as write_err:
                        self.logger.error(f"[{trace_id}] File system write failed for {filename}: {write_err}")
                        observation_buffer.append(f"System Error: Failed to write '{filename}': {str(write_err)}")

            # Step B: Process shell execution commands safely
            if cmd_executions:
                for raw_cmd in cmd_executions:
                    cmd = raw_cmd.strip()
                    self.logger.info(f"[{trace_id}] Executing local terminal command: '{cmd}'")
                    
                    try:
                        # Run the command with a timeout to prevent hanging on interactive inputs or servers
                        result = subprocess.run(
                            cmd,
                            shell=True,
                            text=True,
                            capture_output=True,
                            timeout=15,
                            cwd=self.output_dir
                        )
                        cmd_output = (
                            f"Command executed: '{cmd}'\n"
                            f"Exit Code: {result.returncode}\n"
                            f"STDOUT:\n{result.stdout if result.stdout else '[Empty Output]'}\n"
                            f"STDERR:\n{result.stderr if result.stderr else '[Empty Errors]'}"
                        )
                        observation_buffer.append(cmd_output)
                        self.logger.info(f"[{trace_id}] Command completed (Exit Code: {result.returncode})")
                    except subprocess.TimeoutExpired:
                        self.logger.warning(f"[{trace_id}] Command execution timed out: '{cmd}'")
                        observation_buffer.append(f"System Error: Command timed out after 15 seconds.")
                    except Exception as exec_err:
                        self.logger.error(f"[{trace_id}] Local execution engine failed: {exec_err}")
                        observation_buffer.append(f"System Error: Command execution failed: {str(exec_err)}")

            # Register combined file and command execution outcomes back to AI context
            if observation_buffer:
                memory.register_environment_observation("\n\n".join(observation_buffer))

            elif final_match:
                answer = final_match.group(1).strip()
                self.logger.info(f"[{trace_id}] Final answer extracted successfully.")
                state.completed = True
                state.final_output = answer
                break

            elif search_match:
                search_query = search_match.group(1).strip()
                self.logger.info(f"[{trace_id}] Executing web lookup: '{search_query}'")
                
                results = await self.web.execute_search(search_query)
                if results:
                    target_url = results[0]["url"]
                    scrape_result = await self.web.scrape_target(target_url)
                    
                    if scrape_result.success:
                        observation_log = (
                            f"Retrieved from {scrape_result.title} ({scrape_result.url}):\n"
                            f"{scrape_result.text_content}"
                        )
                        memory.register_environment_observation(observation_log)
                    else:
                        memory.register_environment_observation(
                            f"Failed to access the primary search result URL: {target_url}"
                        )
                else:
                    memory.register_environment_observation(
                        f"Search engine returned 0 results for the query: '{search_query}'"
                    )

            else:
                self.logger.warning(f"[{trace_id}] AI response format mismatch. Prompting format correction.")
                memory.register_environment_observation(
                    "Error: Your response did not trigger a known command. You must respond using "
                    "exactly either 'SEARCH: <query>', '<write_file path=\"...\">...</write_file>', "
                    "'<execute_command>...</execute_command>', or 'FINAL ANSWER: <your answer>'."
                )

            state.current_step += 1

        if not state.completed:
            self.logger.warning(f"[{trace_id}] Step limit reached before final answer was obtained.")
            state.final_output = "Task aborted: Max step limit reached."

        return state