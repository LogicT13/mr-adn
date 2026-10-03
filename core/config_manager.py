"""
core/config_manager.py — Configuration Manager
Loads config/config.json and allows dot-path access.
Supports runtime overrides without touching the file.
"""

from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any

from loguru import logger


class ConfigManager:
    """
    Loads and exposes the application configuration from config/config.json.
    Supports dot-notation key access: cfg.get("ui.window.width")
    """

    CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"

    def __init__(self, config_path: Path | None = None):
        self._path = config_path or self.CONFIG_PATH
        self._data: dict = {}
        self._overrides: dict = {}
        self._load()

    def _load(self) -> None:
        """Read and parse the JSON config file."""
        if not self._path.exists():
            logger.error(f"Config file not found: {self._path}")
            raise FileNotFoundError(f"Config not found: {self._path}")
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = json.load(f)
        logger.debug(f"Config loaded from {self._path}")

    def reload(self) -> None:
        """Hot-reload config from disk (useful for dev)."""
        self._load()
        logger.info("Config reloaded.")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Dot-path accessor.  get("ui.window.width") → 200
        Checks runtime overrides first, then the file data.
        """
        for source in (self._overrides, self._data):
            val = self._dotget(source, key)
            if val is not None:
                return val
        return default

    def set_override(self, key: str, value: Any) -> None:
        """Set a runtime override (not persisted to disk)."""
        parts = key.split(".")
        node = self._overrides
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        logger.debug(f"Config override set: {key} = {value!r}")

    def save(self, key: str, value: Any) -> None:
        """
        Persist a value to the config file.
        Only shallow top-level sections are written safely.
        """
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Config saved: {key} = {value!r}")

    def as_dict(self) -> dict:
        """Return a deep copy of the full merged config."""
        merged = copy.deepcopy(self._data)
        self._deepmerge(merged, self._overrides)
        return merged

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _dotget(data: dict, key: str) -> Any:
        """Navigate nested dict using dot-notation key."""
        parts = key.split(".")
        node = data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    @staticmethod
    def _deepmerge(base: dict, override: dict) -> None:
        """Recursively merge override into base (in-place)."""
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                ConfigManager._deepmerge(base[k], v)
            else:
                base[k] = v
