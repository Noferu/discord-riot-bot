import discord
import logging
import asyncio
import re
import time
from discord.ext import commands
from config import DISCORD_TOKEN, POLL_CHANNEL_ID, ROLE_IDS
from core.ai import ask_ai
from core.riot import (
    players, safe_save,
    get_puuid, get_spectator, get_lp,
    get_last_match_result, get_recent_results,
    RANKED_QUEUE_IDS
)

handler = logging.FileHandler(
    filename='discord.log',
    encoding='utf-8',
    mode='w'
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents
)

# ----------------------------------
# CONTEXT BUILDER
# ----------------------------------

async def get_riot_context(puuids_with_names: list[tuple[str, str]]) -> str:
    """Fetches recent match results for a list of (puuid, display_name) tuples."""
    lines = []
    for puuid, display_name in puuids_with_names:
        results = await get_recent_results(puuid, count=5)
        if not results:
            lines.append(f"{display_name} : aucune partie ranked récente trouvée.")
            continue

        wins   = results.count("win")
        losses = results.count("loss")
        last   = await get_last_match_result(puuid)
        lp     = await get_lp(puuid)

        summary = f"{display_name} : {wins}V {losses}D sur les {len(results)} dernières ranked"
        if lp is not None:
            summary += f", {lp} LP actuellement"
        if last:
            kda     = f"{last['kills']}/{last['deaths']}/{last['assists']}"
            outcome = "victoire" if last["win"] else "défaite"
            summary += f". Dernière game : {outcome} sur {last['champion']} ({kda})"

        lines.append(summary)

    return "\n".join(lines)


async def resolve_players_in_message(message: discord.Message) -> list[tuple[str, str]]:
    """
    Detects players mentioned in a message via three methods:
    1. Discord mentions (@someone) → look up in players.json by discord_id
    2. GameName#TAG in plain text → fetch puuid from Riot API directly
    3. Exact game_name match in plain text → look up in players.json

    Returns a deduplicated list of (puuid, display_name).
    """
    seen_puuids = set()
    result = []

    def add(puuid, name):
        if puuid not in seen_puuids:
            seen_puuids.add(puuid)
            result.append((puuid, name))

    # 1. Discord mentions
    for member in message.mentions:
        if member.id == bot.user.id:
            continue
        discord_id = str(member.id)
        if discord_id in players:
            for account in players[discord_id]["accounts"]:
                add(account["puuid"], f"{account['game_name']}#{account['tag_line']}")

    # 2. GameName#TAG in plain text
    riot_id_pattern = re.compile(r"([\w\s]+)#(\w+)")
    for match in riot_id_pattern.finditer(message.content):
        game_name = match.group(1).strip()
        tag_line  = match.group(2).strip()
        try:
            puuid = await get_puuid(game_name, tag_line)
            add(puuid, f"{game_name}#{tag_line}")
        except Exception:
            pass

    # 3. Exact game_name match in plain text
    content_lower = message.content.lower()
    for data in players.values():
        for account in data["accounts"]:
            if account["game_name"].lower() in content_lower:
                add(account["puuid"], f"{account['game_name']}#{account['tag_line']}")

    # Always include the message author if they have linked accounts
    author_id = str(message.author.id)
    if author_id in players:
        for account in players[author_id]["accounts"]:
            add(account["puuid"], f"{account['game_name']}#{account['tag_line']} (auteur)")

    return result


async def build_ai_contents(message: discord.Message) -> list:
    """
    Builds the full conversation history to send to Gemini:
    - Last 10 channel messages as user/model turns
    - Reference chain (replied-to messages, up to 10)
    - Riot context for detected players
    - The actual message as the final user turn
    """
    contents = []

    # Last 3 channel messages (excluding the triggering message)
    history = []
    async for msg in message.channel.history(limit=4):
        if msg.id == message.id:
            continue
        history.append(msg)
    history.reverse()

    for msg in history:
        role   = "model" if msg.author.id == bot.user.id else "user"
        author = "Shaconnard" if role == "model" else msg.author.display_name
        contents.append({
            "role":  role,
            "parts": [{"text": f"{author} : {msg.content}"}]
        })

    # Reference chain
    ref_chain = []
    ref       = message.reference
    depth     = 0
    while ref and depth < 5:
        try:
            ref_msg = await message.channel.fetch_message(ref.message_id)
            ref_chain.append(ref_msg)
            ref   = ref_msg.reference
            depth += 1
        except Exception:
            break

    if ref_chain:
        ref_chain.reverse()
        ref_text = "\n".join(
            f"{'Shaconnard' if m.author.id == bot.user.id else m.author.display_name} : {m.content}"
            for m in ref_chain
        )
        contents.append({
            "role":  "user",
            "parts": [{"text": f"[Fil de réponses]\n{ref_text}"}]
        })

    # Riot context
    players_in_msg = await resolve_players_in_message(message)
    if players_in_msg:
        riot_context = await get_riot_context(players_in_msg)
        contents.append({
            "role":  "user",
            "parts": [{"text": f"[Contexte LoL des joueurs mentionnés]\n{riot_context}"}]
        })

    # Actual message
    contents.append({
        "role":  "user",
        "parts": [{"text": f"{message.author.display_name} : {message.content}"}]
    })

    return contents

