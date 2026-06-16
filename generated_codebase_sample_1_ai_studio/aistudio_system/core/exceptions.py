# aistudio_system/core/exceptions.py


class AIStudioSystemException(Exception):
    """Base exception class for all custom system errors."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BrowserAutomationException(AIStudioSystemException):
    """Raised when basic Playwright or browser interaction flows break down."""

    pass


class AuthenticationTimeoutException(AIStudioSystemException):
    """Raised when authentication is not completed within the grace period."""

    pass


class ResponseExtractionException(AIStudioSystemException):
    """Raised when scraping mechanisms fail to extract response structures from the DOM."""

    pass


class PipelineException(AIStudioSystemException):
    """Raised when execution flows inside the orchestrator or agent steps break down."""

    pass