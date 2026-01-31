"""Shared utilities, logging setup, and constants for BottleneckWatch."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Application constants
APP_NAME = "BottleneckWatch"
APP_DATA_DIR = Path(os.environ.get("APPDATA", "")) / APP_NAME

# Ensure app data directory exists
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

# File paths
LOG_FILE = APP_DATA_DIR / "bottleneckwatch.log"
CONFIG_FILE = APP_DATA_DIR / "config.json"
DATABASE_FILE = APP_DATA_DIR / "history.db"

# Logging configuration
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] [%(threadName)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Icon configuration
ICON_SIZE = 64

# Pressure thresholds (defaults, overridden by config)
DEFAULT_YELLOW_THRESHOLD = 60
DEFAULT_RED_THRESHOLD = 80

# Colors (RGB tuples)
COLOR_GREEN = (76, 175, 80)    # Material Green 500
COLOR_YELLOW = (255, 193, 7)   # Material Amber 500
COLOR_RED = (244, 67, 54)      # Material Red 500
COLOR_WHITE = (255, 255, 255)

# Logger instance cache
_loggers: dict[str, logging.Logger] = {}
_logging_initialized = False


def setup_logging(level: int = logging.ERROR) -> None:
    """
    Initialize the logging system with file and console handlers.

    Args:
        level: The logging level (e.g., logging.ERROR, logging.INFO, logging.DEBUG)
               Default is ERROR for quiet operation.
    """
    global _logging_initialized

    if _logging_initialized:
        return

    # Create root logger for the application
    root_logger = logging.getLogger("bottleneckwatch")
    root_logger.setLevel(level)

    # Prevent propagation to root logger
    root_logger.propagate = False

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # File handler with rotation
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        # Fall back to console only if file logging fails
        print(f"Warning: Could not create log file: {e}", file=sys.stderr)

    # Console handler for development/debugging
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    _logging_initialized = True

    # Only log initialization message if verbose
    if level <= logging.INFO:
        root_logger.info(f"Logging initialized. Log file: {LOG_FILE}")


def set_log_level(verbose: bool) -> None:
    """
    Change the logging level at runtime.

    Args:
        verbose: If True, set level to INFO. If False, set level to ERROR.
    """
    level = logging.INFO if verbose else logging.ERROR
    root_logger = logging.getLogger("bottleneckwatch")
    root_logger.setLevel(level)

    # Update all handlers
    for handler in root_logger.handlers:
        handler.setLevel(level)

    if verbose:
        root_logger.info("Verbose logging enabled")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the specified module.

    Args:
        name: The name of the module (typically __name__)

    Returns:
        A configured logger instance
    """
    if name in _loggers:
        return _loggers[name]

    # Create child logger under bottleneckwatch namespace
    if name.startswith("bottleneckwatch.") or name == "bottleneckwatch":
        logger_name = name
    else:
        # Extract module name from full path
        module_name = name.split(".")[-1]
        logger_name = f"bottleneckwatch.{module_name}"

    logger = logging.getLogger(logger_name)
    _loggers[name] = logger

    return logger


def format_bytes(num_bytes: int) -> str:
    """
    Format bytes into human-readable string.

    Args:
        num_bytes: Number of bytes

    Returns:
        Formatted string (e.g., "4.2 GB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def format_percentage(value: float) -> str:
    """
    Format a percentage value.

    Args:
        value: Percentage value (0-100)

    Returns:
        Formatted string (e.g., "67.5%")
    """
    return f"{value:.1f}%"
