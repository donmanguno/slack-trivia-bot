"""Tests for question providers (integration tests requiring network)."""

import pytest

from trivia.questions.base import Difficulty, QuestionPool, TriviaQuestion
from trivia.questions.opentdb import OpenTDBProvider
from trivia.questions.trivia_api import TriviaAPIProvider
from trivia.questions.jservice import JServiceProvider


class TestTriviaQuestion:
    def test_default_points(self):
        q = TriviaQuestion(
            question="Test?",
            correct_answer="Yes",
            difficulty=Difficulty.EASY,
            category="Test",
            source="Test",
        )
        assert q.points == 1

    def test_custom_points(self):
        q = TriviaQuestion(
            question="Test?",
            correct_answer="Yes",
            difficulty=Difficulty.EASY,
            category="Test",
            source="Test",
            points=5,
        )
        assert q.points == 5

    def test_difficulty_points(self):
        assert Difficulty.EASY.points == 1
        assert Difficulty.MEDIUM.points == 2
        assert Difficulty.HARD.points == 3


@pytest.mark.network
class TestOpenTDBProvider:
    @pytest.fixture
    def provider(self):
        return OpenTDBProvider()

    @pytest.mark.asyncio
    async def test_fetch_questions(self, provider):
        questions = await provider.fetch_questions(amount=5)
        assert len(questions) > 0
        for q in questions:
            assert q.question
            assert q.correct_answer
            assert q.source == "Open Trivia DB"

    @pytest.mark.asyncio
    async def test_get_categories(self, provider):
        categories = await provider.get_categories()
        assert len(categories) > 0


@pytest.mark.network
class TestTriviaAPIProvider:
    @pytest.fixture
    def provider(self):
        return TriviaAPIProvider()

    @pytest.mark.asyncio
    async def test_fetch_questions(self, provider):
        questions = await provider.fetch_questions(amount=5)
        assert len(questions) > 0
        for q in questions:
            assert q.question
            assert q.correct_answer
            assert q.source == "The Trivia API"

    @pytest.mark.asyncio
    async def test_get_categories(self, provider):
        categories = await provider.get_categories()
        assert len(categories) > 0


@pytest.mark.network
class TestJServiceProvider:
    @pytest.fixture
    def provider(self):
        return JServiceProvider()

    @pytest.mark.asyncio
    async def test_fetch_questions(self, provider):
        questions = await provider.fetch_questions(amount=5)
        assert len(questions) > 0
        for q in questions:
            assert q.question
            assert q.correct_answer
            assert q.source == "jService (Jeopardy)"


@pytest.mark.network
class TestQuestionPool:
    @pytest.mark.asyncio
    async def test_get_question_from_pool(self):
        pool = QuestionPool([OpenTDBProvider(), TriviaAPIProvider()])
        question = await pool.get_question()
        assert question.question
        assert question.correct_answer
