"""Detail View window for BottleneckWatch.

Displays real-time metrics and historical graphs.
"""

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib.dates as mdates

from .config import ConfigManager
from .database import DatabaseManager
from .collector import MemoryMetrics
from .utils import get_logger, format_bytes, format_percentage, APP_NAME

logger = get_logger(__name__)


class DetailWindow:
    """Detail View window showing metrics and graphs."""

    def __init__(
        self,
        config: ConfigManager,
        database: DatabaseManager,
        on_close: Optional[Callable[[], None]] = None,
        root: Optional[tk.Tk] = None
    ) -> None:
        """
        Initialize the Detail View window.

        Args:
            config: Configuration manager instance
            database: Database manager instance
            on_close: Callback when window is closed
            root: Parent tkinter root window (if None, creates one)
        """
        self.config = config
        self.database = database
        self._on_close = on_close

        self._window: Optional[tk.Toplevel] = None
        self._root: Optional[tk.Tk] = root
        self._owns_root = False

        # Current metrics for real-time display
        self._current_pressure: float = 0.0
        self._current_metrics: Optional[MemoryMetrics] = None

        # Graph update timer
        self._update_job: Optional[str] = None

        # Auto-refresh timer
        self._auto_refresh_job: Optional[str] = None

        # Time period selection
        self._time_periods = {
            "Last Hour": 1,
            "Last 6 Hours": 6,
            "Last 24 Hours": 24,
            "Last 7 Days": 168,
            "Last 30 Days": 720
        }

        logger.info("DetailWindow initialized")

    def _create_window(self) -> None:
        """Create the window and its widgets."""
        # Create root window if not provided
        if self._root is None:
            try:
                self._root = tk._default_root
                if self._root is None:
                    self._root = tk.Tk()
                    self._root.withdraw()
                    self._owns_root = True
            except Exception:
                self._root = tk.Tk()
                self._root.withdraw()
                self._owns_root = True

        # Create toplevel window
        self._window = tk.Toplevel(self._root)
        self._window.title(f"{APP_NAME} - Details")
        self._window.geometry("900x850")
        self._window.minsize(700, 650)

        # Handle window close
        self._window.protocol("WM_DELETE_WINDOW", self._handle_close)

        # Create main container with padding
        main_frame = ttk.Frame(self._window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create sections
        self._create_metrics_section(main_frame)
        self._create_graph_section(main_frame)
        self._create_controls_section(main_frame)

    def _create_metrics_section(self, parent: ttk.Frame) -> None:
        """Create the real-time metrics display section."""
        # Metrics frame
        metrics_frame = ttk.LabelFrame(parent, text="Current Metrics", padding="10")
        metrics_frame.pack(fill=tk.X, pady=(0, 10))

        # Create grid for metrics
        self._metric_labels: dict[str, ttk.Label] = {}

        metrics_info = [
            ("pressure", "Memory Pressure:", "0%"),
            ("pressure_raw", "Raw Pressure:", "0%"),
            ("page_faults", "Hard Faults/sec:", "0"),
            ("available_ram", "Available RAM:", "0 GB (0%)"),
            ("committed", "Committed Memory:", "0 GB (0%)"),
            ("disk_busy", "Disk Busy:", "0%"),
            ("page_io", "Page I/O:", "0 KB/s"),
            ("regular_io", "Regular I/O:", "0 KB/s"),
            ("io_breakdown", "I/O Breakdown:", "0% memory / 0% other"),
        ]

        for i, (key, label_text, default) in enumerate(metrics_info):
            row = i // 3
            col = (i % 3) * 2

            label = ttk.Label(metrics_frame, text=label_text, font=("Segoe UI", 9, "bold"))
            label.grid(row=row, column=col, sticky=tk.W, padx=(0, 5), pady=2)

            value_label = ttk.Label(metrics_frame, text=default, font=("Segoe UI", 9))
            value_label.grid(row=row, column=col + 1, sticky=tk.W, padx=(0, 20), pady=2)

            self._metric_labels[key] = value_label

        # Configure grid weights
        for i in range(6):
            metrics_frame.columnconfigure(i, weight=1)

    def _create_graph_section(self, parent: ttk.Frame) -> None:
        """Create the historical graphs section."""
        # Graph frame
        graph_frame = ttk.LabelFrame(parent, text="Historical Data", padding="5")
        graph_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Time period selector
        selector_frame = ttk.Frame(graph_frame)
        selector_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(selector_frame, text="Time Period:").pack(side=tk.LEFT, padx=(0, 5))

        self._time_var = tk.StringVar(value="Last Hour")
        time_combo = ttk.Combobox(
            selector_frame,
            textvariable=self._time_var,
            values=list(self._time_periods.keys()),
            state="readonly",
            width=15
        )
        time_combo.pack(side=tk.LEFT)
        time_combo.bind("<<ComboboxSelected>>", lambda e: self._update_graph())

        # Refresh button
        refresh_btn = ttk.Button(selector_frame, text="Refresh", command=self._update_graph)
        refresh_btn.pack(side=tk.LEFT, padx=(10, 0))

        # Auto-refresh checkbox
        self._auto_refresh_var = tk.BooleanVar(value=False)
        auto_refresh_cb = ttk.Checkbutton(
            selector_frame,
            text="Auto-refresh (30s)",
            variable=self._auto_refresh_var,
            command=self._on_auto_refresh_toggled
        )
        auto_refresh_cb.pack(side=tk.LEFT, padx=(10, 0))

        # Create matplotlib figure
        self._figure = Figure(figsize=(8, 6), dpi=100)
        self._figure.set_facecolor("#f0f0f0")

        # Create subplots (3 rows)
        self._ax_pressure = self._figure.add_subplot(311)
        self._ax_metrics = self._figure.add_subplot(312)
        self._ax_disk_io = self._figure.add_subplot(313)
        self._ax_disk_busy: Optional[plt.Axes] = None  # Twin axis for disk busy %

        # Embed in tkinter
        self._canvas = FigureCanvasTkAgg(self._figure, master=graph_frame)
        self._canvas.draw()
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Add toolbar
        toolbar_frame = ttk.Frame(graph_frame)
        toolbar_frame.pack(fill=tk.X)
        self._toolbar = NavigationToolbar2Tk(self._canvas, toolbar_frame)
        self._toolbar.update()

    def _create_controls_section(self, parent: ttk.Frame) -> None:
        """Create the controls section with export and close buttons."""
        controls_frame = ttk.Frame(parent)
        controls_frame.pack(fill=tk.X)

        # Export button
        export_btn = ttk.Button(controls_frame, text="Export CSV...", command=self._export_csv)
        export_btn.pack(side=tk.LEFT)

        # Sample count label
        self._sample_count_label = ttk.Label(controls_frame, text="Samples: 0")
        self._sample_count_label.pack(side=tk.LEFT, padx=(20, 0))

        # Close button
        close_btn = ttk.Button(controls_frame, text="Close", command=self._handle_close)
        close_btn.pack(side=tk.RIGHT)

    def _format_io_rate(self, bytes_per_sec: float) -> str:
        """Format I/O rate in appropriate units (KB/s, MB/s, GB/s)."""
        if bytes_per_sec >= 1024 * 1024 * 1024:
            return f"{bytes_per_sec / (1024 * 1024 * 1024):.1f} GB/s"
        elif bytes_per_sec >= 1024 * 1024:
            return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
        elif bytes_per_sec >= 1024:
            return f"{bytes_per_sec / 1024:.1f} KB/s"
        else:
            return f"{bytes_per_sec:.0f} B/s"

    def _update_metrics_display(self) -> None:
        """Update the real-time metrics display."""
        if not self._window or not self._window.winfo_exists():
            return

        # Update pressure
        self._metric_labels["pressure"].config(
            text=f"{self._current_pressure:.1f}%"
        )

        if self._current_metrics:
            metrics = self._current_metrics

            # Raw pressure (calculate from current metrics using simple formula)
            raw_pressure = (
                (100 - metrics.available_ram_percent) * 0.3 +
                metrics.committed_ratio * 0.2 +
                min(100, metrics.page_faults_per_sec / 10) * 0.5
            )
            self._metric_labels["pressure_raw"].config(
                text=f"{raw_pressure:.1f}%"
            )

            self._metric_labels["page_faults"].config(
                text=f"{metrics.page_faults_per_sec:.1f}"
            )

            self._metric_labels["available_ram"].config(
                text=f"{format_bytes(metrics.available_ram_bytes)} ({metrics.available_ram_percent:.1f}%)"
            )

            self._metric_labels["committed"].config(
                text=f"{format_bytes(metrics.committed_bytes)} ({metrics.committed_ratio:.1f}%)"
            )

            # Disk I/O metrics
            self._metric_labels["disk_busy"].config(
                text=f"{metrics.disk_percent_busy:.1f}%"
            )

            self._metric_labels["page_io"].config(
                text=f"{self._format_io_rate(metrics.page_io_bytes_per_sec)}"
            )

            self._metric_labels["regular_io"].config(
                text=f"{self._format_io_rate(metrics.regular_io_bytes_per_sec)}"
            )

            self._metric_labels["io_breakdown"].config(
                text=f"{metrics.page_io_percent:.0f}% memory / {metrics.regular_io_percent:.0f}% other"
            )

    def _update_graph(self) -> None:
        """Update the historical graphs."""
        if not self._window or not self._window.winfo_exists():
            return

        # Get time period
        period_name = self._time_var.get()
        hours = self._time_periods.get(period_name, 1)

        # Fetch data from database
        samples = self.database.get_samples_last_hours(hours)

        # Update sample count
        self._sample_count_label.config(text=f"Samples: {len(samples)}")

        if not samples:
            self._ax_pressure.clear()
            self._ax_metrics.clear()
            self._ax_disk_io.clear()
            self._ax_pressure.set_title("No data available")
            self._canvas.draw()
            return

        # Extract data
        timestamps = [datetime.fromtimestamp(s["timestamp"]) for s in samples]
        pressure_smoothed = [s["pressure_smoothed"] for s in samples]
        pressure_raw = [s["pressure_raw"] for s in samples]
        available_ram = [s["available_ram_percent"] for s in samples]
        committed_ratio = [s["committed_ratio"] for s in samples]

        # Disk I/O data (convert to MB/s for readability)
        page_io = [s.get("page_io_bytes_per_sec", 0) / (1024 * 1024) for s in samples]
        disk_read = [s.get("disk_read_bytes_per_sec", 0) / (1024 * 1024) for s in samples]
        disk_write = [s.get("disk_write_bytes_per_sec", 0) / (1024 * 1024) for s in samples]
        disk_busy = [s.get("disk_percent_busy", 0) for s in samples]
        # Calculate regular I/O (total - page I/O)
        regular_io = [max(0, (disk_read[i] + disk_write[i]) - page_io[i]) for i in range(len(samples))]

        # Get thresholds for reference lines
        yellow_threshold, red_threshold = self.config.get_thresholds()

        # Clear and redraw pressure plot
        self._ax_pressure.clear()
        self._ax_pressure.plot(timestamps, pressure_smoothed, "b-", label="Smoothed", linewidth=1.5)
        self._ax_pressure.plot(timestamps, pressure_raw, "b--", alpha=0.4, label="Raw", linewidth=0.8)
        self._ax_pressure.axhline(y=yellow_threshold, color="orange", linestyle=":", alpha=0.7, label=f"Yellow ({yellow_threshold}%)")
        self._ax_pressure.axhline(y=red_threshold, color="red", linestyle=":", alpha=0.7, label=f"Red ({red_threshold}%)")
        self._ax_pressure.set_ylabel("Pressure %")
        self._ax_pressure.set_ylim(0, 100)
        self._ax_pressure.legend(loc="upper left", fontsize=8)
        self._ax_pressure.set_title("Memory Pressure")
        self._ax_pressure.grid(True, alpha=0.3)

        # Clear and redraw metrics plot
        self._ax_metrics.clear()
        self._ax_metrics.plot(timestamps, available_ram, "g-", label="Available RAM %", linewidth=1.2)
        self._ax_metrics.plot(timestamps, committed_ratio, "r-", label="Committed %", linewidth=1.2)
        self._ax_metrics.set_ylabel("Percentage")
        self._ax_metrics.set_ylim(0, 100)
        self._ax_metrics.legend(loc="upper left", fontsize=8)
        self._ax_metrics.set_title("Memory Metrics")
        self._ax_metrics.grid(True, alpha=0.3)

        # Clear and redraw disk I/O plot
        self._ax_disk_io.clear()

        # Remove the old twin axis completely (clearing it causes positioning issues)
        if self._ax_disk_busy is not None:
            self._ax_disk_busy.remove()
            self._ax_disk_busy = None

        # Plot I/O rates on primary axis
        self._ax_disk_io.plot(timestamps, page_io, "m-", label="Page I/O (Memory)", linewidth=1.2)
        self._ax_disk_io.plot(timestamps, regular_io, "c-", label="Regular I/O", linewidth=1.2)
        self._ax_disk_io.set_ylabel("I/O Rate (MB/s)")
        self._ax_disk_io.set_ylim(bottom=0)
        self._ax_disk_io.set_title("Disk I/O (Memory-related vs Regular)")
        self._ax_disk_io.grid(True, alpha=0.3)

        # Add disk busy % on secondary axis (recreate each refresh)
        self._ax_disk_busy = self._ax_disk_io.twinx()
        self._ax_disk_busy.fill_between(timestamps, disk_busy, alpha=0.2, color="gray", label="Disk Busy %")
        self._ax_disk_busy.set_ylabel("Disk Busy %", color="gray")
        self._ax_disk_busy.set_ylim(0, 100)
        self._ax_disk_busy.tick_params(axis="y", labelcolor="gray")

        # Combine legends from both axes
        lines1, labels1 = self._ax_disk_io.get_legend_handles_labels()
        lines2, labels2 = self._ax_disk_busy.get_legend_handles_labels()
        self._ax_disk_io.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)

        # Format x-axis
        for ax in [self._ax_pressure, self._ax_metrics, self._ax_disk_io]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if hours <= 24 else "%m/%d %H:%M"))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=8)

        self._figure.tight_layout()
        self._canvas.draw()

    def _on_auto_refresh_toggled(self) -> None:
        """Handle auto-refresh checkbox toggle."""
        if self._auto_refresh_var.get():
            self._start_auto_refresh()
        else:
            self._stop_auto_refresh()

    def _start_auto_refresh(self) -> None:
        """Start auto-refreshing graphs every 30 seconds."""
        logger.info("Auto-refresh enabled")
        self._update_graph()
        self._auto_refresh_tick()

    def _stop_auto_refresh(self) -> None:
        """Stop auto-refreshing graphs."""
        logger.info("Auto-refresh disabled")
        if self._auto_refresh_job and self._window:
            self._window.after_cancel(self._auto_refresh_job)
            self._auto_refresh_job = None

    def _auto_refresh_tick(self) -> None:
        """Schedule the next auto-refresh."""
        if not self._window or not self._window.winfo_exists():
            return
        self._auto_refresh_job = self._window.after(30000, self._auto_refresh_fire)

    def _auto_refresh_fire(self) -> None:
        """Perform an auto-refresh and schedule the next one."""
        if not self._window or not self._window.winfo_exists():
            return
        self._update_graph()
        self._auto_refresh_tick()

    def _export_csv(self) -> None:
        """Export data to CSV file."""
        # Get time period
        period_name = self._time_var.get()
        hours = self._time_periods.get(period_name, 1)

        # Ask for file location
        filepath = filedialog.asksaveasfilename(
            parent=self._window,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"bottleneckwatch_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )

        if not filepath:
            return

        # Export
        import time
        start_time = time.time() - (hours * 3600)
        success = self.database.export_to_csv(Path(filepath), start_time=start_time)

        if success:
            messagebox.showinfo("Export Complete", f"Data exported to:\n{filepath}", parent=self._window)
        else:
            messagebox.showerror("Export Failed", "Failed to export data. Check logs for details.", parent=self._window)

    def _handle_close(self) -> None:
        """Handle window close."""
        logger.info("Detail window closing")

        # Cancel update timer
        if self._update_job and self._window:
            self._window.after_cancel(self._update_job)
            self._update_job = None

        # Cancel auto-refresh timer
        if self._auto_refresh_job and self._window:
            self._window.after_cancel(self._auto_refresh_job)
            self._auto_refresh_job = None

        # Clean up matplotlib resources to prevent memory leaks
        if hasattr(self, '_figure') and self._figure is not None:
            plt.close(self._figure)
            self._figure = None
            self._ax_pressure = None
            self._ax_metrics = None
            self._ax_disk_io = None
            self._ax_disk_busy = None

        # Destroy window
        if self._window:
            self._window.destroy()
            self._window = None

        # Clean up root if we created it
        if self._owns_root and self._root:
            self._root.destroy()
            self._root = None

        # Call callback
        if self._on_close:
            self._on_close()

    def _schedule_updates(self) -> None:
        """Schedule periodic updates."""
        if not self._window or not self._window.winfo_exists():
            return

        # Update metrics display
        self._update_metrics_display()

        # Schedule next update (every 1 second)
        self._update_job = self._window.after(1000, self._schedule_updates)

    def update_data(self, pressure: float, metrics: Optional[MemoryMetrics] = None) -> None:
        """
        Update the displayed data.

        Args:
            pressure: Current smoothed pressure
            metrics: Current raw metrics
        """
        self._current_pressure = pressure
        self._current_metrics = metrics

    def show(self) -> None:
        """Show the detail window."""
        if self._window and self._window.winfo_exists():
            # Window already exists, bring to front
            self._window.lift()
            self._window.focus_force()
            return

        logger.info("Opening detail window")

        # Create window
        self._create_window()

        # Initial graph update
        self._update_graph()

        # Start periodic updates
        self._schedule_updates()

        # Bring to front
        self._window.lift()
        self._window.focus_force()

    def is_visible(self) -> bool:
        """Check if window is currently visible."""
        return self._window is not None and self._window.winfo_exists()
