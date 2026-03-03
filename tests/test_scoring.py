"""Tests for the scoring manager."""

import os
import tempfile
import time

from trivia.scoring.manager import ScoreManager, SPEED_BONUS_THRESHOLD_SECONDS
from trivia.storage.database import Database


def _make_manager():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    return ScoreManager(db), db, path


class TestScoreManager:
    def test_award_points_basic(self):
        mgr, db, path = _make_manager()
        try:
            q_id = db.record_question("C001", "Q?", "A", "easy", "test", 1)
            total, speed = mgr.award_points("U001", "C001", 1, q_id, time.time())
            assert total == 2  # 1 base + 1 speed bonus (answered immediately)
            assert speed is True
        finally:
            os.unlink(path)

    def test_award_points_no_speed_bonus(self):
        mgr, db, path = _make_manager()
        try:
            q_id = db.record_question("C001", "Q?", "A", "medium", "test", 2)
            asked_at = time.time() - (SPEED_BONUS_THRESHOLD_SECONDS + 5)
            total, speed = mgr.award_points("U001", "C001", 2, q_id, asked_at)
            assert total == 2
            assert speed is False
        finally:
            os.unlink(path)

    def test_leaderboard_via_manager(self):
        mgr, db, path = _make_manager()
        try:
            db.add_score("U001", "C001", 10)
            db.add_score("U002", "C001", 20)
            lb = mgr.get_leaderboard("C001")
            assert len(lb) == 2
            assert lb[0].user_id == "U002"
        finally:
            os.unlink(path)
