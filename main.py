# ============================================================
# THIS IS THE MEMBER BOT
#
# Grok & ChatGPT RULES FOR THIS FILE (DO NOT VIOLATE)
#
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
#
# • Do NOT add any other sections.
# • Do NOT add comments, notes, or explanations inside the code.
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
MOVIE_NIGHT_ANNOUNCEMENT_CHANNEL_ID = _env_int("MOVIE_NIGHT_ANNOUNCEMENT_CHANNEL_ID", 0)  # ・Movies
SECOND_MOVIE_ANNOUNCEMENT_CHANNEL_ID = _env_int("SECOND_MOVIE_ANNOUNCEMENT_CHANNEL_ID", 0)  # ・Ratings
MOVIE_STORAGE_CHANNEL_ID = _env_int("MOVIE_STORAGE_CHANNEL_ID", 0)  # For trailer messages linked to sheets
MAX_POOL_ENTRIES_PER_USER = _env_int("MAX_POOL_ENTRIES_PER_USER", 3) 
PAGE_SIZE = 25

QOTD_CHANNEL_ID = _env_int("QOTD_CHANNEL_ID", 0)

DEFAULT_ICON_URL = os.getenv("DEFAULT_ICON_URL", "")
CHRISTMAS_ICON_URL = os.getenv("CHRISTMAS_ICON_URL", "")
HALLOWEEN_ICON_URL = os.getenv("HALLOWEEN_ICON_URL", "")
CHRISTMAS_ROLES = {"Cranberry": "Admin", "Candy Cane": "Original Member", "Grinch": "Member", "Christmas": "Bots"}
HALLOWEEN_ROLES = {"Cauldron": "Admin", "Candy": "Original Member", "Witchy": "Member", "Halloween": "Bots"}

DEAD_CHAT_ROLE_ID = _env_int("DEAD_CHAT_ROLE_ID", 0)
DEAD_CHAT_ROLE_NAME = os.getenv("DEAD_CHAT_ROLE_NAME", "Dead Chat")
DEAD_CHAT_COLORS = [discord.Color.red(), discord.Color.orange(), discord.Color.gold(), discord.Color.green(), discord.Color.blue(), discord.Color.purple(), discord.Color.magenta(), discord.Color.teal()]

BIRTHDAY_ROLE_ID = _env_int("BIRTHDAY_ROLE_ID", 0)  # The role given when it is their birthday
BIRTHDAY_STORAGE_CHANNEL_ID = _env_int("BIRTHDAY_STORAGE_CHANNEL_ID", 0)
BIRTHDAY_LIST_CHANNEL_ID = _env_int("BIRTHDAY_LIST_CHANNEL_ID", 0)
BIRTHDAY_LIST_MESSAGE_ID = _env_int("BIRTHDAY_LIST_MESSAGE_ID", 0)
MONTH_CHOICES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
MONTH_TO_NUM = {name: f"{i:02d}" for i, name in enumerate(MONTH_CHOICES, start=1)}



############### GLOBAL STATE / STORAGE ###############
storage_message_id: int | None = None
pool_storage_message_id: int | None = None
pool_message_locations: dict[int, tuple[int, int]] = {}
movie_titles: list[dict] = []
request_pool: dict[int, list[tuple[int, str]]] = {}


############### HELPER FUNCTIONS ###############
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
    if BIRTHDAY_LIST_CHANNEL_ID and BIRTHDAY_LIST_MESSAGE_ID:
        return BIRTHDAY_LIST_CHANNEL_ID, BIRTHDAY_LIST_MESSAGE_ID
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
        print("QOTD: All questions used; resetting.")
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
    print(f"QOTD: Posted question from row {row_idx} ({season}).")

def find_role_by_name(guild: discord.Guild, name: str) -> discord.Role | None:
    name_lower = name.lower()
    for role in guild.roles:
        cleaned = role.name.replace("🎄", "").replace("🎃", "").replace("❄️", "").strip()
        if cleaned.lower() == name_lower:
            return role
    return None

async def apply_holiday_theme(guild: discord.Guild, holiday: str) -> int:
    role_map = CHRISTMAS_ROLES if holiday == "christmas" else HALLOWEEN_ROLES
    added = 0
    for color_name, base_keyword in role_map.items():
        color_role = find_role_by_name(guild, color_name)
        if not color_role:
            continue
        async for member in guild.fetch_members(limit=None):
            if any(base_keyword.lower() in r.name.lower() for r in member.roles):
                if color_role not in member.roles:
                    try:
                        await member.add_roles(color_role, reason=f"{holiday.capitalize()} theme")
                        added += 1
                    except:
                        pass
    icon_url = CHRISTMAS_ICON_URL if holiday == "christmas" else HALLOWEEN_ICON_URL
    await apply_icon_to_bot_and_server(guild, icon_url)
    return added

