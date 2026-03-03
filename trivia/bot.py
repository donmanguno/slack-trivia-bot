from __future__ import annotations

import asyncio
import logging
import os
import re
from concurrent.futures import Future
from threading import Thread
from typing import Optional

from slack_bolt import App

from trivia.questions import registry as source_registry
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
# Fallback pool (all sources) used when no per-channel config is set
_default_pool = source_registry.build_pool()
score_manager = ScoreManager(db)
round_manager = RoundManager(_default_pool, score_manager, db)


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
            elif command.startswith("sources"):
                _handle_sources(command, channel_id, say)
            elif command in ("help", ""):
                _handle_help(say)
            else:
                say(
                    "I don't recognize that command. "
                    "Try mentioning me with `help` to see available commands."
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

    @app.action(re.compile(r"^select_sources_"))
    def handle_checkbox_change(ack, action, body):
        """On checkbox toggle: revert any 'Saved!' button back to 'Save',
        preserving the user's current (unsaved) selections."""
        ack()
        channel_id = action["action_id"][len("select_sources_"):]
        current = [opt["value"] for opt in action.get("selected_options", [])]
        user_id = body["user"]["id"]
        try:
            view = build_app_home_view(
                db, user_id,
                current_selections={channel_id: current},
            )
            app.client.views_publish(user_id=user_id, view=view)
        except Exception:
            logger.exception("Failed to update App Home on checkbox change")

    @app.action(re.compile(r"^save_sources_"))
    def handle_save_sources(ack, action, body):
        """Handle source-selection saves from the App Home checkboxes."""
        ack()
        # action_id format: "save_sources_{channel_id}"
        channel_id = action["action_id"][len("save_sources_"):]

        # For App Home views, state lives in body["view"]["state"]["values"],
        # not body["state"]["values"] (which is always empty for home tabs).
        state_values = (
            body.get("view", {}).get("state", {}).get("values", {})
        )

        block_id = f"sources_checkboxes_{channel_id}"
        checkbox_action_id = f"select_sources_{channel_id}"
        checkbox_state = (
            state_values
                .get(block_id, {})
                .get(checkbox_action_id, {})
        )
        selected = [
            opt["value"]
            for opt in checkbox_state.get("selected_options", [])
        ]

        db.set_channel_sources(channel_id, selected)
        logger.info("Updated sources for %s: %s", channel_id, selected or "default (all)")
        user_id = body["user"]["id"]
        try:
            view = build_app_home_view(db, user_id, saved_channel=channel_id)
            app.client.views_publish(user_id=user_id, view=view)
        except Exception:
            logger.exception("Failed to refresh App Home after source save")

    def _handle_start(command: str, channel_id: str, user_id: str, say):
        parts = command.split()
        num_questions = 10
        if len(parts) >= 2:
            try:
                num_questions = int(parts[1])
            except ValueError:
                say("Please specify a valid number of questions, e.g. `start 15`")
                return

        source_names = db.get_channel_sources(channel_id)
        pool = source_registry.build_pool(source_names)
        logger.info(
            "Starting round in %s with sources: %s",
            channel_id, source_names or "default",
        )
        error = _run_async(
            round_manager.start_round(channel_id, user_id, num_questions, pool=pool)
        )
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
        categories = _run_async(_default_pool.get_categories())
        blocks = build_categories_blocks(categories)
        say(blocks=blocks, text="Categories")

    def _handle_sources(command: str, channel_id: str, say):
        parts = command.split()
        all_names = source_registry.ALL_SOURCE_NAMES

        if len(parts) == 1:
            # Show current config
            active = db.get_channel_sources(channel_id)
            lines = []
            for name in all_names:
                enabled = active is None or name in active
                icon = ":white_check_mark:" if enabled else ":white_square:"
                lines.append(f"{icon} *{source_registry.display_name(name)}* (`{name}`)")
            status = "_(using defaults — all enabled)_" if active is None else ""
            say(
                f":satellite: *Question sources for this channel* {status}\n"
                + "\n".join(lines)
                + f"\n\nTo change: `@trivia sources <name1> <name2> ...` "
                f"or `@trivia sources default` to reset.\n"
                f"Available: `{'` `'.join(all_names)}`"
            )
        elif len(parts) >= 2 and parts[1] == "default":
            db.set_channel_sources(channel_id, [])
            say(":white_check_mark: Reset to default sources (all enabled).")
        else:
            requested = parts[1:]
            unknown = [n for n in requested if n not in all_names]
            if unknown:
                say(
                    f":x: Unknown source(s): `{'` `'.join(unknown)}`\n"
                    f"Available: `{'` `'.join(all_names)}`"
                )
                return
            db.set_channel_sources(channel_id, requested)
            names_display = ", ".join(
                f"*{source_registry.display_name(n)}*" for n in requested
            )
            say(f":white_check_mark: Sources for this channel set to: {names_display}")

    def _handle_help(say):
        blocks = build_help_blocks()
        say(blocks=blocks, text="Trivia Bot Help")