# ----------------------------------
# HELPERS
# ----------------------------------

def is_puuid_taken(puuid: str) -> bool:
    """Returns True if the puuid is already linked to any Discord account."""
    for data in players.values():
        for account in data["accounts"]:
            if account["puuid"] == puuid:
                return True
    return False

async def _link_account(ctx, target_member: discord.Member, riot_id: str):
    """Core logic to link a Riot account to a Discord member."""
    discord_id = str(target_member.id)

    if "#" not in riot_id:
        await ctx.send("Format invalide. Utilise : `GameName#TAG`")
        return

    game_name, tag_line = riot_id.rsplit("#", 1)

    if discord_id in players:
        already = any(
            a["game_name"].lower() == game_name.lower() and a["tag_line"].lower() == tag_line.lower()
            for a in players[discord_id]["accounts"]
        )
        if already:
            await ctx.send("Ce compte est déjà sous surveillance… inutile d'insister.")
            return

    try:
        puuid = await get_puuid(game_name, tag_line)
    except Exception as e:
        await ctx.send(f"Introuvable… ou peut-être que tu t'es trompé. ({e})")
        return

    if is_puuid_taken(puuid):
        await ctx.send("Ce compte Riot est déjà lié à un autre utilisateur Discord.")
        return

    if discord_id not in players:
        players[discord_id] = {"accounts": []}

    players[discord_id]["accounts"].append({
        "game_name":           game_name,
        "tag_line":            tag_line,
        "puuid":               puuid,
        "is_ingame":           False,
        "lp_before":           None,
        "last_game_timestamp": None,
    })
    await safe_save(players)
    await ctx.send(f"Compte **{game_name}#{tag_line}** lié à {target_member.mention}… parfait, ça devient intéressant.")

# ----------------------------------
# ROLES
# ----------------------------------

async def update_roles(guild, discord_id, is_ingame, last_game_timestamp, recent_results):
    member = guild.get_member(discord_id)
    if not member:
        return

    ingame_role = guild.get_role(ROLE_IDS["ingame"])
    active_role = guild.get_role(ROLE_IDS["active"])
    win_role    = guild.get_role(ROLE_IDS["win_streak"])
    loss_role   = guild.get_role(ROLE_IDS["loss_streak"])

    # "In game" role
    if is_ingame and ingame_role and ingame_role not in member.roles:
        await member.add_roles(ingame_role)
    elif not is_ingame and ingame_role and ingame_role in member.roles:
        await member.remove_roles(ingame_role)

    # "Active player" role (in game or last game < 30 min ago)
    is_active = is_ingame or (
        last_game_timestamp is not None and
        (time.time() - last_game_timestamp) < 1800
    )
    if is_active and active_role and active_role not in member.roles:
        await member.add_roles(active_role)
    elif not is_active and active_role and active_role in member.roles:
        await member.remove_roles(active_role)

    # "Win streak" role (last 3 games = wins)
    on_win_streak = len(recent_results) >= 3 and all(r == "win" for r in recent_results[:3])
    if on_win_streak and win_role and win_role not in member.roles:
        await member.add_roles(win_role)
    elif not on_win_streak and win_role and win_role in member.roles:
        await member.remove_roles(win_role)

    # "Loss streak" role (last 3 games = losses)
    on_loss_streak = len(recent_results) >= 3 and all(r == "loss" for r in recent_results[:3])
    if on_loss_streak and loss_role and loss_role not in member.roles:
        await member.add_roles(loss_role)
    elif not on_loss_streak and loss_role and loss_role in member.roles:
        await member.remove_roles(loss_role)

# ----------------------------------
# POLL
# ----------------------------------

