"""Database management for BottleneckWatch.

SQLite storage for historical memory pressure data.
"""

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator, Optional

from .utils import get_logger, DATABASE_FILE

logger = get_logger(__name__)

# Database schema version for migrations
SCHEMA_VERSION = 2

CREATE_SAMPLES_TABLE = """
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    pressure_smoothed REAL NOT NULL,
    pressure_raw REAL NOT NULL,
    page_faults REAL NOT NULL,
    available_ram_bytes INTEGER NOT NULL,
    available_ram_percent REAL NOT NULL,
    committed_bytes INTEGER NOT NULL,
    committed_ratio REAL NOT NULL,
    page_io_bytes_per_sec REAL DEFAULT 0,
    disk_read_bytes_per_sec REAL DEFAULT 0,
    disk_write_bytes_per_sec REAL DEFAULT 0,
    disk_percent_busy REAL DEFAULT 0
);
"""

# Migration from schema version 1 to 2: add disk I/O columns
MIGRATE_V1_TO_V2 = [
    "ALTER TABLE samples ADD COLUMN page_io_bytes_per_sec REAL DEFAULT 0",
    "ALTER TABLE samples ADD COLUMN disk_read_bytes_per_sec REAL DEFAULT 0",
    "ALTER TABLE samples ADD COLUMN disk_write_bytes_per_sec REAL DEFAULT 0",
    "ALTER TABLE samples ADD COLUMN disk_percent_busy REAL DEFAULT 0",
]

CREATE_TIMESTAMP_INDEX = """
CREATE INDEX IF NOT EXISTS idx_samples_timestamp ON samples(timestamp);
"""

CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class DatabaseManager:
    """Manages SQLite database for historical data storage."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """
        Initialize the database manager.

        Args:
            db_path: Optional custom path for database file
        """
        self.db_path = db_path or DATABASE_FILE
        self._connection: Optional[sqlite3.Connection] = None

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

        logger.info(f"DatabaseManager initialized: {self.db_path}")

    def _init_database(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Create tables (for new databases)
            cursor.execute(CREATE_SAMPLES_TABLE)
            cursor.execute(CREATE_TIMESTAMP_INDEX)
            cursor.execute(CREATE_META_TABLE)

            # Check current schema version
            cursor.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", "1")
            )
            cursor.execute("SELECT value FROM meta WHERE key = ?", ("schema_version",))
            row = cursor.fetchone()
            current_version = int(row[0]) if row else 1

            # Run migrations if needed
            if current_version < SCHEMA_VERSION:
                self._run_migrations(conn, current_version)

            conn.commit()

        logger.info("Database schema initialized")

    def _run_migrations(self, conn: sqlite3.Connection, from_version: int) -> None:
        """
        Run database migrations from current version to latest.

        Args:
            conn: Database connection
            from_version: Current schema version
        """
        cursor = conn.cursor()

        if from_version < 2:
            logger.info("Migrating database schema from v1 to v2 (adding disk I/O columns)")
            for sql in MIGRATE_V1_TO_V2:
                try:
                    cursor.execute(sql)
                except sqlite3.OperationalError as e:
                    # Column might already exist if migration was partially applied
                    if "duplicate column" not in str(e).lower():
                        raise
                    logger.debug(f"Column already exists, skipping: {e}")

        # Update schema version
        cursor.execute(
            "UPDATE meta SET value = ? WHERE key = ?",
            (str(SCHEMA_VERSION), "schema_version")
        )
        logger.info(f"Database migrated to schema version {SCHEMA_VERSION}")

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection with proper error handling.

        Yields:
            SQLite connection
        """
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}", exc_info=True)
            raise
        finally:
            if conn:
                conn.close()

    def insert_sample(
        self,
        pressure_smoothed: float,
        pressure_raw: float,
        page_faults: float,
        available_ram_bytes: int,
        available_ram_percent: float,
        committed_bytes: int,
        committed_ratio: float,
        timestamp: Optional[float] = None,
        page_io_bytes_per_sec: float = 0.0,
        disk_read_bytes_per_sec: float = 0.0,
        disk_write_bytes_per_sec: float = 0.0,
        disk_percent_busy: float = 0.0
    ) -> None:
        """
        Insert a new sample into the database.

        Args:
            pressure_smoothed: Smoothed pressure percentage
            pressure_raw: Raw pressure percentage
            page_faults: Page faults per second
            available_ram_bytes: Available RAM in bytes
            available_ram_percent: Available RAM percentage
            committed_bytes: Committed memory in bytes
            committed_ratio: Committed memory ratio percentage
            timestamp: Unix timestamp (defaults to current time)
            page_io_bytes_per_sec: Memory-related disk I/O in bytes/sec
            disk_read_bytes_per_sec: Total disk read bytes/sec
            disk_write_bytes_per_sec: Total disk write bytes/sec
            disk_percent_busy: Disk busy percentage (0-100)
        """
        if timestamp is None:
            timestamp = time.time()

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO samples (
                        timestamp, pressure_smoothed, pressure_raw, page_faults,
                        available_ram_bytes, available_ram_percent,
                        committed_bytes, committed_ratio,
                        page_io_bytes_per_sec, disk_read_bytes_per_sec,
                        disk_write_bytes_per_sec, disk_percent_busy
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp, pressure_smoothed, pressure_raw, page_faults,
                        available_ram_bytes, available_ram_percent,
                        committed_bytes, committed_ratio,
                        page_io_bytes_per_sec, disk_read_bytes_per_sec,
                        disk_write_bytes_per_sec, disk_percent_busy
                    )
                )
                conn.commit()

        except Exception as e:
            logger.error(f"Error inserting sample: {e}", exc_info=True)

    def get_samples(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """
        Retrieve samples from the database.

        Args:
            start_time: Start of time range (Unix timestamp)
            end_time: End of time range (Unix timestamp)
            limit: Maximum number of samples to return

        Returns:
            List of sample dictionaries
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                query = "SELECT * FROM samples WHERE 1=1"
                params: list[Any] = []

                if start_time is not None:
                    query += " AND timestamp >= ?"
                    params.append(start_time)

                if end_time is not None:
                    query += " AND timestamp <= ?"
                    params.append(end_time)

                query += " ORDER BY timestamp ASC"

                if limit is not None:
                    query += " LIMIT ?"
                    params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error retrieving samples: {e}", exc_info=True)
            return []

    def get_samples_last_hours(self, hours: int) -> list[dict[str, Any]]:
        """
        Get samples from the last N hours.

        Args:
            hours: Number of hours to look back

        Returns:
            List of sample dictionaries
        """
        start_time = time.time() - (hours * 3600)
        return self.get_samples(start_time=start_time)

    def get_samples_last_days(self, days: int) -> list[dict[str, Any]]:
        """
        Get samples from the last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of sample dictionaries
        """
        start_time = time.time() - (days * 86400)
        return self.get_samples(start_time=start_time)

    def get_latest_sample(self) -> Optional[dict[str, Any]]:
        """
        Get the most recent sample.

        Returns:
            Sample dictionary or None if no samples exist
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM samples ORDER BY timestamp DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return dict(row) if row else None

        except Exception as e:
            logger.error(f"Error retrieving latest sample: {e}", exc_info=True)
            return None

    def get_sample_count(self) -> int:
        """
        Get total number of samples in database.

        Returns:
            Number of samples
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM samples")
                result = cursor.fetchone()
                return result[0] if result else 0

        except Exception as e:
            logger.error(f"Error getting sample count: {e}", exc_info=True)
            return 0

    def cleanup_old_data(self, retention_days: int) -> int:
        """
        Delete samples older than retention period.

        Args:
            retention_days: Number of days to retain data

        Returns:
            Number of samples deleted
        """
        cutoff_time = time.time() - (retention_days * 86400)

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Count samples to delete
                cursor.execute(
                    "SELECT COUNT(*) FROM samples WHERE timestamp < ?",
                    (cutoff_time,)
                )
                count = cursor.fetchone()[0]

                if count > 0:
                    # Delete old samples
                    cursor.execute(
                        "DELETE FROM samples WHERE timestamp < ?",
                        (cutoff_time,)
                    )
                    conn.commit()

                    # Vacuum to reclaim space
                    conn.execute("VACUUM")

                    logger.info(f"Cleaned up {count} old samples (older than {retention_days} days)")

                return count

        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}", exc_info=True)
            return 0

    def clear_all_data(self) -> None:
        """Delete all sample data from the database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM samples")
                conn.commit()
                conn.execute("VACUUM")

            logger.info("All sample data cleared")

        except Exception as e:
            logger.error(f"Error clearing data: {e}", exc_info=True)

    def export_to_csv(self, filepath: Path, start_time: Optional[float] = None, end_time: Optional[float] = None) -> bool:
        """
        Export samples to CSV file.

        Args:
            filepath: Path to output CSV file
            start_time: Optional start of time range
            end_time: Optional end of time range

        Returns:
            True if export successful
        """
        import csv

        samples = self.get_samples(start_time=start_time, end_time=end_time)

        if not samples:
            logger.warning("No samples to export")
            return False

        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=samples[0].keys())
                writer.writeheader()
                writer.writerows(samples)

            logger.info(f"Exported {len(samples)} samples to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}", exc_info=True)
            return False

    def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
        logger.info("Database connection closed")
