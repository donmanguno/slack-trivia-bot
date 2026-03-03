"""Tests for Block Kit UI builders."""

from trivia.questions.base import Difficulty, TriviaQuestion
from trivia.round import ChannelRound, RoundScoreEntry, RoundState
from trivia.storage.models import UserScore
from trivia.ui.blocks import (
    build_categories_blocks,
    build_help_blocks,
    build_leaderboard_blocks,
    build_question_blocks,
    build_round_summary_blocks,
    build_user_stats_blocks,
)


class TestQuestionBlocks:
    def test_builds_valid_blocks(self):
        q = TriviaQuestion(
            question="What is the capital of France?",
            correct_answer="Paris",
            difficulty=Difficulty.MEDIUM,
            category="Geography",
            source="Test",
        )
        blocks = build_question_blocks(q, 3, 10)
        assert len(blocks) == 4
        assert blocks[0]["type"] == "header"
        assert "3/10" in blocks[0]["text"]["text"]
        assert "France" in blocks[1]["text"]["text"]


class TestLeaderboardBlocks:
    def test_empty_leaderboard(self):
        blocks = build_leaderboard_blocks([], "C001")
        assert len(blocks) == 1
        assert "no scores" in blocks[0]["text"]["text"].lower()

    def test_leaderboard_with_scores(self):
        scores = [
            UserScore("U001", "C001", 100, 20),
            UserScore("U002", "C001", 80, 15),
            UserScore("U003", "C001", 50, 10),
        ]
        blocks = build_leaderboard_blocks(scores, "C001")
        assert any("first_place" in str(b) for b in blocks)


class TestUserStatsBlocks:
    def test_no_stats(self):
        blocks = build_user_stats_blocks("U001", None, None)
        assert any("hasn't played" in str(b) for b in blocks)

    def test_with_stats(self):
        channel = UserScore("U001", "C001", 50, 10)
        global_s = UserScore("U001", "", 100, 20)
        blocks = build_user_stats_blocks("U001", channel, global_s)
        assert any("50" in str(b) for b in blocks)


class TestRoundSummaryBlocks:
    def test_empty_round(self):
        r = ChannelRound("C001", 10, "U001", RoundState.IDLE)
        blocks = build_round_summary_blocks(r)
        assert any("no one scored" in str(b).lower() for b in blocks)

    def test_round_with_scores(self):
        r = ChannelRound("C001", 10, "U001", RoundState.IDLE)
        r.round_scores = {
            "U001": RoundScoreEntry("U001", 15, 5),
            "U002": RoundScoreEntry("U002", 10, 3),
        }
        blocks = build_round_summary_blocks(r)
        text = str(blocks)
        assert "15" in text
        assert "U001" in text


class TestHelpBlocks:
    def test_help_has_commands(self):
        blocks = build_help_blocks()
        text = str(blocks)
        assert "start" in text
        assert "skip" in text
        assert "scores" in text


class TestCategoriesBlocks:
    def test_with_categories(self):
        cats = {"Provider A": ["Cat1", "Cat2"], "Provider B": ["Cat3"]}
        blocks = build_categories_blocks(cats)
        text = str(blocks)
        assert "Cat1" in text
        assert "Provider A" in text

    def test_empty_categories(self):
        blocks = build_categories_blocks({"A": [], "B": []})
        assert any("no categories" in str(b).lower() for b in blocks)
