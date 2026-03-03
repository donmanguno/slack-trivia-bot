from __future__ import annotations

import time

from trivia.storage.database import Database

SPEED_BONUS_THRESHOLD_SECONDS = 10.0
SPEED_BONUS_POINTS = 1


class ScoreManager:
    def __init__(self, db: Database):
        self._db = db

    def award_points(
        self,
        user_id: str,
        channel_id: str,
        base_points: int,
        question_id: int,
        question_asked_at: float,
    ) -> tuple[int, bool]:
        """
        Award points to a user. Returns (total_points_awarded, got_speed_bonus).
        """
        elapsed = time.time() - question_asked_at
        speed_bonus = elapsed <= SPEED_BONUS_THRESHOLD_SECONDS
        total = base_points + (SPEED_BONUS_POINTS if speed_bonus else 0)

        self._db.add_score(user_id, channel_id, total)
        self._db.mark_answered(question_id, user_id)

        return total, speed_bonus

    def get_leaderboard(self, channel_id: str, limit: int = 10):
        return self._db.get_leaderboard(channel_id, limit)

    def get_user_stats(self, user_id: str, channel_id: str):
        return self._db.get_user_stats(user_id, channel_id)

    def get_user_global_stats(self, user_id: str):
        return self._db.get_user_global_stats(user_id)
