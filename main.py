# ============================================================
# RULES FOR CHATGPT AND GROK (DO NOT VIOLATE)
# • Use ONLY these sections, in this exact order:
#   ############### IMPORTS ###############
#   ############### CONSTANTS & CONFIG ###############
#   ############### GLOBAL STATE / STORAGE ###############
#   ############### HELPER FUNCTIONS ###############
#   ############### VIEWS / UI COMPONENTS ###############
#   ############### AUTOCOMPLETE FUNCTIONS ###############
#   ############### BACKGROUND TASKS & SCHEDULERS ###############
#   ############### EVENT HANDLERS ###############
#   ############### COMMAND GROUPS ###############
#   ############### ON_READY & BOT START ###############
# • Do NOT add any other sections.
# • Do NOT add comments inside the code. No inline labels.
# ============================================================
# BOT NAME: MEMBER BOT
# PURPOSE
# • Movie Night: sheet sync, pool system, random winner, rating announcements
# • Birthdays: storage, daily role assignment, public birthday list
# • QOTD: seasonal sheet selection, daily scheduler, posting logic
# • Seasonal Themes: themed roles, emojis, server/bot icons
# • Member Tools: Dead Chat color cycle, VC-status role, admin utilities
# ============================================================
# SERVER: Soft Dreamings (≈25 members, ages 25–40)
# • Private friend group; movie nights, QOTD, games, light role events
# • Bots: Admin Bot + Member Bot (this file)
# • Notable Channels:
#   - #k • one-letter chat
#   - #codes • game codes
#   - #graveyard • Dead Chat role, plague events, monthly prize drops
#   - #movies • movie pool
#   - #ratings • post-watch ratings
#   - #qotd • daily questions
# ROLE ACCESS
# OWNER
# • Permissions: Full
# • Commands: All
# ADMINS
# • Permissions: Full admin/moderation
# • Commands: All in this file
# TRUSTED
# • Permissions: Member + announcements + VC status
# • Commands:
#   /birthdays /birthdays_public /media_reload /library_sync
#   /pool_public /pool_remove /qotd_send /random /set_for /remove_for
# MEMBER
# • Permissions: Standard chat + VC + app commands
# • Commands:
#   /birthdays /set /color /pick /pool /replace /search
# ============================================================


############### IMPORTS ###############
import os
import json
import asyncio
import aiohttp
import discord
import random as pyrandom
import gspread
import traceback
import sys
from datetime import datetime, time, timezone
from google.oauth2.service_account import Credentials


############### CONSTANTS & CONFIG ###############
intents = discord.Intents.default()
intents.members = True
bot = discord.Bot(intents=intents)

def _env_int(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"[WARNING] Invalid value for {var_name}: {value!r} — using default {default}")
        return default

GOOGLE_CREDS_RAW = os.getenv("GOOGLE_CREDENTIALS")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
gc = None
if GOOGLE_CREDS_RAW and SHEET_ID:
    try:
        creds_dict = json.loads(GOOGLE_CREDS_RAW)
        creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        print("QOTD: Google Sheets client initialized.")
    except Exception as e:
        print("QOTD init error:", repr(e))
        traceback.print_exc()
else:
    print("QOTD disabled: missing GOOGLE_CREDENTIALS or GOOGLE_SHEET_ID")
    
ENABLE_TV_IN_PICK = False
RATING_CHANNEL_ID = _env_int("RATING_CHANNEL_ID", 0)  # ・Ratings
MOVIE_STORAGE_CHANNEL_ID = _env_int("MOVIE_STORAGE_CHANNEL_ID", 0)  # For trailer messages linked to sheets
MAX_POOL_ENTRIES_PER_USER = _env_int("MAX_POOL_ENTRIES_PER_USER", 3) 
PAGE_SIZE = 25

QOTD_CHANNEL_ID = _env_int("QOTD_CHANNEL_ID", 0)

ICON_DEFAULT_URL = os.getenv("ICON_DEFAULT_URL", "")
ICON_CHRISTMAS_URL = os.getenv("ICON_CHRISTMAS_URL", "")
ICON_HALLOWEEN_URL = os.getenv("ICON_HALLOWEEN_URL", "")
THEME_CHRISTMAS_ROLES = {"Sandy Claws": "Admin", "Grinch": "Original Member", "Cranberry": "Member", "Christmas": "Bots"}
THEME_HALLOWEEN_ROLES = {"Cauldron": "Admin", "Candy": "Original Member", "Witchy": "Member", "Halloween": "Bots"}

DEAD_CHAT_ROLE_ID = _env_int("DEAD_CHAT_ROLE_ID", 0)
DEAD_CHAT_ROLE_NAME = os.getenv("DEAD_CHAT_ROLE_NAME", "Dead Chat")
DEAD_CHAT_COLORS = [discord.Color.red(), discord.Color.orange(), discord.Color.gold(), discord.Color.green(), discord.Color.blue(), discord.Color.purple(), discord.Color.magenta(), discord.Color.teal()]

BIRTHDAY_ROLE_ID = _env_int("BIRTHDAY_ROLE_ID", 0)  # The role given when it is their birthday
BIRTHDAY_STORAGE_CHANNEL_ID = _env_int("BIRTHDAY_STORAGE_CHANNEL_ID", 0)
MONTH_CHOICES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
MONTH_TO_NUM = {name: f"{i:02d}" for i, name in enumerate(MONTH_CHOICES, start=1)}

BOT_LOG_THREAD_ID = _env_int("BOT_LOG_THREAD_ID", 0)


############### GLOBAL STATE / STORAGE ###############
storage_message_id: int | None = None
pool_storage_message_id: int | None = None
pool_message_locations: dict[int, tuple[int, int]] = {}
movie_titles: list[dict] = []
request_pool: dict[int, list[tuple[int, str]]] = {}
startup_logging_done: bool = False
startup_log_buffer = []


############### HELPER FUNCTIONS ###############
async def log_to_thread(content: str):
    if not startup_logging_done:
        startup_log_buffer.append(content)
        return
    channel = bot.get_channel(BOT_LOG_THREAD_ID)
    if not channel:
        return
    try:
        await channel.send(content)
    except Exception:
        pass

