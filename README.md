# Slack Trivia Bot

A round-based trivia bot for Slack that fetches questions from multiple free APIs, supports fuzzy answer matching, per-channel scoring, and anti-solo-play fairness.

## Features

- **Round-based gameplay**: Start a round of N questions (default 10) that auto-advance
- **Multiple trivia sources**: Open Trivia DB, The Trivia API, jService (Jeopardy)
- **Fuzzy answer matching**: Multi-layered matching with normalization, token-based fuzzy scoring, type-specific rules, and alias support
- **Per-channel scoring**: Leaderboards tracked independently per channel
- **Anti-solo-play**: Detects when a single user dominates and freezes them for 10 minutes
- **Auto-pause**: If 3 questions in a row go unanswered, the round pauses
- **App Home**: Persistent leaderboard in the bot's home tab

## Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Enable **Socket Mode** and generate an App-Level Token with `connections:write` scope
3. Under **OAuth & Permissions**, add these bot token scopes:
   - `app_mentions:read`
   - `channels:history`
   - `chat:write`
   - `users:read`
4. Under **Event Subscriptions**, subscribe to:
   - `app_mention`
   - `message.channels`
5. Install the app to your workspace

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your tokens
```

### 3. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Run

```bash
python app.py
```

---

## Docker Deployment

### Build locally

```bash
docker build -t slack-trivia-bot .
```

### Run locally

```bash
docker run -d --restart unless-stopped \
  --env-file .env \
  -v trivia-data:/data \
  slack-trivia-bot
```

The SQLite database is stored in the `/data` volume so scores persist across container restarts.

### Push to GitHub Container Registry (ghcr.io)

1. Generate a GitHub Personal Access Token with the `write:packages` scope at
   [github.com/settings/tokens/new](https://github.com/settings/tokens/new)

2. Export the token and run the push script:

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
./scripts/push-ghcr.sh <your-github-username>
# Optional: pass a specific tag as the second argument (default: latest)
./scripts/push-ghcr.sh <your-github-username> v1.0.0
```

3. Pull and run from any machine:

```bash
docker run -d --restart unless-stopped \
  --env-file .env \
  -v trivia-data:/data \
  ghcr.io/<your-github-username>/slack-trivia-bot:latest
```

> **Note**: ghcr.io packages are private by default. To make the image public, go to
> your GitHub profile → Packages → slack-trivia-bot → Package settings → Change visibility.

## Commands

All commands are triggered by @mentioning the bot:

| Command | Description |
|---|---|
| `@trivia start [n]` | Start a round of n questions (default 10) |
| `@trivia resume` | Resume a paused round |
| `@trivia scores` | Show channel leaderboard (top 10) |
| `@trivia skip` | Vote to skip the current question (needs 2 votes) |
| `@trivia stats [@user]` | Show stats for a user (or yourself) |
| `@trivia categories` | List available question categories |
| `@trivia help` | Show available commands |

During an active question, simply type your answer in the channel -- no @mention needed.

## Scoring

- Easy questions: 1 point
- Medium questions: 2 points
- Hard questions: 3 points
- Speed bonus: +1 point if answered within 10 seconds

## Fairness

- If the same user answers 5 consecutive questions, the round freezes and that user is locked out from starting new rounds for 10 minutes
- If 3 questions in a row go unanswered (auto-skipped after 60s), the round pauses until someone resumes it
# slack-trivia-bot
