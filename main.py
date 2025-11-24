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

MOVIE_STORAGE_CHANNEL_ID = int(os.getenv("MOVIE_STORAGE_CHANNEL_ID", "0"))
TV_STORAGE_CHANNEL_ID    = int(os.getenv("TV_STORAGE_CHANNEL_ID", "0"))

storage_message_id: int | None = None

movie_titles: list[str] = []
tv_titles: list[str] = []

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
        )
        return embed
    sorted_items = sorted(birthdays.items(), key=lambda x: x[1])
    lines = []
    for user_id, mm_dd in sorted_items:
        member = guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        lines.append(f"`{mm_dd}` — **{name}**")
    lines.append("")
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

@bot.slash_command(name="commands", description="Quick reference of admin-only commands")
async def commands(ctx: discord.ApplicationContext):

    embed = discord.Embed(
        title="Admin & Staff Commands",
        color=0x00e1ff
    )

    embed.add_field(
        name="Birthdays",
        value=(
            "• </set_for:1440919374310408235> – Set a birthday for someone else\n"
            "• </remove_for:1440954448468774922> – Remove a member's birthday"
        ),
        inline=False
    )

    embed.add_field(
        name="Movie Night",
        value="• </random:1442017303230156963> – Force-pick & announce a random movie (clears pool)",
        inline=False
    )

    embed.add_field(
        name="Holiday Themes",
        value=(
            "• </holiday_add:1442616885802832115> – Apply Christmas or Halloween color roles\n"
            "• </holiday_remove:1442616885802832116> – Remove all holiday color roles from everyone"
        ),
        inline=False
    )

    await ctx.respond(embed=embed, ephemeral=True)
    

@bot.slash_command(name="info", description="Show all features of the bot")
async def info(ctx: discord.ApplicationContext):
    MEMBERS_ICON = "https://images-ext-1.discordapp.net/external/2i-PtcLgl_msR0VTT2mGn_5dtQiC9DK56PxR4uJfCLI/%3Fsize%3D1024/https/cdn.discordapp.com/avatars/1440914703894188122/ff746b98459152a0ba7c4eff5530cd9d.png?format=webp&quality=lossless&width=534&height=534"
    embed = discord.Embed(
        title="Members - Bot Features",
        color=0x00e1ff
    )
    # ───── Birthday Features ─────
    embed.add_field(
        name="Birthday Features",
        value=(
            "• </set:1440919374310408234> – Let members set their own birthday (month + day)\n"
            "• </set_for:1440919374310408235> – Admins can set someone else’s birthday\n"
            "• </remove_for:1440954448468774922> – Admins can delete a member’s birthday\n"
            "• </birthdays:1440919374310408236> – Show the full server birthday list (ephemeral)\n"
            "• Automatically gives/removes a configurable “Birthday” role on the correct day (UTC)\n"
            "• Maintains a public pinned birthday list that updates instantly\n"
            "• Sends a welcome DM to new members with a link to add their birthday"
        ),
        inline=False
    )
    # ───── Movie/TV Night Features ─────
    embed.add_field(
        name="Movie/TV Night Features",
        value=(
            "• Stores separate movie and TV show libraries (loaded from dedicated channels)\n"
            "• </list:1442017846589653014> movies or /list shows – Browse the full library with paginated view\n"
            "• </pick:1442305353030176800> – Add a movie from the library to the current round’s temporary pool (with autocomplete)\n"
            "• </pool:1442311836497350656> – See everything currently in the pick pool and who added it\n"
            "• </random:1442017303230156963> – Randomly selects one movie from the pool, announces it publicly, then clears the pool\n"
            "• </media_add:1441698665981939825> – Admins can permanently add new movies or shows to the library"
        ),
        inline=False
    )
    # ───── Utility / Admin ─────
    embed.add_field(
        name="Utility / Admin",
        value=(
            "• </say:1440927430209703986> – Make the bot speak in the current channel (admin only)\n"
            "• </color:1442416784635334668> – Lets members with the “Dead Chat” role change that role’s color (hex or named colors)"
        ),
        inline=False
    )
    # ───── Holiday Themes (NEW!) ─────
    embed.add_field(
        name="Holiday Themes",
        value=(
            "• </holiday_add:1442616885802832115> – Instantly apply festive color roles (Christmas = Grinch/Cranberry/Tinsel | Halloween = Cauldron/Candy/Witchy)\n"
            "• </holiday_remove:1442616885802832116> – Remove all holiday color roles from everyone in one click\n"
            "Perfect for Christmas, Halloween, and future holidays!"
        ),
        inline=False
    )
    embed.set_thumbnail(url=MEMBERS_ICON)
    embed.set_footer(text=f"• Bot by Soft Dreamings", icon_url=MEMBERS_ICON)
   
    await ctx.respond(embed=embed)


