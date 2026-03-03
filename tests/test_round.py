"""Tests for the round engine logic (no Slack connection needed)."""

import asyncio
import os
import tempfile

import pytest

from trivia.questions.base import Difficulty, QuestionPool, QuestionProvider, TriviaQuestion
from trivia.round import (
    CONSECUTIVE_SKIP_LIMIT,
    SOLO_PLAY_THRESHOLD,
    ChannelRound,
    RoundManager,
    RoundState,
)
from trivia.scoring.manager import ScoreManager
from trivia.storage.database import Database


class FakeProvider(QuestionProvider):
    """A provider that returns predictable questions."""

    def __init__(self, questions=None):
        self._questions = questions or [
            TriviaQuestion(
                question=f"Question {i}?",
                correct_answer=f"Answer {i}",
                difficulty=Difficulty.EASY,
                category="Test",
                source="Fake",
            )
            for i in range(50)
        ]
        self._index = 0

    @property
    def name(self):
        return "Fake"

    async def fetch_questions(self, amount=10, category=None, difficulty=None):
        batch = self._questions[self._index:self._index + amount]
        self._index += amount
        return batch

    async def get_categories(self):
        return ["Test"]


@pytest.fixture
def setup():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    pool = QuestionPool([FakeProvider()])
    score_mgr = ScoreManager(db)
    mgr = RoundManager(pool, score_mgr, db)

    messages = []
    blocks_messages = []

    def post_msg(channel, text):
        messages.append({"channel": channel, "text": text})

    def post_blocks(channel, blocks, text):
        blocks_messages.append({"channel": channel, "blocks": blocks, "text": text})

    mgr.set_message_handlers(post_msg, post_blocks)

    yield mgr, db, messages, blocks_messages, path

    os.unlink(path)


class TestRoundManager:
    @pytest.mark.asyncio
    async def test_start_round(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        error = await mgr.start_round("C001", "U001", 3)
        assert error is None
        r = mgr.get_round("C001")
        assert r is not None
        assert r.total_questions == 3
        assert r.state == RoundState.WAITING_FOR_ANSWER

    @pytest.mark.asyncio
    async def test_cannot_start_while_active(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        await mgr.start_round("C001", "U001", 3)
        error = await mgr.start_round("C001", "U002", 5)
        assert error is not None
        assert "already in progress" in error

    @pytest.mark.asyncio
    async def test_frozen_user_cannot_start(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        db.set_freeze("U001", "C001", 10)
        error = await mgr.start_round("C001", "U001", 5)
        assert error is not None
        assert "frozen" in error.lower()

    @pytest.mark.asyncio
    async def test_correct_answer_advances(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        await mgr.start_round("C001", "U001", 3)
        r = mgr.get_round("C001")
        assert r.current_question_index == 1

        # Answer correctly (use sleep(0) to let async tasks settle without
        # actually waiting the full between-questions delay)
        await mgr.handle_message("C001", "U001", "Answer 0")
        assert any("got it" in m["text"].lower() for m in msgs)

    @pytest.mark.asyncio
    async def test_wrong_answer_no_advance(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        await mgr.start_round("C001", "U001", 3)
        initial_index = mgr.get_round("C001").current_question_index

        await mgr.handle_message("C001", "U001", "totally wrong")
        assert mgr.get_round("C001").current_question_index == initial_index

    @pytest.mark.asyncio
    async def test_skip_vote_needs_two(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        await mgr.start_round("C001", "U001", 3)

        result = await mgr.handle_skip_vote("C001", "U001")
        assert result is not None
        assert "1 more" in result

    @pytest.mark.asyncio
    async def test_skip_vote_passes_with_two(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        await mgr.start_round("C001", "U001", 3)

        await mgr.handle_skip_vote("C001", "U001")
        result = await mgr.handle_skip_vote("C001", "U002")
        assert result is None
        assert any("skipped" in m["text"].lower() for m in msgs)

    @pytest.mark.asyncio
    async def test_skip_no_active_question(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        result = await mgr.handle_skip_vote("C001", "U001")
        assert "no active" in result.lower()

    @pytest.mark.asyncio
    async def test_resume_not_paused(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        error = await mgr.resume_round("C001")
        assert error is not None

    @pytest.mark.asyncio
    async def test_clamps_round_size(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        await mgr.start_round("C001", "U001", 100)
        r = mgr.get_round("C001")
        assert r.total_questions == 50

    @pytest.mark.asyncio
    async def test_solo_play_detection(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        # Create a round big enough that solo play threshold can trigger
        r = ChannelRound(
            channel_id="C001",
            total_questions=20,
            started_by="U001",
            state=RoundState.WAITING_FOR_ANSWER,
        )
        # Pre-fill recent_answerers with SOLO_PLAY_THRESHOLD - 1 entries
        r.recent_answerers = ["U001"] * (SOLO_PLAY_THRESHOLD - 1)
        result = mgr._check_solo_play(r, "U001")
        # Not triggered yet (need one more)
        assert result is False

        r.recent_answerers.append("U001")
        result = mgr._check_solo_play(r, "U001")
        assert result is True
        assert r.state == RoundState.IDLE

    @pytest.mark.asyncio
    async def test_solo_play_not_triggered_with_variety(self, setup):
        mgr, db, msgs, blk_msgs, _ = setup
        r = ChannelRound(
            channel_id="C001",
            total_questions=20,
            started_by="U001",
            state=RoundState.WAITING_FOR_ANSWER,
        )
        r.recent_answerers = ["U001", "U002", "U001", "U001", "U001"]
        result = mgr._check_solo_play(r, "U001")
        assert result is False
