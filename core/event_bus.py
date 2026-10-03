"""
core/event_bus.py — In-process publish/subscribe event bus.

All inter-module communication goes through here to keep components decoupled.
Uses Qt signals where possible (thread-safe), falls back to callbacks for non-Qt.

Event names (constants defined below):

  HOTKEY_INVOKE        — Global hotkey pressed → open chat
  HOTKEY_SCREENSHOT    — Global hotkey pressed → capture region
  HOTKEY_MUTE          — Global hotkey pressed → toggle mute
  WINDOW_FOCUS_CHANGED — Active foreground window changed
  WINDOWS_SCANNED      — Taskbar window list updated
  AI_RESPONSE_CHUNK    — Streaming text chunk from AI
  AI_RESPONSE_DONE     — AI response complete
  AI_THINKING          — AI is processing (show animation)
  USER_FEEDBACK        — User interacted / silenced / ignored
  SCREENSHOT_TAKEN     — Region screenshot captured
  POSITION_CHANGED     — Window dragged to new position
  PROACTIVITY_TICK     — Bandit tick → maybe show unsolicited message
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable

from loguru import logger


# ── Event name constants ──────────────────────────────────────────────────────
HOTKEY_INVOKE        = "hotkey.invoke"
HOTKEY_SCREENSHOT    = "hotkey.screenshot"
HOTKEY_MUTE          = "hotkey.mute"
WINDOW_FOCUS_CHANGED = "telemetry.focus_changed"
WINDOWS_SCANNED      = "telemetry.windows_scanned"
AI_RESPONSE_CHUNK    = "ai.response_chunk"
AI_RESPONSE_DONE     = "ai.response_done"
AI_THINKING          = "ai.thinking"
AI_OBSERVING         = "ai.observing"
USER_FEEDBACK        = "user.feedback"
SCREENSHOT_TAKEN     = "screenshot.taken"
POSITION_CHANGED     = "ui.position_changed"
PROACTIVITY_TICK     = "bandit.proactivity_tick"


class EventBus:
    """
    Thread-safe publish/subscribe event bus.

    Usage:
        bus = EventBus()
        bus.subscribe("my.event", handler_fn)
        bus.publish("my.event", payload={"key": "val"})

    Handlers are called synchronously in the publishing thread.
    Use EventBus.publish_async() to dispatch in a background thread.
    """

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        """Register a handler for the given event name."""
        with self._lock:
            self._listeners[event].append(handler)
        logger.trace(f"EventBus: subscribed to '{event}' → {handler.__qualname__}")

    def unsubscribe(self, event: str, handler: Callable) -> None:
        """Remove a previously registered handler."""
        with self._lock:
            lst = self._listeners.get(event, [])
            if handler in lst:
                lst.remove(handler)

    def publish(self, event: str, **kwargs) -> None:
        """
        Fire an event synchronously.
        All registered handlers for `event` are called with **kwargs.
        Exceptions in handlers are logged but don't abort the chain.
        """
        with self._lock:
            handlers = list(self._listeners.get(event, []))
        for handler in handlers:
            try:
                handler(**kwargs)
            except Exception as exc:
                logger.exception(f"EventBus handler error for '{event}': {exc}")

    def publish_async(self, event: str, **kwargs) -> None:
        """Fire an event in a daemon background thread."""
        t = threading.Thread(
            target=self.publish, args=(event,), kwargs=kwargs,
            daemon=True, name=f"EventBus-{event}"
        )
        t.start()

    def clear(self, event: str | None = None) -> None:
        """Remove all handlers for an event (or all events if None)."""
        with self._lock:
            if event:
                self._listeners.pop(event, None)
            else:
                self._listeners.clear()
