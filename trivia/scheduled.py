from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Callable, Optional

from trivia.questions.base import QuestionPool
from trivia.storage.database import Database
from trivia.ui.blocks import build_leaderboard_blocks

logger = logging.getLogger(__name__)

DEFAULT_DAILY_HOUR = 9
DEFAULT_WEEKLY_DAY = 0  # Monday


class ScheduledFeatures:
    """Handles daily challenge questions and weekly recap summaries."""

    def __init__(
        self,
        question_pool: QuestionPool,
        db: Database,
        post_message: Callable,
        post_blocks: Callable,
    ):
        self._pool = question_pool
        self._db = db
        self._post_message = post_message
        self._post_blocks = post_blocks
        self._daily_channels: set[str] = set()
        self._weekly_channels: set[str] = set()
        self._daily_hour: int = DEFAULT_DAILY_HOUR
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def enable_daily(self, channel_id: str, hour: int = DEFAULT_DAILY_HOUR) -> None:
        self._daily_channels.add(channel_id)
        self._daily_hour = hour

    def disable_daily(self, channel_id: str) -> None:
        self._daily_channels.discard(channel_id)

    def enable_weekly(self, channel_id: str) -> None:
        self._weekly_channels.add(channel_id)

    def disable_weekly(self, channel_id: str) -> None:
        self._weekly_channels.discard(channel_id)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        thread = Thread(target=self._run_loop, daemon=True)
        thread.start()

    def stop(self) -> None:
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._scheduler())

    async def _scheduler(self) -> None:
        last_daily: Optional[str] = None
        last_weekly: Optional[str] = None

        while self._running:
            now = datetime.utcnow()
            today_key = now.strftime("%Y-%m-%d")
            week_key = now.strftime("%Y-W%W")

            if (
                now.hour == self._daily_hour
                and last_daily != today_key
                and self._daily_channels
            ):
                last_daily = today_key
                await self._post_daily_challenge()

            if (
                now.weekday() == DEFAULT_WEEKLY_DAY
                and now.hour == self._daily_hour
                and last_weekly != week_key
                and self._weekly_channels
            ):
                last_weekly = week_key
                await self._post_weekly_recap()

            await asyncio.sleep(60)

    async def _post_daily_challenge(self) -> None:
        try:
            question = await self._pool.get_question()
        except RuntimeError:
            return

        points = question.points or question.difficulty.points

        from trivia.ui.blocks import build_question_blocks, DIFFICULTY_EMOJI

        diff_emoji = DIFFICULTY_EMOJI.get(question.difficulty, ":white_circle:")

        text = (
            f":calendar: *Daily Trivia Challenge!*\n\n"
            f"*{question.question}*\n\n"
            f"{diff_emoji} {question.difficulty.value.title()} | "
            f":trophy: {points} pt{'s' if points != 1 else ''}\n"
            f"_Reply with your answer!_\n\n"
            f"||Answer: {question.correct_answer}||"
        )

        for channel_id in self._daily_channels:
            try:
                self._post_message(channel_id, text)
                self._db.record_question(
                    channel_id=channel_id,
                    question_text=question.question,
                    correct_answer=question.correct_answer,
                    difficulty=question.difficulty.value,
                    source=question.source,
                    points=points,
                )
            except Exception:
                logger.exception(f"Failed to post daily challenge to {channel_id}")

    async def _post_weekly_recap(self) -> None:
        for channel_id in self._weekly_channels:
            try:
                scores = self._db.get_leaderboard(channel_id, limit=5)
                if not scores:
                    continue

                blocks = [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": ":bar_chart: Weekly Trivia Recap"},
                    },
                ]
                blocks.extend(build_leaderboard_blocks(scores, channel_id))

                self._post_blocks(channel_id, blocks, "Weekly Trivia Recap")
            except Exception:
                logger.exception(f"Failed to post weekly recap to {channel_id}")
