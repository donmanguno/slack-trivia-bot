# Slack Trivia Bot

A round-based trivia bot for Slack. Questions are drawn from multiple sources, answers are fuzzy-matched, scores are tracked per channel, and a fairness system prevents solo-play farming.

## Features

- **Round-based gameplay** — Start a round of N questions (default 10, max 50) that auto-advance without any prompting
- **Multiple question sources** — Open Trivia DB, The Trivia API, and a local Jeopardy! dataset (216k questions)
- **Multiple-choice support** — Questions with choices display A/B/C/D options; answer with just the letter or the full text
- **Fuzzy answer matching** — Multi-layered: normalization, token-based fuzzy scoring, type-specific rules (years, numbers, names), and alias support
- **Per-channel scoring** — Leaderboards tracked independently per channel
- **Configurable question sources** — Per-channel source selection via command or App Home UI
- **Anti-solo-play** — If one user answers 5 consecutive questions, the round ends and they are locked out from starting new rounds for 10 minutes
- **Auto-pause** — If 3 questions in a row go unanswered (timeout after 60s each), the round pauses until resumed
- **App Home** — Persistent leaderboard and interactive source configuration per channel
- **Skip voting** — 2 votes required to skip a question

---

## Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**
2. Paste the contents of `manifest.json` and save
3. Under **Basic Information** → **App-Level Tokens**, generate a token with the `connections:write` scope — this is your `SLACK_APP_TOKEN`
4. Under **OAuth & Permissions** → **Install to Workspace** — this generates your `SLACK_BOT_TOKEN`
5. Invite the bot to any channel with `/invite @Trivia Bot`

> The manifest configures all required scopes, event subscriptions, Socket Mode, and App Home automatically.

### 2. Configure Environment

```bash
cp .env.example .env
# Fill in SLACK_BOT_TOKEN and SLACK_APP_TOKEN
```

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | Bot token from OAuth & Permissions (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Yes | App-level token for Socket Mode (`xapp-...`) |
| `TRIVIA_DEBUG` | No | Set to `1` for verbose debug logging |
| `DB_PATH` | No | Path to SQLite database file (default: `trivia.db` in project root, `/data/trivia.db` in Docker) |

### 3. Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

---

## Docker

### Run with Docker Compose (recommended)

```bash
docker compose up -d
```

Scores are persisted in a named Docker volume (`trivia-data`) mapped to `/data/trivia.db` inside the container.

### Build and run manually

```bash
docker build -t slack-trivia-bot .

docker run -d --restart unless-stopped \
  --env-file .env \
  -v trivia-data:/data \
  slack-trivia-bot
```

### Publish to GitHub Container Registry

Images are built and pushed automatically on each GitHub release via the included Actions workflow (`.github/workflows/release.yml`). No local login required.

To push manually:

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
./scripts/push-ghcr.sh <your-github-username>
./scripts/push-ghcr.sh <your-github-username> v1.2.0   # specific tag
```

To pull and run on a server:

```bash
docker run -d --restart unless-stopped \
  --env-file .env \
  -v trivia-data:/data \
  ghcr.io/<your-github-username>/slack-trivia-bot:latest
```

> ghcr.io packages are private by default. To make the image public: GitHub profile → Packages → slack-trivia-bot → Package settings → Change visibility.

---

## Commands

All commands are triggered by @mentioning the bot. During an active question, type your answer directly in the channel — no @mention needed.

| Command | Description |
|---|---|
| `@trivia start [n]` | Start a round of `n` questions (default 10, max 50) |
| `@trivia resume` | Resume a paused round |
| `@trivia skip` | Vote to skip the current question (2 votes required) |
| `@trivia scores` | Show the channel leaderboard (top 10) |
| `@trivia stats [@user]` | Show stats for yourself or another user |
| `@trivia sources` | Show active question sources for this channel |
| `@trivia sources <name> [name...]` | Set sources for this channel (e.g. `@trivia sources opentdb jeopardy`) |
| `@trivia sources default` | Reset to all sources enabled |
| `@trivia categories` | List available question categories |
| `@trivia help` | Show available commands |

---

## Question Sources

| Key | Name | Type |
|---|---|---|
| `opentdb` | Open Trivia DB | API |
| `trivia_api` | The Trivia API | API |
| `jeopardy` | Jeopardy! (local) | Local dataset (216k questions) |

Sources can be configured per channel. The local Jeopardy! dataset (`data/jeopardy.json`) is the most reliable source since it requires no network calls.

To add a new JSON question file, define a `JsonSchema` in `trivia/questions/json_file.py` and register it in `trivia/questions/registry.py`.

---

## Scoring

| Difficulty | Base points |
|---|---|
| Easy | 1 |
| Medium | 2 |
| Hard | 3 |

**Speed bonus**: +1 point for answering within 10 seconds.

Jeopardy! clue values ($200–$2000) are mapped to difficulty tiers automatically.

---

## Fairness Rules

- **Solo-play freeze**: If one user answers 5 consecutive questions uninterrupted, the round ends immediately and that user cannot start a new round in that channel for 10 minutes. Any other user can start a round normally.
- **Auto-pause**: If 3 questions in a row time out with no answer (60 seconds each), the round pauses. Use `@trivia resume` to continue.

---

## App Home

Open the bot's App Home tab to see:

- Your global stats (total score and correct answers)
- Per-channel leaderboards (top 5 per channel)
- Per-channel question source configuration with checkboxes — select sources and click **Save**
