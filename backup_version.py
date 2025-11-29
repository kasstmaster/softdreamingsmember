# ============================================================
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
from datetime import datetime
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

BIRTHDAY_ROLE_ID = _env_int("BIRTHDAY_ROLE_ID", 1217937235840598026)
BIRTHDAY_STORAGE_CHANNEL_ID = _env_int("BIRTHDAY_STORAGE_CHANNEL_ID", 1440912334813134868)
BIRTHDAY_LIST_CHANNEL_ID = 1440989357535395911
BIRTHDAY_LIST_MESSAGE_ID = 1440989655515271248
MOVIE_STORAGE_CHANNEL_ID = _env_int("MOVIE_STORAGE_CHANNEL_ID", 0)
TV_STORAGE_CHANNEL_ID = _env_int("TV_STORAGE_CHANNEL_ID", 0)
DEAD_CHAT_ROLE_ID = _env_int("DEAD_CHAT_ROLE_ID", 0)
DEAD_CHAT_ROLE_NAME = os.getenv("DEAD_CHAT_ROLE_NAME", "Dead Chat")
QOTD_CHANNEL_ID = _env_int("QOTD_CHANNEL_ID", 0)

CHRISTMAS_ICON_URL = os.getenv("CHRISTMAS_ICON_URL", "")
HALLOWEEN_ICON_URL = os.getenv("HALLOWEEN_ICON_URL", "")
DEFAULT_ICON_URL = os.getenv("DEFAULT_ICON_URL", "")

CHRISTMAS_ROLES = {"Cranberry": "Admin", "lights": "Original Member", "Grinch": "Member", "Christmas": "Bots"}
HALLOWEEN_ROLES = {"Cauldron": "Admin", "Candy": "Original Member", "Witchy": "Member", "Halloween": "Bots"}

DEAD_CHAT_COLORS = [
    discord.Color.red(), discord.Color.orange(), discord.Color.gold(),
    discord.Color.green(), discord.Color.blue(), discord.Color.purple(),
    discord.Color.magenta(), discord.Color.teal(),
]

MONTH_CHOICES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_TO_NUM = {name: f"{i:02d}" for i, name in enumerate(MONTH_CHOICES, start=1)}

PAGE_SIZE = 25


############### GLOBAL STATE / STORAGE ###############
storage_message_id: int | None = None
movie_titles: list[str] = []
tv_titles: list[str] = []
request_pool: dict[int, list[tuple[int, str]]] = {}


############### HELPER FUNCTIONS ###############
def build_mm_dd(month_name: str, day: int) -> str | None:
    month_num = MONTH_TO_NUM.get(month_name)
    if not month_num or not (1 <= day <= 31):
        return None
    return f"{month_num}-{day:02d}"

async def initialize_storage_message():
    global storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel:
        return
    async for msg in channel.history(limit=50):
        if msg.author == bot.user:
            storage_message_id = msg.id
            return
    msg = await channel.send("{}")
    storage_message_id = msg.id

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

async def _load_titles_from_channel(channel_id: int) -> list[str]:
    ch = bot.get_channel(channel_id)
    if not isinstance(ch, discord.TextChannel):
        return []
    titles = []
    try:
        async for msg in ch.history(limit=None, oldest_first=True):
            if (content := (msg.content or "").strip()):
                titles.append(content)
    except:
        pass
    return sorted(set(titles), key=str.lower)

async def initialize_media_lists():
    global movie_titles, tv_titles
    if MOVIE_STORAGE_CHANNEL_ID:
        movie_titles = await _load_titles_from_channel(MOVIE_STORAGE_CHANNEL_ID)
    if TV_STORAGE_CHANNEL_ID:
        tv_titles = await _load_titles_from_channel(TV_STORAGE_CHANNEL_ID)

async def set_birthday(guild_id: int, user_id: int, mm_dd: str):
    data = await _load_storage_message()
    gid = str(guild_id)
    data.setdefault(gid, {})[str(user_id)] = mm_dd
    await _save_storage_message(data)