async def log_exception(tag: str, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    text = f"{tag}: {exc}\n{tb}"
    if len(text) > 1900:
        text = text[:1900]
    await log_to_thread(text)

async def run_startup_checks():
    global storage_message_id, pool_storage_message_id

    lines = []
    lines.append("Startup check report:")
    lines.append("")

    lines.append("[LOGGING]")
    log_channel = bot.get_channel(BOT_LOG_THREAD_ID) if BOT_LOG_THREAD_ID else None
    if BOT_LOG_THREAD_ID == 0:
        lines.append("`⚠️` Log thread ID missing or zero (BOT_LOG_THREAD_ID).")
    elif log_channel is None:
        lines.append("`⚠️` Log thread channel not accessible (BOT_LOG_THREAD_ID does not resolve).")
    else:
        lines.append(f"`✅` Log thread configured in channel {BOT_LOG_THREAD_ID}")
    lines.append("")

    lines.append("[STORAGE]")

    storage_ok = False
    try:
        data = await _load_storage_message()
        storage_ok = isinstance(data, dict)
    except Exception as e:
        await log_exception("startup_check_storage", e)
        storage_ok = False
    if storage_ok:
        lines.append("`✅` Birthday storage data")
    else:
        lines.append("`⚠️` Birthday storage data could not be loaded or parsed")

    birthday_storage_binding_ok = (
        storage_message_id is not None
        and BIRTHDAY_STORAGE_CHANNEL_ID != 0
        and bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID) is not None
    )
    if birthday_storage_binding_ok:
        lines.append(f"`✅` Birthday storage message binding (msg_id={storage_message_id}, channel_id={BIRTHDAY_STORAGE_CHANNEL_ID})")
    else:
        lines.append("`⚠️` Birthday storage message binding missing or inaccessible")

    pool_ok = False
    try:
        pool = await _load_pool_message()
        pool_ok = isinstance(pool, dict)
    except Exception as e:
        await log_exception("startup_check_pool", e)
        pool_ok = False
    if pool_ok:
        lines.append("`✅` Pool storage data")
    else:
        lines.append("`⚠️` Pool storage data could not be loaded or parsed")

    pool_storage_binding_ok = (
        pool_storage_message_id is not None
        and BIRTHDAY_STORAGE_CHANNEL_ID != 0
        and bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID) is not None
    )
    if pool_storage_binding_ok:
        lines.append(f"`✅` Pool storage message binding (msg_id={pool_storage_message_id}, channel_id={BIRTHDAY_STORAGE_CHANNEL_ID})")
    else:
        lines.append("`⚠️` Pool storage message binding missing or inaccessible")

    storage_channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID) if BIRTHDAY_STORAGE_CHANNEL_ID else None
    if storage_channel:
        lines.append("`✅` Birthday storage channel")
    else:
        lines.append("`⚠️` Birthday storage channel not found")

    lines.append("")
    lines.append("[QOTD / MEDIA]")

    sheets_ok = gc is not None and bool(SHEET_ID)
    if sheets_ok:
        lines.append("`✅` Google Sheets client")
    else:
        lines.append("`⚠️` Google Sheets client missing or invalid (credentials or sheet ID)")

    movies_ok = isinstance(movie_titles, list)
    count = len(movie_titles) if movies_ok else 0
    if movies_ok and count > 0:
        lines.append(f"`✅` Movie list loaded ({count} item(s))")
    elif movies_ok:
        lines.append("`⚠️` Movie list loaded as an empty list")
    else:
        lines.append("`⚠️` Movie list is not a valid list object")

    qotd_channel = bot.get_channel(QOTD_CHANNEL_ID) if QOTD_CHANNEL_ID else None
    if qotd_channel:
        lines.append("`✅` QOTD channel")
    else:
        lines.append("`⚠️` QOTD channel not found")

    rating_channel = bot.get_channel(RATING_CHANNEL_ID) if RATING_CHANNEL_ID else None
    if rating_channel:
        lines.append("`✅` Movie rating channel")
    else:
        lines.append("`⚠️` Movie rating channel not found")

    movie_storage_channel = bot.get_channel(MOVIE_STORAGE_CHANNEL_ID) if MOVIE_STORAGE_CHANNEL_ID else None
    if movie_storage_channel:
        lines.append("`✅` Movie storage channel")
    else:
        lines.append("`⚠️` Movie storage channel not found")

    lines.append("")
    lines.append("[THEMES]")

    emoji_names = _collect_theme_emoji_names()
    if emoji_names:
        lines.append(f"`✅` Theme emoji config ({len(emoji_names)} name(s))")
    else:
        lines.append("`⚠️` Theme emoji config missing or empty")

    if THEME_CHRISTMAS_ROLES:
        lines.append("`✅` Christmas role templates")
    else:
        lines.append("`⚠️` Christmas role templates not defined")

    if THEME_HALLOWEEN_ROLES:
        lines.append("`✅` Halloween role templates")
    else:
        lines.append("`⚠️` Halloween role templates not defined")

    if ICON_DEFAULT_URL:
        lines.append("`✅` Default icon URL")
    else:
        lines.append("`⚠️` Default icon URL missing")

    if ICON_CHRISTMAS_URL:
        lines.append("`✅` Christmas icon URL")
    else:
        lines.append("`⚠️` Christmas icon URL missing")

    if ICON_HALLOWEEN_URL:
        lines.append("`✅` Halloween icon URL")
    else:
        lines.append("`⚠️` Halloween icon URL missing")

    lines.append("")
    lines.append("[ROLES / VC]")

    guild = bot.guilds[0] if bot.guilds else None
    if guild is None:
        lines.append("`⚠️` Bot is not connected to a guild")
    else:
        birthday_role = guild.get_role(BIRTHDAY_ROLE_ID) if BIRTHDAY_ROLE_ID else None
        if birthday_role:
            lines.append(f"`✅` Birthday role found ({birthday_role.name}, id={birthday_role.id})")
        else:
            lines.append("`⚠️` Birthday role missing or invalid")

        dead_chat_role = None
        if DEAD_CHAT_ROLE_ID:
            dead_chat_role = guild.get_role(DEAD_CHAT_ROLE_ID)
        if dead_chat_role is None and DEAD_CHAT_ROLE_NAME:
            dead_chat_role = discord.utils.get(guild.roles, name=DEAD_CHAT_ROLE_NAME)

        if dead_chat_role:
            lines.append(f"`✅` Dead Chat role found ({dead_chat_role.name}, id={dead_chat_role.id})")
        else:
            lines.append("`⚠️` Dead Chat role missing or invalid")

        vc_id = 1331501272804884490
        vc_role_id = 1444555985728442390

        vc_channel = guild.get_channel(vc_id)
        vc_role = guild.get_role(vc_role_id)

        if vc_channel:
            lines.append(f"`✅` VC channel found for VC-status tracking ({vc_channel.name}, id={vc_id})")
        else:
            lines.append(f"`⚠️` VC channel {vc_id} not found")

        if vc_role:
            lines.append(f"`✅` VC-status role found ({vc_role.name}, id={vc_role_id})")
        else:
            lines.append(f"`⚠️` VC-status role {vc_role_id} not found")

    lines.append("")
    lines.append("")
    lines.append("All systems passed basic storage + runtime checks.")
    lines.append(f"[STARTUP] Member Bot ready as {bot.user} in {len(bot.guilds)} guild(s).")
    lines.append("Schedulers started: birthday_checker, qotd_scheduler, theme_scheduler.")

    text = "\n".join(lines)
    if len(text) > 1900:
        text = text[:1900]
    await log_to_thread(text)
    
def build_mm_dd(month_name: str, day: int) -> str | None:
    month_num = MONTH_TO_NUM.get(month_name)
    if not month_num or not (1 <= day <= 31):
        return None
    return f"{month_num}-{day:02d}"

