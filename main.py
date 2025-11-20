import os
import json
import asyncio
from datetime import datetime

import discord

intents = discord.Intents.default()
intents.members = True  # needed for on_member_join and role editing

bot = discord.Bot(intents=intents)

# ───────────────── CONFIG ─────────────────

# Role that should be given on someone's birthday
BIRTHDAY_ROLE_ID = int(os.getenv("BIRTHDAY_ROLE_ID", "1217937235840598026"))

# Private storage channel (bot will create its own storage message here)
BIRTHDAY_STORAGE_CHANNEL_ID = int(os.getenv("BIRTHDAY_STORAGE_CHANNEL_ID", "1440912334813134868"))

# ID of the message the bot uses as JSON storage (set at runtime)
storage_message_id: int | None = None


# ───────────── STORAGE IN DISCORD CHANNEL ─────────────

async def initialize_storage_message():
    """
    Ensure there is a bot-authored storage message in the storage channel.
    If one exists, remember its ID. Otherwise create a new one with "{}".
    """
    global storage_message_id

    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel:
        print("Storage channel not found")
        return

    # Try to find an existing message authored by this bot
    async for msg in channel.history(limit=50):
        if msg.author == bot.user:
            storage_message_id = msg.id
            print(f"Found existing storage message: {storage_message_id}")
            return

    # Otherwise create a new storage message
    msg = await channel.send("{}")
    storage_message_id = msg.id
    print(f"Created new storage message: {storage_message_id}")


async def _load_storage_message() -> dict:
    """Load the birthday dict from the storage message."""
    global storage_message_id

    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel or storage_message_id is None:
        return {}

    try:
        msg = await channel.fetch_message(storage_message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return {}

    content = msg.content.strip() or "{}"
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
        return {}
    except json.JSONDecodeError:
        return {}


async def _save_storage_message(data: dict):
    """Save the birthday dict back to the storage message."""
    global storage_message_id

    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel or storage_message_id is None:
        return

    try:
        msg = await channel.fetch_message(storage_message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return

    text = json.dumps(data, indent=2)
    if len(text) > 1900:
        text = text[:1900]
    await msg.edit(content=text)


def normalize_date(date_str: str):
    """Expect MM-DD, return normalized MM-DD or None."""
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


async def get_guild_birthdays(guild_id: int) -> dict:
    data = await _load_storage_message()
    return data.get(str(guild_id), {})


async def build_birthday_embed(guild: discord.Guild) -> discord.Embed:
    birthdays = await get_guild_birthdays(guild.id)
    embed = discord.Embed(title="Our Birthdays!", color=0x2e2f33)

    if not birthdays:
        # Optional: still show the hint even if list is empty
        embed.description = (
            "No birthdays have been set yet.\n\n"
            "Use </set:1440919374310408234> to share your birthday"
        )
        return embed

    items = []
    for user_id, mm_dd in birthdays.items():
        items.append((mm_dd, user_id))

    items.sort(key=lambda x: x[0])  # sort by MM-DD

    lines = [f"`{mm_dd}` — <@{user_id}>" for mm_dd, user_id in items]

    # blank line + hint under the list
    lines.append("")
    lines.append("Use </set:1440919374310408234> to share your birthday")

    embed.description = "\n".join(lines)
    return embed


# ───────────── VIEW WITH REFRESH BUTTON ─────────────

class BirthdayListView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)
        self.guild = guild

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.guild is None or interaction.guild.id != self.guild.id:
            return await interaction.response.send_message("Wrong server.", ephemeral=True)

        embed = await build_birthday_embed(self.guild)
        await interaction.response.edit_message(embed=embed, view=self)


# ───────────── SLASH COMMANDS ─────────────

@bot.slash_command(name="set", description="Set your birthday (MM-DD)")
async def set_birthday_self(
    ctx,
    date: discord.Option(str, "Format: MM-DD (e.g. 03-14)", required=True),
):
    mm_dd = normalize_date(date)
    if not mm_dd:
        return await ctx.respond("Invalid date. Use MM-DD like `03-14`.", ephemeral=True)

    await set_birthday(ctx.guild.id, ctx.author.id, mm_dd)
    await ctx.respond(f"Your birthday has been set to `{mm_dd}`.", ephemeral=True)


@bot.slash_command(name="set_for", description="Set a birthday for another member (MM-DD)")
async def set_birthday_for(
    ctx,
    member: discord.Option(discord.Member, "Member to set birthday for", required=True),
    date: discord.Option(str, "Format: MM-DD (e.g. 03-14)", required=True),
):
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator or to be the server owner.", ephemeral=True)

    mm_dd = normalize_date(date)
    if not mm_dd:
        return await ctx.respond("Invalid date. Use MM-DD like `03-14`.", ephemeral=True)

    await set_birthday(ctx.guild.id, member.id, mm_dd)
    await ctx.respond(f"Set birthday for {member.mention} to `{mm_dd}`.", ephemeral=True)


@bot.slash_command(name="birthdays", description="Show all server birthdays")
async def birthdays_cmd(ctx):
    embed = await build_birthday_embed(ctx.guild)
    view = BirthdayListView(ctx.guild)
    await ctx.respond(embed=embed, view=view)

@bot.slash_command(name="say", description="Make the bot say something in this channel")
async def say(
    ctx,
    message: discord.Option(str, "Message to send", required=True)
):
    # Only admins or server owner
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator.", ephemeral=True)

    await ctx.channel.send(message)
    await ctx.respond("Sent!", ephemeral=True)


# ───────────── EVENTS ─────────────

@bot.event
async def on_ready():
    print(f"{bot.user} is online (birthday bot).")

    # Make sure storage message exists before anything uses it
    await initialize_storage_message()

    bot.loop.create_task(birthday_checker())


@bot.event
async def on_member_join(member: discord.Member):
    # DM new member
    try:
        await member.send(
            """Hey, welcome to the server. Feel free to add your birthday in the channel below so we can all celebrate.
        
https://discord.com/channels/1205041211610501120/1435375785220243598"""
        )
    except discord.Forbidden:
        # DMs disabled; ignore
        pass


# ───────────── BACKGROUND TASK ─────────────

async def birthday_checker():
    await bot.wait_until_ready()
    print("Birthday checker started")

    while not bot.is_closed():
        today = datetime.utcnow().date()
        today_mm_dd = today.strftime("%m-%d")

        all_birthdays = await _load_storage_message()

        for guild in bot.guilds:
            role = guild.get_role(BIRTHDAY_ROLE_ID)
            if not role:
                continue

            birthdays = all_birthdays.get(str(guild.id), {})

            for member in guild.members:
                user_id_str = str(member.id)
                user_bday = birthdays.get(user_id_str)

                if user_bday == today_mm_dd:
                    if role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Birthday")
                        except discord.Forbidden:
                            pass
                else:
                    if role in member.roles and user_bday != today_mm_dd:
                        try:
                            await member.remove_roles(role, reason="Not their birthday")
                        except discord.Forbidden:
                            pass

        await asyncio.sleep(3600)  # check once per hour


# ───────────── START BOT ─────────────

bot.run(os.getenv("TOKEN"))
