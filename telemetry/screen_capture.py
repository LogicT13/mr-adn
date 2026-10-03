"""
telemetry/screen_capture.py — Region screenshot capture and compression.

Usage flow:
  1. User triggers global hotkey → enter "capture mode"
  2. A transparent fullscreen overlay appears for region selection
  3. On mouse release, the region is captured, compressed, and emitted
     via the EventBus (SCREENSHOT_TAKEN) with the raw bytes.
  4. Brain.ask() receives the bytes as an image part.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

from loguru import logger

try:
    import mss
    import mss.tools
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    logger.warning("mss not available — screen capture disabled.")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ScreenCapture:
    """Captures a region of the screen and returns compressed PNG bytes."""

    def __init__(self, max_dimension: int = 1280, quality: int = 85):
        self._max_dim = max_dimension
        self._quality = quality

    def capture_region(self, x: int, y: int, width: int, height: int) -> bytes | None:
        """
        Capture the specified screen region.
        Returns PNG bytes (possibly downscaled) or None on failure.
        """
        if not MSS_AVAILABLE or not PIL_AVAILABLE:
            logger.error("mss or Pillow not installed — cannot capture screen.")
            return None

        if width <= 0 or height <= 0:
            logger.warning(f"Invalid capture region: {width}x{height}")
            return None

        try:
            with mss.mss() as sct:
                monitor = {"top": y, "left": x, "width": width, "height": height}
                raw = sct.grab(monitor)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

            # Downscale if necessary
            img = self._downscale(img)

            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            png_bytes = buf.getvalue()
            logger.info(f"Screenshot captured: {width}x{height} → {len(png_bytes)//1024}KB")
            return png_bytes

        except Exception as exc:
            logger.exception(f"Screen capture failed: {exc}")
            return None

    def capture_full_monitor(self, monitor_index: int = 0) -> bytes | None:
        """Capture a full monitor by index."""
        if not MSS_AVAILABLE:
            return None
        try:
            with mss.mss() as sct:
                # mss.monitors[0] = all monitors combined; [1]+ = individual
                mon = sct.monitors[monitor_index + 1]
                raw = sct.grab(mon)
                if not PIL_AVAILABLE:
                    buf = io.BytesIO()
                    mss.tools.to_png(raw.rgb, raw.size, output=buf)
                    return buf.getvalue()
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                img = self._downscale(img)
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                return buf.getvalue()
        except Exception as exc:
            logger.exception(f"Full monitor capture failed: {exc}")
            return None

    def _downscale(self, img: "Image.Image") -> "Image.Image":
        """Downscale image so its largest dimension ≤ max_dimension."""
        w, h = img.size
        if max(w, h) <= self._max_dim:
            return img
        ratio = self._max_dim / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        return img.resize((new_w, new_h), Image.LANCZOS)
