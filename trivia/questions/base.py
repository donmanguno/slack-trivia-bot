from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    @property
    def points(self) -> int:
        return {
            Difficulty.EASY: 1,
            Difficulty.MEDIUM: 2,
            Difficulty.HARD: 3,
        }[self]


@dataclass
class TriviaQuestion:
    question: str
    correct_answer: str
    difficulty: Difficulty
    category: str
    source: str
    # Other acceptable correct answers (for fuzzy matching)
    alternate_answers: list[str] = field(default_factory=list)
    # Shuffled answer choices for multiple-choice display (correct + incorrect)
    choices: list[str] = field(default_factory=list)
    points: Optional[int] = None

    def __post_init__(self):
        if self.points is None:
            self.points = self.difficulty.points

    @property
    def is_multiple_choice(self) -> bool:
        return len(self.choices) > 1


class QuestionProvider(ABC):
    """Abstract base class for trivia question sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def fetch_questions(
        self,
        amount: int = 10,
        category: Optional[str] = None,
        difficulty: Optional[Difficulty] = None,
    ) -> list[TriviaQuestion]:
        ...

    @abstractmethod
    async def get_categories(self) -> list[str]:
        ...


class QuestionPool:
    """Aggregates multiple providers and serves questions from them."""

    def __init__(self, providers: list[QuestionProvider]):
        self._providers = providers
        self._buffer: list[TriviaQuestion] = []

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    async def get_question(
        self,
        category: Optional[str] = None,
        difficulty: Optional[Difficulty] = None,
    ) -> TriviaQuestion:
        if not self._buffer:
            await self._refill(category=category, difficulty=difficulty)

        if not self._buffer:
            raise RuntimeError("No trivia questions available from any provider")

        return self._buffer.pop()

    async def get_categories(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for provider in self._providers:
            try:
                result[provider.name] = await provider.get_categories()
            except Exception:
                result[provider.name] = []
        return result

    async def _refill(
        self,
        category: Optional[str] = None,
        difficulty: Optional[Difficulty] = None,
    ) -> None:
        for provider in random.sample(self._providers, len(self._providers)):
            try:
                questions = await provider.fetch_questions(
                    amount=10, category=category, difficulty=difficulty
                )
                if questions:
                    random.shuffle(questions)
                    self._buffer.extend(questions)
                    return
            except Exception:
                continue
