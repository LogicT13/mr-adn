"""
telemetry/window_monitor.py — Background Win32 window telemetry.

Polls:
  1. Foreground/active window (title + process name)
  2. All visible taskbar windows (including minimized)

Publishes events to the EventBus when the active window changes.
Also updates Brain's context so AI responses are window-aware.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from core.event_bus import EventBus, WINDOW_FOCUS_CHANGED, WINDOWS_SCANNED
from core.config_manager import ConfigManager

if TYPE_CHECKING:
    pass

try:
    import win32gui
    import win32process
    import psutil
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logger.warning("pywin32/psutil not available — window telemetry disabled.")


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    is_minimized: bool = False
    is_visible: bool = True

    def __str__(self) -> str:
        return f"{self.process_name}: {self.title}" if self.title else self.process_name


class WindowMonitor:
    """
    Background thread that polls Win32 APIs to track the active window
    and all visible taskbar windows.
    """

    def __init__(self, cfg: ConfigManager, event_bus: EventBus):
        self._cfg = cfg
        self._bus = event_bus
        self._interval = cfg.get("telemetry.poll_interval_ms", 2000) / 1000
        self._track_active = cfg.get("telemetry.track_active_window", True)
        self._track_taskbar = cfg.get("telemetry.track_taskbar_windows", True)
        self._history_size = cfg.get("telemetry.context_history_size", 20)

        self._running = False
        self._last_active: str = ""
        self._visible_windows: list[str] = []
        self._history: list[str] = []

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start polling loop (blocking — run in a daemon thread)."""
        if not WIN32_AVAILABLE:
            logger.info("WindowMonitor: skipping (no Win32 support).")
            return
        self._running = True
        logger.info("WindowMonitor: polling started.")
        while self._running:
            try:
                self._tick()
            except Exception as exc:
                logger.debug(f"WindowMonitor tick error: {exc}")
            time.sleep(self._interval)

    def stop(self) -> None:
        self._running = False
        logger.info("WindowMonitor: stopped.")

    # ── Poll logic ────────────────────────────────────────────────────────

    def _tick(self) -> None:
        active = self._get_active_window() if self._track_active else None
        taskbar = self._get_taskbar_windows() if self._track_taskbar else []

        # Publish active window change
        if active and str(active) != self._last_active:
            self._last_active = str(active)
            self._history.append(self._last_active)
            if len(self._history) > self._history_size:
                self._history.pop(0)
            self._bus.publish(
                WINDOW_FOCUS_CHANGED,
                window=active,
                history=list(self._history),
            )

        # Publish taskbar scan
        names = [str(w) for w in taskbar]
        if names != self._visible_windows:
            self._visible_windows = names
            self._bus.publish(WINDOWS_SCANNED, windows=names)

    # ── Win32 helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _get_active_window() -> WindowInfo | None:
        """Return info about the current foreground window."""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                proc = psutil.Process(pid)
                name = proc.name()
            except Exception:
                name = "unknown"
            return WindowInfo(hwnd=hwnd, title=title, process_name=name)
        except Exception as exc:
            logger.trace(f"_get_active_window: {exc}")
            return None

    @staticmethod
    def _get_taskbar_windows() -> list[WindowInfo]:
        """Enumerate all top-level windows that appear in the taskbar."""
        windows: list[WindowInfo] = []

        def _enum_callback(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return
                # Filter out tool windows (no taskbar button)
                ex_style = win32gui.GetWindowLong(hwnd, -20)  # GWL_EXSTYLE
                if ex_style & 0x00000080:  # WS_EX_TOOLWINDOW
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    name = proc.name()
                except Exception:
                    name = "unknown"
                is_min = win32gui.IsIconic(hwnd)
                windows.append(WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    process_name=name,
                    is_minimized=bool(is_min),
                ))
            except Exception:
                pass

        win32gui.EnumWindows(_enum_callback, None)
        return windows

    # ── Public accessors ──────────────────────────────────────────────────

    @property
    def active_window(self) -> str:
        return self._last_active

    @property
    def visible_windows(self) -> list[str]:
        return list(self._visible_windows)

    @property
    def history(self) -> list[str]:
        return list(self._history)
