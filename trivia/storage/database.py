from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .models import QuestionRecord, SoloPlayFreeze, UserScore

_env_db_path = os.environ.get("DB_PATH")
DEFAULT_DB_PATH: Path = (
    Path(_env_db_path) if _env_db_path else Path(__file__).parent.parent.parent / "trivia.db"
)


class Database:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self._db_path = str(db_path)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scores (
                    user_id TEXT,
                    channel_id TEXT,
                    total_score INTEGER DEFAULT 0,
                    correct_answers INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS question_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT,
                    question_text TEXT,
                    correct_answer TEXT,
                    difficulty TEXT,
                    source TEXT,
                    points INTEGER,
                    asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    answered_by TEXT,
                    answered_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS solo_play_freezes (
                    user_id TEXT,
                    channel_id TEXT,
                    frozen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    PRIMARY KEY (user_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS channel_sources (
                    channel_id TEXT,
                    source_name TEXT,
                    PRIMARY KEY (channel_id, source_name)
                );
            """)

    def add_score(self, user_id: str, channel_id: str, points: int) -> UserScore:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO scores (user_id, channel_id, total_score, correct_answers)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(user_id, channel_id) DO UPDATE SET
                    total_score = total_score + ?,
                    correct_answers = correct_answers + 1
                """,
                (user_id, channel_id, points, points),
            )
            row = conn.execute(
                "SELECT * FROM scores WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            ).fetchone()
            return UserScore(**dict(row))

    def get_leaderboard(
        self, channel_id: str, limit: int = 10
    ) -> list[UserScore]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scores
                WHERE channel_id = ?
                ORDER BY total_score DESC
                LIMIT ?
                """,
                (channel_id, limit),
            ).fetchall()
            return [UserScore(**dict(r)) for r in rows]

    def get_user_stats(
        self, user_id: str, channel_id: str
    ) -> Optional[UserScore]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM scores WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            ).fetchone()
            return UserScore(**dict(row)) if row else None

    def get_user_global_stats(self, user_id: str) -> Optional[UserScore]:
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT user_id, '' as channel_id,
                       SUM(total_score) as total_score,
                       SUM(correct_answers) as correct_answers
                FROM scores WHERE user_id = ?
                GROUP BY user_id
                """,
                (user_id,),
            ).fetchone()
            return UserScore(**dict(row)) if row else None

    def record_question(
        self,
        channel_id: str,
        question_text: str,
        correct_answer: str,
        difficulty: str,
        source: str,
        points: int,
    ) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO question_history
                (channel_id, question_text, correct_answer, difficulty, source, points)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (channel_id, question_text, correct_answer, difficulty, source, points),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def mark_answered(
        self, question_id: int, user_id: str
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE question_history
                SET answered_by = ?, answered_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (user_id, question_id),
            )

    def set_freeze(
        self, user_id: str, channel_id: str, duration_minutes: int = 10
    ) -> SoloPlayFreeze:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires = now + timedelta(minutes=duration_minutes)
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO solo_play_freezes (user_id, channel_id, frozen_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, channel_id) DO UPDATE SET
                    frozen_at = ?, expires_at = ?
                """,
                (user_id, channel_id, now.isoformat(), expires.isoformat(),
                 now.isoformat(), expires.isoformat()),
            )
        return SoloPlayFreeze(
            user_id=user_id,
            channel_id=channel_id,
            frozen_at=now,
            expires_at=expires,
        )

    def get_freeze(
        self, user_id: str, channel_id: str
    ) -> Optional[SoloPlayFreeze]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM solo_play_freezes WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            ).fetchone()
            if not row:
                return None
            freeze = SoloPlayFreeze(
                user_id=row["user_id"],
                channel_id=row["channel_id"],
                frozen_at=datetime.fromisoformat(row["frozen_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]),
            )
            return freeze if freeze.is_active else None

    def get_channel_sources(self, channel_id: str) -> list[str] | None:
        """Return the configured source names for a channel, or None if using defaults."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT source_name FROM channel_sources WHERE channel_id = ?",
                (channel_id,),
            ).fetchall()
        if not rows:
            return None
        return [r["source_name"] for r in rows]

    def set_channel_sources(self, channel_id: str, source_names: list[str]) -> None:
        """Persist the source selection for a channel. Empty list resets to default."""
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM channel_sources WHERE channel_id = ?", (channel_id,)
            )
            conn.executemany(
                "INSERT INTO channel_sources (channel_id, source_name) VALUES (?, ?)",
                [(channel_id, name) for name in source_names],
            )

    def get_all_channel_scores(self) -> dict[str, list[UserScore]]:
        """Get leaderboards for all channels (used by App Home)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scores
                ORDER BY channel_id, total_score DESC
                """
            ).fetchall()
            result: dict[str, list[UserScore]] = {}
            for row in rows:
                score = UserScore(**dict(row))
                result.setdefault(score.channel_id, []).append(score)
            return result
