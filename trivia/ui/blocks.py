from __future__ import annotations

from typing import TYPE_CHECKING

from trivia.questions.base import Difficulty, TriviaQuestion

if TYPE_CHECKING:
    from trivia.round import ChannelRound
    from trivia.storage.models import UserScore

DIFFICULTY_EMOJI = {
    Difficulty.EASY: ":large_green_circle:",
    Difficulty.MEDIUM: ":large_yellow_circle:",
    Difficulty.HARD: ":red_circle:",
}


CHOICE_LETTERS = ["A", "B", "C", "D", "E"]


def build_question_blocks(
    question: TriviaQuestion,
    question_num: int,
    total_questions: int,
) -> list[dict]:
    diff_emoji = DIFFICULTY_EMOJI.get(question.difficulty, ":white_circle:")
    points = question.points or question.difficulty.points
    points_text = f"{points} pt{'s' if points != 1 else ''}"
    speed_text = " (+1 speed bonus)"

    question_text = f"*{question.question}*"

    if question.is_multiple_choice:
        choice_lines = "\n".join(
            f"{CHOICE_LETTERS[i]}) {choice}"
            for i, choice in enumerate(question.choices)
        )
        question_text += f"\n\n{choice_lines}"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Question {question_num}/{total_questions}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": question_text,
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"{diff_emoji} {question.difficulty.value.title()} "
                        f"| :trophy: {points_text}{speed_text} "
                        f"| :file_folder: {question.category} "
                        f"| :books: {question.source}"
                    ),
                }
            ],
        },
        {"type": "divider"},
    ]
    return blocks


def build_leaderboard_blocks(
    scores: list[UserScore], channel_id: str
) -> list[dict]:
    if not scores:
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "No scores yet in this channel! Start a trivia round to get going.",
                },
            }
        ]

    MEDALS = {1: ":first_place_medal:", 2: ":second_place_medal:", 3: ":third_place_medal:"}

    lines = []
    for i, score in enumerate(scores, 1):
        medal = MEDALS.get(i, f"*{i}.*")
        lines.append(
            f"{medal} <@{score.user_id}> — "
            f"*{score.total_score}* pts "
            f"({score.correct_answers} correct)"
        )

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Leaderboard"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        },
        {"type": "divider"},
    ]


def build_user_stats_blocks(
    user_id: str,
    channel_score: UserScore | None,
    global_score: UserScore | None,
) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Stats for player"},
        },
    ]

    if channel_score:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*This channel:*\n"
                    f":trophy: *{channel_score.total_score}* points\n"
                    f":white_check_mark: *{channel_score.correct_answers}* correct answers"
                ),
            },
        })

    if global_score:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*All channels:*\n"
                    f":trophy: *{global_score.total_score}* points\n"
                    f":white_check_mark: *{global_score.correct_answers}* correct answers"
                ),
            },
        })

    if not channel_score and not global_score:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<@{user_id}> hasn't played any trivia yet!",
            },
        })

    return blocks


def build_round_summary_blocks(round_: ChannelRound) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Round Complete!"},
        },
    ]

    if round_.round_scores:
        sorted_scores = sorted(
            round_.round_scores.values(),
            key=lambda e: e.points,
            reverse=True,
        )
        MEDALS = {0: ":first_place_medal:", 1: ":second_place_medal:", 2: ":third_place_medal:"}
        lines = []
        for i, entry in enumerate(sorted_scores):
            medal = MEDALS.get(i, f"*{i + 1}.*")
            lines.append(
                f"{medal} <@{entry.user_id}> — *{entry.points}* pts ({entry.correct} correct)"
            )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "No one scored this round! :cricket:"},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Round of {round_.total_questions} questions | Started by <@{round_.started_by}>",
            }
        ],
    })

    return blocks


def build_categories_blocks(
    categories: dict[str, list[str]],
) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Available Categories"},
        },
    ]

    for provider, cats in categories.items():
        if cats:
            cat_list = ", ".join(cats[:20])
            if len(cats) > 20:
                cat_list += f" ... and {len(cats) - 20} more"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{provider}:*\n{cat_list}",
                },
            })

    if not any(categories.values()):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "No categories available right now."},
        })

    return blocks


def build_help_blocks() -> list[dict]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Trivia Bot Commands"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Starting & managing rounds:*\n"
                    "• `start [n]` — Start a round of n questions (default 10)\n"
                    "• `resume` — Resume a paused round\n"
                    "• `skip` — Vote to skip the current question (needs 2 votes)\n\n"
                    "*Scores & stats:*\n"
                    "• `scores` — Show the channel leaderboard\n"
                    "• `stats [@user]` — Show stats for a user (or yourself)\n\n"
                    "*Info:*\n"
                    "• `categories` — List available question categories\n"
                    "• `help` — Show this message\n\n"
                    "*Answering:*\n"
                    "Just type your answer in the channel during an active question — no @mention needed!"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        ":bulb: Scoring: Easy=1pt, Medium=2pt, Hard=3pt. "
                        "+1 speed bonus if answered within 10 seconds."
                    ),
                }
            ],
        },
    ]
