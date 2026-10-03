"""
ui/hotkey_manager.py — Global hotkey listener using pynput.

Runs in its own thread (blocking). Publishes EventBus events when
configured hotkeys are detected.

Hotkeys (configurable in config.json):
  global_invoke     → show chat input
  screenshot_region → start region capture
  mute_toggle       → toggle mute
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

try:
    from pynput import keyboard as pynput_kb
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    logger.warning("pynput not available — global hotkeys disabled.")

from core.event_bus import EventBus, HOTKEY_INVOKE, HOTKEY_SCREENSHOT, HOTKEY_MUTE

if TYPE_CHECKING:
    from core.config_manager import ConfigManager


class HotkeyManager:
    """Listens for global hotkeys and publishes events to the EventBus."""

    def __init__(self, cfg: "ConfigManager", event_bus: EventBus):
        self._cfg = cfg
        self._bus = event_bus
        self._listener: "pynput_kb.GlobalHotKeys | None" = None

        self._hotkeys = {
            cfg.get("hotkeys.global_invoke", "<ctrl>+<alt>+m"):    self._on_invoke,
            cfg.get("hotkeys.screenshot_region", "<ctrl>+<alt>+s"): self._on_screenshot,
            cfg.get("hotkeys.mute_toggle", "<ctrl>+<alt>+z"):       self._on_mute,
        }

    def start(self) -> None:
        """Blocking: start listening. Call from a daemon thread."""
        if not PYNPUT_AVAILABLE:
            logger.info("HotkeyManager: pynput not available, skipping.")
            return
        logger.info(f"HotkeyManager: listening for {list(self._hotkeys.keys())}")
        try:
            self._listener = pynput_kb.GlobalHotKeys(self._hotkeys)
            self._listener.run()  # blocks until stop()
        except Exception as exc:
            logger.error(f"HotkeyManager error: {exc}")

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            logger.info("HotkeyManager: stopped.")

    # ── Handlers ──────────────────────────────────────────────────────────

    def _on_invoke(self):
        logger.debug("Hotkey: invoke")
        self._bus.publish(HOTKEY_INVOKE)

    def _on_screenshot(self):
        logger.debug("Hotkey: screenshot")
        self._bus.publish(HOTKEY_SCREENSHOT)

    def _on_mute(self):
        logger.debug("Hotkey: mute")
        self._bus.publish(HOTKEY_MUTE)
