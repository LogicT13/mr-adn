"""
ui/chat_input.py — Compact floating text input bar.

Appears below or above the main window when the user invokes Mr. ADN.
Emits the submitted(text: str) signal on Enter or Ctrl+Enter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QPainterPath, QFont
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPlainTextEdit, QPushButton, QSizePolicy
)

if TYPE_CHECKING:
    from core.config_manager import ConfigManager

class AutoResizingTextEdit(QPlainTextEdit):
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.textChanged.connect(self._adjust_height)
        self._min_lines = 1
        self._max_lines = 4
        self._adjust_height()

    def keyPressEvent(self, event):
        # Enter normally emits submitted, Shift+Enter inserts new line
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                text = self.toPlainText().strip()
                if text:
                    self.submitted.emit(text)
                event.accept()
        else:
            super().keyPressEvent(event)

    def _adjust_height(self):
        doc = self.document()
        doc.setTextWidth(self.viewport().width())
        
        # Calculate height based on document
        margins = self.contentsMargins()
        line_height = self.fontMetrics().lineSpacing()
        
        min_h = line_height * self._min_lines + margins.top() + margins.bottom() + 8
        max_h = line_height * self._max_lines + margins.top() + margins.bottom() + 8
        
        doc_height = doc.size().height() + margins.top() + margins.bottom() + 8
        
        h = max(min_h, min(doc_height, max_h))
        
        if doc_height > max_h:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            
        self.setFixedHeight(int(h))
        
        parent = self.parentWidget()
        if parent:
            parent.adjustSize()
            if hasattr(parent, 'resized'):
                parent.resized.emit()

class ChatInput(QWidget):
    """Compact frameless input bar that floats below the sprite."""

    submitted = pyqtSignal(str)  # Emitted when user presses Enter
    resized = pyqtSignal()

    def __init__(self, cfg: "ConfigManager", parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        primary = cfg.get("ui.theme.primary_color", "#00FF88")
        font_family = cfg.get("ui.theme.font_family", "Segoe UI")
        font_size = cfg.get("ui.theme.font_size", 12)

        self._input = AutoResizingTextEdit(self)
        self._input.setPlaceholderText("Pregúntame algo...")
        self._input.setMinimumWidth(200)
        self._input.submitted.connect(self._emit)
        
        self._input.setStyleSheet(f"""
            QPlainTextEdit {{
                background: #0D0D2B;
                color: #FFFFFF;
                border: 1px solid {primary};
                border-radius: 6px;
                padding: 5px 10px;
                font-family: '{font_family}';
                font-size: {font_size}px;
                selection-background-color: {primary};
            }}
        """)

        self._send_btn = QPushButton("→", self)
        self._send_btn.setFixedSize(QSize(30, 30))
        self._send_btn.clicked.connect(lambda: self._emit())
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {primary};
                color: #000000;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{ background: #00FFaa; }}
            QPushButton:pressed {{ background: #009944; }}
        """)
        
        layout.addWidget(self._input)
        layout.addWidget(self._send_btn, alignment=Qt.AlignmentFlag.AlignBottom)

    def _emit(self, text: str = ""):
        if not text:
            text = self._input.toPlainText().strip()
            
        if text:
            self.submitted.emit(text)
            self._input.clear()

    def clear_input(self):
        self._input.clear()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#0A0A1A")
        bg.setAlphaF(0.9)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 8, 8)
        painter.fillPath(path, QBrush(bg))
        border = QColor(self._cfg.get("ui.theme.primary_color", "#00FF88"))
        border.setAlphaF(0.4)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            window = self.window()
            if window:
                window.hide()
        else:
            super().keyPressEvent(event)
