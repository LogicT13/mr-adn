"""
core/database.py — SQLite persistence layer.

Tables:
  - interactions      : Full chat history with context snapshots
  - bandit_feedback   : User feedback events for the Bandit algorithm
  - bandit_arms       : Running reward/count stats per arm
  - settings          : Key-value store for runtime preferences
"""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Any

from loguru import logger


class DatabaseManager:
    """
    Manages the SQLite database for Mr. ADN.
    Call initialize() once at startup to create tables.
    Thread-safe via check_same_thread=False + serialized calls.
    """

    def __init__(self, db_path: Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Open the database and create tables if they don't exist."""
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        logger.info(f"Database ready: {self._path}")

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("Database closed.")

    # ── Schema ────────────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS interactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            role        TEXT    NOT NULL,   -- 'user' | 'assistant'
            content     TEXT    NOT NULL,
            context_json TEXT,              -- JSON snapshot of telemetry context
            input_mode  TEXT,               -- 'text' | 'voice' | 'proactive'
            provider    TEXT,
            model       TEXT,
            tokens_used INTEGER
        );

        CREATE TABLE IF NOT EXISTS bandit_feedback (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,   -- 'ignore' | 'silence' | 'interact'
            context_app TEXT,               -- active app at the time
            arm         TEXT    NOT NULL,   -- which action was taken
            reward      REAL    NOT NULL    -- 1.0=interact, 0.0=ignore, -0.5=silence
        );

        CREATE TABLE IF NOT EXISTS bandit_arms (
            arm         TEXT    PRIMARY KEY,
            n_pulls     INTEGER NOT NULL DEFAULT 0,
            total_reward REAL   NOT NULL DEFAULT 0.0,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key         TEXT    PRIMARY KEY,
            value       TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS telemetry_focus (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            window_name TEXT    NOT NULL
        );
        """
        self._conn.executescript(ddl)
        self._conn.commit()
        logger.debug("Database tables verified/created.")

    def log_focus_change(self, window_name: str) -> None:
        """Log a window focus change."""
        if not self._conn:
            return
        query = "INSERT INTO telemetry_focus (timestamp, window_name) VALUES (datetime('now'), ?)"
        try:
            self._conn.execute(query, (window_name,))
            self._conn.commit()
        except Exception as exc:
            logger.error(f"DB log_focus_change error: {exc}")

    # ── Interactions ──────────────────────────────────────────────────────

    def save_interaction(
        self,
        role: str,
        content: str,
        context: dict | None = None,
        input_mode: str = "text",
        provider: str | None = None,
        model: str | None = None,
        tokens_used: int | None = None,
    ) -> int:
        """Persist a chat turn. Returns the new row ID."""
        cursor = self._conn.execute(
            """INSERT INTO interactions
               (timestamp, role, content, context_json, input_mode, provider, model, tokens_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(),
                role,
                content,
                json.dumps(context) if context else None,
                input_mode,
                provider,
                model,
                tokens_used,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_recent_interactions(self, limit: int = 20) -> list[sqlite3.Row]:
        """Return the N most recent interaction rows."""
        cursor = self._conn.execute(
            "SELECT * FROM interactions ORDER BY id DESC LIMIT ?", (limit,)
        )
        return cursor.fetchall()

    # ── Bandit ────────────────────────────────────────────────────────────

    def record_feedback(self, event_type: str, arm: str, reward: float, context_app: str = "") -> None:
        """Log a user feedback event for the bandit learner."""
        self._conn.execute(
            """INSERT INTO bandit_feedback (timestamp, event_type, context_app, arm, reward)
               VALUES (?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), event_type, context_app, arm, reward),
        )
        self._conn.commit()

    def update_bandit_arm(self, arm: str, reward: float) -> None:
        """Upsert the rolling stats for a bandit arm."""
        self._conn.execute(
            """INSERT INTO bandit_arms (arm, n_pulls, total_reward, last_updated)
               VALUES (?, 1, ?, ?)
               ON CONFLICT(arm) DO UPDATE SET
                 n_pulls = n_pulls + 1,
                 total_reward = total_reward + excluded.total_reward,
                 last_updated = excluded.last_updated""",
            (arm, reward, datetime.utcnow().isoformat()),
        )
        self._conn.commit()

    def get_bandit_arms(self) -> list[sqlite3.Row]:
        """Return all bandit arm stats."""
        return self._conn.execute("SELECT * FROM bandit_arms").fetchall()

    # ── Settings (key-value store) ────────────────────────────────────────

    def set_setting(self, key: str, value: Any) -> None:
        self._conn.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, json.dumps(value), datetime.utcnow().isoformat()),
        )
        self._conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])
