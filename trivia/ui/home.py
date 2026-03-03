from __future__ import annotations

from trivia.questions import registry as source_registry
from trivia.storage.database import Database


# ---------------------------------------------------------------------------
# Source configuration blocks (reused from channel-filtered view)
# ---------------------------------------------------------------------------

def _source_config_blocks(
    db: Database,
    channel_id: str,
    saved_channel: str | None = None,
    current_selections: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Checkboxes + Save button for a single channel's source config.

    ``saved_channel``: show confirmation state on the Save button.
    ``current_selections``: live UI state to preserve unsaved edits across re-publishes.
    """
    all_names = source_registry.ALL_SOURCE_NAMES
    options = [
        {
            "text": {"type": "plain_text", "text": source_registry.display_name(n)},
            "value": n,
        }
        for n in all_names
    ]

    just_saved = channel_id == saved_channel
    if current_selections and channel_id in current_selections:
        enabled_names = current_selections[channel_id]
    else:
        active = db.get_channel_sources(channel_id)
        enabled_names = active if active is not None else all_names

    initial_options = [o for o in options if o["value"] in enabled_names]

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":satellite: Question Sources"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Select which question sources are active for this channel, then click *Save*.",
            },
        },
        # Checkboxes and Save button must be in SEPARATE blocks so that Slack
        # includes the checkbox state in body["view"]["state"]["values"] when
        # the button is clicked (elements in the same block don't appear there).
        {
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
        },
        {
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
        },
    ]

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


# ---------------------------------------------------------------------------
# Leaderboard block for a single channel
# ---------------------------------------------------------------------------

def _leaderboard_blocks(db: Database, channel_id: str, limit: int = 10) -> list[dict]:
    from trivia.storage.models import UserScore

    scores = db.get_leaderboard(channel_id, limit=limit)
    if not scores:
        return [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No games played in this channel yet._"},
        }]

    MEDALS = {0: ":first_place_medal:", 1: ":second_place_medal:", 2: ":third_place_medal:"}
    lines = []
    for i, score in enumerate(scores):
        medal = MEDALS.get(i, f"{i + 1}.")
        lines.append(f"{medal} <@{score.user_id}> — *{score.total_score}* pts ({score.correct_answers} correct)")

    return [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    }]


# ---------------------------------------------------------------------------
# Main view builder
# ---------------------------------------------------------------------------

def build_app_home_view(
    db: Database,
    user_id: str,
    selected_channel: str | None = None,
    admin_users: set[str] | None = None,
    saved_channel: str | None = None,
    current_selections: dict[str, list[str]] | None = None,
) -> dict:
    """Build the App Home tab view.

    If ``selected_channel`` is set the view shows that channel's leaderboard
    and source configuration. Otherwise it shows a prompt to pick a channel.
    """
    user_global = db.get_user_global_stats(user_id)
    is_admin = bool(admin_users and user_id in admin_users)

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":game_die: Trivia Bot"},
        },
    ]

    # User global stats
    if user_global:
        blocks.append({
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f":trophy: *Your total score*\n{user_global.total_score} pts",
                },
                {
                    "type": "mrkdwn",
                    "text": f":white_check_mark: *Correct answers*\n{user_global.correct_answers}",
                },
            ],
        })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Mention me in any channel with `start` to begin a trivia round!",
            },
        })

    blocks.append({"type": "divider"})

    # Channel selector
    channel_picker: dict = {
        "type": "actions",
        "block_id": "home_channel_picker",
        "elements": [
            {
                "type": "conversations_select",
                "action_id": "select_home_channel",
                "placeholder": {"type": "plain_text", "text": "Select a channel…"},
                "filter": {"include": ["public", "private"], "exclude_bot_users": True},
            }
        ],
    }
    if selected_channel:
        channel_picker["elements"][0]["initial_conversation"] = selected_channel
    blocks.append(channel_picker)

    if not selected_channel:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_Select a channel above to view its leaderboard and configure question sources._",
            },
        })
        return {"type": "home", "blocks": blocks}

    # --- Channel-specific content ---
    blocks.append({"type": "divider"})

    # Leaderboard
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f":trophy: *Leaderboard* — <#{selected_channel}>"},
    })
    blocks.extend(_leaderboard_blocks(db, selected_channel))

    blocks.append({"type": "divider"})

    # Source configuration
    blocks.extend(_source_config_blocks(
        db, selected_channel,
        saved_channel=saved_channel,
        current_selections=current_selections,
    ))

    # Admin: remove channel data
    if is_admin:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":warning: *Admin* — permanently delete all scores, history, and config for this channel.",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Remove channel data"},
                "style": "danger",
                "action_id": f"remove_channel_{selected_channel}",
                "confirm": {
                    "title": {"type": "plain_text", "text": "Remove channel data?"},
                    "text": {
                        "type": "mrkdwn",
                        "text": f"This will permanently delete all scores, question history, and source config for <#{selected_channel}>. This cannot be undone.",
                    },
                    "confirm": {"type": "plain_text", "text": "Yes, delete"},
                    "deny": {"type": "plain_text", "text": "Cancel"},
                    "style": "danger",
                },
            },
        })

    return {"type": "home", "blocks": blocks}
