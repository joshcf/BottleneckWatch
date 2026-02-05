# BottleneckWatch

A Windows 11 system tray utility that provides at-a-glance insight into memory pressure, similar to macOS's Memory Pressure metric.

## What It Does

BottleneckWatch helps answer the question: **"Do I have enough RAM for my usage?"**

Unlike Task Manager which shows raw memory usage, BottleneckWatch identifies when Windows is genuinely struggling with memory management versus normal operational behaviour. It uses time-weighted analysis to show sustained pressure rather than transient spikes.

## Features

- **System Tray Icon**: Color-coded indicator (green/yellow/red) with percentage overlay
- **Smart Pressure Detection**: Distinguishes between normal memory management and genuine memory inadequacy
- **Time-Smoothed Analysis**: Icon reflects system health over recent minutes, not instantaneous state
- **Disk I/O Monitoring**: Differentiates memory-related disk activity (paging) from regular disk I/O
- **Historical Graphs**: View pressure trends over hours, days, or weeks
- **Configurable Thresholds**: Tune sensitivity to match your needs
- **Data Export**: Export historical data to CSV for analysis
- **Auto-Updates**: Checks for new releases and updates in-place
- **Low Overhead**: Designed to run continuously without impacting system performance
- **No Admin Required**: Runs as a standard user

## Requirements

- Windows 11 (Windows 10 may work but is untested)
- Python 3.10 or higher

## Installation

### Quick Install (Recommended)

1. Download the latest release zip from the [Releases page](https://github.com/joshcf/BottleneckWatch/releases/latest)
2. Extract the zip to a folder of your choice (e.g., `C:\Tools\BottleneckWatch`)
3. Double-click `install.bat`

The install script will:
- Check that Python is installed
- Create a virtual environment
- Install all dependencies

### Manual Install

If you prefer to install manually:

1. Download and extract the latest release (see above), or clone the repository:
   ```
   git clone https://github.com/joshcf/BottleneckWatch.git
   cd BottleneckWatch
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Running BottleneckWatch

### Using Batch Files (Recommended)

- **`run_silent.bat`**: Runs BottleneckWatch without a console window. This is the normal way to run the application.
- **`run.bat`**: Runs with a console window visible. Useful for debugging or if you want to see log output.

### Manual Run

```
venv\Scripts\activate
python main.py
```

Or without a console window:
```
venv\Scripts\pythonw.exe main.py
```

### Auto-Start with Windows

You can enable auto-start from Settings > Startup within the application. This adds an entry to your user's startup programs (no administrator privileges required).

## Usage

Once running, BottleneckWatch appears in your system tray:

- **Green icon**: Memory pressure is normal (0-59%)
- **Yellow icon**: Moderate memory pressure (60-79%)
- **Red icon**: High memory pressure (80-100%)

### Right-Click Menu

- **View Details**: Opens the detailed monitoring window with real-time metrics and historical graphs
- **Settings**: Configure thresholds, sampling frequency, and other options
- **Check for Updates**: Check for and install new versions
- **Exit**: Close BottleneckWatch

### Detail View

The detail window shows:
- Current memory metrics (pressure, page faults, available RAM, committed memory)
- Disk I/O breakdown (memory-related vs regular I/O)
- Historical pressure graphs
- Memory metrics over time

### Settings

Configurable options include:
- **Thresholds**: When to show yellow/red indicators
- **Sampling Frequency**: How often to collect metrics (default: 5 seconds)
- **Smoothing Window**: Time period for averaging pressure (default: 5 minutes)
- **Metric Weights**: Relative importance of page faults, available RAM, and committed memory
- **Data Retention**: How long to keep historical data (default: 30 days)

## How Pressure is Calculated

BottleneckWatch calculates pressure using a weighted combination of:

1. **Page Faults/sec** (50% weight): High page fault rates indicate the system is frequently accessing disk for memory operations
2. **Available RAM** (30% weight): Low available RAM means less headroom for new applications
3. **Committed Memory Ratio** (20% weight): High commit ratio indicates the system is approaching its memory limits

The raw pressure is then smoothed over the configured time window to avoid showing momentary spikes.

## Understanding Disk I/O

The detail view includes a disk I/O graph that helps identify why your system might feel slow:

- **Page I/O (Memory)**: Disk activity caused by memory management (paging/swapping)
- **Regular I/O**: Normal disk activity (loading programs, reading files)
- **Disk Busy %**: Overall disk saturation

If disk is saturated and most I/O is memory-related, you likely need more RAM. If most I/O is regular, the slowness is just disk throughput (consider an SSD upgrade).

## Updating

BottleneckWatch checks for updates automatically on startup (configurable in Settings > About). When an update is available, you can install it from Settings > About or via the "Check for Updates" tray menu item. The application will download the update, close, apply the new files, and restart automatically.

You can also update manually by downloading the latest release from the [Releases page](https://github.com/joshcf/BottleneckWatch/releases/latest) and extracting it over your existing installation.

## Data Storage

BottleneckWatch stores its data in `%APPDATA%\BottleneckWatch\`:
- `config.json`: Your settings
- `history.db`: Historical metrics (SQLite database)
- `bottleneckwatch.log`: Application logs

## Uninstalling

### Using Uninstall Script (Recommended)

1. Exit BottleneckWatch from the tray icon menu
2. Double-click `uninstall.bat`

The uninstall script will:
- Remove BottleneckWatch from Windows startup (if enabled)
- Delete the virtual environment

Your settings and historical data in `%APPDATA%\BottleneckWatch` are preserved. Delete that folder manually if you want to remove all data.

### Manual Uninstall

1. Exit BottleneckWatch from the tray icon menu
2. If auto-start is enabled, disable it in Settings first (or manually remove from Windows startup)
3. Delete the BottleneckWatch folder
4. Optionally, delete `%APPDATA%\BottleneckWatch\` to remove settings and historical data

## Troubleshooting

### BottleneckWatch won't start
- Check the log file at `%APPDATA%\BottleneckWatch\bottleneckwatch.log`
- Ensure Python 3.10+ is installed and in your PATH
- Verify all dependencies are installed: `pip install -r requirements.txt`

### Tray icon not visible
- Check the Windows system tray overflow area (click the ^ arrow)
- Right-click the taskbar > Taskbar settings > enable BottleneckWatch in "Other system tray icons"

### High CPU usage
- Increase the sampling frequency in Settings (e.g., from 5 to 10 seconds)

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Developed with [Claude Code](https://claude.ai/code) by Anthropic
- Built with [psutil](https://github.com/giampaolo/psutil) for cross-platform system monitoring
- System tray functionality via [pystray](https://github.com/moses-palmer/pystray)
- Graphing with [matplotlib](https://matplotlib.org/)
