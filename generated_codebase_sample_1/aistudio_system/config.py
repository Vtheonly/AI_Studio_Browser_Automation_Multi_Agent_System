# aistudio_system/config.py
import os
from typing import List

# Paths
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR: str = os.path.join(BASE_DIR, "aistudio_profile")

# Browser Configuration
HEADLESS: bool = False  # Set to False initially to complete human authentication
PAGE_TIMEOUT_MS: int = 45000
HUMAN_TYPING_DELAY_MS: int = 15

# Selector Configurations (Ordered by Priority/Resilience)
AI_STUDIO_INPUT_SELECTORS: List[str] = [
    "textarea",
    "div[contenteditable='true']",
    "ms-chat-input textarea",
    "textarea[placeholder*='message']",
    "[role='textbox']",
]

AI_STUDIO_BUBBLE_SELECTORS: List[str] = [
    "ms-chat-message",
    ".message-content",
    "div.markdown",
    ".model-response",
    "div.message",
    ".chat-message-text",
]

# Detection Ticks & Tuning
STREAM_STABILITY_SEC: float = 3.0
STREAM_POLL_INTERVAL_SEC: float = 0.5
MAX_GENERATION_TIMEOUT_SEC: int = 120

# Target Endpoints
AI_STUDIO_CHAT_URL: str = "https://aistudio.google.com/app/chat"
SEARCH_ENGINE_URL: str = "https://html.duckduckgo.com/html/"