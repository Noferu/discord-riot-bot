# Discord Riot Bot

A small Discord bot that interacts with the Riot Games API to track friends' League of Legends games.

This project is mainly built for a **private Discord server** to follow players' progress (wins, losses, activity, etc.).

> ⚠️ **Work in progress.**
> This project is in early development and things may change, break, or be restructured at any time.

## What it does

The bot periodically checks the Riot API to see if tracked players:

* started a game
* won or lost
* progressed over time

The goal is simply to **track friends' games and progression inside a Discord server**.

Future ideas may include:

* additional tracking features
* Discord voice activity integration
* more commands and utilities

## Tech stack

* Python
* `discord.py`
* `aiohttp`
* `python-dotenv`

## Setup

Clone the repository:

```bash
git clone https://github.com/Noferu/discord-riot-bot.git
cd discord-riot-bot
```

Create and activate a virtual environment:

```bash
python -m venv venv
venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
DISCORD_TOKEN=your_discord_token
RIOT_API_KEY=your_riot_api_key
```

Run the bot:

```bash
python bot.py
```

## Notes

* The bot is currently designed for a **small private server**.
* The internal structure and features are still evolving.
* The current bot name is **Ogeiv**, but it may change later.

## License

No license defined yet.