"""Pressure calculation for BottleneckWatch.

Calculates memory pressure score from collected metrics using configurable
weights and time-smoothing.
"""

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional

from .config import ConfigManager
from .collector import MemoryMetrics
from .utils import get_logger

logger = get_logger(__name__)


@dataclass
class PressureEvent:
    """Represents a sustained pressure event."""

    start_time: float
    end_time: Optional[float]
    peak_pressure: float
    average_pressure: float


class PressureCalculator:
    """Calculates memory pressure from collected metrics."""

    def __init__(self, config: ConfigManager) -> None:
        """
        Initialize the pressure calculator.

        Args:
            config: Configuration manager instance
        """
        self.config = config

        # Rolling buffer for smoothing
        buffer_size = config.get_smoothing_samples()
        self._pressure_buffer: deque[float] = deque(maxlen=buffer_size)

        # Pressure event tracking (using running stats to avoid unbounded memory)
        self._current_event: Optional[PressureEvent] = None
        self._event_sample_count: int = 0
        self._event_sample_sum: float = 0.0

        logger.info(f"PressureCalculator initialized with buffer size {buffer_size}")

    def _normalize_page_faults(self, faults_per_sec: float) -> float:
        """
        Normalize hard page faults to 0-100 scale using logarithmic mapping.

        Hard page faults (page reads from disk) indicate genuine memory pressure.
        On a healthy system these are typically 0-5/sec; under memory pressure
        they can spike to 50-500+/sec.

        Scale:
        - 0 faults = 0 pressure
        - 10 faults = ~33 pressure
        - 100 faults = ~67 pressure
        - 1000+ faults = 100 pressure

        Args:
            faults_per_sec: Hard page faults (page reads) per second

        Returns:
            Normalized pressure value (0-100)
        """
        if faults_per_sec <= 0:
            return 0.0

        # Logarithmic scale: log10(faults + 1) / log10(1001) * 100
        normalized = (math.log10(faults_per_sec + 1) / math.log10(1001)) * 100
        return min(100.0, max(0.0, normalized))

    def _normalize_available_ram(self, available_percent: float) -> float:
        """
        Normalize available RAM to pressure scale (inverse - low RAM = high pressure).

        Scale:
        - 100% available = 0 pressure
        - 50% available = 50 pressure
        - 0% available = 100 pressure

        Args:
            available_percent: Percentage of RAM available (0-100)

        Returns:
            Normalized pressure value (0-100)
        """
        # Simple inverse: 100 - available_percent
        # But we want to be more aggressive as available RAM drops very low
        if available_percent >= 50:
            # Linear from 0-50 pressure
            return 100 - available_percent
        else:
            # Accelerate pressure as available RAM drops below 50%
            # At 50% available: 50 pressure
            # At 0% available: 100 pressure (but with steeper curve)
            base = 50
            additional = (50 - available_percent) * 1.0  # Can adjust multiplier
            return min(100.0, base + additional)

    def _normalize_committed_ratio(self, committed_ratio: float) -> float:
        """
        Normalize committed memory ratio to pressure scale.

        Scale:
        - 0% committed = 0 pressure
        - 80% committed = 60 pressure
        - 100% committed = 100 pressure (system at commit limit)

        Args:
            committed_ratio: Committed bytes / commit limit (0-100+)

        Returns:
            Normalized pressure value (0-100)
        """
        if committed_ratio <= 0:
            return 0.0

        # Exponential curve that accelerates as we approach commit limit
        if committed_ratio < 80:
            # Linear up to 80% committed = 60 pressure
            return committed_ratio * 0.75
        else:
            # Steeper curve from 80-100%
            base = 60
            additional = ((committed_ratio - 80) / 20) * 40
            return min(100.0, base + additional)

    def calculate_raw_pressure(self, metrics: MemoryMetrics) -> float:
        """
        Calculate instantaneous (raw) pressure from metrics.

        Args:
            metrics: Collected memory metrics

        Returns:
            Raw pressure percentage (0-100)
        """
        weights = self.config.get_weights()

        # Normalize each metric
        page_fault_pressure = self._normalize_page_faults(metrics.page_faults_per_sec)
        available_ram_pressure = self._normalize_available_ram(metrics.available_ram_percent)
        committed_pressure = self._normalize_committed_ratio(metrics.committed_ratio)

        logger.debug(
            f"Normalized pressures: page_faults={page_fault_pressure:.1f}, "
            f"available_ram={available_ram_pressure:.1f}, "
            f"committed={committed_pressure:.1f}"
        )

        # Apply weights
        weighted_pressure = (
            page_fault_pressure * weights.get("page_faults", 0.5) +
            available_ram_pressure * weights.get("available_ram", 0.3) +
            committed_pressure * weights.get("committed_ratio", 0.2)
        )

        return min(100.0, max(0.0, weighted_pressure))

    def add_sample(self, raw_pressure: float) -> float:
        """
        Add a pressure sample and return the smoothed value.

        Uses simple moving average for smoothing.

        Args:
            raw_pressure: The raw pressure value (0-100)

        Returns:
            Smoothed pressure value (0-100)
        """
        self._pressure_buffer.append(raw_pressure)

        # Calculate simple moving average
        if len(self._pressure_buffer) > 0:
            smoothed = sum(self._pressure_buffer) / len(self._pressure_buffer)
        else:
            smoothed = raw_pressure

        # Track pressure events
        self._update_pressure_event(smoothed)

        return smoothed

    def _update_pressure_event(self, smoothed_pressure: float) -> None:
        """
        Track pressure events (sustained high pressure periods).

        Uses running statistics (count + sum) instead of storing all samples
        to prevent unbounded memory growth during long pressure events.

        Args:
            smoothed_pressure: Current smoothed pressure value
        """
        import time

        yellow_threshold, red_threshold = self.config.get_thresholds()

        # Consider "high pressure" as anything above yellow threshold
        is_high_pressure = smoothed_pressure >= yellow_threshold

        if is_high_pressure:
            if self._current_event is None:
                # Start new event
                self._current_event = PressureEvent(
                    start_time=time.time(),
                    end_time=None,
                    peak_pressure=smoothed_pressure,
                    average_pressure=smoothed_pressure
                )
                self._event_sample_count = 1
                self._event_sample_sum = smoothed_pressure
                logger.info(f"Pressure event started at {smoothed_pressure:.1f}%")
            else:
                # Update existing event using running stats
                self._event_sample_count += 1
                self._event_sample_sum += smoothed_pressure
                self._current_event.peak_pressure = max(
                    self._current_event.peak_pressure, smoothed_pressure
                )
                self._current_event.average_pressure = (
                    self._event_sample_sum / self._event_sample_count
                )
        else:
            if self._current_event is not None:
                # End event
                self._current_event.end_time = time.time()
                duration = self._current_event.end_time - self._current_event.start_time

                logger.info(
                    f"Pressure event ended: duration={duration:.1f}s, "
                    f"peak={self._current_event.peak_pressure:.1f}%, "
                    f"avg={self._current_event.average_pressure:.1f}%"
                )

                self._current_event = None
                self._event_sample_count = 0
                self._event_sample_sum = 0.0

    def get_smoothed_pressure(self) -> float:
        """
        Get the current smoothed pressure value.

        Returns:
            Smoothed pressure (0-100), or 0 if no samples
        """
        if len(self._pressure_buffer) > 0:
            return sum(self._pressure_buffer) / len(self._pressure_buffer)
        return 0.0

    def get_pressure_color(self, pressure: Optional[float] = None) -> str:
        """
        Determine the color based on pressure level.

        Args:
            pressure: Pressure value (0-100), or None to use current smoothed

        Returns:
            Color name: "green", "yellow", or "red"
        """
        if pressure is None:
            pressure = self.get_smoothed_pressure()

        yellow_threshold, red_threshold = self.config.get_thresholds()

        if pressure >= red_threshold:
            return "red"
        elif pressure >= yellow_threshold:
            return "yellow"
        else:
            return "green"

    def reset(self) -> None:
        """Reset the calculator state (clears buffer and events)."""
        buffer_size = self.config.get_smoothing_samples()
        self._pressure_buffer = deque(maxlen=buffer_size)
        self._current_event = None
        self._event_sample_count = 0
        self._event_sample_sum = 0.0
        logger.info("PressureCalculator reset")
