import os
import json
import asyncio
import aiohttp
from datetime import datetime
import discord
import random as pyrandom
import gspread
from google.oauth2.service_account import Credentials
import traceback

# ───────────────────────── MONTH / DAY DROPDOWNS ─────────────────────────
MONTH_CHOICES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_TO_NUM = {name: f"{i:02d}" for i, name in enumerate(MONTH_CHOICES, start=1)}

def build_mm_dd(month_name: str, day: int) -> str | None:
    month_num = MONTH_TO_NUM.get(month_name)
    if not month_num or not (1 <= day <= 31):
        return None
    return f"{month_num}-{day:02d}"

intents = discord.Intents.default()
intents.members = True
bot = discord.Bot(intents=intents)

# Safe integer environment variable loader
def _env_int(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"[WARNING] Invalid value for {var_name}: {value!r} — using default {default}")
        return default

# ───────────────────────── CONFIG ─────────────────────────
BIRTHDAY_ROLE_ID            = _env_int("BIRTHDAY_ROLE_ID", 1217937235840598026)
BIRTHDAY_STORAGE_CHANNEL_ID = _env_int("BIRTHDAY_STORAGE_CHANNEL_ID", 1440912334813134868)
BIRTHDAY_LIST_CHANNEL_ID    = 1440989357535395911
BIRTHDAY_LIST_MESSAGE_ID    = 1440989655515271248
MOVIE_REQUESTS_CHANNEL_ID   = _env_int("MOVIE_REQUESTS_CHANNEL_ID", 0)
MOVIE_STORAGE_CHANNEL_ID    = _env_int("MOVIE_STORAGE_CHANNEL_ID", 0)
TV_STORAGE_CHANNEL_ID       = _env_int("TV_STORAGE_CHANNEL_ID", 0)
DEAD_CHAT_ROLE_ID           = _env_int("DEAD_CHAT_ROLE_ID", 0)
DEAD_CHAT_ROLE_NAME         = os.getenv("DEAD_CHAT_ROLE_NAME", "Dead Chat")

# Holiday icons (these are just strings, safe as-is)
CHRISTMAS_ICON_URL          = os.getenv("CHRISTMAS_ICON_URL", "")
HALLOWEEN_ICON_URL          = os.getenv("HALLOWEEN_ICON_URL", "")
DEFAULT_ICON_URL            = os.getenv("DEFAULT_ICON_URL", "")

# QOTD settings
QOTD_CHANNEL_ID             = _env_int("QOTD_CHANNEL_ID", 0)
QOTD_TIME_HOUR              = _env_int("QOTD_TIME_HOUR", 10)

# Colors the Dead Chat role will cycle through
DEAD_CHAT_COLORS = [
    discord.Color.red(),
    discord.Color.orange(),
    discord.Color.gold(),
    discord.Color.green(),
    discord.Color.blue(),
    discord.Color.purple(),
    discord.Color.magenta(),
    discord.Color.teal(),
]

CHRISTMAS_ICON_URL = os.getenv("CHRISTMAS_ICON_URL", "")
HALLOWEEN_ICON_URL = os.getenv("HALLOWEEN_ICON_URL", "")
DEFAULT_ICON_URL   = os.getenv("DEFAULT_ICON_URL", "")

# Storage
storage_message_id: int | None = None
movie_titles: list[str] = []
tv_titles: list[str] = []
request_pool: dict[int, list[tuple[int, str]]] = {}

# ────────────────────── STORAGE HELPERS ──────────────────────
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

# ────────────────────── MEDIA LISTS ──────────────────────
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

# ────────────────────── BIRTHDAY HELPERS ──────────────────────
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

