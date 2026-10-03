"""
telemetry/monitor_detector.py — Multi-monitor geometry detection.

Uses Qt's QScreen API (primary) and Win32 (fallback) to enumerate all
physical monitors and return their rectangles, DPI scale factors, and
primary monitor index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class MonitorInfo:
    index: int
    x: int
    y: int
    width: int
    height: int
    is_primary: bool
    dpi_scale: float = 1.0
    name: str = ""

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def clamp(self, px: int, py: int, win_w: int, win_h: int) -> tuple[int, int]:
        """Clamp a window position so it stays fully within this monitor."""
        cx = max(self.x, min(px, self.right - win_w))
        cy = max(self.y, min(py, self.bottom - win_h))
        return cx, cy

    def __str__(self) -> str:
        flag = " [PRIMARY]" if self.is_primary else ""
        return f"Monitor {self.index}{flag}: {self.width}x{self.height} @ ({self.x},{self.y})"


class MonitorDetector:
    """Detects and caches all available monitors."""

    def __init__(self):
        self._monitors: list[MonitorInfo] = []
        self.refresh()

    def refresh(self) -> None:
        """Re-enumerate monitors (call after display change events)."""
        self._monitors = self._detect_via_qt()
        if not self._monitors:
            self._monitors = self._detect_via_win32()
        if not self._monitors:
            # Fallback: single 1920×1080 monitor
            self._monitors = [MonitorInfo(0, 0, 0, 1920, 1080, True, 1.0, "Default")]
        for m in self._monitors:
            logger.debug(str(m))
        logger.info(f"Detected {len(self._monitors)} monitor(s).")

    @property
    def monitors(self) -> list[MonitorInfo]:
        return list(self._monitors)

    @property
    def primary(self) -> MonitorInfo:
        for m in self._monitors:
            if m.is_primary:
                return m
        return self._monitors[0]

    def monitor_for_point(self, x: int, y: int) -> MonitorInfo:
        """Return the monitor that contains point (x, y), or primary."""
        for m in self._monitors:
            if m.contains(x, y):
                return m
        return self.primary

    def clamp_window(self, x: int, y: int, w: int, h: int) -> tuple[int, int]:
        """Clamp window position to stay within its current monitor."""
        mon = self.monitor_for_point(x + w // 2, y + h // 2)
        return mon.clamp(x, y, w, h)

    # ── Detection backends ─────────────────────────────────────────────────

    @staticmethod
    def _detect_via_qt() -> list[MonitorInfo]:
        """Use QApplication.screens() — most reliable when Qt is running."""
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return []
            screens = app.screens()
            primary_screen = app.primaryScreen()
            monitors = []
            for i, screen in enumerate(screens):
                geom = screen.geometry()
                monitors.append(MonitorInfo(
                    index=i,
                    x=geom.x(),
                    y=geom.y(),
                    width=geom.width(),
                    height=geom.height(),
                    is_primary=(screen == primary_screen),
                    dpi_scale=screen.devicePixelRatio(),
                    name=screen.name(),
                ))
            return monitors
        except Exception as exc:
            logger.debug(f"Qt monitor detection failed: {exc}")
            return []

    @staticmethod
    def _detect_via_win32() -> list[MonitorInfo]:
        """Fallback using EnumDisplayMonitors."""
        try:
            import win32api
            monitors = []
            raw = win32api.EnumDisplayMonitors(None, None)
            primary_handle = None
            # Find primary monitor handle
            for handle, _, _ in raw:
                info = win32api.GetMonitorInfo(handle)
                if info.get("Flags", 0) & 1:  # MONITORINFOF_PRIMARY
                    primary_handle = handle
                    break
            for i, (handle, _, rect) in enumerate(raw):
                info = win32api.GetMonitorInfo(handle)
                x, y, right, bottom = rect
                monitors.append(MonitorInfo(
                    index=i,
                    x=x, y=y,
                    width=right - x,
                    height=bottom - y,
                    is_primary=(handle == primary_handle),
                    name=info.get("Device", f"Monitor{i}"),
                ))
            return monitors
        except Exception as exc:
            logger.debug(f"Win32 monitor detection failed: {exc}")
            return []
