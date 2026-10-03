"""
ui/chat_bubble.py — Floating speech bubble for AI responses.

Appears as a separate frameless window near (but not inside) the main window.
Supports streaming text (append_text) and integrates the chat input.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, QRect, QSize, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontMetrics,
    QPainterPath
)
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QScrollArea, QHBoxLayout, QPushButton, QGraphicsDropShadowEffect

from ui.chat_input import ChatInput

if TYPE_CHECKING:
    from core.config_manager import ConfigManager

import math
from core.event_bus import EventBus, USER_FEEDBACK

class ChatBubble(QWidget):
    """
    Floating frameless window that displays AI responses and the input box.
    Modern aesthetic with shadow, generous padding, and close button.
    """
    
    submitted = pyqtSignal(str)

    def __init__(self, cfg: "ConfigManager", event_bus: EventBus, parent=None):
        super().__init__(
            parent,
            flags=(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            ),
        )
        self._cfg = cfg
        self._bus = event_bus
        self._max_w = cfg.get("ui.speech_bubble.max_width", 350)
        self._max_h = cfg.get("ui.speech_bubble.max_height", 400)
        self._role = "assistant"
        
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMaximumWidth(self._max_w)
        self.setMaximumHeight(self._max_h)

        self._current_label = None
        self._current_text = ""

        self._setup_ui()

    def _setup_ui(self):
        # We need a wrapper to allow shadow rendering
        self._wrapper = QWidget(self)
        self._wrapper.setObjectName("bubbleWrapper")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.addWidget(self._wrapper)
        
        wrapper_layout = QVBoxLayout(self._wrapper)
        wrapper_layout.setContentsMargins(20, 15, 20, 15)
        
        # Header (Close button)
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet("""
            QPushButton { 
                background: transparent; border: none; color: #888; font-weight: bold; font-size: 12px; 
            }
            QPushButton:hover { color: #FFF; }
        """)
        self._close_btn.clicked.connect(self._on_close_clicked)
        header_layout.addWidget(self._close_btn)
        wrapper_layout.addLayout(header_layout)
        
        # Body: QScrollArea instead of QLabel
        self._scroll_area = QScrollArea(self._wrapper)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.4);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background: transparent;")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(10)
        
        self._scroll_area.setWidget(self._scroll_content)
        wrapper_layout.addWidget(self._scroll_area)
        
        # Input Box
        self._chat_input = ChatInput(self._cfg, self._wrapper)
        self._chat_input.submitted.connect(self.submitted.emit)
        self._chat_input.resized.connect(self._adjust_size)
        wrapper_layout.addWidget(self._chat_input)

        # Shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 8)
        self._wrapper.setGraphicsEffect(shadow)

    def _on_close_clicked(self):
        self._dismiss(feedback="ignore")

    def _dismiss(self, feedback: str):
        self.hide()
        # Emit ignore feedback for bandit
        self._bus.publish(USER_FEEDBACK, feedback=feedback)
        
    def show_input(self):
        self._adjust_size()
        self.show()
        self.raise_()
        self._chat_input._input.setFocus()

    def show_message(self, text: str, role: str = "assistant") -> None:
        self._role = role
        self._current_text = text
        self._current_label = QLabel(text)
        self._current_label.setWordWrap(True)
        self._current_label.setMaximumWidth(self._max_w - 70)
        self._current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        color = "#00FF44" if role == "user" else self._cfg.get("ui.theme.text_color", "#FFFFFF")
        if role == "error": color = "#FF3333"
        elif role == "system": color = "#9900FF"
        
        self._current_label.setStyleSheet(
            f"color: {color};"
            f"font-family: '{self._cfg.get('ui.theme.font_family', 'Segoe UI')}';"
            f"font-size: {self._cfg.get('ui.theme.font_size', 13)}px;"
            f"background: transparent;"
        )
        self._scroll_layout.addWidget(self._current_label)
        
        self._wrapper.setStyleSheet(self._get_wrapper_stylesheet())
        
        self._adjust_size()
        self.show()
        self.raise_()
            
        self._scroll_to_bottom()

    def append_text(self, chunk: str) -> None:
        self._current_text += chunk
        cursor_char = "▋" if self._cfg.get("ui.speech_bubble.stream_cursor", True) else ""
        if self._current_label:
            self._current_label.setText(self._current_text + cursor_char)
        
        self._adjust_size()
        if not self.isVisible():
            self.show()
            self.raise_()
            
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        QTimer.singleShot(10, self._do_scroll_to_bottom)
        
    def _do_scroll_to_bottom(self):
        scrollbar = self._scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reposition_near(self, main_geom: "QRect") -> None:
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        gap = 12
        bw = self.width() or self._max_w

        x = main_geom.left() - bw - gap
        if x < screen.left():
            x = main_geom.right() + gap

        y = main_geom.top()
        if y + self.height() > screen.bottom():
            y = screen.bottom() - self.height() - 10

        self.move(x, max(screen.top() + 10, y))

    def _adjust_size(self):
        content_height = self._scroll_content.sizeHint().height()
        input_height = self._chat_input.sizeHint().height() if hasattr(self, '_chat_input') else 0
        margins = self.layout().contentsMargins()
        wrapper_margins = self._wrapper.layout().contentsMargins()
        header_height = 30
        
        total_needed_h = content_height + input_height + margins.top() + margins.bottom() + wrapper_margins.top() + wrapper_margins.bottom() + header_height
        
        min_h = input_height + margins.top() + margins.bottom() + wrapper_margins.top() + wrapper_margins.bottom() + header_height + 50
        
        target_h = max(min_h, min(total_needed_h, self._max_h))
        target_w = self._max_w
        
        self.resize(target_w, target_h)

    def paintEvent(self, event):
        pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._wrapper.setStyleSheet(self._get_wrapper_stylesheet())

    def _get_wrapper_stylesheet(self) -> str:
        color_map = {
            "assistant": self._cfg.get("ui.theme.bubble_color", "#1A1A3A"),
            "user": "#1A3A1A",
            "system": "#2A1A3A",
            "error": "#3A1A1A",
        }
        bg_hex = color_map.get(self._role, color_map["assistant"])
        border_hex = {
            "assistant": self._cfg.get("ui.theme.primary_color", "#00FF88"),
            "user": "#00FF44",
            "system": "#9900FF",
            "error": "#FF3333",
        }.get(self._role, "#00FF88")
        
        return f"""
            #bubbleWrapper {{
                background-color: {bg_hex};
                border: 1px solid {border_hex};
                border-radius: 12px;
            }}
        """