async def initialize_storage_message():
    global storage_message_id, pool_storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel:
        return
    birthday_msg = None
    pool_msg = None
    async for msg in channel.history(limit=50, oldest_first=True):
        if msg.author != bot.user:
            continue
        content = (msg.content or "").strip()
        if content.startswith("POOL_DATA:"):
            pool_msg = msg
        else:
            birthday_msg = msg
        if birthday_msg and pool_msg:
            break
    if birthday_msg is None:
        birthday_msg = await channel.send("{}")
    if pool_msg is None:
        pool_msg = await channel.send("POOL_DATA: {}")
    storage_message_id = birthday_msg.id
    pool_storage_message_id = pool_msg.id

async def _load_storage_message() -> dict:
    global storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel or storage_message_id is None:
        return {}
    try:
        msg = await channel.fetch_message(storage_message_id)
        data = json.loads(msg.content.strip() or "{}")
        return data if isinstance(data, dict) else {}
    except:
        return {}

async def _save_storage_message(data: dict):
    global storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel or storage_message_id is None:
        return
    try:
        msg = await channel.fetch_message(storage_message_id)
        text = json.dumps(data, indent=2)
        if len(text) > 1900:
            text = text[:1900]
        await msg.edit(content=text)
    except:
        pass

async def _load_pool_message() -> dict:
    global pool_storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel or pool_storage_message_id is None:
        return {}
    try:
        msg = await channel.fetch_message(pool_storage_message_id)
        content = (msg.content or "").strip()
        if content.startswith("POOL_DATA:"):
            content = content[len("POOL_DATA:"):].strip()
        data = json.loads(content or "{}")
        return data if isinstance(data, dict) else {}
    except:
        return {}

async def _save_pool_message(data: dict):
    global pool_storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel or pool_storage_message_id is None:
        return
    try:
        msg = await channel.fetch_message(pool_storage_message_id)
        text = "POOL_DATA: " + json.dumps(data, separators=(",", ":"))
        if len(text) > 1900:
            text = text[:1900]
        await msg.edit(content=text)
    except:
        pass

async def load_request_pool():
    global request_pool, pool_message_locations
    raw = await _load_pool_message()
    request_pool = {}
    pool_message_locations = {}
    for gid_str, payload in raw.items():
        try:
            gid = int(gid_str)
        except:
            continue
        entries = []
        message_info = None
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict):
            if isinstance(payload.get("entries"), list):
                entries = payload["entries"]
            message_info = payload.get("message")
        pool_list = []
        for item in entries:
            if isinstance(item, list) and len(item) == 2:
                uid, title = item
                try:
                    uid_int = int(uid)
                except:
                    continue
                pool_list.append((uid_int, str(title)))
        if pool_list:
            request_pool[gid] = pool_list
        if isinstance(message_info, dict):
            ch_id = message_info.get("channel_id")
            msg_id = message_info.get("message_id")
            try:
                ch_id = int(ch_id)
                msg_id = int(msg_id)
            except:
                continue
            pool_message_locations[gid] = (ch_id, msg_id)

async def save_request_pool():
    raw = {}
    all_gids = set(request_pool.keys()) | set(pool_message_locations.keys())
    for gid in all_gids:
        pool = request_pool.get(gid, [])
        obj = {}
        obj["entries"] = [[uid, title] for (uid, title) in pool]
        loc = pool_message_locations.get(gid)
        if loc:
            ch_id, msg_id = loc
            obj["message"] = {"channel_id": ch_id, "message_id": msg_id}
        raw[str(gid)] = obj
    await _save_pool_message(raw)

async def initialize_media_lists():
    global movie_titles
    if gc is None or not SHEET_ID:
        movie_titles = []
        return
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet("Movies")
    vals = ws.get_all_values()[1:]
    movies = []
    for row in vals:
        if not row:
            continue
        title = row[0].strip() if len(row) > 0 else ""
        if not title:
            continue
        poster = row[1].strip() if len(row) > 1 else ""
        trailer = row[2].strip() if len(row) > 2 else ""
        movies.append({"title": title, "poster": poster, "trailer": trailer})
    movie_titles = movies
    print(f"Loaded {len(movie_titles)} movies from sheet.")

async def sync_movie_library_messages():
    if MOVIE_STORAGE_CHANNEL_ID == 0:
        return
    channel = bot.get_channel(MOVIE_STORAGE_CHANNEL_ID)
    if not channel:
        return
    existing = []
    async for msg in channel.history(limit=None, oldest_first=True):
        if msg.author == bot.user:
            existing.append(msg)
    rows = movie_titles
    for idx, movie in enumerate(rows):
        title = movie["title"]
        trailer = movie.get("trailer") or ""
        content = f"{title}\n{trailer}" if trailer else title
        if idx < len(existing):
            m = existing[idx]
            try:
                await m.edit(content=content, view=MovieEntryView())
            except:
                try:
                    await channel.send(content=content, view=MovieEntryView())
                except:
                    pass
        else:
            try:
                await channel.send(content=content, view=MovieEntryView())
            except:
                pass
    for extra in existing[len(rows):]:
        try:
            await extra.delete()
        except:
            pass

async def set_birthday(guild_id: int, user_id: int, mm_dd: str):
    data = await _load_storage_message()
    gid = str(guild_id)
    entry = data.get(gid)
    if entry is None:
        entry = {"birthdays": {}}
    elif not (isinstance(entry, dict) and isinstance(entry.get("birthdays"), dict)):
        entry = {"birthdays": entry if isinstance(entry, dict) else {}}
    entry["birthdays"][str(user_id)] = mm_dd
    data[gid] = entry
    await _save_storage_message(data)

async def get_guild_birthdays(guild_id: int):
    data = await _load_storage_message()
    entry = data.get(str(guild_id), {})
    if isinstance(entry, dict) and isinstance(entry.get("birthdays"), dict):
        return entry["birthdays"]
    return entry if isinstance(entry, dict) else {}

async def build_birthday_embed(guild: discord.Guild) -> discord.Embed:
    birthdays = await get_guild_birthdays(guild.id)
    lines = []
    for user_id, mm_dd in sorted(birthdays.items(), key=lambda x: x[1]):
        member = guild.get_member(int(user_id))
        if member:
            lines.append(f"{member.mention} — `{mm_dd}`")
        else:
            lines.append(f"<@{user_id}> — `{mm_dd}`")
    description = "\n".join(lines) if lines else "No birthdays yet!"
    description += "\n\n**SHARE YOUR BIRTHDAY**\n• </set:1440919374310408234> - Add your birthday to the server’s shared birthday list."
    return discord.Embed(
        title="OUR BIRTHDAYS!",
        description=description,
        color=0x2e2f33
    ).set_footer(text="Messages in this channel are deleted after 5 minutes")

async def get_birthday_public_location(guild_id: int):
    data = await _load_storage_message()
    entry = data.get(str(guild_id))
    if isinstance(entry, dict):
        pm = entry.get("public_message")
        if isinstance(pm, dict):
            ch_id = pm.get("channel_id")
            msg_id = pm.get("message_id")
            if isinstance(ch_id, int) and isinstance(msg_id, int):
                return ch_id, msg_id
    return None

async def set_birthday_public_location(guild_id: int, channel_id: int, message_id: int):
    data = await _load_storage_message()
    gid = str(guild_id)
    entry = data.get(gid)
    if entry is None:
        entry = {"birthdays": {}}
    elif not (isinstance(entry, dict) and isinstance(entry.get("birthdays"), dict)):
        entry = {"birthdays": entry if isinstance(entry, dict) else {}}
    entry["public_message"] = {"channel_id": channel_id, "message_id": message_id}
    data[gid] = entry
    await _save_storage_message(data)

