"""BottleneckWatch - Windows memory pressure monitoring utility.

Entry point for the application.
"""

import signal
import sys
import threading
import tkinter as tk
from queue import Queue, Empty
from typing import Optional

from src.utils import setup_logging, set_log_level, get_logger, APP_NAME
from src.config import ConfigManager
from src.collector import MetricsCollector
from src.calculator import PressureCalculator
from src.database import DatabaseManager
from src.tray import TrayIcon
from src.detail_window import DetailWindow
from src.settings_window import SettingsWindow


class BottleneckWatch:
    """Main application coordinator."""

    def __init__(self) -> None:
        """Initialize the BottleneckWatch application."""
        # Initialize logging first (starts in quiet mode)
        setup_logging()

        # Initialize config and apply log level setting
        self.config = ConfigManager()
        set_log_level(self.config.get("verbose_logging", False))

        self.logger = get_logger(__name__)
        self.logger.info(f"Starting {APP_NAME}")
        self.database = DatabaseManager()
        self.collector = MetricsCollector()
        self.calculator = PressureCalculator(self.config)

        # Communication queue for thread-safe updates
        self.update_queue: Queue = Queue()

        # Shutdown event
        self.shutdown_event = threading.Event()

        # Collection thread
        self.collection_thread: Optional[threading.Thread] = None

        # Tray icon (created in run())
        self.tray: Optional[TrayIcon] = None

        # Tkinter root window (hidden, used for window management)
        self._root: Optional[tk.Tk] = None

        # Windows (created on demand)
        self.detail_window: Optional[DetailWindow] = None
        self.settings_window: Optional[SettingsWindow] = None

        # Current metrics for window updates
        self._current_pressure: float = 0.0
        self._current_metrics = None

        self.logger.info("All components initialized")

    def _collect_initial_pressure(self) -> float:
        """
        Perform an initial synchronous collection to get a real pressure value.

        This ensures the tray icon starts with an actual reading instead of 0.

        Returns:
            Initial pressure percentage, or 0.0 if collection fails
        """
        self.logger.info("Performing initial pressure collection")
        try:
            metrics = self.collector.collect()
            if metrics:
                raw_pressure = self.calculator.calculate_raw_pressure(metrics)
                # For initial value, use raw pressure since we don't have history for smoothing
                self._current_pressure = raw_pressure
                self._current_metrics = metrics

                # Store in database
                self.database.insert_sample(
                    pressure_smoothed=raw_pressure,
                    pressure_raw=raw_pressure,
                    page_faults=metrics.page_faults_per_sec,
                    available_ram_bytes=metrics.available_ram_bytes,
                    available_ram_percent=metrics.available_ram_percent,
                    committed_bytes=metrics.committed_bytes,
                    committed_ratio=metrics.committed_ratio,
                    page_io_bytes_per_sec=metrics.page_io_bytes_per_sec,
                    disk_read_bytes_per_sec=metrics.disk_read_bytes_per_sec,
                    disk_write_bytes_per_sec=metrics.disk_write_bytes_per_sec,
                    disk_percent_busy=metrics.disk_percent_busy
                )

                # Add to calculator's smoothing buffer
                self.calculator.add_sample(raw_pressure)

                self.logger.info(f"Initial pressure: {raw_pressure:.1f}%")
                return raw_pressure
            else:
                self.logger.warning("Initial collection returned no metrics")
                return 0.0
        except Exception as e:
            self.logger.error(f"Error during initial collection: {e}", exc_info=True)
            return 0.0

    def _collection_loop(self) -> None:
        """Background thread for collecting metrics and calculating pressure."""
        self.logger.info("Collection thread started")

        while not self.shutdown_event.is_set():
            try:
                # Collect metrics
                metrics = self.collector.collect()

                if metrics:
                    self.logger.debug(
                        f"Collected metrics: page_faults={metrics.page_faults_per_sec:.1f}, "
                        f"available_ram={metrics.available_ram_percent:.1f}%, "
                        f"committed_ratio={metrics.committed_ratio:.1f}%"
                    )

                    # Calculate pressure
                    raw_pressure = self.calculator.calculate_raw_pressure(metrics)
                    smoothed_pressure = self.calculator.add_sample(raw_pressure)

                    self.logger.debug(
                        f"Pressure: raw={raw_pressure:.1f}%, smoothed={smoothed_pressure:.1f}%"
                    )

                    # Store in database
                    self.database.insert_sample(
                        pressure_smoothed=smoothed_pressure,
                        pressure_raw=raw_pressure,
                        page_faults=metrics.page_faults_per_sec,
                        available_ram_bytes=metrics.available_ram_bytes,
                        available_ram_percent=metrics.available_ram_percent,
                        committed_bytes=metrics.committed_bytes,
                        committed_ratio=metrics.committed_ratio,
                        page_io_bytes_per_sec=metrics.page_io_bytes_per_sec,
                        disk_read_bytes_per_sec=metrics.disk_read_bytes_per_sec,
                        disk_write_bytes_per_sec=metrics.disk_write_bytes_per_sec,
                        disk_percent_busy=metrics.disk_percent_busy
                    )

                    # Queue update for tray icon
                    self.update_queue.put({
                        "pressure": smoothed_pressure,
                        "metrics": metrics
                    })
                else:
                    self.logger.warning("Failed to collect metrics")

            except Exception as e:
                self.logger.error(f"Error in collection loop: {e}", exc_info=True)

            # Wait for next sample interval
            self.shutdown_event.wait(self.config.get("sampling_frequency_seconds", 5))

        self.logger.info("Collection thread stopped")

    def _process_updates(self) -> None:
        """Process updates from the collection thread (called from tkinter mainloop)."""
        if self.shutdown_event.is_set():
            return

        try:
            # Process all pending updates
            while True:
                try:
                    update = self.update_queue.get_nowait()

                    # Store current values for windows
                    self._current_pressure = update["pressure"]
                    self._current_metrics = update["metrics"]

                    # Update tray icon
                    if self.tray:
                        self.tray.update_pressure(update["pressure"])

                    # Update detail window if visible
                    if self.detail_window and self.detail_window.is_visible():
                        self.detail_window.update_data(update["pressure"], update["metrics"])

                except Empty:
                    break

        except Exception as e:
            self.logger.error(f"Error processing updates: {e}", exc_info=True)

        # Schedule next update check
        if self._root and not self.shutdown_event.is_set():
            self._root.after(100, self._process_updates)

    def _on_exit(self) -> None:
        """Handle exit request from tray menu."""
        self.logger.info("Exit requested from tray menu")
        # Schedule shutdown on main thread
        if self._root:
            self._root.after(0, self.shutdown)

    def _on_view_details(self) -> None:
        """Handle View Details menu item."""
        # Schedule on main thread to ensure tkinter safety
        if self._root:
            self._root.after(0, self._show_detail_window)

    def _show_detail_window(self) -> None:
        """Show detail window (must be called from main thread)."""
        self.logger.info("View Details clicked")

        try:
            # Create window if needed
            if self.detail_window is None:
                self.detail_window = DetailWindow(
                    config=self.config,
                    database=self.database,
                    on_close=self._on_detail_window_closed,
                    root=self._root
                )

            # Update with current data and show
            self.detail_window.update_data(self._current_pressure, self._current_metrics)
            self.detail_window.show()

        except Exception as e:
            self.logger.error(f"Error showing detail window: {e}", exc_info=True)

    def _on_detail_window_closed(self) -> None:
        """Handle detail window close."""
        self.logger.debug("Detail window closed")
        self.detail_window = None

    def _on_settings(self) -> None:
        """Handle Settings menu item."""
        # Schedule on main thread to ensure tkinter safety
        if self._root:
            self._root.after(0, self._show_settings_window)

    def _show_settings_window(self) -> None:
        """Show settings window (must be called from main thread)."""
        self.logger.info("Settings clicked")

        try:
            # Create window if needed
            if self.settings_window is None:
                self.settings_window = SettingsWindow(
                    config=self.config,
                    database=self.database,
                    on_close=self._on_settings_window_closed,
                    on_settings_changed=self._on_settings_changed,
                    root=self._root
                )

            self.settings_window.show()

        except Exception as e:
            self.logger.error(f"Error showing settings window: {e}", exc_info=True)

    def _on_settings_window_closed(self) -> None:
        """Handle settings window close."""
        self.logger.debug("Settings window closed")
        self.settings_window = None

    def _on_settings_changed(self) -> None:
        """Handle settings changes."""
        self.logger.info("Settings changed, reinitializing calculator")

        # Reinitialize calculator with new config
        self.calculator = PressureCalculator(self.config)

        # Apply log level setting
        set_log_level(self.config.get("verbose_logging", False))

    def shutdown(self) -> None:
        """Gracefully shut down the application."""
        self.logger.info("Shutting down...")

        # Signal collection thread to stop
        self.shutdown_event.set()

        # Wait for collection thread
        if self.collection_thread and self.collection_thread.is_alive():
            self.collection_thread.join(timeout=5)
            if self.collection_thread.is_alive():
                self.logger.warning("Collection thread did not stop gracefully")

        # Close any open windows
        self.detail_window = None
        self.settings_window = None

        # Stop tray icon
        if self.tray:
            self.tray.stop()

        # Close database
        self.database.close()

        # Quit tkinter mainloop
        if self._root:
            self._root.quit()

        self.logger.info(f"{APP_NAME} shut down complete")

    def run(self) -> None:
        """Run the application."""
        try:
            # Create hidden tkinter root window for managing child windows
            self._root = tk.Tk()
            self._root.withdraw()  # Hide the root window
            self._root.title(APP_NAME)

            # Handle window manager close (shouldn't happen since window is hidden)
            self._root.protocol("WM_DELETE_WINDOW", self.shutdown)

            # Perform initial collection synchronously so tray icon starts with real value
            initial_pressure = self._collect_initial_pressure()

            # Start collection thread
            self.collection_thread = threading.Thread(
                target=self._collection_loop,
                name="CollectionThread",
                daemon=True
            )
            self.collection_thread.start()

            # Create tray icon with initial pressure value
            self.tray = TrayIcon(
                config=self.config,
                on_exit=self._on_exit,
                on_view_details=self._on_view_details,
                on_settings=self._on_settings,
                initial_pressure=initial_pressure
            )

            # Run tray icon in detached mode (separate thread)
            self.tray.run_detached()

            # Start processing updates
            self._root.after(100, self._process_updates)

            # Run tkinter mainloop (this blocks until quit)
            self._root.mainloop()

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            self.shutdown()


def main() -> None:
    """Application entry point."""
    app = BottleneckWatch()

    # Handle SIGINT gracefully
    def signal_handler(sig, frame):
        app.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    app.run()


if __name__ == "__main__":
    main()
