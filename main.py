"""
Mr. ADN — Desktop Assistant
Entry point: python main.py
"""

import sys
import os
import asyncio
import threading
from pathlib import Path

# ── Bootstrap paths ──────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

# ── Load environment variables first ─────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

# ── Logging ──────────────────────────────────────────────────────────────────
from loguru import logger
from core.config_manager import ConfigManager

cfg = ConfigManager()
log_level = cfg.get("app.log_level", "INFO")
log_dir = ROOT_DIR / cfg.get("persistence.log_dir", "data/logs")
log_dir.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(sys.stderr, level=log_level, colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>")
logger.add(log_dir / "mradn_{time:YYYY-MM-DD}.log", rotation="1 day", retention="7 days", level="DEBUG")

# ── PyQt6 ────────────────────────────────────────────────────────────────────
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

# ── App modules ──────────────────────────────────────────────────────────────
from core.database import DatabaseManager
from core.event_bus import EventBus
from telemetry.window_monitor import WindowMonitor
from telemetry.monitor_detector import MonitorDetector
from ai.brain import Brain
from ai.bandit import BanditEngine
from ui.main_window import MainWindow
from ui.hotkey_manager import HotkeyManager


def ensure_data_dirs():
    """Create all required runtime data directories."""
    dirs = [
        ROOT_DIR / "data",
        ROOT_DIR / cfg.get("persistence.log_dir", "data/logs"),
        ROOT_DIR / "assets/sprites/idle",
        ROOT_DIR / "assets/sprites/thinking",
        ROOT_DIR / "assets/sprites/talking",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    logger.debug("Data directories ready.")


def main():
    logger.info("🧬 Mr. ADN starting up...")
    ensure_data_dirs()

    # ── Core infrastructure ───────────────────────────────────────────────
    event_bus = EventBus()
    db = DatabaseManager(ROOT_DIR / cfg.get("persistence.db_path", "data/mradn.db"))
    db.initialize()

    # ── AI subsystems ─────────────────────────────────────────────────────
    bandit = BanditEngine(db, cfg)
    brain = Brain(cfg, event_bus)

    # ── Telemetry ─────────────────────────────────────────────────────────
    monitor_detector = MonitorDetector()
    window_monitor = WindowMonitor(cfg, event_bus)

    from core.event_bus import WINDOW_FOCUS_CHANGED
    event_bus.subscribe(WINDOW_FOCUS_CHANGED, lambda window, **_: db.log_focus_change(str(window)))

    # ── Qt Application ───────────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName(cfg.get("app.name", "Mr. ADN"))
    # Prevent app from closing when last regular window closes
    app.setQuitOnLastWindowClosed(False)

    icon_path = ROOT_DIR / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # ── Main UI window ────────────────────────────────────────────────────
    window = MainWindow(cfg, event_bus, brain, bandit, monitor_detector)
    window.show()

    # ── Global hotkeys (runs in its own thread) ───────────────────────────
    hotkey_mgr = HotkeyManager(cfg, event_bus)
    hotkey_thread = threading.Thread(target=hotkey_mgr.start, daemon=True, name="HotkeyThread")
    hotkey_thread.start()

    # ── Telemetry polling (background thread) ────────────────────────────
    if cfg.get("telemetry.enabled", True):
        monitor_thread = threading.Thread(target=window_monitor.start, daemon=True, name="TelemetryThread")
        monitor_thread.start()

    logger.info("✅ Mr. ADN is alive and watching...")

    exit_code = app.exec()

    # ── Graceful shutdown ─────────────────────────────────────────────────
    logger.info("Shutting down Mr. ADN...")
    hotkey_mgr.stop()
    window_monitor.stop()
    window.save_position()
    db.close()
    logger.info("Goodbye. 🧬")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