async def get_guild_birthdays(guild_id: int):
    data = await _load_storage_message()
    return data.get(str(guild_id), {})

async def build_birthday_embed(guild: discord.Guild) -> discord.Embed:
    birthdays = await get_guild_birthdays(guild.id)
    embed = discord.Embed(title="Our Birthdays!", color=0x2e2f33)
    if not birthdays:
        embed.description = "No birthdays set yet.\nUse </set:1440919374310408234> to add yours!"
        return embed
    lines = []
    for user_id, mm_dd in sorted(birthdays.items(), key=lambda x: x[1]):
        member = guild.get_member(int(user_id))
        name = member.display_name if member else "Unknown User"
        lines.append(f"`{mm_dd}` — **{name}**")
    lines.append("\nUse </set:1440919374310408234> to add yours!")
    embed.description = "\n".join(lines)
    return embed

async def update_birthday_list_message(guild: discord.Guild):
    channel = bot.get_channel(BIRTHDAY_LIST_CHANNEL_ID)
    if not channel:
        return
    try:
        msg = await channel.fetch_message(BIRTHDAY_LIST_MESSAGE_ID)
        embed = await build_birthday_embed(guild)
        await msg.edit(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))
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
        cleaned = role.name.replace("Christmas tree", "").replace("Jack O Lantern", "").replace("Snowflake", "").strip()
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


