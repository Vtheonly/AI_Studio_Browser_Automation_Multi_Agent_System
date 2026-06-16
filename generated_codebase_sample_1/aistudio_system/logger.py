# aistudio_system/logger.py
import logging
import sys
import uuid


class TraceLogger:
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        if not logger.hasHandlers():
            logger.setLevel(logging.DEBUG)

            # Format logs to capture timestamps, levels, filenames, lines, and messages
            formatter = logging.Formatter(
                fmt="%(asctime)s - [%(levelname)s] - [%(name)s] - (%(filename)s:%(lineno)d) - %(message)s"
            )

            # Stream Handler (Stdout)
            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setFormatter(formatter)
            stdout_handler.setLevel(logging.INFO)
            logger.addHandler(stdout_handler)

            # File Handler for deep traces
            file_handler = logging.FileHandler("system_trace.log", encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)
            logger.addHandler(file_handler)

        return logger


def generate_trace_id() -> str:
    """Generates a tracking identifier for single request-response flows."""
    return str(uuid.uuid4())[:8]