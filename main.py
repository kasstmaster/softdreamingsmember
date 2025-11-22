import os
import json
import asyncio
from datetime import datetime

import discord
import random  # for random picks

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

# In-memory media lists
movie_titles: list[str] = []
tv_titles: list[str] = []

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

    titles.sort(key=str.lower)
    return titles

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

# ────────────────────── MEDIA LIST UI (LETTER RANGE BUTTONS) ──────────────────────

MEDIA_RANGES = {
    "0–9": "0123456789",
    "A–E": "abcde",
    "F–J": "fghij",
    "K–O": "klmno",
    "P–T": "pqrst",
    "U–Z": "uvwxyz",
}

def _first_alnum_char(s: str) -> str:
    """Return the first alphanumeric character (lowercased), or '' if none."""
    for ch in s.strip():
        if ch.isalnum():
            return ch.lower()
    return ""

class MediaListView(discord.ui.View):
    def __init__(self, category: str):
        # category is "movies" or "shows"
        super().__init__(timeout=60)
        self.category = category

    async def _show_range(
        self,
        interaction: discord.Interaction,
        label: str,   # e.g. "A–E"
    ):
        items = movie_titles if self.category == "movies" else tv_titles
        if not items:
            await interaction.response.send_message(
                f"No {self.category} stored.",
                ephemeral=True
            )
            return

        allowed = set(MEDIA_RANGES[label])  # e.g. {'a','b','c','d','e'}

        filtered = [
            title for title in items
            if _first_alnum_char(title) in allowed
        ]

        await interaction.response.defer(ephemeral=True, thinking=False)

        if not filtered:
            await interaction.followup.send(
                f"No {self.category} in the **{label}** range.",
                ephemeral=True
            )
            return

        lines = [f"{i+1}. {title}" for i, title in enumerate(filtered)]

        chunks = []
        current = []
        length = 0

        for line in lines:
            if length + len(line) + 1 > 1900:
                chunks.append("\n".join(current))
                current = [line]
                length = len(line) + 1
            else:
                current.append(line)
                length += len(line) + 1

        if current:
            chunks.append("\n".join(current))

        for idx, chunk in enumerate(chunks):
            prefix = f"**{self.category.capitalize()} {label}**\n" if idx == 0 else ""
            await interaction.followup.send(
                prefix + f"```text\n{chunk}\n```",
                ephemeral=True
            )

    # Row 0
    @discord.ui.button(label="0–9", style=discord.ButtonStyle.secondary, row=0)
    async def btn_0_9(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._show_range(interaction, "0–9")

    @discord.ui.button(label="A–E", style=discord.ButtonStyle.primary, row=0)
    async def btn_A_E(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._show_range(interaction, "A–E")

    @discord.ui.button(label="F–J", style=discord.ButtonStyle.primary, row=0)
    async def btn_F_J(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._show_range(interaction, "F–J")

    # Row 1
    @discord.ui.button(label="K–O", style=discord.ButtonStyle.primary, row=1)
    async def btn_K_O(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._show_range(interaction, "K–O")

    @discord.ui.button(label="P–T", style=discord.ButtonStyle.primary, row=1)
    async def btn_P_T(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._show_range(interaction, "P–T")

    @discord.ui.button(label="U–Z", style=discord.ButtonStyle.primary, row=1)
    async def btn_U_Z(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._show_range(interaction, "U–Z")

# ────────────────────── BIRTHDAY HELPERS ──────────────────────

def normalize_date(date_str: str):
    try:
        dt = datetime.strptime(date_str, "%m-%d")
        return dt.strftime("%m-%d")
    except ValueError:
        return None

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

# ────────────────────── SLASH COMMANDS ──────────────────────

@bot.slash_command(name="set", description="Set your birthday (MM-DD)")
async def set_birthday_self(ctx, date: discord.Option(str, "Format: MM-DD", required=True)):
    mm_dd = normalize_date(date)
    if not mm_dd:
        return await ctx.respond("Invalid date. Use MM-DD.", ephemeral=True)
    await set_birthday(ctx.guild.id, ctx.author.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Your birthday has been set to `{mm_dd}`.", ephemeral=True)

@bot.slash_command(name="set_for", description="Set a birthday for another member (MM-DD)")
async def set_birthday_for(ctx,
    member: discord.Option(discord.Member, "Member", required=True),
    date: discord.Option(str, "Format: MM-DD", required=True),
):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator.", ephemeral=True)
    mm_dd = normalize_date(date)
    if not mm_dd:
        return await ctx.respond("Invalid date. Use MM-DD.", ephemeral=True)
    await set_birthday(ctx.guild.id, member.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Birthday set for {member.mention} → `{mm_dd}`.", ephemeral=True)

@bot.slash_command(name="birthdays", description="Show all server birthdays")
async def birthdays_cmd(ctx):
    embed = await build_birthday_embed(ctx.guild)
    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name="say", description="Make the bot say something in this channel")
async def say(ctx, message: discord.Option(str, "Message", required=True)):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator.", ephemeral=True)
    await ctx.channel.send(message)
    await ctx.respond("Sent!", ephemeral=True)

@bot.slash_command(name="remove_for", description="Remove a birthday for another member")
async def remove_birthday_for(ctx, member: discord.Option(discord.Member, "Member to remove birthday for", required=True)):
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

@bot.slash_command(name="request", description="Request a movie or show for others to vote on")
async def request_cmd(ctx, title: discord.Option(str, "Movie or show title", required=True)):
    if MOVIE_REQUESTS_CHANNEL_ID == 0:
        return await ctx.respond("Movie requests channel is not configured.", ephemeral=True)

    channel = bot.get_channel(MOVIE_REQUESTS_CHANNEL_ID)
    if not channel:
        return await ctx.respond("Configured movie requests channel not found.", ephemeral=True)

    embed = discord.Embed(
        title=title,
        description=(
            f"Requested by {ctx.author.mention}\n\n"
            "**[REQUEST A TITLE](https://discord.com/channels/1205041211610501120/1440989357535395911/1440992347709243402)**"
        ),
        color=0x2e2f33,
    )

    msg = await channel.send(embed=embed)

    try:
        await msg.add_reaction("✅")
        await msg.add_reaction("🚫")
    except:
        pass

    await ctx.respond("Your request has been posted for voting.", ephemeral=True)

# ────────────────────── MEDIA COMMANDS ──────────────────────

@bot.slash_command(
    name="media_list",
    description="Browse stored movies or TV shows by letter range (ephemeral)"
)
async def media_list(
    ctx: discord.ApplicationContext,
    category: discord.Option(str, "Which list?", choices=["movies", "shows"], required=True),
):
    items = movie_titles if category == "movies" else tv_titles
    if not items:
        return await ctx.respond(f"No {category} stored.", ephemeral=True)

    view = MediaListView(category=category)
    await ctx.respond(
        f"Select a letter range to view **{category}**.",
        view=view,
        ephemeral=True
    )

@bot.slash_command(
    name="media_random",
    description="Pick a random movie or TV show from the stored lists"
)
async def media_random(
    ctx: discord.ApplicationContext,
    category: discord.Option(str, "Which list?", choices=["movies", "shows"], required=True),
):
    items = movie_titles if category == "movies" else tv_titles

    if not items:
        return await ctx.respond(f"No {category} stored yet.", ephemeral=True)

    choice = random.choice(items)
    await ctx.respond(f"🎲 Random {category[:-1]}: **{choice}**")

@bot.slash_command(
    name="media_add",
    description="Add a new movie or TV show to the stored lists"
)
async def media_add(
    ctx: discord.ApplicationContext,
    category: discord.Option(str, "Which list?", choices=["movies", "shows"], required=True),
    title: discord.Option(str, "Exact title to add", required=True),
):
    # Admin / owner only
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
        movie_titles.sort(key=str.lower)
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
        tv_titles.sort(key=str.lower)
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
