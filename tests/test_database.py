"""Tests for the SQLite storage layer."""

import os
import tempfile
import time

from trivia.storage.database import Database


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path), path


class TestScores:
    def test_add_score_creates_entry(self):
        db, path = _make_db()
        try:
            score = db.add_score("U001", "C001", 5)
            assert score.total_score == 5
            assert score.correct_answers == 1
        finally:
            os.unlink(path)

    def test_add_score_accumulates(self):
        db, path = _make_db()
        try:
            db.add_score("U001", "C001", 5)
            score = db.add_score("U001", "C001", 3)
            assert score.total_score == 8
            assert score.correct_answers == 2
        finally:
            os.unlink(path)

    def test_scores_are_per_channel(self):
        db, path = _make_db()
        try:
            db.add_score("U001", "C001", 5)
            db.add_score("U001", "C002", 10)
            s1 = db.get_user_stats("U001", "C001")
            s2 = db.get_user_stats("U001", "C002")
            assert s1.total_score == 5
            assert s2.total_score == 10
        finally:
            os.unlink(path)

    def test_leaderboard_ordering(self):
        db, path = _make_db()
        try:
            db.add_score("U001", "C001", 5)
            db.add_score("U002", "C001", 10)
            db.add_score("U003", "C001", 3)
            lb = db.get_leaderboard("C001")
            assert lb[0].user_id == "U002"
            assert lb[1].user_id == "U001"
            assert lb[2].user_id == "U003"
        finally:
            os.unlink(path)

    def test_leaderboard_limit(self):
        db, path = _make_db()
        try:
            for i in range(15):
                db.add_score(f"U{i:03d}", "C001", i)
            lb = db.get_leaderboard("C001", limit=5)
            assert len(lb) == 5
        finally:
            os.unlink(path)

    def test_user_global_stats(self):
        db, path = _make_db()
        try:
            db.add_score("U001", "C001", 5)
            db.add_score("U001", "C002", 10)
            global_stats = db.get_user_global_stats("U001")
            assert global_stats.total_score == 15
            assert global_stats.correct_answers == 2
        finally:
            os.unlink(path)

    def test_nonexistent_user_stats(self):
        db, path = _make_db()
        try:
            assert db.get_user_stats("UXXX", "C001") is None
        finally:
            os.unlink(path)


class TestQuestionHistory:
    def test_record_and_mark_answered(self):
        db, path = _make_db()
        try:
            q_id = db.record_question(
                "C001", "What is 2+2?", "4", "easy", "test", 1
            )
            assert q_id is not None
            db.mark_answered(q_id, "U001")
        finally:
            os.unlink(path)


class TestFreezes:
    def test_set_and_get_freeze(self):
        db, path = _make_db()
        try:
            freeze = db.set_freeze("U001", "C001", 10)
            assert freeze.is_active
            retrieved = db.get_freeze("U001", "C001")
            assert retrieved is not None
            assert retrieved.is_active
        finally:
            os.unlink(path)

    def test_no_freeze_for_other_user(self):
        db, path = _make_db()
        try:
            db.set_freeze("U001", "C001", 10)
            assert db.get_freeze("U002", "C001") is None
        finally:
            os.unlink(path)

    def test_expired_freeze_returns_none(self):
        db, path = _make_db()
        try:
            db.set_freeze("U001", "C001", 0)
            time.sleep(0.1)
            assert db.get_freeze("U001", "C001") is None
        finally:
            os.unlink(path)

    def test_get_all_channel_scores(self):
        db, path = _make_db()
        try:
            db.add_score("U001", "C001", 5)
            db.add_score("U002", "C001", 10)
            db.add_score("U001", "C002", 3)
            all_scores = db.get_all_channel_scores()
            assert "C001" in all_scores
            assert "C002" in all_scores
            assert len(all_scores["C001"]) == 2
            assert all_scores["C001"][0].user_id == "U002"
        finally:
            os.unlink(path)
