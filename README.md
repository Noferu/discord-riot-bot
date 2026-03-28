# Shaconnard — Discord LoL Tracker Bot

A Discord bot for private servers that tracks friends' League of Legends games using the Riot Games API, with an AI persona powered by Gemini.

> ⚠️ **Work in progress.** Structure and features may change at any time.

---

## What it does

- Detects when a tracked player **starts or ends a game** by polling the Riot spectator API every 60 seconds
- Posts rich **Components V2 messages** in a designated channel on game start and end (with champion, KDA, LP diff, mode)
- Tracks **ranked LP gains and losses** per game
- Assigns **Discord roles** automatically based on activity and streaks (in game, active, win streak, loss streak)
- Responds to mentions with an **AI persona** (Shaco, demonic jester) powered by Gemini 2.0 Flash, with full context:
  - Last 10 channel messages
  - Reply chain (up to 10 levels)
  - Recent ranked history for any player mentioned (by Discord mention, `GameName#TAG`, or exact game name)

---

## Commands

| Command | Description |
|---|---|
| `!link GameName#TAG` | Link a Riot account to your Discord |
| `!linkfor @member GameName#TAG` | Link a Riot account to another member |
| `!unlink GameName#TAG` | Unlink a specific Riot account |
| `!unlink` | Unlink all your Riot accounts |
| `!list` | Show your own linked accounts |
| `!listall` | Show all tracked accounts on the server |
| `!hello` | Say hi |
| `@Shaconnard <message>` | Talk to the AI |

---

## Project structure

```
discord-riot-bot/
├── bot.py              # Entry point — events, commands, poll loop, AI context builder
├── config.py           # Environment variables and constants
├── players.json        # Persistent player data (auto-generated)
├── requirements.txt
├── .env
├── .gitignore
└── core/
    ├── __init__.py
    ├── ai.py           # Gemini API wrapper and system prompt
    ├── riot.py         # Riot API calls (spectator, match history, LP, PUUID)
    └── layouts.py      # Discord Components V2 GameLayout
```

---

## Setup

Clone the repository:

```bash
git clone https://github.com/Noferu/discord-riot-bot.git
cd discord-riot-bot
```

Create and activate a virtual environment:

```bash
python -m venv venv
venv\Scripts\activate   # Windows
source venv/bin/activate  # macOS/Linux
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file at the project root:

```env
DISCORD_TOKEN=your_discord_token
RIOT_API_KEY=your_riot_api_key
GEMINI_API_KEY=your_gemini_api_key
POLL_CHANNEL_ID=your_channel_id

# Optional — Discord role IDs for automatic role assignment
ROLE_INGAME_ID=0
ROLE_ACTIVE_ID=0
ROLE_WIN_STREAK_ID=0
ROLE_LOSS_STREAK_ID=0
```

Run the bot:

```bash
python bot.py
```

---

## Notes

- Designed for **small private servers** (EUW region, Ranked Solo/Duo tracking)
- Riot development API keys expire every 24 hours — regenerate at [developer.riotgames.com](https://developer.riotgames.com)
- `players.json` is created automatically on first `!link` and persists across restarts
- Role IDs default to `0` (disabled) if not set in `.env`

## License

No license defined yet.