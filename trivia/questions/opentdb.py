from __future__ import annotations

import html
from typing import Optional

import httpx

from .base import Difficulty, QuestionProvider, TriviaQuestion

OPENTDB_BASE = "https://opentdb.com"

DIFFICULTY_MAP = {
    "easy": Difficulty.EASY,
    "medium": Difficulty.MEDIUM,
    "hard": Difficulty.HARD,
}


class OpenTDBProvider(QuestionProvider):
    """Fetches questions from Open Trivia Database (opentdb.com)."""

    def __init__(self):
        self._session_token: Optional[str] = None
        self._categories: Optional[dict[str, int]] = None

    @property
    def name(self) -> str:
        return "Open Trivia DB"

    async def _ensure_token(self, client: httpx.AsyncClient) -> None:
        if self._session_token:
            return
        resp = await client.get(
            f"{OPENTDB_BASE}/api_token.php", params={"command": "request"}
        )
        data = resp.json()
        if data.get("response_code") == 0:
            self._session_token = data["token"]

    async def _load_categories(self, client: httpx.AsyncClient) -> None:
        if self._categories is not None:
            return
        resp = await client.get(f"{OPENTDB_BASE}/api_category.php")
        data = resp.json()
        self._categories = {
            cat["name"]: cat["id"] for cat in data.get("trivia_categories", [])
        }

    async def fetch_questions(
        self,
        amount: int = 10,
        category: Optional[str] = None,
        difficulty: Optional[Difficulty] = None,
    ) -> list[TriviaQuestion]:
        async with httpx.AsyncClient(timeout=10) as client:
            await self._ensure_token(client)
            await self._load_categories(client)

            params: dict = {"amount": min(amount, 50), "type": "multiple"}
            if self._session_token:
                params["token"] = self._session_token
            if difficulty:
                params["difficulty"] = difficulty.value
            if category and self._categories:
                cat_id = self._categories.get(category)
                if cat_id:
                    params["category"] = cat_id

            resp = await client.get(f"{OPENTDB_BASE}/api.php", params=params)
            data = resp.json()

            if data.get("response_code") == 4:
                # Token exhausted, reset it
                self._session_token = None
                await self._ensure_token(client)
                params["token"] = self._session_token
                resp = await client.get(f"{OPENTDB_BASE}/api.php", params=params)
                data = resp.json()

            if data.get("response_code") != 0:
                return []

            return [self._parse(q) for q in data.get("results", [])]

    async def get_categories(self) -> list[str]:
        if self._categories is None:
            async with httpx.AsyncClient(timeout=10) as client:
                await self._load_categories(client)
        return sorted(self._categories.keys()) if self._categories else []

    @staticmethod
    def _parse(raw: dict) -> TriviaQuestion:
        import random
        correct = html.unescape(raw["correct_answer"])
        incorrect = [html.unescape(a) for a in raw.get("incorrect_answers", [])]
        choices = [correct] + incorrect
        random.shuffle(choices)

        return TriviaQuestion(
            question=html.unescape(raw["question"]),
            correct_answer=correct,
            difficulty=DIFFICULTY_MAP.get(raw["difficulty"], Difficulty.MEDIUM),
            category=html.unescape(raw["category"]),
            source="Open Trivia DB",
            choices=choices,
        )