@bot.slash_command(name="membercommands", description="Quick list of commands members can use")
async def membercommands(ctx: discord.ApplicationContext):
    embed = discord.Embed(
        title="Commands",
        color=0x00e1ff
    )

    embed.add_field(
        name="Birthdays",
        value=(
            "• </set:1440919374310408234> – Add your own birthday (month + day)\n"
        ),
        inline=False
    )

    embed.add_field(
        name="Movie & TV Night",
        value=(
            "• </list:1442017846589653014> movies - Browse the movie list\n"
            "• </list:1442017846589653014> shows - Browse the TV show list\n"
            "• </pick:1442305353030176800> – Add a movie to tonight’s voting pool\n"
            "• </pool:1442311836497350656> – See what’s in the current pool"
        ),
        inline=False
    )

    embed.add_field(
        name="Fun & Chat",
        value="• </color:1442416784635334668> – Change Dead Chat role color (if you have the role)",
        inline=False
    )

    await ctx.respond(embed=embed, ephemeral=True)


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
    description="Add a movie to the temporary pick pool"
)
async def pick_cmd(
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


@bot.slash_command(
    name="random",
    description="Choose a random movie from the current pool and reset it"
)
async def random_pick_cmd(ctx: "discord.ApplicationContext"):
    if not ctx.guild:
        return await ctx.respond("This command can only be used in a server.", ephemeral=True)

    guild_id = ctx.guild.id
    pool = request_pool.get(guild_id, [])

    if not pool:
        return await ctx.respond(
            "There are no movies in the pool.\n"
            "Use `/pick` to add movies first.",
            ephemeral=True,
        )

    user_id, title = pyrandom.choice(pool)

    # Reset the pool for this guild
    request_pool[guild_id] = []

    member = ctx.guild.get_member(user_id)
    requester_display = member.mention if member else f"<@{user_id}>"

    # Make the result public so everyone sees what was chosen
    await ctx.respond(
        f"🎲 Random Pick: **{title}**\n"
        f"Requested by {requester_display}\n"
        f"The pool has been cleared. Start a new round with `/pick`."
    )


@bot.slash_command(
    name="pool",
    description="Show all movies currently in the pick pool"
)
async def pool_cmd(ctx: "discord.ApplicationContext"):
    if not ctx.guild:
        return await ctx.respond("This command can only be used in a server.", ephemeral=True)

    guild_id = ctx.guild.id
    pool = request_pool.get(guild_id, [])

    if not pool:
        return await ctx.respond(
            "The pool is currently empty.\nUse `/pick` to add movies.",
            ephemeral=True,
        )

    # Build a list of entries: "Movie Title — Requested by @User"
    lines = []
    for user_id, title in pool:
        member = ctx.guild.get_member(user_id)
        requester = member.mention if member else f"<@{user_id}>"
        lines.append(f"• **{title}** — added by {requester}")

    description = "\n".join(lines)

    embed = discord.Embed(
        title="🎬 Current Pick Pool",
        description=description,
        color=0x2e2f33
    )

    await ctx.respond(embed=embed, ephemeral=True)


COLOR_NAME_MAP = {
    "red":     0xFF0000,
    "blue":    0x0000FF,
    "green":   0x00FF00,
    "purple":  0x800080,
    "pink":    0xFFC0CB,
    "yellow":  0xFFFF00,
    "orange":  0xFFA500,
    "teal":    0x008080,
    "cyan":    0x00FFFF,
    "magenta": 0xFF00FF,
    "black":   0x000000,
    "white":   0xFFFFFF,
    "gray":    0x808080,
    "grey":    0x808080,
    "maroon":  0x800000,
    "navy":    0x000080,
    "lime":    0x32CD32,
    "gold":    0xFFD700
}

@bot.slash_command(name="color", description="Change the Dead Chat role color")
async def color(
    ctx: discord.ApplicationContext,
    color: discord.Option(str, "Hex or name (e.g. #ff0000, ff0000, red, pink)", required=True),
):
    if DEAD_CHAT_ROLE_ID == 0:
        await ctx.respond("Dead Chat role is not configured.", ephemeral=True)
        return

    guild = ctx.guild
    if guild is None:
        await ctx.respond("This command can only be used in a server.", ephemeral=True)
        return

    role = guild.get_role(DEAD_CHAT_ROLE_ID)
    if role is None:
        await ctx.respond("Dead Chat role not found.", ephemeral=True)
        return

    member = ctx.author
    if role not in member.roles:
        await ctx.respond("You don't have the Dead Chat role.", ephemeral=True)
        return

    raw = color.strip().lstrip('#')

    if raw in COLOR_NAME_MAP:
        color_int = COLOR_NAME_MAP[raw]
    else:
        value = raw
        if value.startswith("#"):
            value = value[1:]
        try:
            color_int = int(value, 16)
        except ValueError:
            valid_names = ", ".join(sorted(COLOR_NAME_MAP.keys()))
            await ctx.respond(
                "Use a valid hex color like `#ff0000` / `ff0000` "
                f"or one of these names: {valid_names}.",
                ephemeral=True
            )
            return

    try:
        await role.edit(color=discord.Color(color_int), reason="Dead Chat color change")
    except discord.Forbidden:
        await ctx.respond("I don't have permission to edit that role.", ephemeral=True)
        return

    await ctx.respond(f"Updated {role.name} color.", ephemeral=True)

# ────────────────────── HOLIDAY COLOR ROLES ──────────────────────
HOLIDAY_ROLES = {
    "christmas": {
        1296591590940344330: 1442605535018094592,  # Owners → Grinch
        1296586486635823247: 1442606609405841518,  # Original Members → Cranberry
        1325384410975047735: 1442605476989894788,  # Members → Tinsel
    },
    "halloween": {
        1296591590940344330: 1442607402678747227,  # Owners → Cauldron
        1296586486635823247: 1442607334882021436,  # Original Members → Candy
        1325384410975047735: 1442607365923930132,  # Members → Witchy
    },
}

# All holiday color role IDs (used for /holiday_remove)
ALL_HOLIDAY_ROLE_IDS = {
    1442605535018094592,  # Grinch
    1442606609405841518,  # Cranberry
    1442605476989894788,  # Tinsel
    1442607402678747227,  # Cauldron
    1442607334882021436,  # Candy
    1442607365923930132,  # Witchy
}

@bot.slash_command(name="holiday_add", description="Apply holiday color roles (Admin only)")
async def holiday_add(
    ctx: discord.ApplicationContext,
    holiday: discord.Option(
        str,
        "Which holiday theme?",
        choices=["christmas", "halloween"],
        required=True
    )
):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator or be the server owner.", ephemeral=True)

    await ctx.defer(ephemeral=True)

    mapping = HOLIDAY_ROLES[holiday]
    added_count = 0

    for base_role_id, holiday_role_id in mapping.items():
        base_role = ctx.guild.get_role(base_role_id)
        holiday_role = ctx.guild.get_role(holiday_role_id)
        if not base_role or not holiday_role:
            continue

        async for member in ctx.guild.fetch_members(limit=None):
            if base_role in member.roles and holiday_role not in member.roles:
                try:
                    await member.add_roles(holiday_role, reason=f"Holiday theme: {holiday.capitalize()}")
                    added_count += 1
                except discord.Forbidden:
                    pass  # bot lacks perms
                except discord.HTTPException:
                    pass

    await ctx.followup.send(f"✅ **{holiday.capitalize()}** theme applied! Added holiday color roles to **{added_count}** members.", ephemeral=True)


@bot.slash_command(name="holiday_remove", description="Remove ALL holiday color roles from everyone (Admin only)")
async def holiday_remove(ctx: discord.ApplicationContext):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator or be the server owner.", ephemeral=True)

    await ctx.defer(ephemeral=True)

    removed_count = 0

    for holiday_role_id in ALL_HOLIDAY_ROLE_IDS:
        role = ctx.guild.get_role(holiday_role_id)
        if not role:
            continue

        async for member in ctx.guild.fetch_members(limit=None):
            if role in member.roles:
                try:
                    await member.remove_roles(role, reason="Holiday theme removed")
                    removed_count += 1
                except discord.Forbidden:
                    pass
                except discord.HTTPException:
                    pass

    await ctx.followup.send(f"🧹 All holiday color roles removed from **{removed_count}** role assignments.", ephemeral=True)

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


# ────────────────────── QUESTION OF THE DAY (SIMPLE VERSION – NO COG) ──────────────────────
import requests
from discord.ext import tasks
from datetime import time

QOTD_CHANNEL_ID = 1207917070684004452   # ← change if you want
QOTD_TIME = time(9, 0)                  # 9:00 AM

@tasks.loop(time=QOTD_TIME)
async def daily_qotd():
    channel = bot.get_channel(QOTD_CHANNEL_ID)
    if not channel:
        return

    try:
        r = requests.get("https://thestoryshack.com/tools/random-question-generator/", 
                        headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code != 200:
            return
        text = r.text
        start = text.find('<h2>') + 4
        end = text.find('</h2>', start)
        question = text[start:end].strip()
        if not question.endswith("?"):
            question += "?"

        embed = discord.Embed(title="Question of the Day",
                            description=f"**{question}**",
                            color=0x9b59b6)
        embed.set_footer(text=f"{datetime.now().strftime('%B %d, %Y')} • Reply below!")
        await channel.send(embed=embed)
        print(f"[QOTD] Posted: {question}")
    except Exception as e:
        print(f"[QOTD] Error: {e}")

@daily_qotd.before_loop
async def before_qotd():
    await bot.wait_until_ready()

# ←←← THIS IS THE MAGIC COMMAND THAT WILL DEFINITELY SHOW UP ←←←
@bot.slash_command(name="test_qotd", description="Post a QOTD right now (admin only)")
@commands.has_permissions(administrator=True)
async def test_qotd(ctx):
    await ctx.respond("Fetching question…", ephemeral=True)
    await daily_qotd()   # just calls the same function

# Start the daily task
@bot.event
async def on_ready():
    print(f"{bot.user} is online!")
    await initialize_storage_message()
    await initialize_media_lists()
    bot.loop.create_task(birthday_checker())
    
    # Start the daily QOTD task
    daily_qotd.start()
    
    print("[QOTD] System ready — /test_qotd is live and daily post scheduled for 9 AM!")
    

bot.run(os.getenv("TOKEN"))
