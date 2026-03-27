"""
trellis.hands.display_capture — Physical Display Capture

Captures what Kyle actually sees on the Greenhouse monitor using mss.
Complements the Playwright-based screenshot system (screenshot.py) which
captures headless DOM "code reality."

Used by:
    - POST /api/screenshot endpoint (on-demand display capture)
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import mss
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class DisplayCapture:
    """Result of a display capture operation."""

    image_bytes: bytes
    width: int
    height: int
    monitor_info: dict
    timestamp: str


def list_monitors() -> list[dict]:
    """Return available monitors with dimensions.

    Index 0 is the virtual "all monitors" screen.
    Index 1+ are physical monitors (primary is index 1).
    """
    with mss.mss() as sct:
        monitors: list[dict] = []
        for i, mon in enumerate(sct.monitors):
            monitors.append({
                "index": i,
                "left": mon["left"],
                "top": mon["top"],
                "width": mon["width"],
                "height": mon["height"],
            })
        return monitors


def capture_display(monitor: int | None = None) -> DisplayCapture:
    """Capture a screenshot of the physical display.

    Args:
        monitor: Monitor index (1 = primary, 2+ = additional).
                 None defaults to primary (index 1).

    Returns:
        DisplayCapture with PNG image bytes and metadata.

    Raises:
        RuntimeError: If capture fails (no display, invalid monitor, etc.)
    """
    if monitor is None:
        monitor = 1

    try:
        with mss.mss() as sct:
            if monitor < 0 or monitor >= len(sct.monitors):
                raise ValueError(
                    f"Monitor index {monitor} out of range. "
                    f"Available: 0-{len(sct.monitors) - 1}"
                )

            mon = sct.monitors[monitor]
            screenshot = sct.grab(mon)

            # mss ScreenShot has .rgb (RGB bytes) and .size (width, height)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

            # Convert to PNG bytes
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()

            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            return DisplayCapture(
                image_bytes=png_bytes,
                width=screenshot.size[0],
                height=screenshot.size[1],
                monitor_info={
                    "index": monitor,
                    "left": mon["left"],
                    "top": mon["top"],
                    "width": mon["width"],
                    "height": mon["height"],
                },
                timestamp=timestamp,
            )
    except ValueError:
        raise
    except Exception as e:
        display = os.environ.get("DISPLAY", "<not set>")
        xauth = os.environ.get("XAUTHORITY", "<not set>")
        logger.error(
            "Display capture failed: %s (DISPLAY=%s, XAUTHORITY=%s)",
            e,
            display,
            xauth,
        )
        raise RuntimeError(f"Display capture failed: {e}") from e


def save_temp_screenshot(image_bytes: bytes, temp_dir: Path) -> Path:
    """Save PNG bytes to temp/screenshots/ and run cleanup.

    Args:
        image_bytes: PNG image data.
        temp_dir: Base temp directory (temp/screenshots/ will be created inside).

    Returns:
        Path to the saved file.
    """
    screenshots_dir = temp_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filepath = screenshots_dir / f"display-{timestamp}.png"
    filepath.write_bytes(image_bytes)

    cleanup_temp_screenshots(screenshots_dir)

    return filepath


def cleanup_temp_screenshots(temp_dir: Path, max_files: int = 50) -> None:
    """Delete oldest screenshot files when over the limit.

    Args:
        temp_dir: Directory containing screenshot PNGs.
        max_files: Maximum number of files to keep.
    """
    files = sorted(temp_dir.glob("*.png"), key=lambda f: f.stat().st_mtime)
    if len(files) > max_files:
        for old_file in files[: len(files) - max_files]:
            try:
                old_file.unlink()
                logger.debug("Cleaned up old screenshot: %s", old_file.name)
            except OSError as e:
                logger.warning("Failed to delete %s: %s", old_file, e)