async def update_birthday_list_message(guild: discord.Guild):
    loc = await get_birthday_public_location(guild.id)
    if not loc:
        return
    ch_id, msg_id = loc
    channel = guild.get_channel(ch_id)
    if not channel:
        return
    try:
        msg = await channel.fetch_message(msg_id)
        embed = await build_birthday_embed(guild)
        await msg.edit(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))
    except:
        pass

async def build_pool_embed(guild: discord.Guild) -> discord.Embed:
    pool = request_pool.get(guild.id, [])
    def sort_key(entry):
        uid, _ = entry
        member = guild.get_member(uid)
        if member:
            return member.display_name.lower()
        return f"zzz-{uid}"
    sorted_pool = sorted(pool, key=sort_key)
    new_lines = []
    for u, t in sorted_pool:
        info = next((m for m in movie_titles if m["title"] == t), None)
        poster = info["poster"] if info else ""
        trailer = info["trailer"] if info else ""
        member = guild.get_member(u)
        user_mention = member.mention if member else f"<@{u}>"
        new_lines.append(
            f"{user_mention} — **{t}**"
        )
    lines = new_lines
    description = "\n".join(lines) if lines else "Pool is empty — be the first to add a movie!"
    description += "\n\n**ADD UP TO 3 MOVIES TO THE POOL**\n"
    description += "• </pick:1444584815029522643> - Browse and pick from the dropdown menu\n"
    description += "• </search:1444418642103107675> - If you already know what to pick\n"
    description += "• </replace:1444418642103107676> - Replace one of your picks in the pool"
    return discord.Embed(
        title=movie_night_time(),
        description=description,
        color=0x2e2f33
    ).set_footer(text="Messages in this channel are deleted after 5 minutes")

async def update_pool_public_message(guild: discord.Guild):
    loc = pool_message_locations.get(guild.id)
    if not loc:
        return
    ch_id, msg_id = loc
    channel = guild.get_channel(ch_id)
    if not channel:
        return
    try:
        msg = await channel.fetch_message(msg_id)
        embed = await build_pool_embed(guild)
        await msg.edit(embed=embed)
    except:
        pass

async def get_qotd_sheet_and_tab():
    if gc is None or not SHEET_ID:
        raise RuntimeError("QOTD is not configured.")
    sh = gc.open_by_key(SHEET_ID)
    today = datetime.utcnow()
    tab = "Fall Season" if 10 <= today.month <= 11 else "Christmas" if today.month == 12 else "Regular"
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.sheet1
        tab = ws.title
        print(f"QOTD: worksheet '{tab}' not found, using first sheet.")
    return ws, tab

async def post_daily_qotd():
    if gc is None or not SHEET_ID or QOTD_CHANNEL_ID == 0:
        return
    channel = bot.get_channel(QOTD_CHANNEL_ID)
    if not channel:
        return
    worksheet, season = await get_qotd_sheet_and_tab()
    all_vals = worksheet.get_all_values()
    if len(all_vals) < 2:
        return
    questions = all_vals[1:]
    unused = []
    for row in questions:
        row += [""] * (2 - len(row))
        status_a, status_b = row[0].strip(), row[1].strip() if len(row) > 1 else ""
        question_text = row[1].strip() if len(row) > 1 else row[0].strip()
        if question_text and (not status_a or not status_b):
            unused.append(row)
    if not unused:
        await log_to_thread("QOTD: All questions used; resetting.")
        worksheet.update("A2:B", [[""] * 2 for _ in range(len(questions))])
        unused = questions
    chosen = pyrandom.choice(unused)
    chosen += [""] * (2 - len(chosen))
    question = chosen[1].strip() or chosen[0].strip()
    if not question:
        return
    colors = {"Regular": 0x9b59b6, "Fall Season": 0xe67e22, "Christmas": 0x00ff00}
    embed = discord.Embed(title="Question of the Day", description=question, color=colors.get(season, 0x9b59b6))
    embed.set_footer(text=f"{season} • Reply below!")
    await channel.send(embed=embed)
    row_idx = questions.index(chosen) + 2
    status_col = "A" if chosen[1].strip() else "B"
    worksheet.update(f"{status_col}{row_idx}", [[f"Used {datetime.utcnow().strftime('%Y-%m-%d')}"]])
    await log_to_thread(f"QOTD: Posted question from row {row_idx} ({season}).")

def find_role_by_name(guild: discord.Guild, name: str) -> discord.Role | None:
    name_lower = name.lower()
    for role in guild.roles:
        cleaned = role.name.replace("🎄", "").replace("🎃", "").replace("❄️", "").strip()
        if cleaned.lower() == name_lower:
            return role
    return None

async def apply_theme_for_today(guild: discord.Guild, today: str | None = None):
    if today is None:
        today = datetime.utcnow().strftime("%m-%d")
    removed_roles = await clear_theme_roles(guild)
    removed_emojis = await clear_theme_emojis(guild)
    added_roles = 0
    added_emojis = 0
    mode = "none"
    if "10-01" <= today <= "10-31":
        added_roles = await apply_theme_roles(guild, "halloween")
        added_emojis = await apply_theme_emojis(guild, "halloween")
        mode = "halloween"
    elif "12-01" <= today <= "12-26":
        added_roles = await apply_theme_roles(guild, "christmas")
        added_emojis = await apply_theme_emojis(guild, "christmas")
        mode = "christmas"
    await log_to_thread(f"theme_update guild={guild.id} today={today} mode={mode} roles_cleared={removed_roles} emojis_cleared={removed_emojis} roles_added={added_roles} emojis_added={added_emojis}")
    return mode, removed_roles, removed_emojis, added_roles, added_emojis

async def apply_theme_roles(guild: discord.Guild, theme: str) -> int:
    role_map = THEME_CHRISTMAS_ROLES if theme == "christmas" else THEME_HALLOWEEN_ROLES
    added = 0
    for color_name, base_keyword in role_map.items():
        color_role = find_role_by_name(guild, color_name)
        if not color_role:
            continue
        async for member in guild.fetch_members(limit=None):
            if any(base_keyword.lower() in r.name.lower() for r in member.roles):
                if color_role not in member.roles:
                    try:
                        await member.add_roles(color_role, reason=f"{theme.capitalize()} theme")
                        added += 1
                    except:
                        pass
    icon_url = ICON_CHRISTMAS_URL if theme == "christmas" else ICON_HALLOWEEN_URL
    await apply_icon_to_bot_and_server(guild, icon_url)
    return added

async def clear_theme_roles(guild: discord.Guild) -> int:
    removed = 0
    for color_name in {**THEME_CHRISTMAS_ROLES, **THEME_HALLOWEEN_ROLES}:
        role = find_role_by_name(guild, color_name)
        if role:
            async for member in guild.fetch_members(limit=None):
                if role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Theme ended")
                        removed += 1
                    except:
                        pass
    await apply_icon_to_bot_and_server(guild, ICON_DEFAULT_URL)
    return removed

