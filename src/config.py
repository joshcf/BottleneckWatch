"""Configuration management for BottleneckWatch."""

import json
from pathlib import Path
from typing import Any, Optional

from .utils import get_logger, CONFIG_FILE

logger = get_logger(__name__)

# Default configuration values from CLAUDE.md specification
DEFAULT_CONFIG = {
    "sampling_frequency_seconds": 5,
    "smoothing_window_minutes": 5,
    "minimum_pressure_duration_seconds": 30,
    "thresholds": {
        "yellow": 60,
        "red": 80
    },
    "metric_weights": {
        "page_faults": 0.5,
        "available_ram": 0.3,
        "committed_ratio": 0.2
    },
    "data_retention_days": 30,
    "auto_start": False,
    "verbose_logging": False
}


class ConfigManager:
    """Manages application configuration with JSON persistence."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        """
        Initialize the configuration manager.

        Args:
            config_path: Optional custom path for config file
        """
        self.config_path = config_path or CONFIG_FILE
        self._config: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load configuration from file, creating defaults if needed."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)

                # Merge with defaults to ensure all keys exist
                self._config = self._merge_defaults(loaded_config)
                logger.info(f"Configuration loaded from {self.config_path}")

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in config file: {e}")
                logger.info("Using default configuration")
                self._config = DEFAULT_CONFIG.copy()
                self._save()

            except Exception as e:
                logger.error(f"Error loading config: {e}", exc_info=True)
                self._config = DEFAULT_CONFIG.copy()

        else:
            logger.info("No config file found, creating with defaults")
            self._config = DEFAULT_CONFIG.copy()
            self._save()

    def _merge_defaults(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """
        Merge loaded config with defaults, preserving loaded values.

        Args:
            loaded: The loaded configuration dict

        Returns:
            Merged configuration with all required keys
        """
        result = DEFAULT_CONFIG.copy()

        for key, value in loaded.items():
            if key in result:
                if isinstance(value, dict) and isinstance(result[key], dict):
                    # Merge nested dicts
                    result[key] = {**result[key], **value}
                else:
                    result[key] = value
            else:
                # Keep unknown keys for forward compatibility
                result[key] = value

        return result

    def _save(self) -> None:
        """Save current configuration to file."""
        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)

            logger.info(f"Configuration saved to {self.config_path}")

        except Exception as e:
            logger.error(f"Error saving config: {e}", exc_info=True)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            key: The configuration key (supports dot notation for nested keys)
            default: Default value if key not found

        Returns:
            The configuration value or default
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any, save: bool = True) -> None:
        """
        Set a configuration value.

        Args:
            key: The configuration key (supports dot notation for nested keys)
            value: The value to set
            save: Whether to persist to file immediately
        """
        keys = key.split(".")
        config = self._config

        # Navigate to parent of target key
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        old_value = config.get(keys[-1])
        config[keys[-1]] = value

        logger.info(f"Configuration changed: {key} = {value} (was: {old_value})")

        if save:
            self._save()

    def get_thresholds(self) -> tuple[int, int]:
        """
        Get the pressure thresholds.

        Returns:
            Tuple of (yellow_threshold, red_threshold)
        """
        thresholds = self.get("thresholds", {})
        return (
            thresholds.get("yellow", DEFAULT_CONFIG["thresholds"]["yellow"]),
            thresholds.get("red", DEFAULT_CONFIG["thresholds"]["red"])
        )

    def get_weights(self) -> dict[str, float]:
        """
        Get the metric weights for pressure calculation.

        Returns:
            Dict of metric name to weight
        """
        return self.get("metric_weights", DEFAULT_CONFIG["metric_weights"])

    def get_smoothing_samples(self) -> int:
        """
        Calculate the number of samples for smoothing based on window and frequency.

        Returns:
            Number of samples to keep in rolling buffer
        """
        window_minutes = self.get("smoothing_window_minutes", 5)
        frequency_seconds = self.get("sampling_frequency_seconds", 5)
        return max(1, int((window_minutes * 60) / frequency_seconds))

    def reload(self) -> None:
        """Reload configuration from file."""
        self._load()

    def reset_to_defaults(self, save: bool = True) -> None:
        """
        Reset all configuration to defaults.

        Args:
            save: Whether to persist to file immediately
        """
        self._config = DEFAULT_CONFIG.copy()
        logger.info("Configuration reset to defaults")

        if save:
            self._save()

    def to_dict(self) -> dict[str, Any]:
        """
        Get a copy of the full configuration.

        Returns:
            Copy of the configuration dictionary
        """
        return self._config.copy()