# ────────────────────── MEDIA PAGER VIEW ──────────────────────
PAGE_SIZE = 25

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

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, button, interaction):
        self.page -= 1
        await interaction.response.edit_message(content=self._build_content(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, button, interaction):
        self.page += 1
        await interaction.response.edit_message(content=self._build_content(), view=self)

# ────────────────────── AUTOCOMPLETE ──────────────────────
async def movie_autocomplete(ctx: discord.AutocompleteContext):
    query = (ctx.value or "").lower()
    matches = [m for m in movie_titles if query in m.lower()]
    return matches[:25] or movie_titles[:25]


# ────────────────────── QUESTION OF THE DAY (Google Sheets) ──────────────────────
GOOGLE_CREDS_RAW = os.getenv("GOOGLE_CREDENTIALS")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
QOTD_CHANNEL_ID = int(os.getenv("QOTD_CHANNEL_ID", "0"))
QOTD_TIME_HOUR = int(os.getenv("QOTD_TIME_HOUR", "10"))  # UTC hour

gc = None

if GOOGLE_CREDS_RAW and SHEET_ID:
    try:
        creds_dict = json.loads(GOOGLE_CREDS_RAW)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        gc = gspread.authorize(creds)
        print("QOTD: Google Sheets client initialized.")
    except Exception as e:
        print("QOTD init error:", repr(e))
        traceback.print_exc()
else:
    print("QOTD disabled: missing GOOGLE_CREDENTIALS or GOOGLE_SHEET_ID")


async def get_qotd_sheet_and_tab():
    """
    Returns (worksheet, season_name).

    Season logic:
      - Oct–Nov -> 'Fall Season'
      - Dec     -> 'Christmas'
      - else    -> 'Regular'
    Falls back to the first worksheet if the named tab doesn't exist.
    """
    if gc is None or not SHEET_ID:
        raise RuntimeError("QOTD is not configured (no gc or SHEET_ID).")

    sh = gc.open_by_key(SHEET_ID)
    today = datetime.utcnow()

    if 10 <= today.month <= 11:
        tab = "Fall Season"
    elif today.month == 12:
        tab = "Christmas"
    else:
        tab = "Regular"

    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        # Fallback: use first sheet
        ws = sh.sheet1
        tab = ws.title
        print(f"QOTD: worksheet '{tab}' not found, using first sheet '{tab}' instead.")

    return ws, tab


async def post_daily_qotd():
    """
    Core QOTD logic. Raises exceptions on real errors so callers can handle them.
    """
    if gc is None or not SHEET_ID:
        print("QOTD: Skipping because gc or SHEET_ID is not set.")
        return

    if QOTD_CHANNEL_ID == 0:
        print("QOTD: QOTD_CHANNEL_ID is 0; skipping.")
        return

    channel = bot.get_channel(QOTD_CHANNEL_ID)
    if not channel:
        print(f"QOTD: Could not find channel with ID {QOTD_CHANNEL_ID}.")
        return

    worksheet, season = await get_qotd_sheet_and_tab()

    # Read all rows
    all_vals = worksheet.get_all_values()
    if len(all_vals) < 2:
        print("QOTD: Sheet has no data rows (only header or empty).")
        return

    questions = all_vals[1:]  # skip header row

    # 'unused' = rows where col B is empty or missing
    unused = [row for row in questions if len(row) < 2 or not (row[1] or "").strip()]

    if not unused:
        # Reset all B cells and treat all as unused
        print("QOTD: All questions marked used; resetting column B.")
        worksheet.update("B2:B", [[""] for _ in range(len(questions))])
        unused = questions

    # Choose a random unused row
    chosen = pyrandom.choice(unused)
    # Ensure at least column A exists
    if not chosen or not (chosen[0] or "").strip():
        print("QOTD: Chosen row has no question text; skipping.")
        return

    question = chosen[0].strip()

    # Seasonal styling
    colors = {"Regular": 0x9b59b6, "Fall Season": 0xe67e22, "Christmas": 0x00ff00}
    emojis = {
        "Regular": "Question of the Day",
        "Fall Season": "Fall Question",
        "Christmas": "Christmas Question",
    }

    embed = discord.Embed(
        title=f"{emojis.get(season, 'Question of the Day')} Question of the Day",
        description=f"**{question}**",
        color=colors.get(season, 0x9b59b6),
    )
    embed.set_footer(text=f"{season} • Reply below!")

    await channel.send(embed=embed)

    # Mark as used
    row_idx = questions.index(chosen) + 2  # +2 because of header & 1-based rows
    worksheet.update(
        f"B{row_idx}",
        [[f"Used {datetime.utcnow().strftime('%Y-%m-%d')}"]],
    )
    print(f"QOTD: Posted question from row {row_idx} ({season}).")


async def qotd_scheduler():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.utcnow()
        if now.hour == QOTD_TIME_HOUR and now.minute < 5:
            try:
                await post_daily_qotd()
            except Exception as e:
                print("QOTD scheduler error:", repr(e))
                traceback.print_exc()
        await asyncio.sleep(300)


# Instant test command (admin only)
@bot.slash_command(name="qotd_now", description="Post today's QOTD immediately (admin only)")
async def qotd_now(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only", ephemeral=True)

    await ctx.defer(ephemeral=True)
    try:
        await post_daily_qotd()
    except Exception as e:
        # Log full traceback to Railway
        print("QOTD_NOW ERROR:", repr(e))
        traceback.print_exc()
        # Tell you what went wrong
        return await ctx.followup.send(
            f"QOTD error: `{e}`\nCheck Railway logs for details.",
            ephemeral=True,
        )

    await ctx.followup.send("QOTD posted!", ephemeral=True)

# ────────────────────── COMMANDS ──────────────────────
@bot.slash_command(name="info", description="Show all bot features")
async def info(ctx: discord.ApplicationContext):
    # Same icon/logo as the other bot
    MEMBERS_ICON = "https://images-ext-1.discordapp.net/external/2i-PtcLgl_msR0VTT2mGn_5dtQiC9DK56PxR4uJfCLI/%3Fsize%3D1024/https/cdn.discordapp.com/avatars/1440914703894188122/ff746b98459152a0ba7c4eff5530cd9d.png?format=webp&quality=lossless&width=534&height=534"

    embed = discord.Embed(
        title="Members - Bot Features",
        description="Here's everything I can do in this server!",
        color=0x00e1ff,  # keep this bot's cyan color
    )

    embed.add_field(
        name="Birthday System",
        value=(
            "• </set:1440919374310408234> - Members can set their birthday\n"
            "• </set_for:1440919374310408235> - Admins can set birthdays for others\n"
            "• </remove_for:1440954448468774922> - Admins can remove birthdays\n"
            "• </birthdays:1440919374310408236> - Shows the full birthday list\n"
            "• Auto-updated public birthday list message\n"
            "• Birthday role is given on your day and removed afterward\n"
            "• New members get a welcome DM with a link to add their birthday"
        ),
        inline=False,
    )

    embed.add_field(
        name="Movie & TV Night",
        value=(
            "• Maintains a server-wide library of movies and TV shows\n"
            "• </list:1442017846589653014> – Browse movies or shows (paged list)\n"
            "• </pick:1442305353030176800> – Add your movie pick to the pool\n"
            "• </pool:1442311836497350656> – See the current request pool\n"
            "• </random:1442017303230156963> – Randomly pick a movie from the pool and clear it\n"
            "• </media_add:1441698665981939825> – Admins can add new movies/shows to the library"
        ),
        inline=False,
    )

    embed.add_field(
        name="Holiday Themes",
        value=(
            "• </holiday_add:1442616885802832115> – Apply a holiday server theme\n"
            "  ┣ Matches special roles (Owner / Original Member / Member)\n"
            "  ┗ Gives themed roles like **Grinch**, **Cranberry**, **lights**, **Cauldron**, **Candy**, **Witchy**\n"
            "• </holiday_remove:1442616885802832116> – Remove the holiday server theme"
        ),
        inline=False,
    )

    embed.add_field(
        name="Dead Chat Role Color Cycle",
        value=(
            "• </color:1442666939842433125> – Changes the color of the **Dead Chat** role\n"
            "• Only people who already have the Dead Chat role can use it\n"
            "• Cycles through a set of bright colors for everyone with that role\n"
            "• Uses either the configured role ID or fallback name to find the role"
        ),
        inline=False,
    )

    embed.add_field(
        name="Member & Admin Utilities",
        value=(
            "• </say:1440927430209703986> – Admins can make the bot say a message in any channel\n"
            "• </commands:1442619988635549801> – Quick reference for admin-only commands\n"
            "• </membercommands:1442622321243459598> – Shows everything regular members can use"
        ),
        inline=False,
    )

    embed.add_field(
        name="Automatic Tasks",
        value=(
            "• Loads birthday data and media lists when the bot comes online\n"
            "• Checks birthdays every hour and updates the Birthday role automatically\n"
            "• Sends a birthday-list link DM to new members when they join"
        ),
        inline=False,
    )

    embed.set_thumbnail(url=MEMBERS_ICON)
    embed.set_footer(text="• Bot by Soft Dreamings", icon_url=MEMBERS_ICON)

    await ctx.respond(embed=embed)
    

@bot.slash_command(name="commands", description="Admin / Announcer commands")
async def commands(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    embed = discord.Embed(title="Admin Commands", color=0xff6b6b)
    embed.add_field(
        name="Birthdays",
        value="• </set_for:1440919374310408235>\n• </remove_for:1440954448468774922>",
        inline=False,
    )
    embed.add_field(
        name="Movie Night",
        value="• </random:1442017303230156963> – Force pick",
        inline=False,
    )
    embed.add_field(
        name="Holidays",
        value="• </holiday_add:1442616885802832115>\n• </holiday_remove:1442616885802832116>",
        inline=False,
    )
    embed.set_footer(text="Also: /say • /media_add")
    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name="membercommands", description="What regular members can use")
async def membercommands(ctx):
    embed = discord.Embed(title="Member Commands", color=0x00e1ff)
    embed.add_field(
        name="Birthdays",
        value="• </set:1440919374310408234>\n• </birthdays:1440919374310408236>",
        inline=False,
    )
    embed.add_field(
        name="Movie Night",
        value="• </list:1442017846589653014> movies/shows\n"
              "• </pick:1442305353030176800>\n"
              "• </pool:1442311836497350656>",
        inline=False,
    )
    embed.add_field(
        name="Fun",
        value="• </color:1442666939842433125> (if you have Dead Chat)",
        inline=False,
    )
    embed.add_field(name="Full list?", value="Use **/info**!", inline=False)
    await ctx.respond(embed=embed, ephemeral=True)

# Birthday commands
@bot.slash_command(
    name="set",
    description="Share your birthday with the server"
)
async def set_birthday_self(ctx, month: discord.Option(str, choices=MONTH_CHOICES), day: int):
    mm_dd = build_mm_dd(month, day)
    if not mm_dd:
        return await ctx.respond("Invalid date.", ephemeral=True)
    await set_birthday(ctx.guild.id, ctx.author.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Birthday set to `{mm_dd}`!", ephemeral=True)

@bot.slash_command(
    name="set_for",
    description="Add a birthday for a member"
)
async def set_for(ctx, member: discord.Member, month: discord.Option(str, choices=MONTH_CHOICES), day: int):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    mm_dd = build_mm_dd(month, day)
    if not mm_dd:
        return await ctx.respond("Invalid date.", ephemeral=True)
    await set_birthday(ctx.guild.id, member.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Set {member.mention}'s birthday to `{mm_dd}`", ephemeral=True)

@bot.slash_command(
    name="remove_for",
    description="Remove a members birthday"
)
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

@bot.slash_command(name="birthdays",
    description="View everyones birthdays"
)
async def birthdays_cmd(ctx):
    await ctx.respond(embed=await build_birthday_embed(ctx.guild), ephemeral=True)

# Movie commands
@bot.slash_command(
    name="pick",
    description="Pick a movie to add to the pool"
)
async def pick(ctx, title: discord.Option(str, autocomplete=movie_autocomplete)):
    if not movie_titles:
        return await ctx.respond("Movie list not loaded.", ephemeral=True)
    canon = next((t for t in movie_titles if t.lower() == title.strip().lower()), None)
    if not canon:
        return await ctx.respond("That movie isn't in the library.", ephemeral=True)
    pool = request_pool.setdefault(ctx.guild.id, [])
    pool.append((ctx.author.id, canon))
    await ctx.respond(f"Added **{canon}** • Pool size: `{len(pool)}`", ephemeral=True)

@bot.slash_command(name="pool",
    description="See what movies have been added to todays pool"
)
async def pool(ctx):
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.respond("Pool is empty.", ephemeral=True)
    lines = [
        f"• **{t}** — {ctx.guild.get_member(u).mention if ctx.guild.get_member(u) else '<@'+str(u)+'>'}"
        for u, t in pool
    ]
    await ctx.respond(
        embed=discord.Embed(title="Current Pool", description="\n".join(lines), color=0x2e2f33),
        ephemeral=True,
    )

@bot.slash_command(
    name="random",
    description="The bot will choose a random movie from the pool"
)
async def random_pick(ctx):
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.respond("Pool is empty.", ephemeral=True)
    user_id, title = pyrandom.choice(pool)
    request_pool[ctx.guild.id] = []
    member = ctx.guild.get_member(user_id)
    await ctx.respond(
        f"Random Pick: **{title}**\nRequested by {member.mention if member else '<@'+str(user_id)+'>'}"
    )

@bot.slash_command(
    name="list",
    description="View the list of movies & shows"
)
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

# ────────────────────── HOLIDAY COLOR ROLES (FINAL CORRECTED PAIRINGS) ──────────────────────
CHRISTMAS_ROLES = {"Cranberry": "Owner", "lights": "Original Member", "Grinch": "Member", "Christmas": "Bots"}
HALLOWEEN_ROLES = {"Cauldron": "Owner", "Candy": "Original Member", "Witchy": "Member", "Halloween": "Bots"}

def find_role_by_name(guild: discord.Guild, name: str) -> discord.Role | None:
    name_lower = name.lower()
    for role in guild.roles:
        cleaned = role.name.replace("🎄", "").replace("🎃", "").replace("❄️", "").strip()
        if cleaned.lower() == name_lower:
            return role
    return None


async def apply_icon_to_bot_and_server(guild: discord.Guild, url: str):
    if not url:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return
                data = await resp.read()

        # Bot icon
        try:
            await bot.user.edit(avatar=data)
        except:
            pass

        # Server icon
        try:
            await guild.edit(icon=data)
        except:
            pass

    except:
        pass


async def set_bot_avatar_from_url(url: str):
    if not url:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return
                data = await resp.read()
        await bot.user.edit(avatar=data)
    except Exception:
        pass


@bot.slash_command(
    name="holiday_add",
    description="Apply a holiday theme to the server"
)
async def holiday_add(ctx, holiday: discord.Option(str, choices=["christmas", "halloween"])):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.defer(ephemeral=True)

    role_map = CHRISTMAS_ROLES if holiday == "christmas" else HALLOWEEN_ROLES
    added = 0

    for color_name, base_keyword in role_map.items():
        color_role = find_role_by_name(ctx.guild, color_name)
        if not color_role:
            continue
        async for member in ctx.guild.fetch_members(limit=None):
            if any(base_keyword.lower() in r.name.lower() for r in member.roles):
                if color_role not in member.roles:
                    try:
                        await member.add_roles(color_role, reason=f"{holiday.capitalize()} theme")
                        added += 1
                    except:
                        pass

    await ctx.followup.send(
        f"Applied **{holiday.capitalize()}** theme to **{added}** members! "
        f"{'🎄' if holiday == 'christmas' else '🎃'}",
        ephemeral=True,
    )

    icon_url = CHRISTMAS_ICON_URL if holiday == "christmas" else HALLOWEEN_ICON_URL
    await apply_icon_to_bot_and_server(ctx.guild, icon_url)


@bot.slash_command(
    name="holiday_remove",
    description="Remove the holiday theme from the server"
)
async def holiday_remove(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.defer(ephemeral=True)

    removed = 0
    for color_name in {**CHRISTMAS_ROLES, **HALLOWEEN_ROLES}:
        role = find_role_by_name(ctx.guild, color_name)
        if role:
            async for member in ctx.guild.fetch_members(limit=None):
                if role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Holiday theme ended")
                        removed += 1
                    except:
                        pass

    await ctx.followup.send(
        f"Removed all holiday roles from **{removed}** members.",
        ephemeral=True,
    )

    await apply_icon_to_bot_and_server(ctx.guild, DEFAULT_ICON_URL)


# ────────────────────── DEAD CHAT ROLE – CHANGE ROLE COLOR ONLY ──────────────────────
@bot.slash_command(name="color", description="Change the color of the Dead Chat role")
async def color_cycle(ctx):
    # Resolve the Dead Chat role: ID first, then name as fallback
    dead_chat_role = ctx.guild.get_role(DEAD_CHAT_ROLE_ID) if DEAD_CHAT_ROLE_ID != 0 else None
    if dead_chat_role is None and DEAD_CHAT_ROLE_NAME:
        dead_chat_role = discord.utils.get(ctx.guild.roles, name=DEAD_CHAT_ROLE_NAME)

    if dead_chat_role is None:
        return await ctx.respond(
            "Dead Chat role is not configured correctly. Check DEAD_CHAT_ROLE_ID / DEAD_CHAT_ROLE_NAME.",
            ephemeral=True,
        )

    # Only members who HAVE Dead Chat can use this
    if dead_chat_role not in ctx.author.roles:
        return await ctx.respond("You need the Dead Chat role to use this command!", ephemeral=True)

    # Find current color index in the cycle
    colors = DEAD_CHAT_COLORS
    current_index = None
    for i, c in enumerate(colors):
        if c.value == dead_chat_role.color.value:
            current_index = i
            break

    # If current color not in the list, start at first
    if current_index is None:
        next_index = 0
    else:
        next_index = (current_index + 1) % len(colors)

    next_color = colors[next_index]

    # Edit the role color (affects everyone with Dead Chat)
    try:
        await dead_chat_role.edit(color=next_color, reason="Dead Chat color cycle")
    except discord.Forbidden:
        return await ctx.respond(
            "I don't have permission to edit the Dead Chat role. "
            "Make sure my bot role is above Dead Chat and has Manage Roles.",
            ephemeral=True,
        )

    await ctx.respond(
        f"Changed **Dead Chat** role color (step {next_index + 1}/{len(colors)} in the cycle).",
        ephemeral=True,
    )

# Admin say
@bot.slash_command(name="say")
async def say(ctx, message: str):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.channel.send(message)
    await ctx.respond("Sent!", ephemeral=True)

# Events
@bot.event
async def on_ready():
    print(f"{bot.user} online!")
    await initialize_storage_message()
    await initialize_media_lists()
    bot.loop.create_task(birthday_checker())
    bot.loop.create_task(qotd_scheduler())
    await init_gspread()
    print("QOTD scheduler started + Google Sheets ready!")

@bot.event
async def on_member_join(member):
    try:
        await member.send(
            "Welcome! Add your birthday here → "
            "https://discord.com/channels/1205041211610501120/1440989357535395911/1440989655515271248"
        )
    except:
        pass

async def birthday_checker():
    await bot.wait_until_ready()
    while not bot.is_closed():
        today = datetime.utcnow().strftime("%m-%d")
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
                elif role in member.roles:
                    await member.remove_roles(role, reason="Birthday over")
        await asyncio.sleep(3600)

bot.run(os.getenv("TOKEN"))
