"""
Logging configuration for visual tracking modules.
Sets up debug logging to both console and file.
"""
import logging
import sys
from pathlib import Path


def setup_logging(log_file: str = "eye_tracking_debug.log", level=logging.DEBUG):
    """
    Configure logging for all visual tracking modules.

    Args:
        log_file: Path to debug log file
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    # Create logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler (INFO level)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (DEBUG level - full details)
    log_path = Path(log_file)
    file_handler = logging.FileHandler(log_path, mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Log startup
    root_logger.info(f"Logging initialized - Debug log: {log_path.absolute()}")

    return root_logger
