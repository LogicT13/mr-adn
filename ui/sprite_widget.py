"""
ui/sprite_widget.py — Animated DNA character sprite renderer.

Supports three states: 'idle', 'thinking', 'talking'.
Renderiza los assets originales usando QMovie con fondo transparente.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QMovie
from PyQt6.QtWidgets import QWidget

from loguru import logger

if TYPE_CHECKING:
    from core.config_manager import ConfigManager


class SpriteWidget(QWidget):
    """Renders the Mr. ADN character using QMovie (GIF assets)."""

    STATES = ("idle", "observing", "thinking", "talking")
    ASSETS_DIR = Path(__file__).parent.parent / "assets"
    SPRITE_DIR = ASSETS_DIR / "sprites"

    def __init__(self, cfg: "ConfigManager", parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._state = "idle"
        
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Load movies
        self._movies: dict[str, QMovie] = {}
        self._current_movie: QMovie | None = None
        
        self._load_movies()
        self.set_state("idle")

    def _load_movies(self) -> None:
        """Loads GIF files for each state, falling back to a talking GIF if missing."""
        fallback_dir = self.SPRITE_DIR / "talking"
        fallback_gif = None
        
        if fallback_dir.exists():
            gifs = list(fallback_dir.glob("*.gif"))
            if gifs:
                fallback_gif = gifs[0]

        for state in self.STATES:
            state_dir = self.SPRITE_DIR / state
            gif_path = None
            
            # Find a GIF in the state directory
            if state_dir.exists():
                gifs = list(state_dir.glob("*.gif"))
                if gifs:
                    gif_path = gifs[0]
            
            # Use fallback if no specific GIF found
            if not gif_path:
                gif_path = fallback_gif
                
            if gif_path and gif_path.exists():
                movie = QMovie(str(gif_path))
                if movie.isValid():
                    movie.frameChanged.connect(self.update)
                    self._movies[state] = movie
                    logger.debug(f"Loaded GIF for state '{state}': {gif_path.name}")

        if not self._movies:
            logger.warning("No GIFs found for SpriteWidget!")

    def set_state(self, state: str) -> None:
        # Alias speaking -> talking
        if state == "speaking":
            state = "talking"
            
        if state not in self.STATES:
            return
            
        if self._state == state and self._current_movie:
            # Already in this state and playing
            return
            
        self._state = state
        
        # Stop previous movie
        if self._current_movie:
            self._current_movie.stop()
            
        # Start new movie
        self._current_movie = self._movies.get(state)
        if self._current_movie:
            self._current_movie.start()
            
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        if not self._current_movie:
            return
            
        pixmap = self._current_movie.currentPixmap()
        if pixmap.isNull():
            return
            
        w, h = self.width(), self.height()
        scaled_pixmap = pixmap.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # Center the pixmap
        x = (w - scaled_pixmap.width()) // 2
        y = (h - scaled_pixmap.height()) // 2
        
        painter.drawPixmap(x, y, scaled_pixmap)
