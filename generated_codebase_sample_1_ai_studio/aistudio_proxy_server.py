# aistudio_proxy_server.py
import asyncio
import time
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uvicorn

from infrastructure.browser.playwright_manager import PlaywrightManager
from infrastructure.agents.aistudio_brain import AIStudioBrain
from core.models import AgentPrompt, AgentResponse
from logger import TraceLogger
import config

# Initialize FastAPI App
app = FastAPI(title="AI Studio OpenAI-Compatible Relay Proxy")
logger = TraceLogger.get_logger("ProxyServer")

# Global instances
browser_manager = PlaywrightManager()
brain_agent = AIStudioBrain(browser_manager)


# Pydantic Schemas matching OpenAI Specification
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 1.0
    stream: Optional[bool] = False


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
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible endpoint that forwards chat requests to the web UI."""
    trace_id = str(uuid.uuid4())[:8]
    logger.info(f"[{trace_id}] Received chat completion request via API proxy.")

    if not request.messages:
        raise HTTPException(status_code=400, detail="Messages array cannot be empty.")

    # Compile message history into a clear prompt for the web UI
    compiled_prompt = ""
    for msg in request.messages:
        role_label = msg.role.upper()
        compiled_prompt += f"[{role_label}]: {msg.content}\n\n"
    
    compiled_prompt += "[INSTRUCTIONS]: Formulate your response now based on the conversation history."

    # Send compiled prompt to the automated browser brain
    prompt_dto = AgentPrompt(text=compiled_prompt, trace_id=trace_id)
    response_dto: AgentResponse = await brain_agent.process_reasoning(prompt_dto)

    if not response_dto.success:
        logger.error(f"[{trace_id}] Browser automation error: {response_dto.error_message}")
        raise HTTPException(status_code=500, detail=response_dto.error_message)

    # Format the scraped response to match OpenAI's output standard
    response_payload = {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
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
            "prompt_tokens": -1,  # Tokens are unmetered in the web UI
            "completion_tokens": -1,
            "total_tokens": -1
        }
    }
    
    logger.info(f"[{trace_id}] Request processed successfully. Returning completion payload.")
    return response_payload


@app.get("/v1/models")
async def get_models():
    """Returns a dummy list of supported models to satisfy standard agentic client checks."""
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