"""
ui/capture_overlay.py — Fullscreen translucent region-selection overlay.

Shown when the user triggers the screenshot hotkey.
User draws a rectangle with the mouse; on release, region_selected is emitted
with (x, y, width, height) in screen coordinates.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QCursor
from PyQt6.QtWidgets import QApplication, QWidget


class CaptureOverlay(QWidget):
    """Transparent fullscreen overlay for region selection."""

    region_selected = pyqtSignal(int, int, int, int)  # x, y, w, h

    def __init__(self):
        super().__init__(
            flags=(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.BypassWindowManagerHint
            )
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._selecting = False

    def start(self):
        """Show the overlay on all screens combined."""
        screen_geom = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geom)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._current = self._origin
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._current = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            end = event.globalPosition().toPoint()
            self._current = end
            self.hide()

            if self._origin is not None:
                rect = QRect(self._origin, end).normalized()
                if rect.width() > 10 and rect.height() > 10:
                    self.region_selected.emit(rect.x(), rect.y(), rect.width(), rect.height())
            self._origin = None
            self._current = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._selecting = False
            self._origin = None
            self._current = None
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dark overlay
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self._selecting and self._origin and self._current:
            # Map global coords to widget coords
            origin_local = self.mapFromGlobal(self._origin)
            current_local = self.mapFromGlobal(self._current)
            rect = QRect(origin_local, current_local).normalized()

            # Clear selected region
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            # Draw selection border
            pen = QPen(QColor("#00FF88"), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(rect)

        # Instructions
        painter.setPen(QColor(255, 255, 255, 180))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            "Arrastra para seleccionar región  •  ESC para cancelar      ",
        )
