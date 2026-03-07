from __future__ import annotations

import os
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional

from trivia.matching.fuzzy import AnswerCheck, check_answer
from trivia.questions.base import QuestionPool, TriviaQuestion
from trivia.scoring.manager import ScoreManager
from trivia.storage.database import Database

if TYPE_CHECKING:
    from slack_bolt import App

logger = logging.getLogger(__name__)

QUESTION_TIMEOUT_SECONDS = 60
BETWEEN_QUESTIONS_SECONDS = 2
CONSECUTIVE_SKIP_LIMIT = 3 if os.getenv("ENVIRONMENT") == "production" else 10
SOLO_PLAY_THRESHOLD = 5
FREEZE_DURATION_MINUTES = 10
SKIP_VOTES_REQUIRED = 2 if os.getenv("ENVIRONMENT") == "production" else 1


def _resolve_letter_choice(text: str, choices: list[str]) -> str | None:
    """Return the choice text for a bare letter answer (A/B/C/D), or None.

    Accepts only a single letter with optional surrounding whitespace; any other
    content (e.g. "A I think so") returns None so it falls through to fuzzy matching.
    """
    stripped = text.strip().upper()
    if len(stripped) == 1 and stripped in "ABCD":
        idx = ord(stripped) - ord("A")
        if idx < len(choices):
            return choices[idx]
    return None


class RoundState(Enum):
    IDLE = "idle"
    WAITING_FOR_ANSWER = "waiting_for_answer"
    BETWEEN_QUESTIONS = "between_questions"
    PAUSED = "paused"


@dataclass
class RoundScoreEntry:
    user_id: str
    points: int = 0
    correct: int = 0


@dataclass
class ChannelRound:
    channel_id: str
    total_questions: int
    started_by: str
    pool: QuestionPool
    state: RoundState = RoundState.IDLE
    current_question_index: int = 0
    current_question: Optional[TriviaQuestion] = None
    current_question_db_id: Optional[int] = None
    current_question_asked_at: float = 0.0
    consecutive_auto_skips: int = 0
    recent_answerers: list[str] = field(default_factory=list)
    skip_voters: set[str] = field(default_factory=set)
    round_scores: dict[str, RoundScoreEntry] = field(default_factory=dict)
    _timeout_task: Optional[asyncio.Task] = None
    # Guard against concurrent answer processing
    _processing_answer: bool = False


