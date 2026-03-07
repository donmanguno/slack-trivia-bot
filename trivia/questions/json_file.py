from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from trivia.questions import util

from .base import Difficulty, QuestionProvider, TriviaQuestion

logger = logging.getLogger(__name__)


@dataclass
class JsonSchema:
    """Describes how to map a JSON record to a TriviaQuestion.

    Provide callables for difficulty_fn, points_fn, question_transform, and
    answer_transform to adapt any JSON format without subclassing.
    """

    name: str
    display_name: str
    question_field: str
    answer_field: str
    category_field: str = "category"
    difficulty_fn: Callable[[dict[str, Any]], Difficulty] = field(
        default_factory=lambda: (lambda _: Difficulty.MEDIUM)
    )
    points_fn: Callable[[dict[str, Any]], Optional[int]] = field(
        default_factory=lambda: (lambda _: None)
    )
    question_transform: Callable[[str], str] = field(default_factory=lambda: str.strip)
    answer_transform: Callable[[str], str] = field(default_factory=lambda: str.strip)


# ---------------------------------------------------------------------------
# Jeopardy! schema helpers
# ---------------------------------------------------------------------------

def _jeopardy_dollar_value(record: dict[str, Any]) -> int:
    """Parse the '$200' style value field, normalised to single-Jeopardy scale."""
    value_str = str(record.get("value") or "0")
    try:
        value = int(value_str.replace("$", "").replace(",", ""))
    except ValueError:
        return 0
    # Double Jeopardy! clues are worth 2x; normalise so difficulty stays consistent
    if "Double" in str(record.get("round", "")):
        value = value // 2
    return value


def _jeopardy_difficulty(record: dict[str, Any]) -> Difficulty:
    v = _jeopardy_dollar_value(record)
    if v <= 200:
        return Difficulty.EASY
    if v <= 600:
        return Difficulty.MEDIUM
    return Difficulty.HARD


def _jeopardy_points(record: dict[str, Any]) -> Optional[int]:
    return _jeopardy_difficulty(record).points


def _strip_jeopardy_quotes(text: str) -> str:
    """Questions in this dataset are wrapped in single quotes."""
    text = text.strip()
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        text = text[1:-1].strip()
    return text


JEOPARDY_SCHEMA = JsonSchema(
    name="jeopardy",
    display_name="Jeopardy! (local)",
    question_field="question",
    answer_field="answer",
    category_field="category",
    difficulty_fn=_jeopardy_difficulty,
    points_fn=_jeopardy_points,
    question_transform=_strip_jeopardy_quotes,
)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class JsonFileProvider(QuestionProvider):
    """Loads trivia questions from a local JSON array file.

    The file is loaded once on first use and kept in memory. For very large
    files this is intentional — random sampling from a full in-memory list is
    fast and avoids repeated I/O during a round.
    """

    def __init__(self, path: Path | str, schema: JsonSchema) -> None:
        self._path = Path(path)
        self._schema = schema
        self._records: Optional[list[dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # QuestionProvider interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._schema.display_name

    async def fetch_questions(
        self,
        amount: int = 10,
        category: Optional[str] = None,
        difficulty: Optional[Difficulty] = None,
    ) -> list[TriviaQuestion]:
        pool = await self._load_async()

        if category:
            cat_lower = category.lower()
            pool = [
                r for r in pool
                if cat_lower in str(r.get(self._schema.category_field, "")).lower()
            ]
        if difficulty:
            pool = [r for r in pool if self._schema.difficulty_fn(r) == difficulty]

        if not pool:
            return []

        # Sample generously then parse until we have enough valid questions
        sample = random.sample(pool, min(amount * 5, len(pool)))
        questions: list[TriviaQuestion] = []
        for raw in sample:
            q = self._parse(raw)
            if q:
                q.question = util.html_to_markdown(q.question)
                questions.append(q)
            if len(questions) >= amount:
                break
        return questions

    async def get_categories(self) -> list[str]:
        field_name = self._schema.category_field
        seen: set[str] = set()
        cats: list[str] = []
        for r in await self._load_async():
            cat = str(r.get(field_name, "") or "").strip().title()
            if cat and cat not in seen:
                seen.add(cat)
                cats.append(cat)
        return sorted(cats)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_sync(self) -> list[dict[str, Any]]:
        """Synchronous load — must be called in a thread, not the event loop."""
        if self._records is None:
            logger.info("Loading JSON question source: %s", self._path)
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                raise ValueError(f"Expected a JSON array in {self._path}")
            self._records = data
            logger.info("Loaded %d records from %s", len(self._records), self._path.name)
        return self._records

    async def _load_async(self) -> list[dict[str, Any]]:
        """Load the file without blocking the asyncio event loop.

        After the first call the data is cached in memory, so subsequent calls
        return immediately without dispatching to a thread.
        """
        if self._records is not None:
            return self._records
        return await asyncio.to_thread(self._load_sync)

    def _parse(self, raw: dict[str, Any]) -> Optional[TriviaQuestion]:
        s = self._schema
        question_text = s.question_transform(str(raw.get(s.question_field, "") or ""))
        answer_text = s.answer_transform(str(raw.get(s.answer_field, "") or ""))

        if not question_text or not answer_text:
            return None

        # Strip residual HTML tags (e.g. <i>, <b>) that appear in some datasets
        if "<" in answer_text:
            answer_text = re.sub(r"<[^>]+>", "", answer_text).strip()
        if not answer_text:
            return None

        category = str(raw.get(s.category_field, "General") or "General").strip().title()
        difficulty = s.difficulty_fn(raw)
        points = s.points_fn(raw)

        return TriviaQuestion(
            question=question_text,
            correct_answer=answer_text,
            difficulty=difficulty,
            category=category,
            source=s.display_name,
            points=points,
        )
