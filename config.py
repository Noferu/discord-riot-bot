import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN  = os.getenv("DISCORD_TOKEN")
RIOT_API_KEY   = os.getenv("RIOT_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

POLL_CHANNEL_ID = int(os.getenv("POLL_CHANNEL_ID", 0))

# Regional routing (account, match history)
RIOT_API_BASE_URL = "https://europe.api.riotgames.com"

# Regional routing (spectator, league)
RIOT_REGIONAL_URL = "https://euw1.api.riotgames.com"

# Discord role IDs
ROLE_IDS = {
    "ingame":      0,
    "active":      0,
    "win_streak":  0,
    "loss_streak": 0,
}