from __future__ import annotations

from trivia.questions import registry as source_registry
from trivia.storage.database import Database


def _source_config_blocks(
    db: Database,
    channel_ids: list[str],
    saved_channel: str | None = None,
    current_selections: dict[str, list[str]] | None = None,
) -> list[dict]:
    """``current_selections``: channel_id → list of selected source names reflecting
    the user's live UI state (used to preserve unsaved edits when re-publishing)."""
    """Build interactive source-selection blocks for each channel.

    ``saved_channel``: if set, that channel's Save button shows a confirmation
    state instead of the default label.
    """
    if not channel_ids:
        return []

    blocks: list[dict] = [
        {"type": "divider"},
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":satellite: Question Sources"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Configure which question sources are active per channel, then click *Save*.",
            },
        },
    ]

    all_names = source_registry.ALL_SOURCE_NAMES
    options = [
        {
            "text": {"type": "plain_text", "text": source_registry.display_name(n)},
            "value": n,
        }
        for n in all_names
    ]

    for channel_id in channel_ids:
        just_saved = channel_id == saved_channel
        if current_selections and channel_id in current_selections:
            # Use the live UI state so unsaved selections survive the re-publish
            enabled_names = current_selections[channel_id]
        else:
            active = db.get_channel_sources(channel_id)
            enabled_names = active if active is not None else all_names
        initial_options = [o for o in options if o["value"] in enabled_names]

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*<#{channel_id}>*"},
        })
        # Checkboxes and Save button must be in SEPARATE blocks so that Slack
        # includes the checkbox state in body["view"]["state"]["values"] when
        # the button is clicked (elements in the same block don't appear there).
        blocks.append({
            "type": "actions",
            "block_id": f"sources_checkboxes_{channel_id}",
            "elements": [
                {
                    "type": "checkboxes",
                    "action_id": f"select_sources_{channel_id}",
                    "options": options,
                    "initial_options": initial_options,
                },
            ],
        })
        blocks.append({
            "type": "actions",
            "block_id": f"sources_save_{channel_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": ":white_check_mark: Saved!" if just_saved else "Save",
                    },
                    "style": "primary",
                    "action_id": f"save_sources_{channel_id}",
                },
            ],
        })
        if just_saved:
            active_after = db.get_channel_sources(channel_id)
            names_display = ", ".join(
                source_registry.display_name(n)
                for n in (active_after if active_after is not None else all_names)
            )
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: Sources updated: *{names_display}*",
                    }
                ],
            })

    return blocks


def build_app_home_view(
    db: Database,
    user_id: str,
    saved_channel: str | None = None,
    current_selections: dict[str, list[str]] | None = None,
) -> dict:
    """Build the App Home tab view with global leaderboard, user stats, and source config."""
    all_scores = db.get_all_channel_scores()
    user_global = db.get_user_global_stats(user_id)

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":game_die: Trivia Bot"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Welcome to Trivia Bot! Mention me in any channel with "
                    "`start` to begin a round, or `help` to see all commands."
                ),
            },
        },
        {"type": "divider"},
    ]

    # User's own stats
    if user_global:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Your Stats"},
        })
        blocks.append({
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f":trophy: *Total Score*\n{user_global.total_score}",
                },
                {
                    "type": "mrkdwn",
                    "text": f":white_check_mark: *Correct Answers*\n{user_global.correct_answers}",
                },
            ],
        })
        blocks.append({"type": "divider"})

    # Per-channel leaderboards
    if all_scores:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Channel Leaderboards"},
        })

        for channel_id, scores in all_scores.items():
            top_5 = scores[:5]
            MEDALS = {0: ":first_place_medal:", 1: ":second_place_medal:", 2: ":third_place_medal:"}
            lines = []
            for i, score in enumerate(top_5):
                medal = MEDALS.get(i, f"{i + 1}.")
                lines.append(
                    f"{medal} <@{score.user_id}> — *{score.total_score}* pts"
                )

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*<#{channel_id}>*\n" + "\n".join(lines),
                },
            })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "No trivia has been played yet! Mention me in a channel with `start` to begin.",
            },
        })

    # Source config — show for every channel that has a leaderboard
    channel_ids = list(all_scores.keys())
    blocks.extend(_source_config_blocks(
        db, channel_ids,
        saved_channel=saved_channel,
        current_selections=current_selections,
    ))

    return {
        "type": "home",
        "blocks": blocks,
    }
