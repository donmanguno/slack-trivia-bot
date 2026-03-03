from __future__ import annotations

from typing import Optional

import httpx

from .base import Difficulty, QuestionProvider, TriviaQuestion

JSERVICE_BASE = "https://jservice.io/api"


def _value_to_difficulty(value: Optional[int]) -> Difficulty:
    if value is None:
        return Difficulty.MEDIUM
    if value <= 200:
        return Difficulty.EASY
    if value <= 600:
        return Difficulty.MEDIUM
    return Difficulty.HARD


def _value_to_points(value: Optional[int]) -> int:
    if value is None:
        return 2
    if value <= 200:
        return 1
    if value <= 400:
        return 2
    return 3


class JServiceProvider(QuestionProvider):
    """Fetches Jeopardy-style questions from jService.io."""

    @property
    def name(self) -> str:
        return "jService (Jeopardy)"

    async def fetch_questions(
        self,
        amount: int = 10,
        category: Optional[str] = None,
        difficulty: Optional[Difficulty] = None,
    ) -> list[TriviaQuestion]:
        async with httpx.AsyncClient(timeout=10) as client:
            params: dict = {"count": min(amount, 100)}

            resp = await client.get(f"{JSERVICE_BASE}/random", params=params)
            resp.raise_for_status()
            data = resp.json()

            questions = []
            for raw in data:
                q = self._parse(raw)
                if q and q.question.strip() and q.correct_answer.strip():
                    if difficulty is None or q.difficulty == difficulty:
                        questions.append(q)

            return questions

    async def get_categories(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{JSERVICE_BASE}/categories", params={"count": 50}
            )
            resp.raise_for_status()
            data = resp.json()
            return [cat["title"].title() for cat in data if cat.get("title")]

    @staticmethod
    def _parse(raw: dict) -> Optional[TriviaQuestion]:
        answer = raw.get("answer", "")
        question_text = raw.get("question", "")
        if not answer or not question_text:
            return None

        # Clean HTML tags from jService answers
        import re

        answer = re.sub(r"<[^>]+>", "", answer).strip()
        if not answer:
            return None

        value = raw.get("value")
        category_data = raw.get("category", {})
        category_title = category_data.get("title", "General") if category_data else "General"

        return TriviaQuestion(
            question=question_text,
            correct_answer=answer,
            difficulty=_value_to_difficulty(value),
            category=category_title.title(),
            source="jService (Jeopardy)",
            points=_value_to_points(value),
        )
