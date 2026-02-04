"""Memory metrics collection for BottleneckWatch.

Collects Windows memory metrics using psutil and WMI.
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional

import psutil

from .utils import get_logger

logger = get_logger(__name__)


@dataclass
class MemoryMetrics:
    """Container for collected memory metrics."""

    timestamp: float
    page_faults_per_sec: float
    available_ram_bytes: int
    available_ram_percent: float
    committed_bytes: int
    committed_limit: int
    committed_ratio: float
    total_ram_bytes: int

    # Disk I/O metrics (optional, for detail view graphing)
    page_io_bytes_per_sec: float = 0.0  # Memory-related disk I/O
    disk_read_bytes_per_sec: float = 0.0  # Total disk reads
    disk_write_bytes_per_sec: float = 0.0  # Total disk writes
    disk_percent_busy: float = 0.0  # Disk saturation indicator

    @property
    def total_disk_io_bytes_per_sec(self) -> float:
        """Total disk I/O (reads + writes) in bytes per second."""
        return self.disk_read_bytes_per_sec + self.disk_write_bytes_per_sec

    @property
    def regular_io_bytes_per_sec(self) -> float:
        """Non-memory disk I/O (total - page I/O) in bytes per second."""
        return max(0.0, self.total_disk_io_bytes_per_sec - self.page_io_bytes_per_sec)

    @property
    def page_io_percent(self) -> float:
        """Percentage of disk I/O that is memory-related."""
        total = self.total_disk_io_bytes_per_sec
        if total <= 0:
            return 0.0
        return min(100.0, (self.page_io_bytes_per_sec / total) * 100)

    @property
    def regular_io_percent(self) -> float:
        """Percentage of disk I/O that is regular (non-memory)."""
        return 100.0 - self.page_io_percent


class MetricsCollector:
    """Collects memory metrics from Windows."""

    def __init__(self) -> None:
        """Initialize the metrics collector."""
        self._last_page_faults: Optional[int] = None
        self._last_collection_time: Optional[float] = None
        self._wmi = None
        self._wmi_available = False
        self._wmi_thread_id: Optional[int] = None  # Track which thread owns WMI

        logger.info("MetricsCollector initialized (WMI will be initialized lazily)")

    def _ensure_wmi(self) -> bool:
        """
        Ensure WMI is initialized for the current thread.

        WMI COM objects are apartment-threaded and cannot be shared across threads.
        This method initializes COM and WMI on first use or reinitializes if called
        from a different thread.

        Returns:
            True if WMI is available, False otherwise
        """
        current_thread = threading.current_thread().ident

        # Check if we need to (re)initialize WMI
        if self._wmi is None or self._wmi_thread_id != current_thread:
            if self._wmi is not None:
                logger.debug(f"Reinitializing WMI for thread {current_thread} (was {self._wmi_thread_id})")

            try:
                # COM must be initialized on each thread before using WMI
                import pythoncom
                pythoncom.CoInitialize()

                import wmi
                self._wmi = wmi.WMI()
                self._wmi_available = True
                self._wmi_thread_id = current_thread
                logger.info(f"WMI initialized successfully on thread {current_thread}")
            except ImportError as e:
                logger.warning(f"WMI or pythoncom module not available: {e}")
                self._wmi_available = False
            except Exception as e:
                logger.warning(f"Failed to initialize WMI: {e}")
                self._wmi_available = False

        return self._wmi_available

    def _get_page_faults_per_sec_wmi(self) -> Optional[float]:
        """
        Get hard page faults per second using WMI performance counters.

        Hard page faults (page reads) occur when a page must be fetched from
        disk, indicating actual memory pressure. This excludes soft page faults
        (resolved in-memory from standby list, zero-fill, or copy-on-write)
        which are normal high-frequency operations that don't indicate pressure.

        Returns:
            Hard page faults (page reads) per second, or None if unavailable
        """
        if not self._ensure_wmi():
            return None

        try:
            # Query Win32_PerfFormattedData_PerfOS_Memory for hard faults/sec
            perf_data = self._wmi.Win32_PerfFormattedData_PerfOS_Memory()
            if perf_data:
                # PageReadsPersec counts hard page faults - disk read operations
                # caused by page fault resolution. This directly measures when
                # the system must go to disk because the page is not in RAM.
                # (Unlike PageFaultsPersec which includes soft faults that are
                # resolved in-memory and don't indicate memory pressure.)
                return float(perf_data[0].PageReadsPersec)
        except Exception as e:
            logger.debug(f"WMI hard page fault query failed: {e}")

        return None

    def _get_page_faults_per_sec_psutil(self) -> float:
        """
        Estimate hard page faults per second using psutil as a fallback.

        Uses swap I/O (bytes swapped in/out) as a proxy for hard page faults,
        since psutil doesn't expose the PageReadsPersec counter directly.

        Returns:
            Estimated hard page faults per second
        """
        try:
            # Get system-wide swap statistics
            swap = psutil.swap_memory()
            vm = psutil.virtual_memory()

            current_time = time.time()

            # psutil doesn't directly give page faults, but we can use
            # swap I/O as a proxy for hard page faults
            # sin = bytes swapped in, sout = bytes swapped out
            current_faults = swap.sin + swap.sout  # Total swap I/O in bytes

            if self._last_page_faults is not None and self._last_collection_time is not None:
                time_delta = current_time - self._last_collection_time
                if time_delta > 0:
                    fault_delta = current_faults - self._last_page_faults
                    # Convert bytes to approximate page count (4KB pages)
                    page_faults = fault_delta / 4096
                    faults_per_sec = max(0, page_faults / time_delta)

                    self._last_page_faults = current_faults
                    self._last_collection_time = current_time

                    return faults_per_sec

            # First sample - store for next calculation
            self._last_page_faults = current_faults
            self._last_collection_time = current_time

            return 0.0

        except Exception as e:
            logger.debug(f"psutil page fault calculation failed: {e}")
            return 0.0

    def collect(self) -> Optional[MemoryMetrics]:
        """
        Collect current memory metrics.

        Returns:
            MemoryMetrics object with current values, or None on failure
        """
        try:
            timestamp = time.time()

            # Get memory information from psutil
            vm = psutil.virtual_memory()

            # Calculate basic metrics
            total_ram = vm.total
            available_ram = vm.available
            available_ram_percent = (available_ram / total_ram) * 100

            # Committed memory - Windows specific
            # In psutil, 'used' approximates committed memory
            # For more accurate committed bytes, we need the commit limit too
            committed_bytes = vm.total - vm.available

            # Try to get actual commit limit from WMI or use total RAM as fallback
            committed_limit = self._get_commit_limit() or vm.total
            committed_ratio = (committed_bytes / committed_limit) * 100 if committed_limit > 0 else 0

            # Get hard page faults per second (disk reads caused by page faults)
            # Try WMI first (more accurate), fall back to psutil estimation
            page_faults = self._get_page_faults_per_sec_wmi()
            if page_faults is None:
                page_faults = self._get_page_faults_per_sec_psutil()

            # Get disk I/O metrics
            page_io_bytes = self._get_page_io_bytes_per_sec()
            disk_read, disk_write, disk_busy = self._get_disk_io_metrics()

            metrics = MemoryMetrics(
                timestamp=timestamp,
                page_faults_per_sec=page_faults,
                available_ram_bytes=available_ram,
                available_ram_percent=available_ram_percent,
                committed_bytes=committed_bytes,
                committed_limit=committed_limit,
                committed_ratio=committed_ratio,
                total_ram_bytes=total_ram,
                page_io_bytes_per_sec=page_io_bytes,
                disk_read_bytes_per_sec=disk_read,
                disk_write_bytes_per_sec=disk_write,
                disk_percent_busy=disk_busy
            )

            return metrics

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}", exc_info=True)
            return None

    def _get_commit_limit(self) -> Optional[int]:
        """
        Get the system commit limit (physical RAM + page file size).

        Returns:
            Commit limit in bytes, or None if unavailable
        """
        if not self._ensure_wmi():
            return None

        try:
            # Query Win32_OperatingSystem for TotalVirtualMemorySize
            os_info = self._wmi.Win32_OperatingSystem()
            if os_info:
                # TotalVirtualMemorySize is in KB
                return int(os_info[0].TotalVirtualMemorySize) * 1024
        except Exception as e:
            logger.debug(f"Failed to get commit limit: {e}")

        return None

    def _get_page_io_bytes_per_sec(self) -> float:
        """
        Get memory-related disk I/O in bytes per second.

        Uses page reads and writes from memory performance counters.
        Each page is 4KB.

        Returns:
            Page I/O in bytes per second
        """
        if not self._ensure_wmi():
            return 0.0

        try:
            perf_data = self._wmi.Win32_PerfFormattedData_PerfOS_Memory()
            if perf_data:
                # PagesInputPersec = pages read from disk (note: 'Pages' not 'Page')
                # PagesOutputPersec = pages written to disk
                page_inputs = float(perf_data[0].PagesInputPersec)
                page_outputs = float(perf_data[0].PagesOutputPersec)
                # Convert pages to bytes (4KB per page)
                result = (page_inputs + page_outputs) * 4096
                logger.debug(f"Page I/O: {result/1024:.1f} KB/s ({page_inputs:.0f} in + {page_outputs:.0f} out)")
                return result
            else:
                logger.warning("No data returned from Win32_PerfFormattedData_PerfOS_Memory")
        except Exception as e:
            logger.warning(f"Failed to get page I/O: {e}", exc_info=True)

        return 0.0

    def _get_disk_io_metrics(self) -> tuple[float, float, float]:
        """
        Get disk I/O metrics from physical disk performance counters.

        Returns:
            Tuple of (read_bytes_per_sec, write_bytes_per_sec, percent_busy)
        """
        if not self._ensure_wmi():
            return (0.0, 0.0, 0.0)

        try:
            # Query physical disk performance - "_Total" gives aggregate of all disks
            perf_data = self._wmi.Win32_PerfFormattedData_PerfDisk_PhysicalDisk(Name="_Total")
            if perf_data:
                disk = perf_data[0]
                read_bytes = float(disk.DiskReadBytesPersec)
                write_bytes = float(disk.DiskWriteBytesPersec)
                # PercentDiskTime can exceed 100% on systems with multiple disks
                # Clamp to 100 for display purposes
                percent_busy = min(100.0, float(disk.PercentDiskTime))
                logger.debug(f"Disk I/O: read={read_bytes/1024:.1f}KB/s, write={write_bytes/1024:.1f}KB/s, busy={percent_busy:.1f}%")
                return (read_bytes, write_bytes, percent_busy)
            else:
                logger.warning("No data returned from Win32_PerfFormattedData_PerfDisk_PhysicalDisk")
        except Exception as e:
            logger.warning(f"Failed to get disk I/O metrics: {e}", exc_info=True)

        return (0.0, 0.0, 0.0)
