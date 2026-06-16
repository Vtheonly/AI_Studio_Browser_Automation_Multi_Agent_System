# aistudio_proxy_server.py
import sys
import os

# Dynamic path resolution to prevent ModuleNotFoundError
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.join(current_dir, "aistudio_system"))

import asyncio
import time
import uuid
from fastapi import FastAPI, HTTPException
from typing import List, Dict, Any, Optional
import uvicorn

from infrastructure.browser.playwright_manager import PlaywrightManager
from infrastructure.agents.aistudio_brain import AIStudioBrain
from core.models import AgentPrompt
from logger import TraceLogger
import config

# Initialize FastAPI App
app = FastAPI(title="AI Studio OpenAI-Compatible Relay Proxy")
logger = TraceLogger.get_logger("ProxyServer")

# Global instances
browser_manager = PlaywrightManager()
brain_agent = AIStudioBrain(browser_manager)

@app.on_event("startup")
async def startup_event():
    """Initializes the browser and validates the AI Studio workspace on server start."""
    logger.info("Initializing background automated browser session...")
    await browser_manager.initialize()
    await brain_agent.setup()
    logger.info("Local relay server is armed and ready.")

@app.on_event("shutdown")
async def shutdown_event():
    """Safely terminates browser processes on server shutdown."""
    logger.info("Shutting down background browser session...")
    await browser_manager.terminate()

@app.post("/v1/chat/completions")
async def chat_completions(request: Dict[str, Any]):
    """
    OpenAI-compatible endpoint that accepts raw request dictionaries.
    To prevent multi-turn anti-bot detection and desync issues, this server
    reloads the workspace on every single request and submits the entire history
    compiled into a single, unified text prompt.
    """
    trace_id = str(uuid.uuid4())[:8]
    logger.info(f"[{trace_id}] Received chat completion request via API proxy.")

    messages = request.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="Missing or invalid 'messages' list in request payload.")

    model = request.get("model", "gemini-2.5")

    # 1. Stateless Sync: Reload the workspace on EVERY single request to ensure clean DOM and state
    logger.info(f"[{trace_id}] Resetting AI Studio workspace to a clean, stateless tab.")
    if hasattr(brain_agent, "reset_chat"):
        await brain_agent.reset_chat()
    else:
        # Fallback if subclass does not contain reset_chat yet
        page = await browser_manager.get_primary_page()
        await page.goto(config.AI_STUDIO_CHAT_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2.0)

    # 2. Compile the ENTIRE message history into a single, unified mega-prompt
    compiled_prompt = (
        "You are Cline, a highly skilled software engineer working in a local development environment. "
        "Below is the complete state, tool execution logs, and conversation history of our active session. "
        "Review the history, logs, and observations below, and formulate your NEXT step or action.\n\n"
        "=== SYSTEM CONTEXT AND CONVERSATION HISTORY ===\n\n"
    )
    
    for msg in messages:
        role_label = str(msg.get("role", "user")).upper()
        content_val = msg.get("content")
        parsed_txt = _extract_text_content(content_val)
        
        # Format the turn within the single block
        compiled_prompt += f"--- {role_label} TURN ---\n{parsed_txt}\n\n"
        
    compiled_prompt += (
        "=== END OF HISTORY ===\n\n"
        "[INSTRUCTIONS]: You must formulate your next response as Cline. "
        "If you need to use tools, write them clearly. If you have finished, summarize your results."
    )

    # 3. Send the single prompt to the automated browser brain
    prompt_dto = AgentPrompt(text=compiled_prompt, trace_id=trace_id)
    response_dto = await brain_agent.process_reasoning(prompt_dto)

    if not response_dto.success:
        logger.error(f"[{trace_id}] Browser automation error: {response_dto.error_message}")
        raise HTTPException(status_code=500, detail=response_dto.error_message)

    # Format output payload
    response_payload = {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_dto.text
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": -1,
            "completion_tokens": -1,
            "total_tokens": -1
        }
    }
    
    logger.info(f"[{trace_id}] Request successfully completed in a single turn.")
    return response_payload

def _extract_text_content(content_val: Any) -> str:
    """Helper utility to extract clean string data from complex/multimodal payloads."""
    if isinstance(content_val, str):
        return content_val
    elif isinstance(content_val, list):
        text_accumulator = []
        for block in content_val:
            if isinstance(block, dict) and block.get("type") == "text":
                text_accumulator.append(str(block.get("text", "")))
        return "\n".join(text_accumulator)
    return ""

@app.get("/v1/models")
async def get_models():
    """Returns a dummy list of supported models to satisfy standard client checks."""
    return {
        "object": "list",
        "data": [
            {"id": "gemini-2.5-pro", "object": "model", "owned_by": "google"},
            {"id": "gemini-2.5-flash", "object": "model", "owned_by": "google"}
        ]
    }

def start_server():
    uvicorn.run(
        "aistudio_proxy_server:app",
        host=config.PROXY_HOST,
        port=config.PROXY_PORT,
        log_level="info"
    )

if __name__ == "__main__":
    start_server()