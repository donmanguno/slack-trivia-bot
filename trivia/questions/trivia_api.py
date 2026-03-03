from __future__ import annotations

from typing import Optional

import httpx

from .base import Difficulty, QuestionProvider, TriviaQuestion

TRIVIA_API_BASE = "https://the-trivia-api.com/v2"

DIFFICULTY_MAP = {
    "easy": Difficulty.EASY,
    "medium": Difficulty.MEDIUM,
    "hard": Difficulty.HARD,
}


class TriviaAPIProvider(QuestionProvider):
    """Fetches questions from the-trivia-api.com."""

    @property
    def name(self) -> str:
        return "The Trivia API"

    async def fetch_questions(
        self,
        amount: int = 10,
        category: Optional[str] = None,
        difficulty: Optional[Difficulty] = None,
    ) -> list[TriviaQuestion]:
        async with httpx.AsyncClient(timeout=10) as client:
            params: dict = {"limit": min(amount, 50)}
            if difficulty:
                params["difficulties"] = difficulty.value
            if category:
                params["categories"] = category.lower().replace(" ", "_").replace("&", "and")

            resp = await client.get(f"{TRIVIA_API_BASE}/questions", params=params)
            resp.raise_for_status()
            data = resp.json()

            return [self._parse(q) for q in data]

    async def get_categories(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{TRIVIA_API_BASE}/categories")
            resp.raise_for_status()
            data = resp.json()
            return sorted(data.keys()) if isinstance(data, dict) else []

    @staticmethod
    def _parse(raw: dict) -> TriviaQuestion:
        import random
        difficulty = DIFFICULTY_MAP.get(
            raw.get("difficulty", "medium"), Difficulty.MEDIUM
        )
        correct = raw["correctAnswer"]
        incorrect = raw.get("incorrectAnswers", [])
        choices = [correct] + incorrect
        random.shuffle(choices)

        return TriviaQuestion(
            question=raw["question"]["text"],
            correct_answer=correct,
            difficulty=difficulty,
            category=raw.get("category", "General"),
            source="The Trivia API",
            choices=choices,
        )
