"""
Standalone (single-file) version of the AI Studio browser-automation agent.
Use this for quick local experiments. The modular version lives in
the `aistudio_system/` directory.
"""
import asyncio
import os
from playwright.async_api import async_playwright


class AIStudioAgent:
    def __init__(self, profile_dir="./aistudio_profile", headless=False):
        self.profile_dir = os.path.abspath(profile_dir)
        self.headless = headless
        self.playwright = None
        self.context = None
        self.page = None

    async def start(self):
        """Initializes the browser session using a persistent user profile."""
        self.playwright = await async_playwright().start()

        # Launching with a persistent context saves your login session
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
            no_viewport=True,
        )
        self.page = await self.context.new_page()

        # Direct link to the Chat interface, which is ideal for multi-turn conversations
        await self.page.goto("https://aistudio.google.com/app/chat", wait_until="domcontentloaded")

    async def check_auth(self):
        """
        Checks if the workspace is loaded. If a login screen is detected,
        pauses to allow the user to log in manually.
        """
        print("Checking Google authentication status...")
        print("If a login prompt appears in the browser, please sign in manually.")

        while True:
            # Check for standard elements present only when logged in
            is_input_visible = (
                await self.page.locator("textarea").is_visible()
                or await self.page.get_by_placeholder("Type a message").is_visible()
                or await self.page.get_by_role("textbox").is_visible()
            )
            if is_input_visible:
                print("Workspace detected. Authentication successful.")
                break
            await asyncio.sleep(2)

    async def send_prompt(self, prompt_text: str) -> str:
        """
        Sends a prompt to the AI Studio interface and scrapes the output
        once generation is complete.
        """
        input_selector = "textarea"
        try:
            await self.page.wait_for_selector(input_selector, timeout=10000)
        except Exception:
            # Fallback to general textbox role if the element structure shifts
            input_selector = '[role="textbox"]'
            await self.page.wait_for_selector(input_selector, timeout=5000)

        # Clear any residue in the text area
        await self.page.focus(input_selector)
        await self.page.keyboard.down("Control")
        await self.page.keyboard.press("KeyA")
        await self.page.keyboard.up("Control")
        await self.page.keyboard.press("Backspace")

        # Type the prompt simulating natural human speed slightly to avoid rapid trigger flags
        await self.page.type(input_selector, prompt_text, delay=10)

        # Submit the prompt via keyboard input
        await self.page.keyboard.press("Enter")

        # Give the UI a moment to register and start streaming
        await asyncio.sleep(3)

        # Polling loop to extract text and detect when the model has stopped writing
        last_text = ""
        stable_ticks = 0
        max_wait = 90  # Seconds
        for _ in range(max_wait):
            current_text = await self._get_latest_bubble()

            # If text has stopped growing and we actually have captured characters, count stability
            if current_text == last_text and len(current_text) > 0:
                stable_ticks += 1
                if stable_ticks >= 3:  # No changes for 3 seconds indicates generation finished
                    break
            else:
                last_text = current_text
                stable_ticks = 0

            await asyncio.sleep(1)
        return last_text

    async def _get_latest_bubble(self) -> str:
        """Extracts the text of the newest model response from the page DOM."""
        try:
            text = await self.page.evaluate('''() => {
                const bubbles = document.querySelectorAll(
                    'ms-chat-message, .message-content, .markdown, .model-response'
                );
                if (bubbles.length > 0) {
                    return bubbles[bubbles.length - 1].innerText;
                }

                // Fallback to reading the general message containers
                const fallbackContainer = document.querySelector('ms-chat-view, .conversation-container');
                if (fallbackContainer) {
                    return fallbackContainer.innerText;
                }
                return "";
            }''')
            return text.strip()
        except Exception:
            return ""

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()