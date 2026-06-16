"""
Standalone test script for the single-file AIStudioAgent.
Run once with headless=False to log in manually, then you can switch to headless=True.
"""
import asyncio
from aistudio_agent import AIStudioAgent


async def run_test():
    # Keep headless=False so you can watch the automation and complete the login
    agent = AIStudioAgent(headless=False)

    try:
        await agent.start()
        await agent.check_auth()

        # Test Query
        test_prompt = "Translate the word 'Environment' into Spanish. Return only the single translated word."
        print(f"\nSending test prompt: '{test_prompt}'")

        response = await agent.send_prompt(test_prompt)

        print("\n--- Scraped Response ---")
        print(response)
        print("------------------------")

        if response and ("medio" in response.lower() or "ambiente" in response.lower()):
            print("Test Status: SUCCESS. Scraped content matches expectation.")
        else:
            print("Test Status: FAILED/UNVERIFIED. Output was empty or did not match expected translation.")

    except Exception as e:
        print(f"An error occurred during testing: {e}")
    finally:
        # Keep browser open for a few seconds before closing
        await asyncio.sleep(5)
        await agent.close()


if __name__ == "__main__":
    asyncio.run(run_test())