async def poll_players(channel, guild):
    while True:
        for discord_id_str, data in players.items():
            discord_id = int(discord_id_str)

            for account in data["accounts"]:
                puuid      = account["puuid"]
                game_name  = account["game_name"]
                was_ingame = account.get("is_ingame", False)

                try:
                    game_data = await get_spectator(puuid)
                except Exception as e:
                    print(f"Spectator error for {game_name}: {e}")
                    continue

                is_now_ingame = game_data is not None

                # -- GAME STARTED --
                if not was_ingame and is_now_ingame:
                    account["is_ingame"] = True
                    account["lp_before"] = await get_lp(puuid)

                    participants  = game_data.get("participants", [])
                    other_players = [
                        p.get("riotId", "Unknown") for p in participants if p["puuid"] != puuid
                    ]
                    queue_id    = game_data.get("gameQueueConfigId", 0)
                    queue_name  = RANKED_QUEUE_IDS.get(queue_id, "Normal")
                    champion    = next(
                        (p.get("championId", "?") for p in participants if p["puuid"] == puuid), "?"
                    )
                    game_length = game_data.get("gameLength", 0)
                    duration    = f"{game_length // 60}:{game_length % 60:02d}"
                    others      = ", ".join(other_players[:5]) or "—"

                    embed = discord.Embed(
                        title=f"🟢 {game_name} entre en game",
                        color=discord.Color.green()
                    )

                    embed.add_field(name="Champion", value=f"`{champion}`", inline=True)
                    embed.add_field(name="Mode", value=f"`{queue_name}`", inline=True)
                    embed.add_field(name="Durée", value=f"`{duration}`", inline=True)

                    embed.add_field(
                        name="Autres joueurs",
                        value=others or "—",
                        inline=False
                    )

                    embed.set_footer(text="Le spectacle commence…")

                    await channel.send(embed=embed)

                # -- GAME ENDED --
                elif was_ingame and not is_now_ingame:
                    account["is_ingame"]           = False
                    account["last_game_timestamp"] = time.time()

                    await asyncio.sleep(30)

                    result = await get_last_match_result(puuid)

                    if result and result["queue_id"] in RANKED_QUEUE_IDS:
                        lp_after  = await get_lp(puuid)
                        lp_before = account.get("lp_before")
                        lp_diff   = (lp_after - lp_before) if (lp_after is not None and lp_before is not None) else None

                        outcome = "✅ Victoire" if result["win"] else "❌ Défaite"
                        kda     = f"{result['kills']}/{result['deaths']}/{result['assists']}"
                        lp_str  = f"`{lp_diff:+d} LP`" if lp_diff is not None else "`—`"

                        embed = discord.Embed(
                            title=f"{outcome} — {game_name}",
                            color=discord.Color.green() if result["win"] else discord.Color.red()
                        )

                        embed.add_field(name="Champion", value=f"`{result['champion']}`", inline=True)
                        embed.add_field(name="KDA", value=f"`{kda}`", inline=True)
                        embed.add_field(name="LP", value=lp_str, inline=True)

                        embed.set_footer(text="Le spectacle… était prévisible.")

                        await channel.send(embed=embed)

                    elif result:
                        outcome = "✅ Victoire" if result["win"] else "❌ Défaite"
                        kda     = f"{result['kills']}/{result['deaths']}/{result['assists']}"

                        embed = discord.Embed(
                            title=f"{outcome} — {game_name} (normal)",
                            color=discord.Color.green() if result["win"] else discord.Color.red()
                        )

                        embed.add_field(name="Champion", value=f"`{result['champion']}`", inline=True)
                        embed.add_field(name="KDA", value=f"`{kda}`", inline=True)

                        embed.set_footer(text="Rien d'inattendu.")

                        await channel.send(embed=embed)

                    account["lp_before"] = None

                    recent_results = await get_recent_results(puuid)
                    await update_roles(
                        guild, discord_id,
                        is_ingame=False,
                        last_game_timestamp=account["last_game_timestamp"],
                        recent_results=recent_results
                    )

                # Update ingame + active roles every tick
                await update_roles(
                    guild, discord_id,
                    is_ingame=is_now_ingame,
                    last_game_timestamp=account.get("last_game_timestamp"),
                    recent_results=[]
                )

            await safe_save(players)

        await asyncio.sleep(60)

# ----------------------------------
# EVENTS
# ----------------------------------

@bot.event
async def on_ready():
    print(f"Oh… le spectacle commence. {bot.user.name} était déjà là… il attendait juste le bon moment.")
    channel = bot.get_channel(POLL_CHANNEL_ID)
    guild   = channel.guild if channel else None
    if channel and guild:
        bot.loop.create_task(poll_players(channel, guild))
    else:
        print(f"Channel {POLL_CHANNEL_ID} not found.")

@bot.event
async def on_member_join(member):
    await member.send(
        f"Hahaha… bienvenue {member.name}. Tu ne sais vraiment pas où tu as mis les pieds… hahaha."
    )

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user.mentioned_in(message):
        async with message.channel.typing():
            try:
                contents = await build_ai_contents(message)
                response = await ask_ai(contents)
            except Exception as e:
                print(f"AI error: {e}")
                response = "Oh… tu attends une réponse ? Pas maintenant. Réessaie plus tard… ou abandonne, ça m'est égal."
        await message.reply(response)

    if "merde" in message.content.lower():
        await message.delete()
        await message.channel.send(
            f"Doucement {message.author.mention}… ce genre de mots, c'est mon domaine. Contente-toi de jouer, je m'occupe du reste… hehe."
        )

    await bot.process_commands(message)