async def clear_holiday_theme(guild: discord.Guild) -> int:
    removed = 0
    for color_name in {**CHRISTMAS_ROLES, **HALLOWEEN_ROLES}:
        role = find_role_by_name(guild, color_name)
        if role:
            async for member in guild.fetch_members(limit=None):
                if role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Holiday theme ended")
                        removed += 1
                    except:
                        pass
    await apply_icon_to_bot_and_server(guild, DEFAULT_ICON_URL)
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

def _collect_holiday_emoji_names() -> set[str]:
    names: set[str] = set()
    for env_name in ("CHRISTMAS_EMOJIS", "HALLOWEEN_EMOJIS"):
        config = _load_emoji_config_from_env(env_name)
        for item in config:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return names

async def apply_holiday_emojis(guild: discord.Guild, holiday: str) -> int:
    env_name = "CHRISTMAS_EMOJIS" if holiday == "christmas" else "HALLOWEEN_EMOJIS"
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
                emoji = await guild.create_custom_emoji(name=name, image=data, reason=f"{holiday} emoji")
                print(f"EMOJI_CREATED {emoji.name} size={len(data)}")
                existing_names.add(emoji.name)
                created += 1
            except Exception as e:
                print(f"EMOJI_ERROR {name}: {repr(e)}")
                continue
    return created

async def clear_holiday_emojis(guild: discord.Guild) -> int:
    names = _collect_holiday_emoji_names()
    if not names:
        return 0
    removed = 0
    for emoji in list(guild.emojis):
        if emoji.name not in names:
            continue
        try:
            await emoji.delete(reason="Holiday emoji cleanup")
            removed += 1
        except:
            continue
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
    while not bot.is_closed():
        now = datetime.utcnow()
        if now.hour == TARGET_HOUR_UTC and now.minute == TARGET_MINUTE:
            try:
                await post_daily_qotd()
            except Exception as e:
                print("QOTD scheduler error:", repr(e))
                traceback.print_exc()
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def holiday_scheduler():
    await bot.wait_until_ready()
    TARGET_HOUR_UTC = 9
    TARGET_MINUTE = 0
    while not bot.is_closed():
        now = datetime.utcnow()
        if now.hour == TARGET_HOUR_UTC and now.minute == TARGET_MINUTE:
            today = now.strftime("%m-%d")
            for guild in bot.guilds:
                if "10-01" <= today <= "10-31":
                    await clear_holiday_theme(guild)
                    await apply_holiday_theme(guild, "halloween")
                    await clear_holiday_emojis(guild)
                    await apply_holiday_emojis(guild, "halloween")
                elif "12-01" <= today <= "12-26":
                    await clear_holiday_theme(guild)
                    await apply_holiday_theme(guild, "christmas")
                    await clear_holiday_emojis(guild)
                    await apply_holiday_emojis(guild, "christmas")
                else:
                    await clear_holiday_theme(guild)
                    await clear_holiday_emojis(guild)
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def birthday_checker():
    await bot.wait_until_ready()
    TARGET_HOUR_UTC = 15
    TARGET_MINUTE = 0
    while not bot.is_closed():
        now = datetime.utcnow()
        if now.hour == TARGET_HOUR_UTC and now.minute == TARGET_MINUTE:
            today = now.strftime("%m-%d")
            for guild in bot.guilds:
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
            await asyncio.sleep(61)
        await asyncio.sleep(30)


############### EVENT HANDLERS ###############
@bot.event
async def on_ready():
    print(f"{bot.user} online!")
    bot.add_view(MovieEntryView())
    try:
        await initialize_storage_message()
        await initialize_media_lists()
        await load_request_pool()
    except Exception as e:
        print("INIT ERROR:", repr(e))
        traceback.print_exc()
    bot.loop.create_task(birthday_checker())
    bot.loop.create_task(qotd_scheduler())
    bot.loop.create_task(holiday_scheduler())
    print("QOTD scheduler started + Google Sheets ready!")

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
    primary_channel = ctx.guild.get_channel(MOVIE_NIGHT_ANNOUNCEMENT_CHANNEL_ID)
    if primary_channel:
        await primary_channel.send(first_text)
    second_channel = ctx.guild.get_channel(SECOND_MOVIE_ANNOUNCEMENT_CHANNEL_ID)
    if second_channel:
        second_text = (
            f"**{winner_title}**"
        )
        msg = await second_channel.send(second_text)
        for emoji in ["😍", "😃", "🙂", "🫤", "😒", "🤢"]:
            await msg.add_reaction(emoji)
    await ctx.followup.send("Winner announced in both channels.", ephemeral=True)

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
        print("qotd_send ERROR:", repr(e))
        traceback.print_exc()
        return await ctx.followup.send(f"QOTD error: `{type(e).__name__}` – `{repr(e)}`", ephemeral=True)
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


############### ON_READY & BOT START ###############
bot.run(os.getenv("TOKEN"))
