# main.py
"""Application entrypoint for the multi-agent AI Studio system.

Run from the project root:
    python main.py
"""
import asyncio
import os
import sys

# Ensure the `aistudio_system/` package directory is on sys.path so the
# absolute imports inside it (e.g. ``from core.interfaces...``) resolve
# regardless of the user's current working directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
_AIS_PATH = os.path.join(_HERE, "aistudio_system")
if _AIS_PATH not in sys.path:
    sys.path.insert(0, _AIS_PATH)

from infrastructure.browser.playwright_manager import PlaywrightManager
from infrastructure.agents.aistudio_brain import AIStudioBrain
from infrastructure.agents.web_crawler import WebCrawler
from pipeline.orchestrator import MultiAgentOrchestrator
from logger import TraceLogger
from core.exceptions import AIStudioSystemException


async def main():
    logger = TraceLogger.get_logger("ApplicationEntry")
    logger.info("Initializing multi-agent system components...")

    # Instantiate infrastructure layers
    browser_manager = PlaywrightManager()
    brain_agent = AIStudioBrain(browser_manager)
    web_crawler = WebCrawler(browser_manager)

    # Instantiate orchestrator
    orchestrator = MultiAgentOrchestrator(brain=brain_agent, web=web_crawler)

    try:
        # Initialize browser context
        await browser_manager.initialize()

        # Run agent setup and check sign-in status
        await brain_agent.setup()

        # Orchestrate objective resolution
        target_objective = (
            "Find the release year of the movie 'Interstellar' and tell me "
            "the name of the director."
        )

        logger.info(f"Starting pipeline execution: '{target_objective}'")
        result_state = await orchestrator.run_pipeline(target_objective)

        print("\n" + "=" * 50)
        print("PIPELINE RESULT")
        print("=" * 50)
        print(f"Goal:         {result_state.goal}")
        print(f"Completed:    {result_state.completed}")
        print(f"Steps Taken:  {result_state.current_step}")
        print(f"Final Answer: \n{result_state.final_output}")
        print("=" * 50 + "\n")
    except AIStudioSystemException as system_err:
        logger.critical(f"A system boundary exception occurred: {system_err.message}")
    except Exception as general_err:
        logger.critical(f"An unexpected error occurred: {general_err}", exc_info=True)
    finally:
        # Gracefully shut down and clean up active browser resources
        logger.info("Shutting down and cleaning up browser processes...")
        await browser_manager.terminate()


if __name__ == "__main__":
    # Ensure modern event loop execution policies on all platforms
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())