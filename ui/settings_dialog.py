"""
ui/settings_dialog.py — Configuration dialog (Configuración).

Allows the user to change:
  - AI provider and model
  - Proactivity / bandit settings
  - Theme colors
  - Windows autostart
  - API key (masked)
"""

from __future__ import annotations

import os
import winreg
from typing import TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QSlider, QGroupBox,
    QTabWidget, QWidget, QFormLayout, QMessageBox
)

if TYPE_CHECKING:
    from core.config_manager import ConfigManager
    from ai.bandit import BanditEngine


AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "MrADN"


class SettingsDialog(QDialog):
    """Modal settings dialog."""

    def __init__(self, cfg: "ConfigManager", bandit: "BanditEngine", parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._bandit = bandit
        self.setWindowTitle("Mr. ADN — Configuración")
        self.setMinimumWidth(420)
        self.setStyleSheet(self._style())
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._ai_tab(), "🤖 IA")
        tabs.addTab(self._behavior_tab(), "🧠 Comportamiento")
        tabs.addTab(self._system_tab(), "⚙️ Sistema")
        tabs.addTab(self._stats_tab(), "📊 Estadísticas")
        layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Guardar")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    # ── Tabs ──────────────────────────────────────────────────────────────

    def _ai_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["gemini", "openai", "ollama"])
        self._provider_combo.setCurrentText(self._cfg.get("ai.provider", "gemini"))
        form.addRow("Proveedor:", self._provider_combo)

        self._model_input = QLineEdit(self._cfg.get("ai.model", "gemini-3.5-flash-lite"))
        form.addRow("Modelo:", self._model_input)

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("(guardado en .env)")
        form.addRow("API Key:", self._api_key_input)

        self._streaming_check = QCheckBox("Streaming de respuesta")
        self._streaming_check.setChecked(self._cfg.get("ai.streaming", True))
        form.addRow("", self._streaming_check)

        return w

    def _behavior_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._proactive_check = QCheckBox("Hablar espontáneamente")
        self._proactive_check.setChecked(self._cfg.get("bandit.enabled", True))
        form.addRow("", self._proactive_check)

        self._draggable_check = QCheckBox("Permitir arrastrar")
        self._draggable_check.setChecked(self._cfg.get("ui.movement.draggable", True))
        form.addRow("", self._draggable_check)

        self._drift_check = QCheckBox("Movimiento autónomo sutil")
        self._drift_check.setChecked(self._cfg.get("ui.movement.autonomous_drift", False))
        form.addRow("", self._drift_check)

        self._input_mode_combo = QComboBox()
        self._input_mode_combo.addItems(["text", "voice"])
        self._input_mode_combo.setCurrentText(self._cfg.get("ui.input_mode", "text"))
        form.addRow("Modo de entrada:", self._input_mode_combo)

        return w

    def _system_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._autostart_check = QCheckBox("Iniciar con Windows")
        self._autostart_check.setChecked(self._is_autostart_enabled())
        form.addRow("", self._autostart_check)

        self._telemetry_check = QCheckBox("Monitorear ventanas activas")
        self._telemetry_check.setChecked(self._cfg.get("telemetry.enabled", True))
        form.addRow("", self._telemetry_check)

        debug_check = QCheckBox("Modo debug (logs detallados)")
        debug_check.setChecked(self._cfg.get("app.debug", False))
        form.addRow("", debug_check)
        self._debug_check = debug_check

        return w

    def _stats_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        stats = self._bandit.get_stats()
        layout.addWidget(QLabel(f"Proactividad actual: {stats['proactivity_score']:.2%}"))
        for arm, data in stats.items():
            if arm == "proactivity_score":
                continue
            lbl = QLabel(
                f"[{arm}]  pulls: {data['pulls']}  "
                f"total: {data['total_reward']:.1f}  "
                f"avg: {data['avg_reward']:.2f}"
            )
            layout.addWidget(lbl)
        reset_btn = QPushButton("Reset estadísticas Bandit")
        reset_btn.clicked.connect(self._reset_bandit)
        layout.addWidget(reset_btn)
        layout.addStretch()
        return w

    # ── Actions ───────────────────────────────────────────────────────────

    def _save(self):
        self._cfg.save("ai.provider", self._provider_combo.currentText())
        self._cfg.save("ai.model", self._model_input.text().strip())
        self._cfg.save("ai.streaming", self._streaming_check.isChecked())
        self._cfg.save("bandit.enabled", self._proactive_check.isChecked())
        self._cfg.save("ui.movement.draggable", self._draggable_check.isChecked())
        self._cfg.save("ui.movement.autonomous_drift", self._drift_check.isChecked())
        self._cfg.save("ui.input_mode", self._input_mode_combo.currentText())
        self._cfg.save("telemetry.enabled", self._telemetry_check.isChecked())
        self._cfg.save("app.debug", self._debug_check.isChecked())

        # Autostart
        if self._autostart_check.isChecked():
            self._enable_autostart()
        else:
            self._disable_autostart()

        # API key (write to .env if provided)
        key = self._api_key_input.text().strip()
        if key:
            self._write_env_key(self._provider_combo.currentText(), key)

        logger.info("Settings saved.")
        self.accept()

    def _reset_bandit(self):
        reply = QMessageBox.question(
            self, "Reset", "¿Resetear todas las estadísticas del Bandit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            for arm in ["interact", "ignore", "silence"]:
                self._bandit._n[arm] = 0
                self._bandit._q[arm] = 0.0

    # ── Autostart (Windows registry) ──────────────────────────────────────

    @staticmethod
    def _is_autostart_enabled() -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    @staticmethod
    def _enable_autostart() -> None:
        import sys
        exe = sys.executable
        script = str(Path(__file__).parent.parent / "main.py")
        value = f'"{exe}" "{script}"'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, value)
            winreg.CloseKey(key)
            logger.info(f"Autostart enabled: {value}")
        except Exception as exc:
            logger.error(f"Failed to enable autostart: {exc}")

    @staticmethod
    def _disable_autostart() -> None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, APP_NAME)
            winreg.CloseKey(key)
            logger.info("Autostart disabled.")
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.error(f"Failed to disable autostart: {exc}")

    @staticmethod
    def _write_env_key(provider: str, key: str) -> None:
        """Append/update the API key in the .env file."""
        env_path = Path(__file__).parent.parent / ".env"
        env_key_map = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
        env_var = env_key_map.get(provider)
        if not env_var:
            return
        lines = []
        if env_path.exists():
            with open(env_path) as f:
                lines = f.readlines()
        new_line = f"{env_var}={key}\n"
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}="):
                lines[i] = new_line
                found = True
                break
        if not found:
            lines.append(new_line)
        with open(env_path, "w") as f:
            f.writelines(lines)
        logger.info(f"API key for {provider} written to .env")

    @staticmethod
    def _style() -> str:
        return """
        QDialog { background: #0D0D2B; color: #FFFFFF; }
        QTabWidget::pane { border: 1px solid #333366; background: #0D0D2B; }
        QTabBar::tab { background: #1A1A3A; color: #AAAACC; padding: 6px 14px; }
        QTabBar::tab:selected { background: #0D0D2B; color: #00FF88; border-bottom: 2px solid #00FF88; }
        QLabel { color: #CCCCFF; }
        QLineEdit { background: #1A1A3A; color: #FFFFFF; border: 1px solid #333366; border-radius: 4px; padding: 4px; }
        QComboBox { background: #1A1A3A; color: #FFFFFF; border: 1px solid #333366; border-radius: 4px; padding: 4px; }
        QCheckBox { color: #CCCCFF; }
        QPushButton { background: #1A1A4A; color: #00FF88; border: 1px solid #00FF88; border-radius: 5px; padding: 6px 14px; }
        QPushButton:hover { background: #00FF88; color: #000000; }
        """


# Allow _enable_autostart to use Path
from pathlib import Path
