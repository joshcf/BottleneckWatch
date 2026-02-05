"""System tray icon for BottleneckWatch.

Displays memory pressure status in the Windows system tray.
"""

from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw, ImageFont

from .config import ConfigManager
from .utils import (
    get_logger,
    ICON_SIZE,
    COLOR_GREEN,
    COLOR_YELLOW,
    COLOR_RED,
    COLOR_WHITE,
    APP_NAME
)

logger = get_logger(__name__)


class TrayIcon:
    """Manages the system tray icon display."""

    def __init__(
        self,
        config: ConfigManager,
        on_exit: Callable[[], None],
        on_view_details: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        on_check_updates: Optional[Callable[[], None]] = None,
        initial_pressure: float = 0.0
    ) -> None:
        """
        Initialize the tray icon.

        Args:
            config: Configuration manager instance
            on_exit: Callback for exit menu item
            on_view_details: Callback for View Details menu item
            on_settings: Callback for Settings menu item
            on_check_updates: Callback for Check for Updates menu item
            initial_pressure: Initial pressure value to display (avoids showing 0 on startup)
        """
        self.config = config
        self._on_exit = on_exit
        self._on_view_details = on_view_details
        self._on_settings = on_settings
        self._on_check_updates = on_check_updates

        self._current_pressure: float = initial_pressure
        self._update_available: bool = False
        self._icon: Optional[pystray.Icon] = None

        # Try to load a font for the percentage text
        self._font = self._load_font()

        logger.info(f"TrayIcon initialized with initial pressure: {initial_pressure:.1f}%")

    def _load_font(self) -> Optional[ImageFont.FreeTypeFont]:
        """
        Load a font for rendering percentage text.

        Returns:
            Font object or None if loading fails
        """
        # Try common Windows fonts
        font_names = [
            "arial.ttf",
            "arialbd.ttf",  # Arial Bold
            "segoeui.ttf",
            "segoeuib.ttf",  # Segoe UI Bold
            "tahoma.ttf",
            "verdana.ttf"
        ]

        font_size = int(ICON_SIZE * 0.5)  # 50% of icon size

        for font_name in font_names:
            try:
                return ImageFont.truetype(font_name, font_size)
            except (OSError, IOError):
                continue

        # Fall back to default font
        logger.warning("Could not load TrueType font, using default")
        return None

    def _get_color_for_pressure(self, pressure: float) -> tuple[int, int, int]:
        """
        Determine icon color based on pressure level.

        Args:
            pressure: Pressure percentage (0-100)

        Returns:
            RGB color tuple
        """
        yellow_threshold, red_threshold = self.config.get_thresholds()

        if pressure >= red_threshold:
            return COLOR_RED
        elif pressure >= yellow_threshold:
            return COLOR_YELLOW
        else:
            return COLOR_GREEN

    def _create_icon_image(self, pressure: float) -> Image.Image:
        """
        Create an icon image with color and percentage overlay.

        Args:
            pressure: Pressure percentage (0-100)

        Returns:
            PIL Image object
        """
        # Get background color
        bg_color = self._get_color_for_pressure(pressure)

        # Create solid square image
        image = Image.new("RGB", (ICON_SIZE, ICON_SIZE), bg_color)
        draw = ImageDraw.Draw(image)

        # Render percentage text
        text = str(int(round(pressure)))

        if self._font:
            # Get text bounding box for centering
            bbox = draw.textbbox((0, 0), text, font=self._font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # Center text in icon
            x = (ICON_SIZE - text_width) // 2
            y = (ICON_SIZE - text_height) // 2 - bbox[1]  # Adjust for baseline

            draw.text((x, y), text, fill=COLOR_WHITE, font=self._font)
        else:
            # Fallback without custom font
            draw.text((ICON_SIZE // 4, ICON_SIZE // 4), text, fill=COLOR_WHITE)

        return image

    def _create_menu(self) -> pystray.Menu:
        """
        Create the context menu for the tray icon.

        Returns:
            pystray Menu object
        """
        items = [
            pystray.MenuItem(
                "View Details",
                self._handle_view_details,
                default=True  # Double-click action
            ),
            pystray.MenuItem(
                "Settings",
                self._handle_settings
            ),
            pystray.MenuItem(
                "Check for Updates",
                self._handle_check_updates
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Exit",
                self._handle_exit
            )
        ]

        return pystray.Menu(*items)

    def _handle_view_details(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle View Details menu click."""
        logger.debug("View Details menu item clicked")
        if self._on_view_details:
            self._on_view_details()

    def _handle_settings(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle Settings menu click."""
        logger.debug("Settings menu item clicked")
        if self._on_settings:
            self._on_settings()

    def _handle_check_updates(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle Check for Updates menu click."""
        logger.debug("Check for Updates menu item clicked")
        if self._on_check_updates:
            self._on_check_updates()

    def _handle_exit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle Exit menu click."""
        logger.info("Exit menu item clicked")
        self._on_exit()

    def _get_tooltip(self) -> str:
        """
        Generate tooltip text for current state.

        Returns:
            Tooltip string
        """
        pressure = self._current_pressure
        yellow_threshold, red_threshold = self.config.get_thresholds()

        if pressure >= red_threshold:
            status = "High"
        elif pressure >= yellow_threshold:
            status = "Moderate"
        else:
            status = "Normal"

        tooltip = f"{APP_NAME}\nMemory Pressure: {pressure:.0f}% ({status})"
        if self._update_available:
            tooltip += "\n(Update available)"
        return tooltip

    def update_pressure(self, pressure: float) -> None:
        """
        Update the displayed pressure value.

        Args:
            pressure: New pressure percentage (0-100)
        """
        # Only update if pressure changed significantly (>1%)
        if abs(pressure - self._current_pressure) < 1.0:
            return

        old_pressure = self._current_pressure
        self._current_pressure = pressure

        # Check for threshold crossings (for logging)
        yellow_threshold, red_threshold = self.config.get_thresholds()

        old_color = self._get_color_for_pressure(old_pressure)
        new_color = self._get_color_for_pressure(pressure)

        if old_color != new_color:
            color_name = "red" if new_color == COLOR_RED else "yellow" if new_color == COLOR_YELLOW else "green"
            logger.info(f"Pressure threshold crossed: {old_pressure:.1f}% -> {pressure:.1f}% (now {color_name})")

        # Update icon if running
        if self._icon:
            self._icon.icon = self._create_icon_image(pressure)
            self._icon.title = self._get_tooltip()

    def _create_icon(self) -> None:
        """Create the pystray icon object."""
        initial_image = self._create_icon_image(self._current_pressure)

        self._icon = pystray.Icon(
            name=APP_NAME,
            icon=initial_image,
            title=self._get_tooltip(),
            menu=self._create_menu()
        )

    def run(self) -> None:
        """Run the tray icon (blocks until exit)."""
        logger.info("Starting tray icon (blocking mode)")

        self._create_icon()

        # Run the icon (this blocks)
        self._icon.run()

        logger.info("Tray icon stopped")

    def run_detached(self) -> None:
        """Run the tray icon in a separate thread (non-blocking)."""
        logger.info("Starting tray icon (detached mode)")

        self._create_icon()

        # Run the icon in a separate thread
        self._icon.run_detached()

        logger.info("Tray icon running in background")

    def set_update_available(self, available: bool) -> None:
        """
        Set whether an update is available (affects tooltip).

        Args:
            available: True if an update is available
        """
        self._update_available = available
        if self._icon:
            self._icon.title = self._get_tooltip()

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._icon:
            logger.info("Stopping tray icon")
            self._icon.stop()
            self._icon = None
