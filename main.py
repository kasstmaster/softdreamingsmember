import os
import json
import asyncio
from datetime import datetime

# ───────────────────────── MONTH / DAY DROPDOWNS ─────────────────────────

MONTH_CHOICES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

MONTH_TO_NUM = {
    name: f"{i:02d}" for i, name in enumerate(MONTH_CHOICES, start=1)
}

def build_mm_dd(month_name: str, day: int) -> str | None:
    """Convert 'November', 1 → '11-01'. Returns None if invalid."""
    month_num = MONTH_TO_NUM.get(month_name)
    if not month_num:
        return None
    if day < 1 or day > 31:
        return None
    return f"{month_num}-{day:02d}"

import discord
import random as pyrandom

intents = discord.Intents.default()
intents.members = True

bot = discord.Bot(intents=intents)

BIRTHDAY_ROLE_ID = int(os.getenv("BIRTHDAY_ROLE_ID", "1217937235840598026"))
BIRTHDAY_STORAGE_CHANNEL_ID = int(os.getenv("BIRTHDAY_STORAGE_CHANNEL_ID", "1440912334813134868"))
BIRTHDAY_LIST_CHANNEL_ID = 1440989357535395911
BIRTHDAY_LIST_MESSAGE_ID = 1440989655515271248
MOVIE_REQUESTS_CHANNEL_ID = int(os.getenv("MOVIE_REQUESTS_CHANNEL_ID", "0"))

# Separate storage channels for movies / TV shows
MOVIE_STORAGE_CHANNEL_ID = int(os.getenv("MOVIE_STORAGE_CHANNEL_ID", "0"))
TV_STORAGE_CHANNEL_ID    = int(os.getenv("TV_STORAGE_CHANNEL_ID", "0"))

storage_message_id: int | None = None

# In-memory media lists (loaded from channels on startup)
movie_titles: list[str] = []
tv_titles: list[str] = []

# Per-guild temporary request pool: guild_id -> list of (user_id, title)
request_pool: dict[int, list[tuple[int, str]]] = {}

# ────────────────────── BIRTHDAY STORAGE ──────────────────────

async def initialize_storage_message():
    global storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel:
        print("Storage channel not found.")
        return
    async for msg in channel.history(limit=50):
        if msg.author == bot.user:
            storage_message_id = msg.id
            print(f"Found existing storage message: {storage_message_id}")
            return
    msg = await channel.send("{}")
    storage_message_id = msg.id
    print(f"Created new storage message: {storage_message_id}")

async def _load_storage_message() -> dict:
    global storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel or storage_message_id is None:
        return {}
    try:
        msg = await channel.fetch_message(storage_message_id)
    except:
        return {}
    content = msg.content.strip() or "{}"
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}

async def _save_storage_message(data: dict):
    global storage_message_id
    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel or storage_message_id is None:
        return
    try:
        msg = await channel.fetch_message(storage_message_id)
    except:
        return
    text = json.dumps(data, indent=2)
    if len(text) > 1900:
        text = text[:1900]
    await msg.edit(content=text)

# ────────────────────── MEDIA (MOVIES / TV SHOWS) LISTS ──────────────────────

async def _load_titles_from_channel(channel_id: int) -> list[str]:
    """Read all non-empty messages from a channel and treat each as a title."""
    ch = bot.get_channel(channel_id)
    if not isinstance(ch, discord.TextChannel):
        print(f"[Media] Channel {channel_id} not found or not a text channel.")
        return []

    titles: list[str] = []
    try:
        async for msg in ch.history(limit=None, oldest_first=True):
            content = (msg.content or "").strip()
            if content:
                titles.append(content)
    except discord.Forbidden:
        print(f"[Media] No permission to read history in channel {channel_id}.")
        return []

    # Sort and dedupe
    return sorted(set(titles), key=str.lower)


async def initialize_media_lists():
    """Load movies and TV shows from their storage channels into memory."""
    global movie_titles, tv_titles

    # Movies
    if MOVIE_STORAGE_CHANNEL_ID != 0:
        movie_titles = await _load_titles_from_channel(MOVIE_STORAGE_CHANNEL_ID)
        print(f"[Media] Movies loaded: {len(movie_titles)}")
    else:
        print("[Media] MOVIE_STORAGE_CHANNEL_ID is 0 (movies disabled).")

    # TV shows
    if TV_STORAGE_CHANNEL_ID != 0:
        tv_titles = await _load_titles_from_channel(TV_STORAGE_CHANNEL_ID)
        print(f"[Media] TV shows loaded: {len(tv_titles)}")
    else:
        print("[Media] TV_STORAGE_CHANNEL_ID is 0 (shows disabled).")