class RoundManager:
    """Manages trivia rounds across all channels."""

    def __init__(
        self,
        question_pool: QuestionPool,
        score_manager: ScoreManager,
        db: Database,
    ):
        self._pool = question_pool
        self._scores = score_manager
        self._db = db
        self._rounds: dict[str, ChannelRound] = {}
        self._post_message: Optional[Callable] = None
        self._post_blocks: Optional[Callable] = None

    def set_message_handlers(
        self,
        post_message: Callable,
        post_blocks: Callable,
    ) -> None:
        self._post_message = post_message
        self._post_blocks = post_blocks

    def get_round(self, channel_id: str) -> Optional[ChannelRound]:
        return self._rounds.get(channel_id)

    def is_active(self, channel_id: str) -> bool:
        r = self._rounds.get(channel_id)
        return r is not None and r.state != RoundState.IDLE

    async def start_round(
        self, channel_id: str, user_id: str, num_questions: int = 10,
        pool: Optional[QuestionPool] = None,
    ) -> str | None:
        """Start a new round. Returns error message or None on success."""
        freeze = None
        if os.getenv("ENVIRONMENT") == "production":
            freeze = self._db.get_freeze(user_id, channel_id)
        if freeze:
            remaining = int((freeze.expires_at.timestamp() - time.time()) / 60) + 1
            logger.info("User %s is frozen in %s for %d more minute(s)", user_id, channel_id, remaining)
            return (
                f"You're frozen for solo play! "
                f"Try again in ~{remaining} minute{'s' if remaining != 1 else ''}. "
                f"Another player can start a round."
            )

        existing = self._rounds.get(channel_id)
        if existing and existing.state != RoundState.IDLE:
            if existing.state == RoundState.PAUSED:
                return "There's a paused round in this channel. Use `resume` to continue it."
            return "A round is already in progress in this channel!"

        num_questions = max(1, min(num_questions, 50))
        logger.info("Starting round of %d questions in %s (started by %s)", num_questions, channel_id, user_id)

        round_ = ChannelRound(
            channel_id=channel_id,
            total_questions=num_questions,
            started_by=user_id,
            pool=pool if pool is not None else self._pool,
            state=RoundState.BETWEEN_QUESTIONS,
        )
        self._rounds[channel_id] = round_

        await self._post_msg(
            channel_id,
            f":game_die: *Trivia round started!* {num_questions} questions coming up. "
            f"Type your answers directly in the channel!",
        )

        await self._serve_next_question(channel_id)
        return None

    async def resume_round(self, channel_id: str) -> str | None:
        """Resume a paused round. Returns error message or None on success."""
        round_ = self._rounds.get(channel_id)
        if not round_ or round_.state == RoundState.IDLE:
            return "No round to resume. Use `start` to begin a new one."
        if round_.state != RoundState.PAUSED:
            return "The round isn't paused!"

        logger.info("Resuming paused round in %s", channel_id)
        round_.consecutive_auto_skips = 0
        await self._post_msg(channel_id, ":arrow_forward: *Round resumed!* Here comes the next question...")
        await self._serve_next_question(channel_id)
        return None

    async def handle_message(
        self, channel_id: str, user_id: str, text: str
    ) -> None:
        """Process a channel message as a potential answer."""
        round_ = self._rounds.get(channel_id)
        if not round_:
            logger.debug("handle_message: no round for channel %s", channel_id)
            return
        if round_.state != RoundState.WAITING_FOR_ANSWER:
            logger.debug(
                "handle_message: channel %s state is %s, not WAITING_FOR_ANSWER",
                channel_id, round_.state.value,
            )
            return
        if not round_.current_question:
            logger.debug("handle_message: no current question in %s", channel_id)
            return
        if round_._processing_answer:
            logger.debug("handle_message: already processing an answer in %s", channel_id)
            return

        # For multiple-choice questions, resolve a bare letter (A/B/C/D) to its
        # full choice text before fuzzy matching.
        question = round_.current_question
        answer_text = text
        letter_choice = None
        if question.is_multiple_choice:
            letter_choice = _resolve_letter_choice(text, question.choices)
            if letter_choice is not None:
                answer_text = letter_choice
                logger.debug(
                    "Letter answer '%s' resolved to '%s' in %s",
                    text.strip().upper(), answer_text, channel_id,
                )

        logger.debug(
            "Checking answer '%s' against correct answer '%s' in %s",
            answer_text, question.correct_answer, channel_id,
        )

        result = check_answer(
            answer_text,
            question.correct_answer,
            question.alternate_answers,
        )

        # If the user typed a letter but it wasn't the right one, give a clean
        # "wrong" response without the "close, try again" prompt.
        if letter_choice is not None and not result.is_correct:
            logger.debug("Letter answer was wrong, no 'close' feedback")
            return

        logger.debug(
            "Answer check result: %s (score=%.1f) for '%s'",
            result.result.value, result.score, answer_text,
        )

        if result.is_correct:
            round_._processing_answer = True
            try:
                await self._handle_correct_answer(round_, user_id, result)
            finally:
                round_._processing_answer = False
        elif result.is_close:
            await self._post_msg(
                channel_id,
                f"<@{user_id}> That's close! Try again :eyes:",
            )

    async def handle_skip_vote(self, channel_id: str, user_id: str) -> str | None:
        """Register a skip vote. Returns feedback string or None (skip triggered)."""
        round_ = self._rounds.get(channel_id)
        if not round_ or round_.state != RoundState.WAITING_FOR_ANSWER:
            return "No active question to skip."

        round_.skip_voters.add(user_id)
        votes = len(round_.skip_voters)
        logger.info("Skip vote in %s: %d/%d votes", channel_id, votes, SKIP_VOTES_REQUIRED)

        if votes >= SKIP_VOTES_REQUIRED:
            self._cancel_timeout(round_)
            round_.consecutive_auto_skips = 0
            answer = round_.current_question.correct_answer if round_.current_question else "?"
            await self._post_msg(
                channel_id,
                f":fast_forward: *Skipped!* The answer was: *{answer.strip()}*",
            )
            await self._advance_round(channel_id)
            return None
        else:
            remaining = SKIP_VOTES_REQUIRED - votes
            return f"Skip vote registered! Need {remaining} more vote{'s' if remaining != 1 else ''} to skip."

    async def _serve_next_question(self, channel_id: str) -> None:
        round_ = self._rounds.get(channel_id)
        if not round_:
            return

        if round_.current_question_index >= round_.total_questions:
            await self._end_round(channel_id)
            return

        try:
            question = await round_.pool.get_question()
        except Exception:
            logger.exception("Failed to fetch question for %s", channel_id)
            await self._post_msg(
                channel_id,
                ":warning: Couldn't fetch a trivia question. Round ending early.",
            )
            await self._end_round(channel_id)
            return

        round_.current_question = question
        round_.current_question_index += 1
        round_.skip_voters = set()
        round_.current_question_asked_at = time.time()
        round_._processing_answer = False

        logger.info(
            "Serving question %d/%d in %s: '%s' (answer: '%s')",
            round_.current_question_index, round_.total_questions,
            channel_id, question.question, question.correct_answer,
        )

        try:
            q_id = self._db.record_question(
                channel_id=channel_id,
                question_text=question.question,
                correct_answer=question.correct_answer,
                difficulty=question.difficulty.value,
                source=question.source,
                points=question.points or question.difficulty.points,
            )
            round_.current_question_db_id = q_id
        except Exception:
            logger.exception("Failed to record question to DB")
            round_.current_question_db_id = None

        round_.state = RoundState.WAITING_FOR_ANSWER

        from trivia.ui.blocks import build_question_blocks

        blocks = build_question_blocks(
            question=question,
            question_num=round_.current_question_index,
            total_questions=round_.total_questions,
        )
        await self._post_blocks_msg(
            channel_id,
            blocks,
            f"Question {round_.current_question_index}/{round_.total_questions}",
        )

        self._schedule_timeout(channel_id)

    async def _handle_correct_answer(
        self, round_: ChannelRound, user_id: str, result: AnswerCheck
    ) -> None:
        self._cancel_timeout(round_)
        question = round_.current_question
        if not question:
            return

        base_points = question.points or question.difficulty.points
        try:
            total_points, speed_bonus = self._scores.award_points(
                user_id=user_id,
                channel_id=round_.channel_id,
                base_points=base_points,
                question_id=round_.current_question_db_id or 0,
                question_asked_at=round_.current_question_asked_at,
            )
        except Exception:
            logger.exception("Failed to award points to %s in %s", user_id, round_.channel_id)
            total_points = base_points
            speed_bonus = False

        entry = round_.round_scores.setdefault(
            user_id, RoundScoreEntry(user_id=user_id)
        )
        entry.points += total_points
        entry.correct += 1

        round_.consecutive_auto_skips = 0
        round_.recent_answerers.append(user_id)

        logger.info(
            "Correct answer by %s in %s: +%d pts (speed=%s)",
            user_id, round_.channel_id, total_points, speed_bonus,
        )

        bonus_text = " :zap: *Speed bonus!*" if speed_bonus else ""
        await self._post_msg(
            round_.channel_id,
            f":white_check_mark: <@{user_id}> got it! The answer is *{question.correct_answer.strip()}*. "
            f"+{total_points} point{'s' if total_points != 1 else ''}{bonus_text}",
        )

        if self._check_solo_play(round_, user_id):
            return

        await self._advance_round(round_.channel_id)

    def _check_solo_play(self, round_: ChannelRound, user_id: str) -> bool:
        if len(round_.recent_answerers) < SOLO_PLAY_THRESHOLD:
            return False

        last_n = round_.recent_answerers[-SOLO_PLAY_THRESHOLD:]
        if all(uid == user_id for uid in last_n):
            logger.warning(
                "Solo-play detected in %s: %s answered last %d questions",
                round_.channel_id, user_id, SOLO_PLAY_THRESHOLD,
            )
            self._db.set_freeze(user_id, round_.channel_id, FREEZE_DURATION_MINUTES)
            round_.state = RoundState.IDLE

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._post_msg(
                        round_.channel_id,
                        f":ice_cube: *Solo play detected!* <@{user_id}> answered the last "
                        f"{SOLO_PLAY_THRESHOLD} questions alone. Round frozen.\n"
                        f"<@{user_id}> is locked out for {FREEZE_DURATION_MINUTES} minutes. "
                        f"Another player can start a new round.",
                    )
                )
            except RuntimeError:
                logger.exception("Could not post solo-play message")
            return True
        return False

    async def _advance_round(self, channel_id: str) -> None:
        round_ = self._rounds.get(channel_id)
        if not round_:
            return

        if round_.current_question_index >= round_.total_questions:
            await self._end_round(channel_id)
            return

        round_.state = RoundState.BETWEEN_QUESTIONS
        logger.debug("Between questions in %s, waiting %ds", channel_id, BETWEEN_QUESTIONS_SECONDS)
        await asyncio.sleep(BETWEEN_QUESTIONS_SECONDS)
        await self._serve_next_question(channel_id)

    async def _handle_timeout(self, channel_id: str) -> None:
        round_ = self._rounds.get(channel_id)
        if not round_ or round_.state != RoundState.WAITING_FOR_ANSWER:
            return

        answer = round_.current_question.correct_answer if round_.current_question else "?"
        round_.consecutive_auto_skips += 1
        logger.info(
            "Question timed out in %s (consecutive auto-skips: %d)",
            channel_id, round_.consecutive_auto_skips,
        )

        await self._post_msg(
            channel_id,
            f":hourglass: *Time's up!* The answer was: *{answer.strip()}*",
        )

        if round_.current_question_index >= round_.total_questions:
            await self._end_round(channel_id)
            return

        if round_.consecutive_auto_skips >= CONSECUTIVE_SKIP_LIMIT:
            round_.state = RoundState.PAUSED
            remaining = round_.total_questions - round_.current_question_index
            await self._post_msg(
                channel_id,
                f":pause: *Round paused* — {CONSECUTIVE_SKIP_LIMIT} questions in a row went unanswered. "
                f"{remaining} question{'s' if remaining != 1 else ''} remaining. "
                f"Mention me with `resume` to continue!",
            )
            return

        await self._advance_round(channel_id)

    async def _end_round(self, channel_id: str) -> None:
        round_ = self._rounds.get(channel_id)
        if not round_:
            return

        logger.info("Round ended in %s", channel_id)
        from trivia.ui.blocks import build_round_summary_blocks

        blocks = build_round_summary_blocks(round_)
        await self._post_blocks_msg(channel_id, blocks, "Round complete!")
        round_.state = RoundState.IDLE

    def _schedule_timeout(self, channel_id: str) -> None:
        round_ = self._rounds.get(channel_id)
        if not round_:
            return

        self._cancel_timeout(round_)

        async def _timeout():
            await asyncio.sleep(QUESTION_TIMEOUT_SECONDS)
            await self._handle_timeout(channel_id)

        loop = asyncio.get_running_loop()
        round_._timeout_task = loop.create_task(_timeout())

    def _cancel_timeout(self, round_: ChannelRound) -> None:
        if round_._timeout_task and not round_._timeout_task.done():
            round_._timeout_task.cancel()
            round_._timeout_task = None

    async def _post_msg(self, channel_id: str, text: str) -> None:
        if self._post_message:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._post_message, channel_id, text)
            except Exception:
                logger.exception("Failed to post message to %s", channel_id)

    async def _post_blocks_msg(
        self, channel_id: str, blocks: list, fallback_text: str
    ) -> None:
        if self._post_blocks:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._post_blocks, channel_id, blocks, fallback_text)
            except Exception:
                logger.exception("Failed to post blocks to %s", channel_id)
