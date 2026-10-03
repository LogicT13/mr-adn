"""
ui/main_window.py — Mr. ADN's main frameless, translucent, always-on-top window.

Features:
  - Frameless + translucent (Win32 layered window)
  - Stay-on-top
  - Draggable to any monitor
  - Animated sprite (DNA helix character)
  - Speech bubble with streaming text
  - Right-click context menu
  - Left-click or hotkey → open chat input
  - Position persistence across sessions
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import (
    Qt, QPoint, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, QObject, QSize
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QFontMetrics,
    QMouseEvent, QContextMenuEvent, QCursor, QPainterPath
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QMenu, QSizePolicy, QSystemTrayIcon
)

from core.event_bus import (
    EventBus, AI_RESPONSE_CHUNK, AI_RESPONSE_DONE, AI_THINKING,
    HOTKEY_INVOKE, HOTKEY_SCREENSHOT, WINDOW_FOCUS_CHANGED,
    WINDOWS_SCANNED, USER_FEEDBACK, SCREENSHOT_TAKEN, POSITION_CHANGED
)
from ui.chat_bubble import ChatBubble
from ui.chat_input import ChatInput
from ui.sprite_widget import SpriteWidget
from ui.capture_overlay import CaptureOverlay

if TYPE_CHECKING:
    from core.config_manager import ConfigManager
    from ai.brain import Brain
    from ai.bandit import BanditEngine
    from telemetry.monitor_detector import MonitorDetector


class _QtBridge(QObject):
    """Qt signals for cross-thread UI updates (must live on the Qt thread)."""
    response_chunk = pyqtSignal(str)
    response_done  = pyqtSignal(str, bool)
    ai_thinking    = pyqtSignal()
    ai_observing   = pyqtSignal()
    hotkey_invoke  = pyqtSignal()
    hotkey_shot    = pyqtSignal()
    window_changed = pyqtSignal(str)

class MainWindow(QWidget):
    """
    The main floating desktop pet window.
    Transparent background, frameless, always on top.
    """

    POSITION_FILE = Path(__file__).parent.parent / "data" / "position.json"

    def __init__(
        self,
        cfg: "ConfigManager",
        event_bus: EventBus,
        brain: "Brain",
        bandit: "BanditEngine",
        monitor_detector: "MonitorDetector",
    ):
        super().__init__(flags=(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool  # No taskbar entry
        ))
        self._cfg = cfg
        self._bus = event_bus
        self._brain = brain
        self._bandit = bandit
        self._monitors = monitor_detector

        # Qt bridge for cross-thread signals
        self._bridge = _QtBridge()
        self._bridge.response_chunk.connect(self._on_response_chunk)
        self._bridge.response_done.connect(self._on_response_done)
        self._bridge.ai_thinking.connect(self._on_ai_thinking)
        self._bridge.ai_observing.connect(self._on_ai_observing)
        self._bridge.hotkey_invoke.connect(self._show_chat_input)
        self._bridge.hotkey_shot.connect(self._start_capture)
        self._bridge.window_changed.connect(self._on_window_changed)

        # Subscribe to EventBus (called from other threads → use signal bridge)
        from core.event_bus import AI_OBSERVING
        self._bus.subscribe(AI_RESPONSE_CHUNK,    lambda chunk, **_: self._bridge.response_chunk.emit(chunk))
        self._bus.subscribe(AI_RESPONSE_DONE,     lambda text, error=False, **_: self._bridge.response_done.emit(text, error))
        self._bus.subscribe(AI_THINKING,          lambda **_: self._bridge.ai_thinking.emit())
        self._bus.subscribe(AI_OBSERVING,         lambda **_: self._bridge.ai_observing.emit())
        self._bus.subscribe(HOTKEY_INVOKE,        lambda **_: self._bridge.hotkey_invoke.emit())
        self._bus.subscribe(HOTKEY_SCREENSHOT,    lambda **_: self._bridge.hotkey_shot.emit())
        self._bus.subscribe(WINDOW_FOCUS_CHANGED, lambda window, **_: self._bridge.window_changed.emit(str(window)))
        self._bus.subscribe(WINDOWS_SCANNED,      self._on_windows_scanned)

        # State
        self._drag_pos: QPoint | None = None
        self._is_muted = False
        self._current_response = ""
        self._pending_screenshot: bytes | None = None

        # Widgets
        self._setup_ui()
        self._restore_position()
        self._setup_tray()

        # Proactivity timer (checks bandit every N seconds)
        self._proactivity_timer = QTimer(self)
        self._proactivity_timer.timeout.connect(self._proactivity_tick)
        self._proactivity_timer.start(30_000)  # check every 30s

        logger.info("MainWindow created.")

    # ── UI Setup ──────────────────────────────────────────────────────────

    def _setup_ui(self):
        w = self._cfg.get("ui.window.width", 200)
        h = self._cfg.get("ui.window.height", 260)
        self.setFixedSize(QSize(w, h))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowOpacity(self._cfg.get("ui.window.opacity", 0.95))

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Sprite widget (DNA character animation)
        self._sprite = SpriteWidget(self._cfg, self)
        self._sprite.setFixedSize(w - 16, 180)
        layout.addWidget(self._sprite)

        # Status label (small text below sprite)
        self._status_label = QLabel("", self)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            f"color: {self._cfg.get('ui.theme.primary_color', '#00FF88')};"
            f"font-family: '{self._cfg.get('ui.theme.font_family', 'Segoe UI')}';"
            f"font-size: 9px; background: transparent;"
        )
        self._status_label.setText("Mr. ADN ✦")
        self._status_label.hide() # Hidden so it doesn't float text under the sprite
        layout.addWidget(self._status_label)

        # Chat bubble (hidden by default)
        self._bubble = ChatBubble(self._cfg, self._bus, parent=None)  # Separate floating window
        self._bubble.submitted.connect(self._on_user_input)

        # Capture overlay (hidden)
        self._capture_overlay = CaptureOverlay()
        self._capture_overlay.region_selected.connect(self._on_region_selected)

    def _setup_tray(self):
        """System tray icon for quick access."""
        icon = self.style().standardIcon(
            self.style().StandardPixmap.SP_ComputerIcon
        )
        self._tray = QSystemTrayIcon(icon, self)
        tray_menu = QMenu()
        tray_menu.addAction("Mostrar / Ocultar", self._toggle_visibility)
        tray_menu.addAction("Configuración", self._open_settings)
        tray_menu.addSeparator()
        tray_menu.addAction("Salir", QApplication.quit)
        self._tray.setContextMenu(tray_menu)
        self._tray.setToolTip("Mr. ADN")
        self._tray.show()
        self._tray.activated.connect(self._on_tray_activated)

    # ── Painting (custom transparent background + border) ─────────────────

    def paintEvent(self, event):
        # The window is completely frameless and transparent.
        # We don't draw any background rectangle so the character floats naturally.
        pass

    # ── Mouse events (drag) ───────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos and self._cfg.get("ui.movement.draggable", True):
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            # Clamp to monitors
            cx, cy = self._monitors.clamp_window(new_pos.x(), new_pos.y(), self.width(), self.height())
            self.move(cx, cy)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self._save_position()
            self._bus.publish(POSITION_CHANGED, x=self.x(), y=self.y())
        elif event.button() == Qt.MouseButton.RightButton:
            pass  # handled by contextMenuEvent

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._show_chat_input()

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = QMenu(self)
        menu.setStyleSheet(self._context_menu_style())

        action_chat  = menu.addAction("💬  Chatear")
        action_cap   = menu.addAction("📸  Capturar pantalla")
        menu.addSeparator()
        action_mute  = menu.addAction("🔇  Silenciar" if not self._is_muted else "🔈  Activar")
        action_stats = menu.addAction("📊  Estadísticas Bandit")
        action_cfg   = menu.addAction("⚙️   Configuración")
        menu.addSeparator()
        action_quit  = menu.addAction("✖  Salir")

        action = menu.exec(event.globalPos())
        if action == action_chat:   self._show_chat_input()
        elif action == action_cap:  self._start_capture()
        elif action == action_mute: self._toggle_mute()
        elif action == action_stats: self._show_bandit_stats()
        elif action == action_cfg:  self._open_settings()
        elif action == action_quit: QApplication.quit()

    # ── Chat / Input ──────────────────────────────────────────────────────

    def _show_chat_input(self):
        if self._is_muted:
            return
        self._bubble.show_input()
        self._bubble.reposition_near(self.geometry())

    def _on_user_input(self, text: str):
        """User submitted a message from ChatInput."""
        if not text.strip():
            return
        self._bubble.show_message(f"🧑: {text}", role="user")
        self._bubble.reposition_near(self.geometry())

        self._brain.ask(
            user_text=text,
            image_bytes=self._pending_screenshot,
            input_mode="text",
        )
        self._pending_screenshot = None

    # ── AI response handlers ───────────────────────────────────────────────

    def _on_ai_thinking(self):
        self._sprite.set_state("thinking")
        self._status_label.setText("pensando...")
        self._bubble.show_message("...", role="assistant")
        self._bubble.reposition_near(self.geometry())
        
    def _on_ai_observing(self):
        self._sprite.set_state("observing")
        self._status_label.setText("observando...")

    def _on_response_chunk(self, chunk: str):
        self._current_response += chunk
        self._bubble.append_text(chunk)
        self._sprite.set_state("speaking")

    def _on_response_done(self, text: str, error: bool):
        self._current_response = ""
        self._sprite.set_state("idle")
        self._status_label.setText("Mr. ADN ✦")
        if error:
            self._bubble.show_message(f"⚠ {text}", role="error")

    # ── Telemetry callbacks ───────────────────────────────────────────────

    def _on_window_changed(self, window_str: str):
        self._brain.active_window = window_str
        if self._sprite._state == "idle":
            self._sprite.set_state("observing")
            self._status_label.setText("observando...")
            QTimer.singleShot(2500, self._revert_to_idle)

    def _revert_to_idle(self):
        if self._sprite._state == "observing":
            self._sprite.set_state("idle")
            self._status_label.setText("Mr. ADN ✦")

    def _on_windows_scanned(self, windows: list, **_):
        self._brain.visible_windows = windows

    # ── Screenshot / Capture ──────────────────────────────────────────────

    def _start_capture(self):
        self._capture_overlay.start()

    def _on_region_selected(self, x: int, y: int, w: int, h: int):
        from telemetry.screen_capture import ScreenCapture
        cap = ScreenCapture()
        img_bytes = cap.capture_region(x, y, w, h)
        if img_bytes:
            self._pending_screenshot = img_bytes
            self._bus.publish(SCREENSHOT_TAKEN, bytes=img_bytes)
            self._bubble.show_message("📸 Región capturada. ¿Qué quieres saber?", role="system")
            self._bubble.reposition_near(self.geometry())
            self._show_chat_input()

    # ── Proactivity (bandit-driven) ───────────────────────────────────────

    def _proactivity_tick(self):
        if self._is_muted:
            return
        if self._bandit.should_interrupt():
            context = self._brain.active_window
            proactive_prompt = (
                f"Genera un comentario breve, útil y contextual sobre lo que "
                f"está haciendo el usuario (ventana: {context or 'desconocida'}). "
                f"Sin preguntar, solo un tip o dato interesante. Máximo 2 oraciones."
            )
            self._brain.ask(user_text=proactive_prompt, input_mode="proactive")

    # ── Position persistence ──────────────────────────────────────────────

    def _save_position(self):
        self.POSITION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.POSITION_FILE, "w") as f:
            json.dump({"x": self.x(), "y": self.y()}, f)

    def _restore_position(self):
        try:
            if self.POSITION_FILE.exists():
                with open(self.POSITION_FILE) as f:
                    pos = json.load(f)
                x, y = int(pos["x"]), int(pos["y"])
                x, y = self._monitors.clamp_window(x, y, self.width(), self.height())
                self.move(x, y)
                return
        except Exception as exc:
            logger.debug(f"Position restore failed: {exc}")
        # Default: near top-right of primary monitor
        primary = self._monitors.primary
        self.move(primary.right - self.width() - 40, primary.y + 60)

    def save_position(self):
        """Called on application exit."""
        self._save_position()

    # ── Misc helpers ──────────────────────────────────────────────────────

    def _toggle_mute(self):
        self._is_muted = not self._is_muted
        logger.info(f"Muted: {self._is_muted}")
        self._status_label.setText("🔇 silenciado" if self._is_muted else "Mr. ADN ✦")

    def _toggle_visibility(self):
        self.setVisible(not self.isVisible())

    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._cfg, self._bandit, parent=self)
        dlg.exec()

    def _show_bandit_stats(self):
        stats = self._bandit.get_stats()
        lines = [f"Proactividad: {stats['proactivity_score']:.2%}", ""]
        for arm, data in stats.items():
            if arm == "proactivity_score":
                continue
            lines.append(f"{arm}: pulls={data['pulls']} avg={data['avg_reward']:.2f}")
        self._bubble.show_message("\n".join(lines), role="system")
        self._bubble.reposition_near(self.geometry())

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_visibility()

    @staticmethod
    def _context_menu_style() -> str:
        return """
        QMenu {
            background-color: #0D0D2B;
            border: 1px solid #00FF88;
            border-radius: 8px;
            color: #FFFFFF;
            font-size: 12px;
            padding: 4px;
        }
        QMenu::item { padding: 6px 20px; border-radius: 4px; }
        QMenu::item:selected { background-color: #1A1A4A; color: #00FF88; }
        QMenu::separator { height: 1px; background: #333366; margin: 3px 8px; }
        """
