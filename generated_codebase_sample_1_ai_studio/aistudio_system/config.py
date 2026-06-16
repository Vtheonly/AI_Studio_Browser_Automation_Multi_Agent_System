# config.py
import os
from typing import List

# File Paths
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR: str = os.path.join(BASE_DIR, "aistudio_profile")

# Browser Configuration
HEADLESS: bool = False  # Set to False initially to complete human authentication
PAGE_TIMEOUT_MS: int = 60000
MAX_LOGIN_GRACE_PERIOD_SEC: int = 180

# Human Simulation Parameters
HUMAN_TYPING_ERROR_RATE: float = 0.01
HUMAN_KEYPRESS_MIN_SEC: float = 0.01
HUMAN_KEYPRESS_MAX_SEC: float = 0.05
INTER_COMMAND_JITTER_MIN_SEC: float = 1.0
INTER_COMMAND_JITTER_MAX_SEC: float = 3.0

# Selectors
AI_STUDIO_INPUT_SELECTORS: List[str] = [
    'textarea[aria-label="Type something"]',
    "ms-chat-input textarea",
    "textarea[placeholder*='Type']",
    "textarea[placeholder*='message']",
    "div[contenteditable='true']",
    "textarea",
    "[role='textbox']"
]

AI_STUDIO_BUBBLE_SELECTORS: List[str] = [
    "ms-chat-message",
    ".message-content",
    "div.markdown",
    ".model-response",
    "div.message",
    ".chat-message-text"
]

AI_STUDIO_STOP_INDICATORS: List[str] = [
    "button:has-text('Stop')",
    "button:has-text('Cancel')",
    "button[aria-label*='Stop']",
    ".generating",
    "ms-stop-button"
]

# Tuning
STREAM_STABILITY_SEC: float = 3.0
STREAM_POLL_INTERVAL_SEC: float = 0.5
MAX_GENERATION_TIMEOUT_SEC: int = 120

# Endpoints
AI_STUDIO_CHAT_URL: str = "https://aistudio.google.com/app/chat"
SEARCH_ENGINE_URL: str = "https://html.duckduckgo.com/html/"

# Proxy Server settings
PROXY_HOST: str = "127.0.0.1"
PROXY_PORT: int = 8000