# ----------------------------------
# COMMANDS
# ----------------------------------

@bot.command()
async def hello(ctx):
    await ctx.send(f"Oh… {ctx.author.mention}. Je t'avais déjà remarqué.")

@bot.command()
async def link(ctx, *, riot_id: str):
    """Link a Riot account to your own Discord account."""
    await _link_account(ctx, ctx.author, riot_id)

@bot.command(name="linkfor")
async def link_for(ctx, member: discord.Member, *, riot_id: str):
    """Link a Riot account to another Discord member (admin only)."""
    # Uncomment to restrict to admins:
    # if not ctx.author.guild_permissions.administrator:
    #     await ctx.send("Tu n'as pas la permission de faire ça.")
    #     return
    await _link_account(ctx, member, riot_id)

@bot.command(name="list")
async def list_own(ctx):
    """List your own linked Riot accounts."""
    discord_id = str(ctx.author.id)

    if discord_id not in players or not players[discord_id]["accounts"]:
        await ctx.send("Tu n'as aucun compte lié… tu te caches ?")
        return

    embed = discord.Embed(
        title=f"👁️ Comptes de {ctx.author.display_name}",
        color=discord.Color.purple()
    )
    accounts = "\n".join(
        f"• **{a['game_name']}#{a['tag_line']}**"
        for a in players[discord_id]["accounts"]
    )
    embed.add_field(name="Comptes Riot", value=accounts, inline=False)
    embed.set_footer(text="Ils jouent… je regarde 👁️")
    await ctx.send(embed=embed)

@bot.command(name="listall")
async def list_all(ctx):
    """List all tracked Riot accounts across all Discord members."""
    if not players:
        await ctx.send(embed=discord.Embed(
            title="👁️ Observation vide...",
            description="Aucun compte à surveiller… pour l'instant.",
            color=discord.Color.red()
        ))
        return

    embed = discord.Embed(
        title="👁️ Tous les comptes surveillés",
        description="Voici ceux qui sont actuellement sous observation...",
        color=discord.Color.purple()
    )
    for discord_id_str, data in players.items():
        member   = ctx.guild.get_member(int(discord_id_str))
        name     = member.display_name if member else f"ID {discord_id_str}"
        accounts = "\n".join(
            f"• **{a['game_name']}#{a['tag_line']}**"
            for a in data["accounts"]
        )
        embed.add_field(name=f"🧍 {name}", value=accounts, inline=False)
    embed.set_footer(text="Ils jouent… je regarde 👁️")
    await ctx.send(embed=embed)

@bot.command()
async def unlink(ctx, *, riot_id: str = None):
    discord_id = str(ctx.author.id)

    if discord_id not in players:
        await ctx.send("Je n'ai jamais rien eu sur toi… étrange.")
        return

    if riot_id:
        if "#" not in riot_id:
            await ctx.send("Format invalide. Utilise : `!unlink GameName#TAG`")
            return

        game_name, tag_line = riot_id.rsplit("#", 1)
        before = len(players[discord_id]["accounts"])
        players[discord_id]["accounts"] = [
            a for a in players[discord_id]["accounts"]
            if not (a["game_name"].lower() == game_name.lower() and a["tag_line"].lower() == tag_line.lower())
        ]

        if len(players[discord_id]["accounts"]) < before:
            if not players[discord_id]["accounts"]:
                del players[discord_id]
            await safe_save(players)
            await ctx.send(f"Compte **{riot_id}** retiré… dommage, ça devenait intéressant.")
        else:
            await ctx.send("Je ne trouve rien sous ce nom… tu es sûr de toi ?")
    else:
        del players[discord_id]
        await safe_save(players)
        await ctx.send("Plus rien à observer… tu fuis déjà ?")

@bot.command(name="refreshpuuid")
async def refresh_puuid(ctx):
    """Refresh all PUUIDs from game_name#tag_line via Riot API."""
    updated = 0
    failed = []

    for discord_id_str, data in players.items():
        for account in data["accounts"]:
            try:
                new_puuid = await get_puuid(account["game_name"], account["tag_line"])
                account["puuid"] = new_puuid
                updated += 1
            except Exception as e:
                failed.append(f"{account['game_name']}#{account['tag_line']} ({e})")

    await safe_save(players)

    msg = f"✅ {updated} compte(s) mis à jour."
    if failed:
        msg += "\n❌ Échecs :\n" + "\n".join(failed)

    await ctx.send(msg)

# ----------------------------------

bot.run(
    DISCORD_TOKEN,
    log_handler=handler,
    log_level=logging.DEBUG
)