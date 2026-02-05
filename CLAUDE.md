# BottleneckWatch

## Project Overview

BottleneckWatch is a Windows 11 system tray utility that helps users identify hardware bottlenecks in their system. Originally focused on memory pressure (similar to macOS's Memory Pressure metric), it has evolved to help answer the broader question: "Why is my PC slow?" by identifying whether the bottleneck is RAM, disk I/O, or simply waiting for data to load.

The goal is to help users make informed decisions about hardware upgrades by showing them where their system is genuinely struggling versus normal operational behaviour.

## Core Philosophy

- **Sustained pressure, not transient spikes**: The tool should distinguish between normal system operations and genuine hardware inadequacy
- **Time-weighted analysis**: Tray icon reflects overall system health over recent minutes, not instantaneous state
- **Data-driven tuning**: All thresholds and weights are configurable to allow experimentation and refinement
- **User respect**: Non-invasive, runs as standard user, auto-start is opt-in
- **Bottleneck identification**: Help users understand if slowness is due to RAM, disk, or other factors

## Technical Requirements

### Platform
- Windows 11 Home/Pro
- Python 3.10+
- Must run as standard user (no administrator privileges required)

### Dependencies
- `psutil` - cross-platform system monitoring
- `pystray` - system tray functionality
- `pillow` - icon generation
- `wmi` - Windows-specific metrics
- `pywin32` - Windows API access
- `matplotlib` - graphing
- `sqlite3` - persistent data storage (built into Python)

## Feature Requirements - Version 1

### System Tray Icon
- **Visual design**:
  - Simple solid square at maximum system tray dimensions
  - Full icon colour change: green (healthy) → yellow (moderate pressure) → red (high pressure)
  - Percentage overlaid as number only (e.g., "67") in contrasting colour (white)
- **Update frequency**: 5 seconds default (user-configurable)
- **Behaviour**: Colour reflects time-smoothed pressure, not instantaneous readings

### Right-Click Context Menu
- **View Details**: Opens detailed monitoring window
- **Settings**: Opens configuration panel
- **Check for Updates**: Opens Settings window on the About tab
- **Exit**: Cleanly shuts down application

### Detail View Window
- **Real-time metrics display**:
  - Current pressure percentage
  - Individual component metrics (page faults/sec, available RAM %, committed memory ratio, etc.)
  - Disk I/O metrics (page I/O, regular I/O, disk busy %)
  - Smoothed vs raw readings
- **Historical graphs**:
  - Memory pressure graph (smoothed and raw)
  - Memory metrics graph (available RAM %, committed %)
  - Disk I/O graph with:
    - Page I/O (memory-related disk activity)
    - Regular I/O (non-memory disk activity)
    - Disk busy % (saturation indicator)
  - Configurable time periods (last hour, 6 hours, 24 hours, 7 days, 30 days)
  - Auto-refresh option (30-second interval, toggled via checkbox)
- **Data access**:
  - Current session data
  - Historical data loaded from disk
  - Export capability (CSV)

### Settings Panel
- **Thresholds**:
  - Green → Yellow pressure threshold (%)
  - Yellow → Red pressure threshold (%)
- **Timing**:
  - Update/sampling frequency (seconds)
  - Smoothing time window (minutes)
  - Minimum duration for sustained pressure before colour change (seconds)
- **Algorithm tuning**:
  - Individual metric weights (page faults, available RAM, committed memory)
- **Data management**:
  - Data retention period (days)
  - Clear historical data option
  - Cleanup old data option
- **Startup**:
  - Auto-start with Windows toggle (default: DISABLED)
  - Verbose logging toggle (default: DISABLED) - when disabled, only errors are logged
- **About**:
  - Application name, version, and GitHub link
  - Auto-check for updates on startup toggle
  - Manual check for updates button
  - Update Now button (shown when update is available)
- **Apply/Save/Cancel** buttons

### Data Storage
- **Configuration**: JSON file in `%APPDATA%\BottleneckWatch\config.json`
- **Historical data**: SQLite database in `%APPDATA%\BottleneckWatch\history.db`
- **Log file**: `%APPDATA%\BottleneckWatch\bottleneckwatch.log`
- **Database Schema** (version 2):
  - id (primary key)
  - timestamp
  - pressure_smoothed
  - pressure_raw
  - page_faults
  - available_ram_bytes
  - available_ram_percent
  - committed_bytes
  - committed_ratio
  - page_io_bytes_per_sec (memory-related disk I/O)
  - disk_read_bytes_per_sec
  - disk_write_bytes_per_sec
  - disk_percent_busy

### Pressure Calculation Algorithm

**Key principle**: Identify genuine memory inadequacy, not normal memory management

**Primary metric**: Page fault frequency (indicates disk swapping)

**Supporting metrics**:
- Available RAM percentage
- Committed memory ratio (committed/limit)

**Processing**:
1. Collect raw metrics every sampling interval
2. Calculate instantaneous pressure score (weighted combination)
3. Apply time-smoothing (simple moving average) over configurable window
4. Store both raw and smoothed values
5. Update tray icon based on smoothed value
6. Flag "pressure events" when smoothed value exceeds threshold for minimum duration

**Weights** (user-configurable):
- Page faults/sec: 50%
- Available RAM: 30%
- Committed ratio: 20%

**Thresholds** (user-configurable):
- Green: 0-59% pressure
- Yellow: 60-79% pressure
- Red: 80-100% pressure

### Disk I/O Analysis

The detail view includes disk I/O monitoring to help differentiate:
- **Page I/O (Memory-related)**: Disk activity caused by memory management (paging/swapping)
- **Regular I/O**: Normal disk activity (loading programs, reading files)
- **Disk Busy %**: Overall disk saturation

This helps users understand:
- If disk is saturated with mostly page I/O → likely need more RAM
- If disk is saturated with mostly regular I/O → disk throughput is the bottleneck
- If disk is not saturated → neither RAM nor disk is the issue

## Application Architecture

### Components

1. **Data Collection Module** (`collector.py`)
   - Interfaces with Windows Performance Counters via psutil/WMI
   - Samples metrics at configured frequency
   - Collects both memory metrics and disk I/O metrics
   - Handles WMI threading requirements (lazy initialization per thread)

2. **Pressure Calculator** (`calculator.py`)
   - Implements pressure algorithm
   - Maintains smoothing buffer (bounded deque)
   - Applies weights and thresholds
   - Detects pressure events using running statistics (memory-efficient)

3. **Database Manager** (`database.py`)
   - SQLite interface with schema versioning
   - Automatic migrations between schema versions
   - Stores historical samples
   - Queries for graphing
   - Manages data retention

4. **Configuration Manager** (`config.py`)
   - Loads/saves settings from JSON
   - Provides defaults
   - Validates settings
   - Supports dot-notation for nested keys

5. **Tray Icon** (`tray.py`)
   - Manages system tray presence
   - Generates coloured icons with percentage overlay
   - Handles context menu (View Details, Settings, Check for Updates, Exit)
   - Displays tooltip with current status and update availability

6. **Detail View Window** (`detail_window.py`)
   - Real-time metric display
   - Three historical graphs (pressure, memory, disk I/O)
   - Time period selection
   - Auto-refresh checkbox (30-second interval)
   - CSV data export
   - Proper matplotlib cleanup to prevent memory leaks

7. **Settings Window** (`settings_window.py`)
   - Configuration UI with tabbed interface (Thresholds, Timing, Weights, Data, Startup, About)
   - Input validation
   - Auto-start registry management
   - Database cleanup tools
   - About tab with version info, GitHub link, and update management

8. **Auto-Updater** (`updater.py`)
   - Checks GitHub releases API for newer versions
   - Downloads and extracts update zip to staging directory
   - Generates a batch script to apply the update after the app exits
   - Supports skipping versions and async checking
   - Version comparison uses date-based format (YYYY-MM-DD-HH)

9. **Release Script** (`release.py`)
   - Generates date-based version strings from UTC time
   - Updates `__version__` in `src/__init__.py`
   - Git commit, tag, and push
   - Creates distributable zip (excludes dev files)
   - Creates GitHub release via `gh` CLI
   - Supports `--dry-run` mode

10. **Main Application** (`main.py`)
    - Coordinates all components
    - Initial synchronous collection for immediate display
    - Main event loop (tkinter)
    - Background update checks (on startup if enabled, then every 7 days)
    - Update application flow (download, extract, script, restart)
    - Graceful shutdown

### Threading Model
- Main thread: GUI (tkinter mainloop, windows)
- Collection thread: Data collection and processing
- Tray thread: pystray runs in detached mode
- Update check thread: Background GitHub API calls
- Update apply thread: Download and extraction
- Thread-safe communication via queues
- WMI initialized per-thread due to COM apartment threading requirements

## Default Configuration
```json
{
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
  "auto_start": false,
  "verbose_logging": false,
  "auto_update_check": true,
  "skipped_version": null
}
```

## Development Status

### Completed (v1)
- [x] Project structure setup
- [x] Data collection module with memory and disk I/O metrics
- [x] Pressure calculator with bounded memory usage
- [x] System tray icon with colour changes and percentage
- [x] Database storage with schema migrations
- [x] Detail view with three graphs
- [x] Settings window with all options
- [x] Configuration persistence
- [x] Data export (CSV)
- [x] Auto-start with Windows
- [x] Initial pressure collection (no 0% on startup)
- [x] Memory efficiency review
- [x] GitHub release preparation

### Completed (Post-v1)
- [x] Auto-update system (check, download, extract, apply via batch script)
- [x] Release automation script (`release.py` with `--dry-run` support)
- [x] About tab in Settings with version info and update controls
- [x] "Check for Updates" tray menu item
- [x] Background update checks (on startup, then every 7 days)
- [x] Skip version support for updates
- [x] Auto-refresh checkbox for detail view graphs (30-second interval)

### Future Enhancements
- Notification system with custom thresholds
- CPU metrics and bottleneck detection
- Network I/O monitoring
- More sophisticated pressure algorithms
- Multi-monitor DPI awareness
- Installer/packaging (MSI or similar)

## Constraints & Considerations

- **No administrator privileges**: All metrics must be accessible to standard users
- **Low overhead**: Monitoring tool shouldn't impact system performance
- **Memory efficient**: Tool runs continuously, must not leak memory
- **Graceful degradation**: Handle missing metrics or permissions failures
- **Windows 11 specific**: Can use modern Windows APIs, no legacy support needed
- **User privacy**: All data stored locally, no telemetry

## File Structure
```
BottleneckWatch/
├── CLAUDE.md                 # This file (development notes)
├── README.md                 # User-facing documentation
├── LICENSE                   # MIT License
├── requirements.txt          # Python dependencies
├── .gitignore               # Git ignore patterns
├── install.bat              # Automated installation script
├── run.bat                  # Run with console (for debugging)
├── run_silent.bat           # Run without console (normal use)
├── uninstall.bat            # Cleanup script
├── main.py                  # Application entry point
├── release.py               # Release automation script
└── src/
    ├── __init__.py           # Version and GitHub repo constants
    ├── collector.py          # Metrics collection (memory + disk I/O)
    ├── calculator.py         # Pressure calculation
    ├── database.py           # SQLite interface with migrations
    ├── config.py             # Configuration management
    ├── tray.py               # System tray icon
    ├── detail_window.py      # Detail view GUI with graphs
    ├── settings_window.py    # Settings GUI
    ├── updater.py            # Auto-update from GitHub releases
    └── utils.py              # Shared utilities and logging
```

## Notes for Claude Code

- **Code style**: Well-commented, clear variable names, docstrings for all functions/classes
- **Error handling**: Robust exception handling, especially for Windows API calls
- **Logging**: File-based logging with rotation (10MB max, 5 backups)
- **Type hints**: Use Python type hints for clarity
- **Modularity**: Keep components loosely coupled for easier testing and modification
- **Memory efficiency**: Use bounded data structures (deque with maxlen), running statistics instead of lists
- **Threading**: WMI objects are COM apartment-threaded, must initialize per-thread
- **Matplotlib**: Clean up figures on window close to prevent memory leaks

## Debugging and Logging

### Logging Setup
- Python's `logging` module with file-based output
- Log file: `%APPDATA%\BottleneckWatch\bottleneckwatch.log`
- Log rotation: max 10MB per file, keep last 5 files
- Default level: INFO (DEBUG available for troubleshooting)
- Thread IDs included for multi-threaded debugging
- Millisecond precision timestamps

### What to Log

**INFO level**:
- Application startup/shutdown
- Configuration loaded/saved
- Settings changes
- Pressure threshold crossings
- Pressure events (start/end)
- Database operations
- Auto-start registry modifications
- WMI initialization per thread
- Update checks (start, result, download, apply)
- Auto-refresh enable/disable

**WARNING level**:
- Failed metric collection (with recovery)
- Missing optional features

**ERROR level**:
- Exceptions with full stack traces
- Critical failures

**DEBUG level**:
- Raw metric values at each sample
- Calculated pressure scores
- Disk I/O values
- GUI window events

## Resolved Questions

1. **Graphing library**: matplotlib (good performance, familiar API)
2. **Smoothing algorithm**: Simple moving average with bounded deque
3. **Page fault normalization**: Logarithmic scale (0→0, 10→33, 100→67, 1000→100)
4. **Additional metrics**: Disk I/O added (page I/O vs regular I/O)
5. **Icon size**: Fixed 64px, system scales as needed
6. **Update mechanism**: Download zip from GitHub releases, extract to staging, generate batch script that waits for process exit then copies files over
7. **Version format**: Date-based `YYYY-MM-DD-HH` (UTC), supports lexicographic comparison

---

**Project Start Date**: January 2026
**Developer**: Joshua C Froelich (with Claude Code assistance)
