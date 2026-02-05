"""Settings window for BottleneckWatch.

Provides configuration UI for all application settings.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Optional, TYPE_CHECKING
import webbrowser
import winreg

from . import __version__, GITHUB_REPO
from .config import ConfigManager
from .database import DatabaseManager
from .utils import get_logger, APP_NAME

if TYPE_CHECKING:
    from .updater import UpdateChecker

logger = get_logger(__name__)

# Registry key for auto-start
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "BottleneckWatch"


class SettingsWindow:
    """Settings configuration window."""

    def __init__(
        self,
        config: ConfigManager,
        database: DatabaseManager,
        on_close: Optional[Callable[[], None]] = None,
        on_settings_changed: Optional[Callable[[], None]] = None,
        root: Optional[tk.Tk] = None,
        updater: Optional["UpdateChecker"] = None,
        on_apply_update: Optional[Callable[[], None]] = None
    ) -> None:
        """
        Initialize the Settings window.

        Args:
            config: Configuration manager instance
            database: Database manager instance
            on_close: Callback when window is closed
            on_settings_changed: Callback when settings are applied
            root: Parent tkinter root window (if None, creates one)
            updater: Update checker instance for the About tab
            on_apply_update: Callback to trigger update application and shutdown
        """
        self.config = config
        self.database = database
        self._on_close = on_close
        self._on_settings_changed = on_settings_changed
        self._updater = updater
        self._on_apply_update = on_apply_update

        self._window: Optional[tk.Toplevel] = None
        self._root: Optional[tk.Tk] = root
        self._owns_root = False

        # Track if settings have been modified
        self._modified = False

        logger.info("SettingsWindow initialized")

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
        self._window.title(f"{APP_NAME} - Settings")
        self._window.geometry("500x550")
        self._window.minsize(450, 500)
        self._window.resizable(True, True)

        # Handle window close
        self._window.protocol("WM_DELETE_WINDOW", self._handle_close)

        # Create main container with padding
        main_frame = ttk.Frame(self._window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Create notebook for tabbed settings
        self._notebook = ttk.Notebook(main_frame)
        self._notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Create tabs
        self._create_thresholds_tab()
        self._create_timing_tab()
        self._create_weights_tab()
        self._create_data_tab()
        self._create_startup_tab()
        self._create_about_tab()

        # Create buttons
        self._create_buttons(main_frame)

        # Load current values
        self._load_values()

    def _create_thresholds_tab(self) -> None:
        """Create the thresholds settings tab."""
        frame = ttk.Frame(self._notebook, padding="15")
        self._notebook.add(frame, text="Thresholds")

        # Info label
        info = ttk.Label(
            frame,
            text="Set the pressure thresholds for color changes.\n"
                 "Green: 0 to Yellow threshold\n"
                 "Yellow: Yellow threshold to Red threshold\n"
                 "Red: Red threshold to 100",
            justify=tk.LEFT,
            foreground="gray"
        )
        info.pack(anchor=tk.W, pady=(0, 15))

        # Yellow threshold
        yellow_frame = ttk.Frame(frame)
        yellow_frame.pack(fill=tk.X, pady=5)

        ttk.Label(yellow_frame, text="Yellow threshold (%):").pack(side=tk.LEFT)
        self._yellow_var = tk.IntVar()
        yellow_spin = ttk.Spinbox(
            yellow_frame,
            from_=10,
            to=90,
            textvariable=self._yellow_var,
            width=10,
            command=self._mark_modified
        )
        yellow_spin.pack(side=tk.RIGHT)
        yellow_spin.bind("<KeyRelease>", lambda e: self._mark_modified())

        # Red threshold
        red_frame = ttk.Frame(frame)
        red_frame.pack(fill=tk.X, pady=5)

        ttk.Label(red_frame, text="Red threshold (%):").pack(side=tk.LEFT)
        self._red_var = tk.IntVar()
        red_spin = ttk.Spinbox(
            red_frame,
            from_=20,
            to=100,
            textvariable=self._red_var,
            width=10,
            command=self._mark_modified
        )
        red_spin.pack(side=tk.RIGHT)
        red_spin.bind("<KeyRelease>", lambda e: self._mark_modified())

    def _create_timing_tab(self) -> None:
        """Create the timing settings tab."""
        frame = ttk.Frame(self._notebook, padding="15")
        self._notebook.add(frame, text="Timing")

        # Info label
        info = ttk.Label(
            frame,
            text="Configure sampling and smoothing behavior.",
            justify=tk.LEFT,
            foreground="gray"
        )
        info.pack(anchor=tk.W, pady=(0, 15))

        # Sampling frequency
        freq_frame = ttk.Frame(frame)
        freq_frame.pack(fill=tk.X, pady=5)

        ttk.Label(freq_frame, text="Sampling frequency (seconds):").pack(side=tk.LEFT)
        self._frequency_var = tk.IntVar()
        freq_spin = ttk.Spinbox(
            freq_frame,
            from_=1,
            to=60,
            textvariable=self._frequency_var,
            width=10,
            command=self._mark_modified
        )
        freq_spin.pack(side=tk.RIGHT)
        freq_spin.bind("<KeyRelease>", lambda e: self._mark_modified())

        # Smoothing window
        smooth_frame = ttk.Frame(frame)
        smooth_frame.pack(fill=tk.X, pady=5)

        ttk.Label(smooth_frame, text="Smoothing window (minutes):").pack(side=tk.LEFT)
        self._smoothing_var = tk.IntVar()
        smooth_spin = ttk.Spinbox(
            smooth_frame,
            from_=1,
            to=30,
            textvariable=self._smoothing_var,
            width=10,
            command=self._mark_modified
        )
        smooth_spin.pack(side=tk.RIGHT)
        smooth_spin.bind("<KeyRelease>", lambda e: self._mark_modified())

        # Minimum pressure duration
        duration_frame = ttk.Frame(frame)
        duration_frame.pack(fill=tk.X, pady=5)

        ttk.Label(duration_frame, text="Min. pressure duration (seconds):").pack(side=tk.LEFT)
        self._duration_var = tk.IntVar()
        duration_spin = ttk.Spinbox(
            duration_frame,
            from_=5,
            to=300,
            textvariable=self._duration_var,
            width=10,
            command=self._mark_modified
        )
        duration_spin.pack(side=tk.RIGHT)
        duration_spin.bind("<KeyRelease>", lambda e: self._mark_modified())

    def _create_weights_tab(self) -> None:
        """Create the metric weights settings tab."""
        frame = ttk.Frame(self._notebook, padding="15")
        self._notebook.add(frame, text="Weights")

        # Info label
        info = ttk.Label(
            frame,
            text="Adjust the relative importance of each metric.\n"
                 "Weights should sum to 1.0 (100%).",
            justify=tk.LEFT,
            foreground="gray"
        )
        info.pack(anchor=tk.W, pady=(0, 15))

        # Page faults weight
        pf_frame = ttk.Frame(frame)
        pf_frame.pack(fill=tk.X, pady=5)

        ttk.Label(pf_frame, text="Hard faults weight:").pack(side=tk.LEFT)
        self._weight_pf_var = tk.DoubleVar()
        pf_scale = ttk.Scale(
            pf_frame,
            from_=0.0,
            to=1.0,
            variable=self._weight_pf_var,
            orient=tk.HORIZONTAL,
            command=lambda v: self._update_weight_labels()
        )
        pf_scale.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))
        self._weight_pf_label = ttk.Label(pf_frame, text="0.50", width=5)
        self._weight_pf_label.pack(side=tk.RIGHT)

        # Available RAM weight
        ram_frame = ttk.Frame(frame)
        ram_frame.pack(fill=tk.X, pady=5)

        ttk.Label(ram_frame, text="Available RAM weight:").pack(side=tk.LEFT)
        self._weight_ram_var = tk.DoubleVar()
        ram_scale = ttk.Scale(
            ram_frame,
            from_=0.0,
            to=1.0,
            variable=self._weight_ram_var,
            orient=tk.HORIZONTAL,
            command=lambda v: self._update_weight_labels()
        )
        ram_scale.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))
        self._weight_ram_label = ttk.Label(ram_frame, text="0.30", width=5)
        self._weight_ram_label.pack(side=tk.RIGHT)

        # Committed ratio weight
        cr_frame = ttk.Frame(frame)
        cr_frame.pack(fill=tk.X, pady=5)

        ttk.Label(cr_frame, text="Committed ratio weight:").pack(side=tk.LEFT)
        self._weight_cr_var = tk.DoubleVar()
        cr_scale = ttk.Scale(
            cr_frame,
            from_=0.0,
            to=1.0,
            variable=self._weight_cr_var,
            orient=tk.HORIZONTAL,
            command=lambda v: self._update_weight_labels()
        )
        cr_scale.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))
        self._weight_cr_label = ttk.Label(cr_frame, text="0.20", width=5)
        self._weight_cr_label.pack(side=tk.RIGHT)

        # Total label
        total_frame = ttk.Frame(frame)
        total_frame.pack(fill=tk.X, pady=(15, 5))

        ttk.Label(total_frame, text="Total:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self._weight_total_label = ttk.Label(total_frame, text="1.00", font=("Segoe UI", 9, "bold"))
        self._weight_total_label.pack(side=tk.RIGHT)

    def _update_weight_labels(self) -> None:
        """Update weight display labels and mark as modified."""
        pf = self._weight_pf_var.get()
        ram = self._weight_ram_var.get()
        cr = self._weight_cr_var.get()
        total = pf + ram + cr

        self._weight_pf_label.config(text=f"{pf:.2f}")
        self._weight_ram_label.config(text=f"{ram:.2f}")
        self._weight_cr_label.config(text=f"{cr:.2f}")
        self._weight_total_label.config(
            text=f"{total:.2f}",
            foreground="red" if abs(total - 1.0) > 0.01 else "black"
        )

        self._mark_modified()

    def _create_data_tab(self) -> None:
        """Create the data management tab."""
        frame = ttk.Frame(self._notebook, padding="15")
        self._notebook.add(frame, text="Data")

        # Info label
        info = ttk.Label(
            frame,
            text="Configure data retention and management.",
            justify=tk.LEFT,
            foreground="gray"
        )
        info.pack(anchor=tk.W, pady=(0, 15))

        # Retention period
        retention_frame = ttk.Frame(frame)
        retention_frame.pack(fill=tk.X, pady=5)

        ttk.Label(retention_frame, text="Data retention (days):").pack(side=tk.LEFT)
        self._retention_var = tk.IntVar()
        retention_spin = ttk.Spinbox(
            retention_frame,
            from_=1,
            to=365,
            textvariable=self._retention_var,
            width=10,
            command=self._mark_modified
        )
        retention_spin.pack(side=tk.RIGHT)
        retention_spin.bind("<KeyRelease>", lambda e: self._mark_modified())

        # Database info
        info_frame = ttk.LabelFrame(frame, text="Database Info", padding="10")
        info_frame.pack(fill=tk.X, pady=(15, 5))

        sample_count = self.database.get_sample_count()
        self._db_info_label = ttk.Label(info_frame, text=f"Total samples: {sample_count:,}")
        self._db_info_label.pack(anchor=tk.W)

        # Clear data button
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(15, 5))

        clear_btn = ttk.Button(btn_frame, text="Clear All Data...", command=self._clear_data)
        clear_btn.pack(side=tk.LEFT)

        cleanup_btn = ttk.Button(btn_frame, text="Cleanup Old Data", command=self._cleanup_data)
        cleanup_btn.pack(side=tk.LEFT, padx=(10, 0))

    def _create_startup_tab(self) -> None:
        """Create the startup settings tab."""
        frame = ttk.Frame(self._notebook, padding="15")
        self._notebook.add(frame, text="Startup")

        # Info label
        info = ttk.Label(
            frame,
            text="Configure application startup behavior.",
            justify=tk.LEFT,
            foreground="gray"
        )
        info.pack(anchor=tk.W, pady=(0, 15))

        # Auto-start checkbox
        self._autostart_var = tk.BooleanVar()
        autostart_check = ttk.Checkbutton(
            frame,
            text="Start BottleneckWatch when Windows starts",
            variable=self._autostart_var,
            command=self._mark_modified
        )
        autostart_check.pack(anchor=tk.W, pady=5)

        # Note about admin
        note = ttk.Label(
            frame,
            text="Note: This adds an entry to your user's startup programs.\n"
                 "No administrator privileges required.",
            justify=tk.LEFT,
            foreground="gray",
            font=("Segoe UI", 8)
        )
        note.pack(anchor=tk.W, pady=(10, 0))

        # Separator
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)

        # Verbose logging checkbox
        self._verbose_var = tk.BooleanVar()
        verbose_check = ttk.Checkbutton(
            frame,
            text="Enable verbose logging",
            variable=self._verbose_var,
            command=self._mark_modified
        )
        verbose_check.pack(anchor=tk.W, pady=5)

        # Note about verbose logging
        verbose_note = ttk.Label(
            frame,
            text="When enabled, detailed logs are written to file and console.\n"
                 "When disabled, only errors are logged.",
            justify=tk.LEFT,
            foreground="gray",
            font=("Segoe UI", 8)
        )
        verbose_note.pack(anchor=tk.W, pady=(5, 0))

    def _create_about_tab(self) -> None:
        """Create the About tab with version info and update controls."""
        frame = ttk.Frame(self._notebook, padding="15")
        self._notebook.add(frame, text="About")

        # App name and version
        name_label = ttk.Label(
            frame,
            text=APP_NAME,
            font=("Segoe UI", 14, "bold")
        )
        name_label.pack(anchor=tk.W, pady=(0, 2))

        version_label = ttk.Label(
            frame,
            text=f"Version: {__version__}",
            font=("Segoe UI", 10)
        )
        version_label.pack(anchor=tk.W, pady=(0, 5))

        # GitHub link
        repo_url = f"https://github.com/{GITHUB_REPO}"
        link_label = ttk.Label(
            frame,
            text=repo_url,
            foreground="blue",
            cursor="hand2",
            font=("Segoe UI", 9, "underline")
        )
        link_label.pack(anchor=tk.W, pady=(0, 10))
        link_label.bind("<Button-1>", lambda e: webbrowser.open(repo_url))

        # Separator
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Update section
        update_frame = ttk.LabelFrame(frame, text="Updates", padding="10")
        update_frame.pack(fill=tk.X, pady=(0, 10))

        # Auto-update checkbox
        self._auto_update_var = tk.BooleanVar(value=self.config.get("auto_update_check", True))
        auto_check = ttk.Checkbutton(
            update_frame,
            text="Automatically check for updates on startup",
            variable=self._auto_update_var,
            command=self._on_auto_update_toggled
        )
        auto_check.pack(anchor=tk.W, pady=(0, 10))

        # Check for updates button and status
        btn_row = ttk.Frame(update_frame)
        btn_row.pack(fill=tk.X)

        self._check_update_btn = ttk.Button(
            btn_row,
            text="Check for Updates",
            command=self._on_check_updates_clicked
        )
        self._check_update_btn.pack(side=tk.LEFT)

        self._update_status_label = ttk.Label(btn_row, text="")
        self._update_status_label.pack(side=tk.LEFT, padx=(10, 0))

        # Update Now button (hidden initially)
        self._update_now_btn = ttk.Button(
            update_frame,
            text="Update Now",
            command=self._on_update_now_clicked
        )
        # Don't pack yet - shown when update is available

        # If updater already has a pending update, show it
        if self._updater and self._updater.latest_update:
            self._show_update_available(self._updater.latest_update.version)

    def _on_auto_update_toggled(self) -> None:
        """Handle auto-update checkbox toggle."""
        self.config.set("auto_update_check", self._auto_update_var.get())

    def _on_check_updates_clicked(self) -> None:
        """Handle Check for Updates button click."""
        if not self._updater:
            self._update_status_label.config(text="Update checker not available")
            return

        self._check_update_btn.config(state=tk.DISABLED)
        self._update_status_label.config(text="Checking...")
        self._update_now_btn.pack_forget()

        def on_result(update_info):
            # Schedule UI update on main thread
            if self._window and self._window.winfo_exists():
                self._window.after(0, lambda: self._handle_update_result(update_info))

        self._updater.check_for_update_async(on_result)

    def _handle_update_result(self, update_info) -> None:
        """Handle the result of an update check (called on main thread)."""
        self._check_update_btn.config(state=tk.NORMAL)

        if update_info:
            self._show_update_available(update_info.version)
        else:
            self._update_status_label.config(text="You are up to date.")
            self._update_now_btn.pack_forget()

    def _show_update_available(self, version: str) -> None:
        """Show that an update is available."""
        self._update_status_label.config(text=f"Update available: {version}")
        self._update_now_btn.pack(anchor=tk.W, pady=(10, 0))

    def _on_update_now_clicked(self) -> None:
        """Handle Update Now button click."""
        if not self._updater or not self._updater.latest_update:
            return

        update = self._updater.latest_update

        result = messagebox.askyesno(
            "Update Available",
            f"Update to version {update.version}?\n\n"
            f"The application will close and restart automatically.",
            parent=self._window
        )

        if result and self._on_apply_update:
            self._on_apply_update()

    def show_about_tab(self) -> None:
        """Show the settings window with the About tab selected."""
        self.show()
        if self._notebook:
            # Select the last tab (About)
            self._notebook.select(self._notebook.tabs()[-1])

    def _create_buttons(self, parent: ttk.Frame) -> None:
        """Create the action buttons."""
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X)

        # Reset to defaults
        reset_btn = ttk.Button(btn_frame, text="Reset to Defaults", command=self._reset_defaults)
        reset_btn.pack(side=tk.LEFT)

        # Cancel
        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self._handle_close)
        cancel_btn.pack(side=tk.RIGHT, padx=(5, 0))

        # Apply
        self._apply_btn = ttk.Button(btn_frame, text="Apply", command=self._apply_settings)
        self._apply_btn.pack(side=tk.RIGHT, padx=(5, 0))

        # Save
        save_btn = ttk.Button(btn_frame, text="Save", command=self._save_and_close)
        save_btn.pack(side=tk.RIGHT)

    def _load_values(self) -> None:
        """Load current configuration values into the UI."""
        # Thresholds
        yellow, red = self.config.get_thresholds()
        self._yellow_var.set(yellow)
        self._red_var.set(red)

        # Timing
        self._frequency_var.set(self.config.get("sampling_frequency_seconds", 5))
        self._smoothing_var.set(self.config.get("smoothing_window_minutes", 5))
        self._duration_var.set(self.config.get("minimum_pressure_duration_seconds", 30))

        # Weights
        weights = self.config.get_weights()
        self._weight_pf_var.set(weights.get("page_faults", 0.5))
        self._weight_ram_var.set(weights.get("available_ram", 0.3))
        self._weight_cr_var.set(weights.get("committed_ratio", 0.2))
        self._update_weight_labels()

        # Data
        self._retention_var.set(self.config.get("data_retention_days", 30))

        # Startup
        self._autostart_var.set(self._check_autostart())
        self._verbose_var.set(self.config.get("verbose_logging", False))

        self._modified = False

    def _check_autostart(self) -> bool:
        """Check if auto-start is currently enabled in registry."""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            logger.debug(f"Error checking autostart: {e}")
            return False

    def _set_autostart(self, enabled: bool) -> bool:
        """Set or remove auto-start registry entry."""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
            try:
                if enabled:
                    import sys
                    # Use pythonw.exe for no console window
                    python_exe = sys.executable.replace("python.exe", "pythonw.exe")
                    import os
                    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
                    value = f'"{python_exe}" "{script_path}"'
                    winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, value)
                    logger.info(f"Auto-start enabled: {value}")
                else:
                    try:
                        winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
                        logger.info("Auto-start disabled")
                    except FileNotFoundError:
                        pass  # Already not set
                return True
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            logger.error(f"Error setting autostart: {e}", exc_info=True)
            return False

    def _mark_modified(self) -> None:
        """Mark settings as modified."""
        self._modified = True

    def _validate_settings(self) -> bool:
        """Validate current settings values."""
        # Check thresholds
        yellow = self._yellow_var.get()
        red = self._red_var.get()

        if yellow >= red:
            messagebox.showerror(
                "Invalid Settings",
                "Yellow threshold must be less than red threshold.",
                parent=self._window
            )
            return False

        # Check weights sum
        total = self._weight_pf_var.get() + self._weight_ram_var.get() + self._weight_cr_var.get()
        if abs(total - 1.0) > 0.01:
            result = messagebox.askyesno(
                "Weight Warning",
                f"Weights sum to {total:.2f} instead of 1.0.\n\n"
                "This may produce unexpected pressure values.\n"
                "Continue anyway?",
                parent=self._window
            )
            if not result:
                return False

        return True

    def _apply_settings(self) -> None:
        """Apply current settings without closing."""
        if not self._validate_settings():
            return

        # Save thresholds
        self.config.set("thresholds.yellow", self._yellow_var.get(), save=False)
        self.config.set("thresholds.red", self._red_var.get(), save=False)

        # Save timing
        self.config.set("sampling_frequency_seconds", self._frequency_var.get(), save=False)
        self.config.set("smoothing_window_minutes", self._smoothing_var.get(), save=False)
        self.config.set("minimum_pressure_duration_seconds", self._duration_var.get(), save=False)

        # Save weights
        self.config.set("metric_weights.page_faults", round(self._weight_pf_var.get(), 2), save=False)
        self.config.set("metric_weights.available_ram", round(self._weight_ram_var.get(), 2), save=False)
        self.config.set("metric_weights.committed_ratio", round(self._weight_cr_var.get(), 2), save=False)

        # Save data
        self.config.set("data_retention_days", self._retention_var.get(), save=False)

        # Save auto-start
        self.config.set("auto_start", self._autostart_var.get(), save=False)

        # Save verbose logging
        self.config.set("verbose_logging", self._verbose_var.get(), save=True)

        # Apply auto-start to registry
        self._set_autostart(self._autostart_var.get())

        self._modified = False
        logger.info("Settings applied")

        # Notify callback
        if self._on_settings_changed:
            self._on_settings_changed()

    def _save_and_close(self) -> None:
        """Save settings and close window."""
        self._apply_settings()
        self._handle_close()

    def _reset_defaults(self) -> None:
        """Reset all settings to defaults."""
        result = messagebox.askyesno(
            "Reset to Defaults",
            "Are you sure you want to reset all settings to defaults?",
            parent=self._window
        )

        if result:
            self.config.reset_to_defaults()
            self._load_values()
            logger.info("Settings reset to defaults")

    def _clear_data(self) -> None:
        """Clear all historical data."""
        result = messagebox.askyesno(
            "Clear All Data",
            "Are you sure you want to delete ALL historical data?\n\n"
            "This action cannot be undone.",
            icon="warning",
            parent=self._window
        )

        if result:
            self.database.clear_all_data()
            self._db_info_label.config(text="Total samples: 0")
            messagebox.showinfo("Data Cleared", "All historical data has been deleted.", parent=self._window)

    def _cleanup_data(self) -> None:
        """Cleanup old data based on retention setting."""
        retention = self._retention_var.get()
        deleted = self.database.cleanup_old_data(retention)

        sample_count = self.database.get_sample_count()
        self._db_info_label.config(text=f"Total samples: {sample_count:,}")

        messagebox.showinfo(
            "Cleanup Complete",
            f"Deleted {deleted:,} samples older than {retention} days.\n"
            f"Remaining samples: {sample_count:,}",
            parent=self._window
        )

    def _handle_close(self) -> None:
        """Handle window close."""
        if self._modified:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                parent=self._window
            )

            if result is None:  # Cancel
                return
            elif result:  # Yes - save
                self._apply_settings()

        logger.info("Settings window closing")

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

    def show(self) -> None:
        """Show the settings window."""
        if self._window and self._window.winfo_exists():
            # Window already exists, bring to front
            self._window.lift()
            self._window.focus_force()
            return

        logger.info("Opening settings window")

        # Create window
        self._create_window()

        # Bring to front
        self._window.lift()
        self._window.focus_force()

    def is_visible(self) -> bool:
        """Check if window is currently visible."""
        return self._window is not None and self._window.winfo_exists()