async def apply_icon_to_bot_and_server(guild: discord.Guild, url: str):
    if not url:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return
                data = await resp.read()
        await bot.user.edit(avatar=data)
        await guild.edit(icon=data)
    except:
        pass

def _load_emoji_config_from_env(env_name: str) -> list[dict]:
    raw = os.getenv(env_name, "[]")
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            print(f"{env_name} loaded {len(data)} item(s)")
            return data
        print(f"{env_name} not a list: {type(data).__name__}")
    except Exception as e:
        print(f"{env_name} JSON error: {repr(e)}")
    return []

def _collect_theme_emoji_names() -> set[str]:
    names: set[str] = set()
    for env_name in ("THEME_CHRISTMAS_EMOJIS", "THEME_HALLOWEEN_EMOJIS"):
        config = _load_emoji_config_from_env(env_name)
        for item in config:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return names

async def apply_theme_emojis(guild: discord.Guild, theme: str) -> int:
    env_name = "THEME_CHRISTMAS_EMOJIS" if theme == "christmas" else "THEME_HALLOWEEN_EMOJIS"
    config = _load_emoji_config_from_env(env_name)
    if not config:
        print(f"{env_name} is empty or invalid")
        return 0
    created = 0
    existing_names = {e.name for e in guild.emojis}
    if hasattr(guild, "emoji_limit") and len(existing_names) >= guild.emoji_limit:
        print(f"{env_name}: emoji limit reached ({len(existing_names)}/{guild.emoji_limit}), skipping creation")
        return 0
    async with aiohttp.ClientSession() as session:
        for item in config:
            if not isinstance(item, dict):
                print(f"{env_name} bad item (not dict): {item!r}")
                continue
            name = item.get("name")
            url = item.get("url")
            if not isinstance(name, str) or not isinstance(url, str):
                print(f"{env_name} bad types: name={type(name).__name__}, url={type(url).__name__}")
                continue
            if not name or not url:
                print(f"{env_name} missing name or url: {item!r}")
                continue
            if name in existing_names:
                print(f"Emoji {name} already exists, skipping")
                continue
            try:
                async with session.get(url) as resp:
                    print(f"FETCH {name} {url} -> {resp.status}")
                    if resp.status != 200:
                        continue
                    data = await resp.read()
                emoji = await guild.create_custom_emoji(name=name, image=data, reason=f"{theme} emoji")
                print(f"EMOJI_CREATED {emoji.name} size={len(data)}")
                existing_names.add(emoji.name)
                created += 1
            except Exception as e:
                await log_exception(f"EMOJI_ERROR_{name}", e)
                continue
    await log_to_thread(f"{env_name}: created {created} emoji(s) in guild {guild.id}.")
    return created

async def clear_theme_emojis(guild: discord.Guild) -> int:
    names = _collect_theme_emoji_names()
    if not names:
        return 0
    removed = 0
    for emoji in list(guild.emojis):
        if emoji.name not in names:
            continue
        try:
            await emoji.delete(reason="Theme emoji cleanup")
            removed += 1
        except Exception as e:
            await log_exception(f"THEME_EMOJI_REMOVE_{emoji.name}", e)
            continue
    await log_to_thread(f"Theme emoji cleanup: removed {removed} emoji(s) in guild {guild.id}.")
    return removed

def movie_night_time() -> str:
    return "MOVIE NIGHTS START AT 6PM PACIFIC PST"