############### VIEWS / UI COMPONENTS ###############
class MediaPagerView(discord.ui.View):
    def __init__(self, category: str, page: int = 0):
        super().__init__(timeout=120)
        self.category = category
        self.page = page

    def _items(self):
        return movie_titles if self.category == "movies" else tv_titles

    def _max_page(self):
        return max(0, (len(self._items()) - 1) // PAGE_SIZE)

    def _build_content(self):
        items = self._items()
        if not items:
            return "No items."
        max_page = self._max_page()
        self.page = max(0, min(self.page, max_page))
        start = self.page * PAGE_SIZE
        slice_items = items[start:start + PAGE_SIZE]
        lines = [f"{i+1}. {t}" for i, t in enumerate(slice_items, start+1)]
        header = f"{self.category.capitalize()} • Page {self.page+1}/{max_page+1} ({len(items)} total)"
        return f"{header}\n```text\n" + "\n".join(lines if lines else ["Empty"]) + "\n```"

    async def send_initial(self, ctx):
        await ctx.respond(self._build_content(), view=self, ephemeral=True)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, button, interaction):
        self.page -= 1
        await interaction.response.edit_message(content=self._build_content(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, button, interaction):
        self.page += 1
        await interaction.response.edit_message(content=self._build_content(), view=self)


############### AUTOCOMPLETE FUNCTIONS ###############
async def movie_autocomplete(ctx: discord.AutocompleteContext):
    query = (ctx.value or "").lower()
    matches = [m for m in movie_titles if query in m.lower()]
    return matches[:25] or movie_titles[:25]


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
                elif "12-01" <= today <= "12-26":
                    await clear_holiday_theme(guild)
                    await apply_holiday_theme(guild, "christmas")
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
            data = await _load_storage_message()
            for guild in bot.guilds:
                role = guild.get_role(BIRTHDAY_ROLE_ID)
                if not role:
                    continue
                bdays = data.get(str(guild.id), {})
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
    await initialize_storage_message()
    await initialize_media_lists()
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


############### COMMAND GROUPS ###############
@bot.slash_command(name="info", description="Show all bot features")
async def info(ctx: discord.ApplicationContext):
    MEMBERS_ICON = "https://images-ext-1.discordapp.net/external/2i-PtcLgl_msR0VTT2mGn_5dtQiC9DK56PxR4uJfCLI/%3Fsize%3D1024/https/cdn.discordapp.com/avatars/1440914703894188122/ff746b98459152a0ba7c4eff5530cd9d.png?format=webp&quality=lossless&width=534&height=534"
    embed = discord.Embed(title="Members - Bot Features", description="Here's everything I can do in this server!", color=0x00e1ff)
    embed.add_field(name="Birthday System", value="• </set:1440919374310408234> - Members can set their birthday\n• </set_for:1440919374310408235> - Admins can set birthdays for others\n• </remove_for:1440954448468774922> - Admins can remove birthdays\n• </birthdays:1440919374310408236> - Shows the full birthday list\n• Auto-updated public birthday list message\n• Birthday role is given on your day and removed afterward\n• New members get a welcome DM with a link to add their birthday", inline=False)
    embed.add_field(name="Movie & TV Night", value="• Maintains a server-wide library of movies and TV shows\n• </list:1442017846589653014> – Browse movies or shows (paged list)\n• </pick:1442305353030176800> – Add your movie pick to the pool\n• </pool:1442311836497350656> – See the current request pool\n• </random:1442017303230156963> – Randomly pick a movie from the pool and clear it\n• </media_add:1441698665981939825> – Admins can add new movies/shows to the library", inline=False)
    embed.add_field(name="Holiday Themes", value="• </holiday_add:1442616885802832115> – Apply a holiday server theme\n ┣ Matches special roles (Admin / Original Member / Member)\n ┗ Gives themed roles like **Grinch**, **Cranberry**, **lights**, **Cauldron**, **Candy**, **Witchy**\n• </holiday_remove:1442616885802832116> – Remove the holiday server theme", inline=False)
    embed.add_field(name="Dead Chat Role Color Cycle", value="• </color:1442666939842433125> – Changes the color of the **Dead Chat** role\n• Only people who already have the Dead Chat role can use it\n• Cycles through a set of bright colors for everyone with that role\n• Uses either the configured role ID or fallback name to find the role", inline=False)
    embed.add_field(name="Member & Admin Utilities", value="• </say:1440927430209703986> – Admins can make the bot say a message in any channel\n• </commands:1442619988635549801> – Quick reference for admin-only commands", inline=False)
    embed.add_field(name="Automatic Tasks", value="• Loads birthday data and media lists when the bot comes online\n• Checks birthdays every hour and updates the Birthday role automatically\n• Sends a birthday-list link DM to new members when they join", inline=False)
    embed.add_field(name="Question of the Day", value="• Automatically posts a daily Question of the Day in the configured channel\n• Pulls questions from your Google Sheet (organized by seasons)\n• Tracks used questions and resets when all are used\n• </qotd_now:1444114293170765845> – Admins can post a QOTD immediately", inline=False)
    embed.set_thumbnail(url=MEMBERS_ICON)
    embed.set_footer(text="• Bot by Soft Dreamings", icon_url=MEMBERS_ICON)
    await ctx.respond(embed=embed)

@bot.slash_command(name="commands", description="Admin / Announcer commands")
async def commands(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    embed = discord.Embed(title="Admin Commands", color=0xff6b6b)
    embed.add_field(name="Birthdays", value="• </set_for:1440919374310408235>\n• </remove_for:1440954448468774922>", inline=False)
    embed.add_field(name="Movie Night", value="• </random:1442017303230156963> – Force pick", inline=False)
    embed.add_field(name="Holidays", value="• </holiday_add:1442616885802832115>\n• </holiday_remove:1442616885802832116>", inline=False)
    embed.set_footer(text="Also: /say • /media_add")
    await ctx.respond(embed=embed, ephemeral=True)

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
    gid, uid = str(ctx.guild.id), str(member.id)
    if data.get(gid, {}).pop(uid, None):
        await _save_storage_message(data)
        await update_birthday_list_message(ctx.guild)
        await ctx.respond(f"Removed birthday for {member.mention}", ephemeral=True)
    else:
        await ctx.respond("No birthday found.", ephemeral=True)

@bot.slash_command(name="birthdays", description="View everyones birthdays")
async def birthdays_cmd(ctx):
    await ctx.respond(embed=await build_birthday_embed(ctx.guild), ephemeral=True)

@bot.slash_command(name="pick", description="Pick a movie to add to the pool")
async def pick(ctx, title: discord.Option(str, autocomplete=movie_autocomplete)):
    if not movie_titles:
        return await ctx.respond("Movie list not loaded.", ephemeral=True)
    canon = next((t for t in movie_titles if t.lower() == title.strip().lower()), None)
    if not canon:
        return await ctx.respond("That movie isn't in the library.", ephemeral=True)
    pool = request_pool.setdefault(ctx.guild.id, [])
    pool.append((ctx.author.id, canon))
    await ctx.respond(f"Added **{canon}** • Pool size: `{len(pool)}`", ephemeral=True)

@bot.slash_command(name="pool", description="See what movies have been added to todays pool")
async def pool(ctx):
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.respond("Pool is empty.", ephemeral=True)
    lines = [f"• **{t}** — {ctx.guild.get_member(u).mention if ctx.guild.get_member(u) else '<@'+str(u)+'>'}" for u, t in pool]
    await ctx.respond(embed=discord.Embed(title="Current Pool", description="\n".join(lines), color=0x2e2f33), ephemeral=True)

@bot.slash_command(name="random", description="The bot will choose a random movie from the pool")
async def random_pick(ctx):
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.respond("Pool is empty.", ephemeral=True)
    user_id, title = pyrandom.choice(pool)
    request_pool[ctx.guild.id] = []
    member = ctx.guild.get_member(user_id)
    await ctx.respond(f"Random Pick: **{title}**\nRequested by {member.mention if member else '<@'+str(user_id)+'>'}")

@bot.slash_command(name="list", description="View the list of movies & shows")
async def list_media(ctx, category: discord.Option(str, choices=["movies", "shows"])):
    items = movie_titles if category == "movies" else tv_titles
    if not items:
        return await ctx.respond(f"No {category} loaded.", ephemeral=True)
    view = MediaPagerView(category)
    await view.send_initial(ctx)

@bot.slash_command(name="media_add")
async def media_add(ctx, category: discord.Option(str, choices=["movies", "shows"]), title: str):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    title = title.strip()
    target = movie_titles if category == "movies" else tv_titles
    ch_id = MOVIE_STORAGE_CHANNEL_ID if category == "movies" else TV_STORAGE_CHANNEL_ID
    if ch_id and title not in target:
        ch = bot.get_channel(ch_id)
        if ch:
            await ch.send(title)
        target.append(title)
        target.sort(key=str.lower)
    await ctx.respond(f"Added **{title}** to {category}.", ephemeral=True)

@bot.slash_command(name="holiday_add", description="Apply a holiday theme to the server")
async def holiday_add(ctx, holiday: discord.Option(str, choices=["christmas", "halloween"])):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.defer(ephemeral=True)
    added = await apply_holiday_theme(ctx.guild, holiday)
    await ctx.followup.send(f"Applied **{holiday.capitalize()}** theme to **{added}** members! {'Christmas tree' if holiday == 'christmas' else 'Jack O Lantern'}", ephemeral=True)

@bot.slash_command(name="holiday_remove", description="Remove the holiday theme from the server")
async def holiday_remove(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.defer(ephemeral=True)
    removed = await clear_holiday_theme(ctx.guild)
    await ctx.followup.send(f"Removed all holiday roles from **{removed}** members.", ephemeral=True)

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

@bot.slash_command(name="qotd_now", description="Post today's QOTD immediately (admin only)")
async def qotd_now(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only", ephemeral=True)
    await ctx.defer(ephemeral=True)
    try:
        await post_daily_qotd()
    except Exception as e:
        print("QOTD_NOW ERROR:", repr(e))
        traceback.print_exc()
        return await ctx.followup.send(f"QOTD error: `{type(e).__name__}` – `{repr(e)}`", ephemeral=True)
    await ctx.followup.send("QOTD posted!", ephemeral=True)


############### ON_READY & BOT START ###############
bot.run(os.getenv("TOKEN"))
