import os
import json
import asyncio
from datetime import datetime

import discord

intents = discord.Intents.default()
intents.members = True 

bot = discord.Bot(intents=intents)

# ───────────────────────────────────────────────
# CONFIG
# ───────────────────────────────────────────────

# Role given on someone's birthday
BIRTHDAY_ROLE_ID = int(os.getenv("BIRTHDAY_ROLE_ID", "1217937235840598026"))

# Hidden storage channel where JSON is stored
BIRTHDAY_STORAGE_CHANNEL_ID = int(os.getenv("BIRTHDAY_STORAGE_CHANNEL_ID", "1440912334813134868"))

# The permanent public birthday list message
BIRTHDAY_LIST_CHANNEL_ID = 1435375785220243598
BIRTHDAY_LIST_MESSAGE_ID = 1440951605225848874

# Will be filled on startup
storage_message_id: int | None = None


# ───────────────────────────────────────────────
# INTERNAL STORAGE MESSAGE
# ───────────────────────────────────────────────

async def initialize_storage_message():
    """Ensure a bot-authored JSON storage message exists. Otherwise create one."""
    global storage_message_id

    channel = bot.get_channel(BIRTHDAY_STORAGE_CHANNEL_ID)
    if not channel:
        print("Storage channel not found.")
        return

    # Look for an existing bot-authored message
    async for msg in channel.history(limit=50):
        if msg.author == bot.user:
            storage_message_id = msg.id
            print(f"Found existing storage message: {storage_message_id}")
            return

    # Create fresh storage message
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


# ───────────────────────────────────────────────
# BIRTHDAY UTILITIES
# ───────────────────────────────────────────────

def normalize_date(date_str: str):
    """Return 'MM-DD' or None if invalid."""
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


# ───────────────────────────────────────────────
# BUILD EMBED + UPDATE PUBLIC LIST
# ───────────────────────────────────────────────

async def build_birthday_embed(guild: discord.Guild) -> discord.Embed:
    birthdays = await get_guild_birthdays(guild.id)
    embed = discord.Embed(title="Our Birthdays!", color=0x2e2f33)

    if not birthdays:
        embed.description = (
            "No birthdays have been set yet.\n\n"
            "Use </set:1440919374310408234> to share your birthday"
        )
        return embed

    # birthdays dict = { user_id: "MM-DD" }
    # Sort by MM-DD
    sorted_items = sorted(
        birthdays.items(),  # yields (user_id, mm_dd)
        key=lambda x: x[1]  # sort by date
    )

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
    """Auto-update the public birthday list message."""
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
        await msg.edit(embed=embed)
        print("Birthday list updated.")
    except Exception as e:
        print("Failed to update list:", e)


# ───────────────────────────────────────────────
# SLASH COMMANDS
# ───────────────────────────────────────────────

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
async def remove_birthday_for(
    ctx,
    member: discord.Option(discord.Member, "Member to remove birthday for", required=True)
):
    # Only admins or owner can use this
    if not ctx.author.guild_permissions.administrator and ctx.guild.owner_id != ctx.author.id:
        return await ctx.respond("You need Administrator.", ephemeral=True)

    data = await _load_storage_message()
    gid = str(ctx.guild.id)
    uid = str(member.id)

    if gid not in data or uid not in data[gid]:
        return await ctx.respond("That member has no birthday set.", ephemeral=True)

    # Remove the birthday entry
    del data[gid][uid]

    # Save back to storage
    await _save_storage_message(data)

    # Update the public birthday list
    await update_birthday_list_message(ctx.guild)

    await ctx.respond(f"Removed birthday for {member.mention}.", ephemeral=True)


# ───────────────────────────────────────────────
# EVENTS
# ───────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"{bot.user} is online (birthday bot).")

    await initialize_storage_message()
    bot.loop.create_task(birthday_checker())


@bot.event
async def on_member_join(member):
    try:
        await member.send(
            """Hey, welcome to the server. Feel free to add your birthday in the channel below so we can all celebrate.

https://discord.com/channels/1205041211610501120/1435375785220243598"""
        )
    except:
        pass


# ───────────────────────────────────────────────
# BIRTHDAY CHECKER LOOP
# ───────────────────────────────────────────────

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

                # Give role
                if bday == today_mm_dd:
                    if role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Birthday")
                        except:
                            pass

                # Remove role
                else:
                    if role in member.roles:
                        try:
                            await member.remove_roles(role, reason="Birthday ended")
                        except:
                            pass

        await asyncio.sleep(3600)


# ───────────────────────────────────────────────
# START BOT
# ───────────────────────────────────────────────

bot.run(os.getenv("TOKEN"))
