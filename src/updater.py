"""Auto-update functionality for BottleneckWatch.

Checks GitHub for new releases and applies updates automatically.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from . import __version__, GITHUB_REPO
from .config import ConfigManager
from .utils import get_logger, APP_DATA_DIR

logger = get_logger(__name__)

# Directory for staging updates
UPDATES_DIR = APP_DATA_DIR / "updates"

# Install directory: parent of src/
INSTALL_DIR = Path(__file__).resolve().parent.parent

# GitHub API URL for latest release
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Request timeout in seconds
REQUEST_TIMEOUT = 10


@dataclass
class UpdateInfo:
    """Information about an available update."""
    version: str
    download_url: str
    release_notes: str


class UpdateChecker:
    """Checks GitHub for new releases and manages the update process."""

    def __init__(self, config: ConfigManager) -> None:
        """
        Initialize the update checker.

        Args:
            config: Configuration manager instance
        """
        self.config = config
        self._current_version = __version__
        self._latest_update: Optional[UpdateInfo] = None

        # Clean up any leftover staging files from a previous update
        self._cleanup_staging()

        logger.info(f"UpdateChecker initialized (current version: {self._current_version})")

    def _cleanup_staging(self) -> None:
        """Remove any leftover files from a previous update."""
        if UPDATES_DIR.exists():
            try:
                shutil.rmtree(UPDATES_DIR)
                logger.info("Cleaned up leftover update staging directory")
            except Exception as e:
                logger.warning(f"Failed to clean up update staging directory: {e}")

    @property
    def current_version(self) -> str:
        """Get the current application version."""
        return self._current_version

    @property
    def latest_update(self) -> Optional[UpdateInfo]:
        """Get the latest available update info, if any."""
        return self._latest_update

    def check_for_update(self) -> Optional[UpdateInfo]:
        """
        Check GitHub for a newer release.

        Returns:
            UpdateInfo if a newer version is available, None otherwise
        """
        try:
            logger.info("Checking for updates...")

            request = Request(
                GITHUB_API_URL,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"BottleneckWatch/{self._current_version}"
                }
            )

            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))

            tag_name = data.get("tag_name", "")
            # Strip leading 'v' if present
            remote_version = tag_name.lstrip("v")

            if not remote_version:
                logger.warning("Could not parse version from release tag")
                return None

            # Lexicographic comparison works for YYYY-MM-DD-HH format
            if remote_version <= self._current_version:
                logger.info(f"Up to date (current: {self._current_version}, latest: {remote_version})")
                self._latest_update = None
                return None

            # Check if user has skipped this version
            skipped = self.config.get("skipped_version")
            if skipped and skipped == remote_version:
                logger.info(f"Skipping version {remote_version} (user chose to skip)")
                self._latest_update = None
                return None

            # Find the zip asset download URL
            download_url = None
            for asset in data.get("assets", []):
                if asset["name"].endswith(".zip"):
                    download_url = asset["browser_download_url"]
                    break

            if not download_url:
                logger.warning("No zip asset found in latest release")
                return None

            release_notes = data.get("body", "No release notes available.")

            update_info = UpdateInfo(
                version=remote_version,
                download_url=download_url,
                release_notes=release_notes
            )

            self._latest_update = update_info
            logger.info(f"Update available: {remote_version} (current: {self._current_version})")
            return update_info

        except HTTPError as e:
            if e.code == 403:
                logger.warning("GitHub API rate limit reached, skipping update check")
            elif e.code == 404:
                logger.warning("No releases found on GitHub")
            else:
                logger.warning(f"HTTP error checking for updates: {e.code} {e.reason}")
            return None

        except URLError as e:
            logger.warning(f"Network error checking for updates: {e.reason}")
            return None

        except Exception as e:
            logger.warning(f"Error checking for updates: {e}")
            return None

    def check_for_update_async(
        self,
        callback: Callable[[Optional[UpdateInfo]], None]
    ) -> None:
        """
        Check for updates in a background thread.

        Args:
            callback: Function called with UpdateInfo or None when check completes.
                      Called from the background thread - caller must handle thread safety.
        """
        def _check() -> None:
            result = self.check_for_update()
            callback(result)

        thread = threading.Thread(
            target=_check,
            name="UpdateCheckThread",
            daemon=True
        )
        thread.start()

    def download_update(
        self,
        update_info: UpdateInfo,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Optional[Path]:
        """
        Download the update zip file.

        Args:
            update_info: The update to download
            progress_callback: Optional callback(bytes_downloaded, total_bytes)

        Returns:
            Path to downloaded zip file, or None on failure
        """
        try:
            # Create updates directory
            UPDATES_DIR.mkdir(parents=True, exist_ok=True)

            zip_path = UPDATES_DIR / f"BottleneckWatch-{update_info.version}.zip"

            logger.info(f"Downloading update from {update_info.download_url}")

            request = Request(
                update_info.download_url,
                headers={
                    "User-Agent": f"BottleneckWatch/{self._current_version}"
                }
            )

            with urlopen(request, timeout=60) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 8192

                with open(zip_path, "wb") as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size:
                            progress_callback(downloaded, total_size)

            # Validate the zip file
            if not zipfile.is_zipfile(zip_path):
                logger.error("Downloaded file is not a valid zip archive")
                zip_path.unlink(missing_ok=True)
                return None

            logger.info(f"Download complete: {zip_path} ({downloaded} bytes)")
            return zip_path

        except Exception as e:
            logger.error(f"Error downloading update: {e}", exc_info=True)
            return None

    def extract_update(self, zip_path: Path) -> Optional[Path]:
        """
        Extract the downloaded update to a staging directory.

        Args:
            zip_path: Path to the downloaded zip file

        Returns:
            Path to the staging directory, or None on failure
        """
        staging_dir = UPDATES_DIR / "staging"

        try:
            # Clean up any existing staging directory
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

            staging_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"Extracting update to {staging_dir}")

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(staging_dir)

            # The zip may contain a top-level directory - flatten if so
            contents = list(staging_dir.iterdir())
            if len(contents) == 1 and contents[0].is_dir():
                # Move contents of the single subdirectory up
                inner_dir = contents[0]
                for item in inner_dir.iterdir():
                    shutil.move(str(item), str(staging_dir / item.name))
                inner_dir.rmdir()

            logger.info("Update extracted successfully")
            return staging_dir

        except Exception as e:
            logger.error(f"Error extracting update: {e}", exc_info=True)
            return None

    def check_install_writable(self) -> bool:
        """
        Check if the install directory is writable.

        Returns:
            True if the install directory can be written to
        """
        test_file = INSTALL_DIR / ".update_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
            return True
        except Exception:
            return False

    def generate_update_script(self, staging_dir: Path) -> Optional[Path]:
        """
        Generate a batch script that applies the update after the app exits.

        The script:
        1. Waits for the current process to exit
        2. Copies staging files over the install directory
        3. Runs pip install if requirements.txt changed
        4. Cleans up staging directory
        5. Restarts the application
        6. Deletes itself

        Args:
            staging_dir: Path to the staging directory with new files

        Returns:
            Path to the generated batch script, or None on failure
        """
        try:
            script_path = UPDATES_DIR / "do_update.bat"
            pid = os.getpid()
            install_dir = str(INSTALL_DIR)
            staging_str = str(staging_dir)
            run_bat = str(INSTALL_DIR / "run_silent.bat")
            updates_dir = str(UPDATES_DIR)

            # Check if requirements.txt exists in staging and differs from current
            new_requirements = staging_dir / "requirements.txt"
            current_requirements = INSTALL_DIR / "requirements.txt"

            check_requirements = ""
            if new_requirements.exists():
                try:
                    new_content = new_requirements.read_text(encoding="utf-8").strip()
                    current_content = ""
                    if current_requirements.exists():
                        current_content = current_requirements.read_text(encoding="utf-8").strip()

                    if new_content != current_content:
                        # Find the pip executable in the venv or system
                        pip_exe = str(INSTALL_DIR / "venv" / "Scripts" / "pip.exe")
                        req_path = str(INSTALL_DIR / "requirements.txt")
                        check_requirements = f'''
echo Installing updated dependencies...
if exist "{pip_exe}" (
    "{pip_exe}" install -r "{req_path}"
) else (
    pip install -r "{req_path}"
)
'''
                except Exception as e:
                    logger.warning(f"Could not compare requirements.txt: {e}")

            script_content = f'''@echo off
echo BottleneckWatch Updater
echo Waiting for application to exit...

:waitloop
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitloop
)

echo Application exited. Applying update...

xcopy /E /Y /Q "{staging_str}\\*" "{install_dir}\\"
if errorlevel 1 (
    echo ERROR: Failed to copy update files.
    pause
    goto cleanup
)
{check_requirements}
echo Update applied successfully.

:cleanup
echo Cleaning up...
rmdir /S /Q "{updates_dir}\\staging" 2>NUL

echo Restarting BottleneckWatch...
start "" "{run_bat}"

echo Update complete.
(goto) 2>nul & del "%~f0"
'''

            script_path.write_text(script_content, encoding="utf-8")
            logger.info(f"Update script generated: {script_path}")
            return script_path

        except Exception as e:
            logger.error(f"Error generating update script: {e}", exc_info=True)
            return None

    def apply_update(self, update_info: UpdateInfo,
                     progress_callback: Optional[Callable[[str], None]] = None) -> Optional[Path]:
        """
        Download, extract, and prepare the update for application.

        This method performs all steps up to generating the batch script.
        The caller should then launch the script and shut down the app.

        Args:
            update_info: The update to apply
            progress_callback: Optional callback(status_message) for UI updates

        Returns:
            Path to the update batch script, or None on failure
        """
        if progress_callback:
            progress_callback("Checking install directory...")

        if not self.check_install_writable():
            logger.error("Install directory is not writable")
            return None

        if progress_callback:
            progress_callback("Downloading update...")

        zip_path = self.download_update(update_info)
        if not zip_path:
            return None

        if progress_callback:
            progress_callback("Extracting update...")

        staging_dir = self.extract_update(zip_path)
        if not staging_dir:
            return None

        # Clean up the zip file
        try:
            zip_path.unlink()
        except Exception:
            pass

        if progress_callback:
            progress_callback("Preparing update script...")

        script_path = self.generate_update_script(staging_dir)
        if not script_path:
            return None

        if progress_callback:
            progress_callback("Ready to apply update.")

        return script_path

    def launch_update_script(self, script_path: Path) -> bool:
        """
        Launch the update batch script as a detached process.

        Args:
            script_path: Path to the update batch script

        Returns:
            True if the script was launched successfully
        """
        try:
            # Launch the batch script detached from this process
            subprocess.Popen(
                ["cmd.exe", "/c", str(script_path)],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                close_fds=True
            )

            logger.info("Update script launched, application should exit now")
            return True

        except Exception as e:
            logger.error(f"Error launching update script: {e}", exc_info=True)
            return False

    def skip_version(self, version: str) -> None:
        """
        Mark a version as skipped so the user won't be prompted again.

        Args:
            version: The version string to skip
        """
        self.config.set("skipped_version", version)
        self._latest_update = None
        logger.info(f"Version {version} marked as skipped")
