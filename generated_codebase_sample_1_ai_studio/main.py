# main.py
import asyncio
from openai import AsyncOpenAI
from logger import TraceLogger
import config

async def main():
    logger = TraceLogger.get_logger("ClientApp")
    logger.info("Initializing test client connected to local API relay...")

    # Point the client to your local proxy server instead of Google or OpenAI's servers
    client = AsyncOpenAI(
        base_url=f"http://{config.PROXY_HOST}:{config.PROXY_PORT}/v1",
        api_key="sk-dummy-key-not-required-for-web-ui"
    )

    objective = (
        "Write a clean Python function that checks if a given number is prime. "
        "Include docstrings and a brief usage example."
    )

    logger.info(f"Sending objective to local proxy: '{objective}'")
    
    try:
        response = await client.chat.completions.create(
            model="gemini-2.5-pro",
            messages=[
                {"role": "user", "content": objective}
            ]
        )
        
        print("\n" + "="*60)
        print("RESPONSE RETRIEVED VIA API PROXY RELAY")
        print("="*60)
        print(response.choices[0].message.content)
        print("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"Failed to communicate with local proxy server: {e}")

if __name__ == "__main__":
    asyncio.run(main())