# ────────────────────── BIRTHDAY HELPERS ──────────────────────

async def set_birthday(guild_id: int, user_id: int, mm_dd: str):
    data = await _load_storage_message()
    gid = str(guild_id)
    if gid not in data:
        data[gid] = {}
    data[gid][str(user_id)] = mm_dd
    await _save_storage_message(data)

async def get_guild_birthdays(guild_id: int):
    data = await _load_storage_message()
    return data.get(str(guild_id), {})

async def build_birthday_embed(guild: discord.Guild) -> discord.Embed:
    birthdays = await get_guild_birthdays(guild.id)
    embed = discord.Embed(title="Our Birthdays!", color=0x2e2f33)
    if not birthdays:
        embed.description = (
            "No birthdays have been set yet.\n\n"
            "Use </set:1440919374310408234> to share your birthday"
        )
        return embed
    sorted_items = sorted(birthdays.items(), key=lambda x: x[1])
    lines = []
    for user_id, mm_dd in sorted_items:
        member = guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        lines.append(f"`{mm_dd}` — **{name}**")
    lines.append("")
    lines.append("Use </set:1440919374310408234> to share your birthday")
    embed.description = "\n".join(lines)
    return embed

async def update_birthday_list_message(guild: discord.Guild):
    channel = bot.get_channel(BIRTHDAY_LIST_CHANNEL_ID)
    if not channel:
        print("Birthday list channel not found.")
        return
    try:
        msg = await channel.fetch_message(BIRTHDAY_LIST_MESSAGE_ID)
    except:
        print("Birthday list message not found.")
        return
    embed = await build_birthday_embed(guild)
    try:
        allowed = discord.AllowedMentions(users=True)
        await msg.edit(embed=embed, allowed_mentions=allowed)
        print("Birthday list updated.")
    except Exception as e:
        print("Failed to update list:", e)

# ────────────────────── MEDIA PAGER VIEW ──────────────────────

PAGE_SIZE = 25  # titles per page

