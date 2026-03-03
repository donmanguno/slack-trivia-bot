from __future__ import annotations

import asyncio
import logging
import os
import re
from concurrent.futures import Future
from threading import Thread
from typing import Optional

from slack_bolt import App

from trivia.questions.base import QuestionPool
from trivia.questions.jservice import JServiceProvider
from trivia.questions.opentdb import OpenTDBProvider
from trivia.questions.trivia_api import TriviaAPIProvider
from trivia.round import RoundManager
from trivia.scoring.manager import ScoreManager
from trivia.storage.database import Database
from trivia.ui.blocks import (
    build_categories_blocks,
    build_help_blocks,
    build_leaderboard_blocks,
    build_user_stats_blocks,
)
from trivia.ui.home import build_app_home_view

logger = logging.getLogger(__name__)

_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        thread = Thread(target=_loop.run_forever, daemon=True, name="trivia-async-loop")
        thread.start()
        logger.debug("Started background asyncio event loop")
    return _loop


def _run_async(coro, timeout: int = 120):
    """Submit a coroutine to the background loop and block until complete."""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _fire_async(coro) -> None:
    """Submit a coroutine to the background loop without waiting for the result.
    Used for answer processing so the Bolt handler thread is freed immediately."""
    loop = _get_loop()
    asyncio.run_coroutine_threadsafe(coro, loop)


db = Database()
question_pool = QuestionPool([
    OpenTDBProvider(),
    TriviaAPIProvider(),
    JServiceProvider(),
])
score_manager = ScoreManager(db)
round_manager = RoundManager(question_pool, score_manager, db)


def _parse_command(text: str, bot_user_id: str) -> str:
    """Extract the command portion from an @mention message."""
    cleaned = re.sub(rf"<@{bot_user_id}>", "", text).strip()
    return cleaned.lower()


def register_handlers(app: App) -> None:
    """Register all Slack event handlers on the Bolt app."""

    def post_message(channel_id: str, text: str) -> None:
        logger.debug("Posting message to %s: %s", channel_id, text[:80])
        app.client.chat_postMessage(channel=channel_id, text=text)

    def post_blocks(channel_id: str, blocks: list, fallback_text: str) -> None:
        logger.debug("Posting blocks to %s (%s)", channel_id, fallback_text)
        app.client.chat_postMessage(
            channel=channel_id, blocks=blocks, text=fallback_text
        )

    round_manager.set_message_handlers(post_message, post_blocks)

    @app.event("app_home_opened")
    def handle_app_home_opened(event, client):
        user_id = event.get("user", "")
        if event.get("tab") == "home":
            try:
                view = build_app_home_view(db, user_id)
                client.views_publish(user_id=user_id, view=view)
            except Exception:
                logger.exception("Failed to publish app home for %s", user_id)

    @app.event("app_mention")
    def handle_mention(event, say, context):
        bot_user_id = context.get("bot_user_id", "")
        text = event.get("text", "")
        channel_id = event.get("channel", "")
        user_id = event.get("user", "")

        command = _parse_command(text, bot_user_id)
        logger.info("app_mention in %s from %s: command='%s'", channel_id, user_id, command)

        try:
            if command.startswith("start"):
                _handle_start(command, channel_id, user_id, say)
            elif command == "resume":
                _handle_resume(channel_id, say)
            elif command in ("scores", "leaderboard"):
                _handle_scores(channel_id, say)
            elif command == "skip":
                _handle_skip(channel_id, user_id, say)
            elif command.startswith("stats"):
                _handle_stats(text, channel_id, user_id, say)
            elif command == "categories":
                _handle_categories(say)
            elif command in ("help", ""):
                _handle_help(say)
            else:
                say(
                    f"I don't recognize that command. "
                    f"Try mentioning me with `help` to see available commands."
                )
        except Exception:
            logger.exception("Error handling mention in %s", channel_id)
            say("Something went wrong. Check the bot logs.")

    @app.event("message")
    def handle_message(event, context):
        logger.debug("message event received: type=%s subtype=%s channel=%s",
                     event.get("type"), event.get("subtype"), event.get("channel"))

        # Ignore edits, joins, bot posts, etc.
        if event.get("subtype"):
            logger.debug("message ignored: has subtype '%s'", event.get("subtype"))
            return
        if event.get("bot_id"):
            logger.debug("message ignored: from bot_id '%s'", event.get("bot_id"))
            return

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        text = event.get("text", "")

        if not text or not channel_id or not user_id:
            logger.debug("message ignored: missing field (text=%r channel=%r user=%r)",
                         bool(text), bool(channel_id), bool(user_id))
            return

        # Skip @mentions -- handled by app_mention
        bot_user_id = context.get("bot_user_id", "")
        if bot_user_id and f"<@{bot_user_id}>" in text:
            logger.debug("message ignored: is an @mention")
            return

        is_active = round_manager.is_active(channel_id)
        logger.debug(
            "message from %s in %s: '%s' | round active=%s",
            user_id, channel_id, text[:60], is_active,
        )

        if is_active:
            # Fire-and-forget: do not block the Bolt thread
            # (correct answers trigger a 10s sleep before next question)
            _fire_async(round_manager.handle_message(channel_id, user_id, text))

    def _handle_start(command: str, channel_id: str, user_id: str, say):
        parts = command.split()
        num_questions = 10
        if len(parts) >= 2:
            try:
                num_questions = int(parts[1])
            except ValueError:
                say("Please specify a valid number of questions, e.g. `start 15`")
                return

        error = _run_async(round_manager.start_round(channel_id, user_id, num_questions))
        if error:
            say(error)

    def _handle_resume(channel_id: str, say):
        error = _run_async(round_manager.resume_round(channel_id))
        if error:
            say(error)

    def _handle_scores(channel_id: str, say):
        scores = score_manager.get_leaderboard(channel_id)
        blocks = build_leaderboard_blocks(scores, channel_id)
        say(blocks=blocks, text="Leaderboard")

    def _handle_skip(channel_id: str, user_id: str, say):
        result = _run_async(round_manager.handle_skip_vote(channel_id, user_id))
        if result:
            say(result)

    def _handle_stats(raw_text: str, channel_id: str, user_id: str, say):
        target_user = user_id
        mentions = re.findall(r"<@(U[A-Z0-9]+)>", raw_text)
        for m in mentions:
            if m != user_id:
                target_user = m
                break

        channel_score = score_manager.get_user_stats(target_user, channel_id)
        global_score = score_manager.get_user_global_stats(target_user)
        blocks = build_user_stats_blocks(target_user, channel_score, global_score)
        say(blocks=blocks, text=f"Stats for <@{target_user}>")

    def _handle_categories(say):
        categories = _run_async(question_pool.get_categories())
        blocks = build_categories_blocks(categories)
        say(blocks=blocks, text="Categories")

    def _handle_help(say):
        blocks = build_help_blocks()
        say(blocks=blocks, text="Trivia Bot Help")
