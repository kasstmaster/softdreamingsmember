import os
import json
import asyncio
from datetime import datetime

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

import discord
import random as pyrandom

intents = discord.Intents.default()
intents.members = True
bot = discord.Bot(intents=intents)

# ───────────────────────── CONFIG ─────────────────────────
BIRTHDAY_ROLE_ID = int(os.getenv("BIRTHDAY_ROLE_ID", "1217937235840598026"))
BIRTHDAY_STORAGE_CHANNEL_ID = int(os.getenv("BIRTHDAY_STORAGE_CHANNEL_ID", "1440912334813134868"))
BIRTHDAY_LIST_CHANNEL_ID = 1440989357535395911
BIRTHDAY_LIST_MESSAGE_ID = 1440989655515271248

MOVIE_REQUESTS_CHANNEL_ID = int(os.getenv("MOVIE_REQUESTS_CHANNEL_ID", "0"))
MOVIE_STORAGE_CHANNEL_ID = int(os.getenv("MOVIE_STORAGE_CHANNEL_ID", "0"))
TV_STORAGE_CHANNEL_ID = int(os.getenv("TV_STORAGE_CHANNEL_ID", "0"))

# Holiday & Member Role IDs
DEAD_CHAT_ROLE_ID = 0  # Set if you use /color command

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

    def _items(self): return movie_titles if self.category == "movies" else tv_titles
    def _max_page(self): return max(0, (len(self._items()) - 1) // PAGE_SIZE)

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
        return f"{header}\n```text\n{' '.join(lines) if lines else 'Empty'}\n```"

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

# ────────────────────── COMMANDS ──────────────────────
@bot.slash_command(name="info", description="Show all bot features")
async def info(ctx):
    embed = discord.Embed(title="Members - Bot Features", color=0x00e1ff)
    embed.add_field(name="Birthday Features", value="• </set:1440919374310408234> – Set your birthday\n• </set_for:1440919374310408235> – Admin set\n• </remove_for:1440954448468774922> – Admin remove\n• </birthdays:1440919374310408236> – View list\n• Auto role + public list + welcome DM", inline=False)
    embed.add_field(name="Movie/TV Night", value="• </list:1442017846589653014> movies/shows\n• </pick:1442305353030176800>\n• </pool:1442311836497350656>\n• </random:1442017303230156963>\n• </media_add:1441698665981939825> (admin)", inline=False)
    embed.add_field(name="Utility / Admin", value="• </say:1440927430209703986> (admin)\n• </color:1442416784635334668> (Dead Chat role)", inline=False)
    embed.add_field(name="Holiday Themes", value="• </holiday_add:1442616885802832115> – Apply Christmas/Halloween colors\n• </holiday_remove:NEW> – Remove all holiday roles", inline=False)
    embed.set_footer(text="Bot by Soft Dreamings")
    await ctx.respond(embed=embed)

@bot.slash_command(name="commands", description="Admin-only command reference")
async def commands(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    embed = discord.Embed(title="Admin Commands", color=0xff6b6b)
    embed.add_field(name="Birthdays", value="• </set_for:1440919374310408235>\n• </remove_for:1440954448468774922>", inline=False)
    embed.add_field(name="Movie Night", value="• </random:1442017303230156963> – Force pick", inline=False)
    embed.add_field(name="Holidays", value="• </holiday_add:1442616885802832115>\n• </holiday_remove:1442616885802832116>", inline=False)
    embed.set_footer(text="Also: /say • /media_add")
    await ctx.respond(embed=embed, ephemeral=True)

@bot.slash_command(name="membercommands", description="What regular members can use")
async def membercommands(ctx):
    embed = discord.Embed(title="Member Commands", color=0x00e1ff)
    embed.add_field(name="Birthdays", value="• </set:1440919374310408234>\n• </birthdays:1440919374310408236>", inline=False)
    embed.add_field(name="Movie Night", value="• </list:1442017846589653014> movies/shows\n• </pick:1442305353030176800>\n• </pool:1442311836497350656>", inline=False)
    embed.add_field(name="Fun", value="• </color:1442416784635334668> (if you have Dead Chat)", inline=False)
    embed.add_field(name="Full list?", value="Use **/info**!", inline=False)
    await ctx.respond(embed=embed, ephemeral=True)

# Birthday commands
@bot.slash_command(name="set")
async def set_birthday_self(ctx, month: discord.Option(str, choices=MONTH_CHOICES), day: int):
    mm_dd = build_mm_dd(month, day)
    if not mm_dd:
        return await ctx.respond("Invalid date.", ephemeral=True)
    await set_birthday(ctx.guild.id, ctx.author.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Birthday set to `{mm_dd}`!", ephemeral=True)

@bot.slash_command(name="set_for")
async def set_for(ctx, member: discord.Member, month: discord.Option(str, choices=MONTH_CHOICES), day: int):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    mm_dd = build_mm_dd(month, day)
    if not mm_dd:
        return await ctx.respond("Invalid date.", ephemeral=True)
    await set_birthday(ctx.guild.id, member.id, mm_dd)
    await update_birthday_list_message(ctx.guild)
    await ctx.respond(f"Set {member.mention}'s birthday to `{mm_dd}`", ephemeral=True)

@bot.slash_command(name="remove_for")
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

@bot.slash_command(name="birthdays")
async def birthdays_cmd(ctx):
    await ctx.respond(embed=await build_birthday_embed(ctx.guild), ephemeral=True)

# Movie commands
@bot.slash_command(name="pick")
async def pick(ctx, title: discord.Option(str, autocomplete=movie_autocomplete)):
    if not movie_titles:
        return await ctx.respond("Movie list not loaded.", ephemeral=True)
    canon = next((t for t in movie_titles if t.lower() == title.strip().lower()), None)
    if not canon:
        return await ctx.respond("That movie isn't in the library.", ephemeral=True)
    pool = request_pool.setdefault(ctx.guild.id, [])
    pool.append((ctx.author.id, canon))
    await ctx.respond(f"Added **{canon}** • Pool size: `{len(pool)}`", ephemeral=True)

@bot.slash_command(name="pool")
async def pool(ctx):
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.respond("Pool is empty.", ephemeral=True)
    lines = [f"• **{t}** — {ctx.guild.get_member(u).mention if ctx.guild.get_member(u) else '<@'+str(u)+'>'}" for u, t in pool]
    await ctx.respond(embed=discord.Embed(title="Current Pool", description="\n".join(lines), color=0x2e2f33), ephemeral=True)

@bot.slash_command(name="random")
async def random_pick(ctx):
    pool = request_pool.get(ctx.guild.id, [])
    if not pool:
        return await ctx.respond("Pool is empty.", ephemeral=True)
    user_id, title = pyrandom.choice(pool)
    request_pool[ctx.guild.id] = []
    member = ctx.guild.get_member(user_id)
    await ctx.respond(f"Random Pick: **{title}**\nRequested by {member.mention if member else '<@'+str(user_id)+'>'}")

@bot.slash_command(name="list")
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


# ────────────────────── HOLIDAY COLOR ROLES (BY NAME – KEEPS YOUR PRETTY NAMES) ──────────────────────
CHRISTMAS_ROLES = ["Grinch", "Cranberry", "Tinsel"]
HALLOWEEN_ROLES = ["Cauldron", "Candy", "Witchy"]

def find_role_by_name(guild: discord.Guild, name: str) -> discord.Role | None:
    name_lower = name.lower()
    for role in guild.roles:
        cleaned = role.name.replace("🎄", "").replace("🎃", "").replace("❄️", "").strip()
        if cleaned.lower() == name_lower:
            return role
    return None

@bot.slash_command(name="holiday_add")
async def holiday_add(ctx, holiday: discord.Option(str, choices=["christmas", "halloween"])):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.defer(ephemeral=True)
    roles = CHRISTMAS_ROLES if holiday == "christmas" else HALLOWEEN_ROLES
    added = 0
    for role_name in roles:
        role = find_role_by_name(ctx.guild, role_name)
        if role:
            async for member in ctx.guild.fetch_members(limit=None):
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"{holiday.capitalize()} theme")
                        added += 1
                    except:
                        pass
    await ctx.followup.send(f"Applied **{holiday.capitalize()}** theme to **{added}** members! {'🎄' if holiday=='christmas' else '🎃'}", ephemeral=True)

@bot.slash_command(name="holiday_remove")
async def holiday_remove(ctx):
    if not (ctx.author.guild_permissions.administrator or ctx.guild.owner_id == ctx.author.id):
        return await ctx.respond("Admin only.", ephemeral=True)
    await ctx.defer(ephemeral=True)
    removed = 0
    for role_name in CHRISTMAS_ROLES + HALLOWEEN_ROLES:
        role = find_role_by_name(ctx.guild, role_name)
        if role:
            async for member in ctx.guild.fetch_members(limit=None):
                if role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Holiday theme ended")
                        removed += 1
                    except:
                        pass
    await ctx.followup.send(f"Removed all holiday roles from **{removed}** members.", ephemeral=True)
    

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

@bot.event
async def on_member_join(member):
    try:
        await member.send("Welcome! Add your birthday here → https://discord.com/channels/1205041211610501120/1440989357535395911/1440989655515271248")
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
