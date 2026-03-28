import aiohttp
import asyncio
import json
from config import RIOT_API_KEY, RIOT_API_BASE_URL, RIOT_REGIONAL_URL

PLAYERS_FILE = "players.json"
_lock = asyncio.Lock()

RANKED_QUEUE_IDS = {420: "Ranked Solo/Duo", 440: "Ranked Flex"}

# ----------------------------------
# PLAYERS FILE
# ----------------------------------

def load_players():
    try:
        with open(PLAYERS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_players(players):
    with open(PLAYERS_FILE, "w") as f:
        json.dump(players, f, indent=4)

async def safe_save(players):
    async with _lock:
        save_players(players)

players = load_players()

# ----------------------------------
# HTTP HELPER
# ----------------------------------

async def riot_get(url, params=None):
    headers = {"X-Riot-Token": RIOT_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            return await response.json()

# ----------------------------------
# RIOT API
# ----------------------------------

async def get_puuid(game_name, tag_line):
    url = f"{RIOT_API_BASE_URL}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    data = await riot_get(url)
    return data["puuid"]

async def get_name_and_tag(puuid):
    url = f"{RIOT_API_BASE_URL}/riot/account/v1/accounts/by-puuid/{puuid}"
    data = await riot_get(url)
    return f"{data['gameName']}#{data['tagLine']}"

async def get_spectator(puuid):
    """Returns live game data, or None if the player is not in game."""
    url = f"{RIOT_REGIONAL_URL}/lol/spectator/v5/active-games/by-summoner/{puuid}"
    return await riot_get(url)

async def get_lp(puuid):
    """Returns the player's current ranked solo LP, or None if unranked."""
    url = f"{RIOT_REGIONAL_URL}/lol/league/v4/entries/by-puuid/{puuid}"
    data = await riot_get(url)
    if not data:
        return None
    for entry in data:
        if entry["queueType"] == "RANKED_SOLO_5x5":
            return entry["leaguePoints"]
    return None

async def get_last_match_result(puuid):
    """Returns the result of the last completed ranked game."""
    url = f"{RIOT_API_BASE_URL}/lol/match/v5/matches/by-puuid/{puuid}/ids"
    match_ids = await riot_get(url, params={"start": 0, "count": 1, "queue": 420})
    if not match_ids:
        return None

    match = await riot_get(f"{RIOT_API_BASE_URL}/lol/match/v5/matches/{match_ids[0]}")
    if not match:
        return None

    participant = next(
        (p for p in match["info"]["participants"] if p["puuid"] == puuid),
        None
    )
    if not participant:
        return None

    return {
        "win":      participant["win"],
        "kills":    participant["kills"],
        "deaths":   participant["deaths"],
        "assists":  participant["assists"],
        "champion": participant["championName"],
        "queue_id": match["info"]["queueId"],
    }

async def get_recent_results(puuid, count=5):
    """Returns a list of recent ranked game outcomes ('win' or 'loss')."""
    url = f"{RIOT_API_BASE_URL}/lol/match/v5/matches/by-puuid/{puuid}/ids"
    match_ids = await riot_get(url, params={"start": 0, "count": count, "queue": 420})
    if not match_ids:
        return []

    results = []
    for match_id in match_ids:
        match = await riot_get(f"{RIOT_API_BASE_URL}/lol/match/v5/matches/{match_id}")
        if not match:
            continue
        participant = next(
            (p for p in match["info"]["participants"] if p["puuid"] == puuid),
            None
        )
        if participant:
            results.append("win" if participant["win"] else "loss")

    return results