class MediaPagerView(discord.ui.View):
    def __init__(self, category: str, page: int = 0, page_size: int = PAGE_SIZE):
        super().__init__(timeout=120)
        self.category = category  # "movies" or "shows"
        self.page = page
        self.page_size = page_size

    def _items(self) -> list[str]:
        return movie_titles if self.category == "movies" else tv_titles

    def _max_page(self) -> int:
        items = self._items()
        if not items:
            return 0
        return (len(items) - 1) // self.page_size

    def _update_buttons_state(self):
        max_page = self._max_page()
        if hasattr(self, "prev_button"):
            self.prev_button.disabled = self.page <= 0
        if hasattr(self, "next_button"):
            self.next_button.disabled = self.page >= max_page

    def _build_page_content(self) -> str:
        items = self._items()
        if not items:
            return "No items."

        max_page = self._max_page()
        # Clamp page just in case list size changed
        self.page = max(0, min(self.page, max_page))

        start = self.page * self.page_size
        end = start + self.page_size
        slice_items = items[start:end]

        lines = [f"{i+1}. {title}" for i, title in enumerate(slice_items, start=start)]
        body = "\n".join(lines) if lines else "No items on this page."

        header = (
            f"{self.category.capitalize()} list — page {self.page+1}/{max_page+1} "
            f"(total {len(items)})"
        )

        self._update_buttons_state()
        return f"{header}\n```text\n{body}\n```"

    async def send_initial(self, ctx: "discord.ApplicationContext"):
        content = self._build_page_content()
        await ctx.respond(content, view=self, ephemeral=True)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.page -= 1
        content = self._build_page_content()
        await interaction.response.edit_message(content=content, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.page += 1
        content = self._build_page_content()
        await interaction.response.edit_message(content=content, view=self)

# ────────────────────── AUTOCOMPLETE HELPER ──────────────────────

async def request_title_autocomplete(ctx: "discord.AutocompleteContext"):
    query = (ctx.value or "").lower()

    if not movie_titles:
        return []

    if not query:
        # First 25 movies if they haven't typed anything
        return movie_titles[:25]

    matches = [m for m in movie_titles if query in m.lower()]
    return matches[:25]

# ────────────────────── SLASH COMMANDS ──────────────────────

@bot.slash_command(name="set", description="Set your birthday")
async def set_birthday_self(
    ctx: "discord.ApplicationContext",
    month: discord.Option(str, "Month", choices=MONTH_CHOICES, required=True),
    day: discord.Option(int, "Day", min_value=1, max_value=31, required=True),
):
    mm_dd = build_mm_dd(month, day)
    if not mm_dd:
        return await ctx.respond("Invalid date.", ephemeral=True)

    await set_birthday(ctx.guild.id, ctx.author.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Your birthday has been set to `{mm_dd}`.", ephemeral=True)

@bot.slash_command(name="set_for", description="Set a birthday for another member")
async def set_birthday_for(
    ctx: "discord.ApplicationContext",
    member: discord.Option(discord.Member, "Member", required=True),
    month: discord.Option(str, "Month", choices=MONTH_CHOICES, required=True),
    day: discord.Option(int, "Day", min_value=1, max_value=31, required=True),
):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator.", ephemeral=True)

    mm_dd = build_mm_dd(month, day)
    if not mm_dd:
        return await ctx.respond("Invalid date.", ephemeral=True)

    await set_birthday(ctx.guild.id, member.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Birthday set for {member.mention} → `{mm_dd}`.", ephemeral=True)

@bot.slash_command(name="birthdays", description="Show all server birthdays")
async def birthdays_cmd(ctx: "discord.ApplicationContext"):
    embed = await build_birthday_embed(ctx.guild)
    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name="say", description="Make the bot say something in this channel")
async def say(ctx: "discord.ApplicationContext", message: discord.Option(str, "Message", required=True)):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator.", ephemeral=True)
    await ctx.channel.send(message)
    await ctx.respond("Sent!", ephemeral=True)

@bot.slash_command(name="remove_for", description="Remove a birthday for another member")
async def remove_birthday_for(
    ctx: "discord.ApplicationContext",
    member: discord.Option(discord.Member, "Member to remove birthday for", required=True),
):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator.", ephemeral=True)
    data = await _load_storage_message()
    gid = str(ctx.guild.id)
    uid = str(member.id)
    if gid not in data or uid not in data[gid]:
        return await ctx.respond("That member has no birthday set.", ephemeral=True)
    del data[gid][uid]
    await _save_storage_message(data)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Removed birthday for {member.mention}.", ephemeral=True)

@bot.slash_command(
    name="pick",
    description="Randomly pick one movie from the current request pool and reset it"
)
async def pick_cmd(ctx: "discord.ApplicationContext"):
    if not ctx.guild:
        return await ctx.respond("This command can only be used in a server.", ephemeral=True)

    guild_id = ctx.guild.id
    pool = request_pool.get(guild_id, [])

    if not pool:
        return await ctx.respond(
            "There are no requests in the pool yet.\n"
            "Ask everyone to use `/request` first.",
            ephemeral=True,
        )

    user_id, title = pyrandom.choice(pool)

    # Reset the pool for this guild
    request_pool[guild_id] = []

    member = ctx.guild.get_member(user_id)
    requester_display = member.mention if member else f"<@{user_id}>"

    # Make the result public so everyone sees what was chosen
    await ctx.respond(
        f"🎲 Picked: **{title}**\n"
        f"Requested by {requester_display}\n"
        f"The pool has been cleared. Start a new round with `/request`."
    )

@bot.slash_command(
    name="request",
    description="Add a movie to the current random pick pool"
)
async def request_cmd(
    ctx: "discord.ApplicationContext",
    title: discord.Option(
        str,
        "Movie title (must be in the list)",
        required=True,
        autocomplete=request_title_autocomplete,
    ),
):
    if not ctx.guild:
        return await ctx.respond("This command can only be used in a server.", ephemeral=True)

    if not movie_titles:
        return await ctx.respond(
            "No movies are currently loaded. Try again later.",
            ephemeral=True,
        )

    # Validate against the canonical movie list
    canon_map = {t.lower(): t for t in movie_titles}
    key = title.strip().lower()

    if key not in canon_map:
        return await ctx.respond(
            "That movie is not in our library.\n"
            "Use `/list movies` to browse available titles.",
            ephemeral=True,
        )

    canon_title = canon_map[key]

    # Per-guild pool entry
    guild_id = ctx.guild.id
    pool = request_pool.setdefault(guild_id, [])
    pool.append((ctx.author.id, canon_title))

    await ctx.respond(
        f"Added **{canon_title}** to this round’s pool.\n"
        f"Current pool size: `{len(pool)}`.",
        ephemeral=True,
    )

# ────────────────────── MEDIA COMMANDS ──────────────────────

@bot.slash_command(
    name="list",
    description="Browse our available movies or TV shows"
)
async def list(
    ctx: "discord.ApplicationContext",
    category: discord.Option(str, "Which list?", choices=["movies", "shows"], required=True),
):
    items = movie_titles if category == "movies" else tv_titles
    if not items:
        return await ctx.respond(f"No {category} stored.", ephemeral=True)

    view = MediaPagerView(category=category)
    await view.send_initial(ctx)

@bot.slash_command(
    name="random",
    description="Pick a random movie or TV show from the list"
)
async def media_random(
    ctx: "discord.ApplicationContext",
    category: discord.Option(str, "Which list?", choices=["movies", "shows"], required=True),
):
    items = movie_titles if category == "movies" else tv_titles

    if not items:
        return await ctx.respond(f"No {category} stored yet.", ephemeral=True)

    choice_title = pyrandom.choice(items)
    kind = "movie" if category == "movies" else "show"

    await ctx.respond(f"🎲 Random {kind}: **{choice_title}**")

@bot.slash_command(
    name="media_add",
    description="Add a new movie or TV show to the stored lists"
)
async def media_add(
    ctx: "discord.ApplicationContext",
    category: discord.Option(str, "Which list?", choices=["movies", "shows"], required=True),
    title: discord.Option(str, "Exact title to add", required=True),
):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator.", ephemeral=True)

    title = title.strip()
    if not title:
        return await ctx.respond("Title cannot be empty.", ephemeral=True)

    global movie_titles, tv_titles

    if category == "movies":
        if MOVIE_STORAGE_CHANNEL_ID == 0:
            return await ctx.respond("Movie storage channel is not configured.", ephemeral=True)
        if title in movie_titles:
            return await ctx.respond("That movie is already in the list.", ephemeral=True)

        ch = bot.get_channel(MOVIE_STORAGE_CHANNEL_ID)
        if not ch:
            return await ctx.respond("Movie storage channel not found.", ephemeral=True)

        await ch.send(title)
        movie_titles.append(title)
        movie_titles = sorted(set(movie_titles), key=str.lower)
        await ctx.respond(f"Added **{title}** to movies.", ephemeral=True)

    else:  # shows
        if TV_STORAGE_CHANNEL_ID == 0:
            return await ctx.respond("TV storage channel is not configured.", ephemeral=True)
        if title in tv_titles:
            return await ctx.respond("That show is already in the list.", ephemeral=True)

        ch = bot.get_channel(TV_STORAGE_CHANNEL_ID)
        if not ch:
            return await ctx.respond("TV storage channel not found.", ephemeral=True)

        await ch.send(title)
        tv_titles.append(title)
        tv_titles = sorted(set(tv_titles), key=str.lower)
        await ctx.respond(f"Added **{title}** to TV shows.", ephemeral=True)

# ────────────────────── EVENTS ──────────────────────

@bot.event
async def on_ready():
    print(f"{bot.user} is online (birthday bot).")
    await initialize_storage_message()
    await initialize_media_lists()
    bot.loop.create_task(birthday_checker())

@bot.event
async def on_member_join(member):
    try:
        await member.send(
            """Hey, welcome to the server. Feel free to add your birthday in the channel below so we can all celebrate.

https://discord.com/channels/1205041211610501120/1440989357535395911/1440989655515271248"""
        )
    except:
        pass

async def birthday_checker():
    await bot.wait_until_ready()
    print("Birthday checker started.")
    while not bot.is_closed():
        today_mm_dd = datetime.utcnow().strftime("%m-%d")
        all_data = await _load_storage_message()
        for guild in bot.guilds:
            role = guild.get_role(BIRTHDAY_ROLE_ID)
            if not role:
                continue
            birthdays = all_data.get(str(guild.id), {})
            for member in guild.members:
                bday = birthdays.get(str(member.id))
                if bday == today_mm_dd:
                    if role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Birthday")
                        except:
                            pass
                else:
                    if role in member.roles:
                        try:
                            await member.remove_roles(role, reason="Birthday ended")
                        except:
                            pass
        await asyncio.sleep(3600)

bot.run(os.getenv("TOKEN"))
