from __future__ import annotations

from trivia.storage.database import Database


def build_app_home_view(db: Database, user_id: str) -> dict:
    """Build the App Home tab view with global leaderboard and user stats."""
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

    return {
        "type": "home",
        "blocks": blocks,
    }