############### VIEWS / UI COMPONENTS ###############
class MediaPagerView(discord.ui.View):
    def __init__(self, category: str, page: int = 0):
        super().__init__(timeout=120)
        self.category = category
        self.page = page

        self.dropdown = discord.ui.Select(
            placeholder="✅ Select One",
            min_values=1,
            max_values=1,
            options=[]
        )
        self.dropdown.callback = self.on_select
        self.add_item(self.dropdown)

    def _items(self):
        return movie_titles

    def _page_size(self):
        return min(PAGE_SIZE, 25)

    def _max_page(self):
        items = self._items()
        if not items:
            return 0
        size = self._page_size()
        return max(0, (len(items) - 1) // size)

    def _page_slice(self):
        items = self._items()
        size = self._page_size()

        if not items:
            return [], 0

        max_page = self._max_page()
        self.page = max(0, min(self.page, max_page))

        start = self.page * size
        end = min(start + size, len(items))
        return items[start:end], start

    def _build_content(self):
        items = self._items()
        if not items:
            return "No items."

        max_page = self._max_page()
        page_items, _ = self._page_slice()

        lines = [f"{i}. {m['title']}" for i, m in enumerate(page_items, 1)]

        header = f"Movies • Page {self.page+1}/{max_page+1} ({len(items)} total)"
        return f"{header}\n```text\n" + "\n".join(lines if lines else ["Empty"]) + "\n```"

    def _refresh_dropdown(self):
        page_items, start = self._page_slice()
        options = []

        for i, item in enumerate(page_items):
            index = start + i
            title = item["title"]
            label = f"{i+1}. {title}"
            if len(label) > 100:
                label = label[:97] + "..."
            options.append(discord.SelectOption(label=label, value=str(index)))

        if not options:
            options.append(discord.SelectOption(label="No items on this page", value="none", default=True))

        self.dropdown.options = options

    async def send_initial(self, ctx):
        self._refresh_dropdown()
        await ctx.respond(self._build_content(), view=self, ephemeral=True)

    async def on_select(self, interaction: discord.Interaction):
        if not self.dropdown.values:
            return await interaction.response.send_message("No selection.", ephemeral=True)

        value = self.dropdown.values[0]
        if value == "none":
            return await interaction.response.send_message("Nothing to add from this page.", ephemeral=True)

        try:
            index = int(value)
        except ValueError:
            return await interaction.response.send_message("Invalid selection.", ephemeral=True)

        items = self._items()
        if index < 0 or index >= len(items):
            return await interaction.response.send_message("That item no longer exists.", ephemeral=True)

        selected = items[index]
        movie_title = selected["title"]

        canon = next((m for m in movie_titles if m["title"].lower() == movie_title.lower()), None)
        if not canon:
            return await interaction.response.send_message("That movie is no longer in the library.", ephemeral=True)

        movie_title = canon["title"]
        guild = interaction.guild
        user = interaction.user

        if guild is None:
            return await interaction.response.send_message("This can only be used in a server.", ephemeral=True)

        pool = request_pool.setdefault(guild.id, [])

        if any(t.lower() == movie_title.lower() for _, t in pool):
            return await interaction.response.send_message(
                "**This movie is already in today’s pool!** Only one copy allowed.",
                ephemeral=True
            )

        user_count = sum(1 for uid, _ in pool if uid == user.id)
        if user_count >= MAX_POOL_ENTRIES_PER_USER:
            return await interaction.response.send_message(
                f"You already have `{MAX_POOL_ENTRIES_PER_USER}` pick(s) in the pool. Use </replace:1444418642103107676> to swap one.",
                ephemeral=True,
            )

        pool.append((user.id, movie_title))
        await save_request_pool()
        await update_pool_public_message(guild)

        await interaction.response.send_message(
            f"Added **{movie_title}** • You now have `{user_count + 1}` pick(s) in the pool.",
            ephemeral=True,
        )

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, button, interaction):
        self.page -= 1
        self._refresh_dropdown()
        await interaction.response.edit_message(content=self._build_content(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, button, interaction):
        self.page += 1
        self._refresh_dropdown()
        await interaction.response.edit_message(content=self._build_content(), view=self)

class MovieEntryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Add to Pool", style=discord.ButtonStyle.primary, custom_id="movie_entry_add_to_pool")
    async def add_to_pool(self, button, interaction: discord.Interaction):
        message = interaction.message
        if not message or not message.content:
            return await interaction.response.send_message("I can't read this movie title.", ephemeral=True)
        lines = message.content.splitlines()
        if not lines:
            return await interaction.response.send_message("I can't read this movie title.", ephemeral=True)
        movie_title = lines[0].strip()
        guild = interaction.guild
        user = interaction.user
        if guild is None:
            return await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
        canon = next((m for m in movie_titles if m["title"].lower() == movie_title.lower()), None)
        if not canon:
            return await interaction.response.send_message("That movie is no longer in the library.", ephemeral=True)
        movie_title = canon["title"]
        pool = request_pool.setdefault(guild.id, [])
        if any(t.lower() == movie_title.lower() for _, t in pool):
            return await interaction.response.send_message(
                "**This movie is already in today’s pool!** Only one copy allowed.",
                ephemeral=True,
            )
        user_count = sum(1 for uid, _ in pool if uid == user.id)
        if user_count >= MAX_POOL_ENTRIES_PER_USER:
            return await interaction.response.send_message(
                f"You already have `{MAX_POOL_ENTRIES_PER_USER}` pick(s) in the pool. Use </replace:1444418642103107676> to swap one.",
                ephemeral=True,
            )
        pool.append((user.id, movie_title))
        await save_request_pool()
        await update_pool_public_message(guild)
        await interaction.response.send_message(
            f"Added **{movie_title}** • You now have `{user_count + 1}` pick(s) in the pool.",
            ephemeral=True,
        )


############### AUTOCOMPLETE FUNCTIONS ###############
async def movie_autocomplete(ctx: discord.AutocompleteContext):
    query = (ctx.value or "").lower()
    titles = [m["title"] for m in movie_titles]
    if query:
        titles = [t for t in titles if query in t.lower()]
    return titles[:25]

async def my_pool_movie_autocomplete(ctx: discord.AutocompleteContext):
    guild = ctx.interaction.guild
    if guild is None:
        return []
    pool = request_pool.get(guild.id, [])
    user_id = ctx.interaction.user.id
    titles = [title for uid, title in pool if uid == user_id]
    query = (ctx.value or "").lower()
    if query:
        titles = [t for t in titles if query in t.lower()]
    return titles[:25]


############### BACKGROUND TASKS & SCHEDULERS ###############
async def qotd_scheduler():
    await bot.wait_until_ready()
    TARGET_HOUR_UTC = 17
    TARGET_MINUTE = 0
    await log_to_thread("qotd_scheduler started.")
    while not bot.is_closed():
        now = datetime.utcnow()
        if now.hour == TARGET_HOUR_UTC and now.minute == TARGET_MINUTE:
            try:
                await post_daily_qotd()
            except Exception as e:
                await log_exception("qotd_scheduler", e)
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def theme_scheduler():
    await bot.wait_until_ready()
    TARGET_HOUR_UTC = 9
    TARGET_MINUTE = 0
    await log_to_thread("theme_scheduler started.")
    while not bot.is_closed():
        now = datetime.utcnow()
        if now.hour == TARGET_HOUR_UTC and now.minute == TARGET_MINUTE:
            today = now.strftime("%m-%d")
            for guild in bot.guilds:
                try:
                    await apply_theme_for_today(guild, today)
                except Exception as e:
                    await log_exception(f"theme_scheduler_guild_{guild.id}", e)
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def birthday_checker():
    await bot.wait_until_ready()
    TARGET_HOUR_UTC = 15
    TARGET_MINUTE = 0
    await log_to_thread("birthday_checker started.")
    while not bot.is_closed():
        now = datetime.utcnow()
        if now.hour == TARGET_HOUR_UTC and now.minute == TARGET_MINUTE:
            today = now.strftime("%m-%d")
            for guild in bot.guilds:
                try:
                    role = guild.get_role(BIRTHDAY_ROLE_ID)
                    if not role:
                        continue
                    bdays = await get_guild_birthdays(guild.id)
                    for member in guild.members:
                        if bdays.get(str(member.id)) == today:
                            if role not in member.roles:
                                await member.add_roles(role, reason="Birthday!")
                        else:
                            if role in member.roles:
                                await member.remove_roles(role, reason="Birthday over")
                    await log_to_thread(f"birthday_checker guild={guild.id} today={today} birthdays_tracked={len(bdays)}")
                except Exception as e:
                    await log_exception(f"birthday_checker_guild_{guild.id}", e)
            await asyncio.sleep(61)
        await asyncio.sleep(30)


############### EVENT HANDLERS ###############
@bot.event
async def on_ready():
    print(f"{bot.user} is online!")
    bot.add_view(GameNotificationView())
    await run_all_inits_with_logging()
    await log_to_bot_channel(f"Bot ready as {bot.user} in {len(bot.guilds)} guild(s).")

    global startup_logging_done, startup_log_buffer
    try:
        channel = bot.get_channel(BOT_LOG_THREAD_ID) if BOT_LOG_THREAD_ID != 0 else None
        if channel and startup_log_buffer:
            big_text = "---------------------------- STARTUP LOGS ----------------------------\n" + "\n".join(startup_log_buffer)
            if len(big_text) > 1900:
                big_text = big_text[:1900]
            await channel.send(big_text)
    except Exception:
        pass
    startup_logging_done = True
    startup_log_buffer = []

    await init_last_activity_storage()
    bot.loop.create_task(twitch_watcher())
    bot.loop.create_task(infected_watcher())
    bot.loop.create_task(member_join_watcher())
    bot.loop.create_task(activity_inactive_watcher())
    if sticky_storage_message_id is None:
        print("STORAGE NOT INITIALIZED — Run /sticky_init, /prize_init and /deadchat_init")
    else:
        await initialize_dead_chat()

@bot.event
async def on_member_join(member):
    try:
        await member.send("Welcome! Add your birthday here → https://discord.com/channels/1205041211610501120/1440989357535395911/1440989655515271248")
    except:
        pass

@bot.event
async def on_voice_state_update(member, before, after):
    vc_id = 1331501272804884490
    role = member.guild.get_role(1444555985728442390)
    if not role:
        return

    if after.channel and after.channel.id == vc_id:
        if role not in member.roles:
            await member.add_roles(role, reason="Joined VC")
    elif before.channel and before.channel.id == vc_id:
        if role in member.roles:
            await member.remove_roles(role, reason="Left VC")

@bot.event
async def on_application_command_error(ctx, error):
    await log_exception("application_command_error", error)
    try:
        await ctx.respond("An internal error occurred.", ephemeral=True)
    except Exception:
        pass

@bot.event
async def on_error(event, *args, **kwargs):
    exc_type, exc, tb = sys.exc_info()
    if exc is None:
        await log_to_thread(f"Unhandled error in event {event} with no exception info.")
    else:
        await log_exception(f"Unhandled error in event {event}", exc)


############### COMMAND GROUPS ###############
@bot.slash_command(name="editbotmsg", description="Edit a bot message in this channel with up to 4 lines")
async def editbotmsg(
    ctx,
    message_id: str,
    line1: str,
    line2: str = "",
    line3: str = "",
    line4: str = ""
):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    try:
        msg_id_int = int(message_id)
    except ValueError:
        return await ctx.respond("Invalid message ID.", ephemeral=True)
    try:
        msg = await ctx.channel.fetch_message(msg_id_int)
    except discord.NotFound:
        return await ctx.respond("Message not found in this channel.", ephemeral=True)
    except discord.Forbidden:
        return await ctx.respond("I cannot access that message.", ephemeral=True)
    except discord.HTTPException:
        return await ctx.respond("Error fetching that message.", ephemeral=True)
    if msg.author.id != bot.user.id:
        return await ctx.respond("That message was not sent by me.", ephemeral=True)
    new_content = "\n".join([line for line in [line1, line2, line3, line4] if line.strip() != ""])
    await msg.edit(content=new_content)
    await ctx.respond("Message updated.", ephemeral=True)

@bot.slash_command(name="set", description="Share your birthday with the server")
async def set_birthday_self(ctx, month: discord.Option(str, choices=MONTH_CHOICES), day: int):
    mm_dd = build_mm_dd(month, day)
    if not mm_dd:
        return await ctx.respond("Invalid date.", ephemeral=True)
    await set_birthday(ctx.guild.id, ctx.author.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Birthday set to `{mm_dd}`!", ephemeral=True)

@bot.slash_command(name="set_for", description="Add a birthday for a member")
async def set_for(ctx, member: discord.Member, month: discord.Option(str, choices=MONTH_CHOICES), day: int):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    mm_dd = build_mm_dd(month, day)
    if not mm_dd:
        return await ctx.respond("Invalid date.", ephemeral=True)
    await set_birthday(ctx.guild.id, member.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Set {member.mention}'s birthday to `{mm_dd}`", ephemeral=True)

@bot.slash_command(name="remove_for", description="Remove a members birthday")
async def remove_for(ctx, member: discord.Member):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    data = await _load_storage_message()
    gid = str(ctx.guild.id)
    entry = data.get(gid)
    removed = False
    if isinstance(entry, dict):
        if isinstance(entry.get("birthdays"), dict):
            if entry["birthdays"].pop(str(member.id), None):
                removed = True
        else:
            if entry.pop(str(member.id), None):
                removed = True
            entry = {"birthdays": entry}
            data[gid] = entry
    if removed:
        await _save_storage_message(data)
        await update_birthday_list_message(ctx.guild)
        await ctx.respond(f"Removed birthday for {member.mention}", ephemeral=True)
    else:
        await ctx.respond("No birthday found.", ephemeral=True)

@bot.slash_command(name="birthdays", description="View everyones birthdays")
async def birthdays_cmd(ctx):
    await ctx.respond(embed=await build_birthday_embed(ctx.guild), ephemeral=True)

@bot.slash_command(name="birthdays_public", description="Create or update the public birthday list message")
async def birthdays_public(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    embed = await build_birthday_embed(ctx.guild)
    loc = await get_birthday_public_location(ctx.guild.id)
    if loc:
        ch_id, msg_id = loc
        channel = ctx.guild.get_channel(ch_id)
        if channel:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))
                await ctx.respond("Updated the existing public birthday list message.", ephemeral=True)
                return
            except:
                pass
    msg = await ctx.channel.send(embed=embed)
    await set_birthday_public_location(ctx.guild.id, ctx.channel.id, msg.id)
    await ctx.respond("Created a new public birthday list message in this channel.", ephemeral=True)

@bot.slash_command(name="media_reload", description="Reload movie list from Google Sheets")
async def media_reload(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.defer(ephemeral=True)
    await initialize_media_lists()
    await ctx.followup.send("Reloaded movie list from Google Sheets.", ephemeral=True)

@bot.slash_command(name="library_sync", description="Sync movie library messages with the Movies sheet")
async def library_sync(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    if MOVIE_STORAGE_CHANNEL_ID == 0:
        return await ctx.respond("MOVIE_STORAGE_CHANNEL_ID is not configured.", ephemeral=True)
    await ctx.defer(ephemeral=True)
    await initialize_media_lists()
    await sync_movie_library_messages()
    await ctx.followup.send("Library messages synced with Google Sheets.", ephemeral=True)

@bot.slash_command(name="pool_remove", description="Admin: Remove a pick from today's movie pool")
async def pool_remove(
    ctx,
    user: discord.Option(discord.Member, "User whose pick to remove", required=False),
    title: discord.Option(str, "Exact title to remove (case-insensitive)", required=False, autocomplete=movie_autocomplete),
):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.respond("Pool is empty.", ephemeral=True)
    if not user and not title:
        return await ctx.respond("Specify either a user or a title.", ephemeral=True)
    removed = []
    new_pool = []
    target_title = title.lower().strip() if title else None
    target_uid = user.id if user else None
    for uid, movie_title in pool:
        match = False
        if target_uid and uid == target_uid:
            if not target_title or movie_title.lower() == target_title:
                match = True
        elif target_title and movie_title.lower() == target_title:
            match = True
        if match:
            member = ctx.guild.get_member(uid)
            mention = member.mention if member else f"<@{uid}>"
            removed.append(f"{mention} — **{movie_title}**")
        else:
            new_pool.append((uid, movie_title))
    if not removed:
        return await ctx.respond("No matching pick found.", ephemeral=True)
    request_pool[ctx.guild.id] = new_pool
    await save_request_pool()
    await update_pool_public_message(ctx.guild)
    await ctx.respond("Removed:\n" + "\n".join(removed), ephemeral=True)

if ENABLE_TV_IN_PICK:
    @bot.slash_command(name="pick", description="Browse the movie or TV collection and add picks to today's pool")
    async def pick_browser(ctx, category: discord.Option(str, choices=["movies", "shows"], default="movies")):
        view = MediaPagerView(category)
        await view.send_initial(ctx)
else:
    @bot.slash_command(name="pick", description="Browse the movie collection and add picks to today's pool")
    async def pick_browser(ctx):
        view = MediaPagerView("movies")
        await view.send_initial(ctx)

@bot.slash_command(name="search", description="Search the movie list and add your pick")
async def pick(ctx, title: discord.Option(str, autocomplete=movie_autocomplete)):
    if not movie_titles:
        return await ctx.respond("Movie list not loaded.", ephemeral=True)
    canon = next((t for t in movie_titles if t["title"].lower() == title.strip().lower()), None)
    if not canon:
        return await ctx.respond("That movie isn't in the library.", ephemeral=True)
    movie_title = canon["title"]
    pool = request_pool.setdefault(ctx.guild.id, [])
    if any(t.lower() == movie_title.lower() for _, t in pool):
        return await ctx.respond("**This movie is already in today’s pool!** Only one copy allowed.", ephemeral=True)
    user_count = sum(1 for uid, _ in pool if uid == ctx.author.id)
    if user_count >= MAX_POOL_ENTRIES_PER_USER:
        return await ctx.respond(
            f"You already have `{MAX_POOL_ENTRIES_PER_USER}` pick(s) in the pool. Use `/replace` to swap one.",
            ephemeral=True,
        )
    pool.append((ctx.author.id, movie_title))
    await save_request_pool()
    await update_pool_public_message(ctx.guild)
    await ctx.respond(f"Added **{movie_title}** • You now have `{user_count + 1}` pick(s) in the pool.", ephemeral=True)

@bot.slash_command(name="replace", description="Replace one of your existing picks in the pool")
async def pick_replace(
    ctx,
    old_title: discord.Option(str, autocomplete=my_pool_movie_autocomplete),
    new_title: discord.Option(str, autocomplete=movie_autocomplete),
):
    if not movie_titles:
        return await ctx.respond("Movie list not loaded.", ephemeral=True)
    canon_new = next((m for m in movie_titles if m["title"].lower() == new_title.strip().lower()), None)
    if not canon_new:
        return await ctx.respond("That movie isn't in the library.", ephemeral=True)
    new_movie_title = canon_new["title"]
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.respond("Pool is empty.", ephemeral=True)
    indices = [
        i for i, (uid, title) in enumerate(pool)
        if uid == ctx.author.id and title == old_title
    ]
    if not indices:
        return await ctx.respond("That pick is not in the pool as yours.", ephemeral=True)
    idx = indices[0]
    pool[idx] = (ctx.author.id, new_movie_title)
    request_pool[ctx.guild.id] = pool
    await save_request_pool()
    await update_pool_public_message(ctx.guild)
    await ctx.respond(
        f"Replaced **{old_title}** with **{new_movie_title}** in the pool.",
        ephemeral=True
    )

@bot.slash_command(name="pool", description="See what movies have been added to todays pool")
async def pool(ctx):
    embed = await build_pool_embed(ctx.guild)
    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name="random", description="Pick tonight's winner — unpicked movies roll over to tomorrow!")
async def random_pick(ctx):
    await ctx.defer(ephemeral=True)
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.followup.send("Pool is empty.", ephemeral=True)

    winner_idx = pyrandom.randrange(len(pool))
    winner_id, winner_title = pool[winner_idx]

    request_pool[ctx.guild.id] = [e for i, e in enumerate(pool) if i != winner_idx]
    await save_request_pool()
    await update_pool_public_message(ctx.guild)

    member = ctx.guild.get_member(winner_id)
    mention = member.mention if member else f"<@{winner_id}>"

    rollover = len(request_pool[ctx.guild.id])
    rollover_text = (
        f"\n\n{rollover} movie{'s' if rollover != 1 else ''} rolled over to the next pool"
        if rollover else ""
    )

    first_text = (
        f"Pool Winner: **{winner_title}**\n"
        f"{mention}'s pick!{rollover_text}\n\n"
    )

    await ctx.channel.send(first_text)

    second_channel = ctx.guild.get_channel(RATING_CHANNEL_ID)
    if second_channel:
        second_text = f"**{winner_title}**"
        msg = await second_channel.send(second_text)
        for emoji in ["😍", "😃", "🙂", "🫤", "😒", "🤢"]:
            await msg.add_reaction(emoji)
        summary = "Winner announced here and in the rating channel."
    else:
        summary = "Winner announced here. Rating channel not configured."

    await ctx.followup.send(summary, ephemeral=True)

@bot.slash_command(name="color", description="Change the color of the Dead Chat role")
async def color_cycle(ctx):
    dead_chat_role = ctx.guild.get_role(DEAD_CHAT_ROLE_ID) if DEAD_CHAT_ROLE_ID != 0 else None
    if dead_chat_role is None and DEAD_CHAT_ROLE_NAME:
        dead_chat_role = discord.utils.get(ctx.guild.roles, name=DEAD_CHAT_ROLE_NAME)
    if dead_chat_role is None:
        return await ctx.respond("Dead Chat role is not configured correctly.", ephemeral=True)
    if dead_chat_role not in ctx.author.roles:
        return await ctx.respond("You need the Dead Chat role to use this command!", ephemeral=True)
    colors = DEAD_CHAT_COLORS
    current_index = next((i for i, c in enumerate(colors) if c.value == dead_chat_role.color.value), None)
    next_index = 0 if current_index is None else (current_index + 1) % len(colors)
    next_color = colors[next_index]
    try:
        await dead_chat_role.edit(color=next_color, reason="Dead Chat color cycle")
    except discord.Forbidden:
        return await ctx.respond("I don't have permission to edit the Dead Chat role.", ephemeral=True)
    await ctx.respond(f"Changed **Dead Chat** role color (step {next_index + 1}/{len(colors)} in the cycle).", ephemeral=True)

@bot.slash_command(name="say")
async def say(ctx, message: str):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.channel.send(message)
    await ctx.respond("Sent!", ephemeral=True)

@bot.slash_command(name="qotd_send", description="Post today's QOTD immediately (admin only)")
async def qotd_send(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only", ephemeral=True)
    await ctx.defer(ephemeral=True)
    try:
        await post_daily_qotd()
    except Exception as e:
        await log_exception("qotd_send", e)
        return await ctx.followup.send("QOTD error: an internal error occurred.", ephemeral=True)
    await ctx.followup.send("QOTD posted!", ephemeral=True)

@bot.slash_command(name="pool_public", description="Create or update the public pool message")
async def pool_public(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    embed = await build_pool_embed(ctx.guild)
    loc = pool_message_locations.get(ctx.guild.id)
    if loc:
        ch_id, msg_id = loc
        channel = ctx.guild.get_channel(ch_id)
        if channel:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                return await ctx.respond("Updated the public pool message.", ephemeral=True)
            except:
                pass
    msg = await ctx.channel.send(embed=embed)
    pool_message_locations[ctx.guild.id] = (ctx.channel.id, msg.id)
    await save_request_pool()
    await ctx.respond("Created a new public pool message in this channel.", ephemeral=True)

@bot.slash_command(name="theme_update", description="Recheck the date and apply the current seasonal theme for this server")
async def theme_update(ctx):
    if ctx.guild is None:
        return await ctx.respond("This can only be used in a server.", ephemeral=True)
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.defer(ephemeral=True)
    today = datetime.utcnow().strftime("%m-%d")
    mode, removed_roles, removed_emojis, added_roles, added_emojis = await apply_theme_for_today(ctx.guild, today)
    if mode == "halloween":
        label = "Halloween theme applied."
    elif mode == "christmas":
        label = "Christmas theme applied."
    else:
        label = "Cleared theme and reverted to default."
    summary = f"{label}\nRoles cleared: {removed_roles}\nEmojis cleared: {removed_emojis}\nRoles added: {added_roles}\nEmojis added: {added_emojis}"
    await ctx.followup.send(summary, ephemeral=True)


############### ON_READY & BOT START ###############
bot.run(os.getenv("TOKEN"))
