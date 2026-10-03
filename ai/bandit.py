"""
ai/bandit.py — UCB1 Multi-Armed Bandit for proactivity calibration.

Arms:
  - interact : User engaged with the spontaneous message  → reward +1.0
  - ignore   : User closed/dismissed the bubble silently  → reward  0.0
  - silence  : User explicitly silenced Mr. ADN           → reward -0.5

The bandit adjusts the proactivity score (probability of spontaneous
interruption) upward when interactions are rewarded and downward
when the user ignores or silences.

Persistence: stats are stored in SQLite via DatabaseManager.
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime, timedelta

from loguru import logger

from core.config_manager import ConfigManager
from core.database import DatabaseManager


REWARD_MAP = {
    "interact": 1.0,
    "ignore":   0.0,
    "silence": -0.5,
}


class BanditEngine:
    """
    UCB1 bandit that estimates the expected reward for proactive interruptions
    and outputs a proactivity score in [min_proactivity, max_proactivity].
    """

    def __init__(self, db: DatabaseManager, cfg: ConfigManager):
        self._db = db
        self._cfg = cfg
        self._arms: list[str] = cfg.get("bandit.arms", ["ignore", "silence", "interact"])
        self._c = cfg.get("bandit.exploration_constant", 1.41)
        self._min_p = cfg.get("bandit.min_proactivity", 0.05)
        self._max_p = cfg.get("bandit.max_proactivity", 0.80)
        self._cooldown = cfg.get("bandit.cooldown_after_silence_sec", 300)
        self._min_interval = cfg.get("bandit.min_interval_between_interruptions_sec", 120)
        self._last_silence_ts: float = 0.0
        self._last_interrupt_ts: float = 0.0

        # In-memory stats (seeded from DB)
        self._n: dict[str, int] = {arm: 0 for arm in self._arms}
        self._q: dict[str, float] = {arm: 0.0 for arm in self._arms}
        self._load_from_db()

        logger.info(f"BanditEngine ready | proactivity={self.proactivity_score:.2f}")

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def proactivity_score(self) -> float:
        """Current estimated probability of triggering a spontaneous message."""
        score = self._estimate_score()
        return max(self._min_p, min(self._max_p, score))

    def should_interrupt(self) -> bool:
        """Return True if the bandit decides to show a proactive message now."""
        now = time.time()

        # Enforce cooldown after a silence event
        if now - self._last_silence_ts < self._cooldown:
            return False

        # Enforce minimum interval between interruptions
        if now - self._last_interrupt_ts < self._min_interval:
            return False

        p = self.proactivity_score
        decision = random.random() < p
        if decision:
            self._last_interrupt_ts = now
            logger.debug(f"Bandit: interrupt triggered (p={p:.2f})")
        return decision

    def record_feedback(self, event_type: str, context_app: str = "") -> None:
        """
        Called when the user reacts to a spontaneous message.
        event_type: 'interact' | 'ignore' | 'silence'
        """
        if event_type not in REWARD_MAP:
            logger.warning(f"Unknown bandit event_type: {event_type}")
            return

        reward = REWARD_MAP[event_type]
        arm = event_type  # arm == event_type in this design

        # Update in-memory stats
        self._n[arm] = self._n.get(arm, 0) + 1
        self._q[arm] = self._q.get(arm, 0.0) + reward

        # Persist
        self._db.record_feedback(event_type, arm, reward, context_app)
        self._db.update_bandit_arm(arm, reward)

        if event_type == "silence":
            self._last_silence_ts = time.time()

        logger.info(f"Bandit feedback: {event_type} | reward={reward} | "
                    f"new proactivity≈{self.proactivity_score:.2f}")

    def get_stats(self) -> dict:
        """Return current arm stats for display in settings."""
        stats = {}
        for arm in self._arms:
            n = self._n.get(arm, 0)
            q = self._q.get(arm, 0.0)
            stats[arm] = {
                "pulls": n,
                "total_reward": round(q, 3),
                "avg_reward": round(q / n, 3) if n > 0 else 0.0,
            }
        stats["proactivity_score"] = round(self.proactivity_score, 3)
        return stats

    # ── Internal ──────────────────────────────────────────────────────────

    def _estimate_score(self) -> float:
        """
        UCB1 value for the 'interact' arm normalized to a proactivity score.
        When data is scarce, returns the configured initial proactivity.
        """
        total_pulls = sum(self._n.values())
        if total_pulls < 3:
            return self._cfg.get("bandit.initial_proactivity", 0.30)

        best_val = -float("inf")
        for arm in self._arms:
            n_arm = self._n.get(arm, 0)
            if n_arm == 0:
                return self._max_p  # Unseen arm → explore
            q = self._q[arm] / n_arm
            ucb = q + self._c * math.sqrt(math.log(total_pulls) / n_arm)
            if arm == "interact" and ucb > best_val:
                best_val = ucb

        # Map UCB value (roughly 0–2) → proactivity (min–max)
        normalized = (best_val + 0.5) / 2.5  # shift & scale to ~[0,1]
        return self._min_p + normalized * (self._max_p - self._min_p)

    def _load_from_db(self) -> None:
        """Seed in-memory stats from persisted DB rows."""
        rows = self._db.get_bandit_arms()
        for row in rows:
            arm = row["arm"]
            if arm in self._arms:
                self._n[arm] = row["n_pulls"]
                self._q[arm] = row["total_reward"]
        logger.debug(f"Bandit stats loaded: {self._n}")
