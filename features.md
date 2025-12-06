# 1. Birthday System (Storage, Role, Public List)
Per-Guild Birthday Storage

Stores birthdays per guild as mm-dd per user in a JSON blob in a storage message in BIRTHDAY_STORAGE_CHANNEL_ID.

Uses:

initialize_storage_message() to ensure:

1 message for birthdays JSON

1 message for pool data (POOL_DATA:)

Helpers:

set_birthday(guild_id, user_id, mm_dd) to set/update a user birthday.

get_guild_birthdays(guild_id) to read all birthdays.

_load_storage_message / _save_storage_message to read/write persistent JSON.

Birthday Role Assignment (Daily Checker)

Background task birthday_checker:

Runs once per minute, and when now.hour == 15 and now.minute == 0 UTC:

For each guild:

Looks up BIRTHDAY_ROLE_ID.

Compares today’s "%m-%d" with saved birthdays.

Adds birthday role to members whose date matches.

Removes the role from members whose date does not match.

Effect: birthday role is automatically maintained per day for each member.

Birthday List Embeds

build_birthday_embed(guild):

Builds an embed with all birthdays in sorted mm-dd order.

Shows each user mention + their date.

Adds a call-to-action in the description:

Slash command to set birthday (/set).

Footer explains that messages in this channel auto-delete after 5 minutes (assumes external cleanup).

get_birthday_public_location / set_birthday_public_location:

Tracks where the public birthday list embed lives:

Either from storage JSON

Or fallback to BIRTHDAY_LIST_CHANNEL_ID / BIRTHDAY_LIST_MESSAGE_ID.

Public Birthday List Updating

update_birthday_list_message(guild):

Fetches the configured public birthday message (location from storage or env).

Edits it with an up-to-date birthday embed.

Slash commands:

/birthdays — shows the birthday list ephemerally to the user.

/birthdays_public — creates or updates the persistent public birthday list message in a channel (admin only).

# 2. Movie Library & Request Pool System

This is the main “movie night” framework.

Google Sheets Movie Library

On startup:

initialize_media_lists() reads Google Sheet (via service account):

Sheet key SHEET_ID

Worksheet "Movies"

Loads all movies (skipping header row) into movie_titles, each with:

title

poster URL

trailer URL

If Google credentials not present, QOTD + library features are effectively disabled.

Movie Storage Channel Sync

sync_movie_library_messages() keeps MOVIE_STORAGE_CHANNEL_ID in sync with the Google Sheet:

For each movie row:

Either edits existing bot message at that index

Or creates a new message

Content: first line = title; second line (optional) = trailer link.

Attaches MovieEntryView (with “Add to Pool” button) to each message.

Deletes any extra older bot messages beyond the current number of movies.

Request Pool Storage (Per Guild)

Persistent storage:

Second storage message in BIRTHDAY_STORAGE_CHANNEL_ID holds POOL_DATA: { ... }.

In memory:

request_pool: dict[guild_id, list[(user_id, title)]]

pool_message_locations: dict[guild_id, (channel_id, message_id)] for the public pool embed.

Functions:

load_request_pool() — loads both pool entries and public message locations from POOL_DATA.

save_request_pool() — writes pool entries and message location back to POOL_DATA.

Pool Embeds & Public Pool Message

build_pool_embed(guild):

Shows all pool picks in alphabetical order by member display name.

Format: <member mention> — **Movie Title**

Footer: same “deleted after 5 minutes” note.

Includes usage instructions:

/pick

/search

/replace

update_pool_public_message(guild):

If there’s a recorded message location for this guild, refreshes its embed.

/pool:

Shows the pool embed ephemerally to the user.

/pool_public (admin only):

Creates or updates the persistent public pool message in any channel and writes its location to storage.

# 3. Movie Selection & Pool Management Commands
Browsing Library (Picker)

MediaPagerView (dropdown + Prev/Next buttons):

Paginates through movie_titles with PAGE_SIZE entries per page.

Shows a text list of titles with numbers, and a dropdown labeled “✅ Select One”.

On select:

Validates that the guild is present.

Enforces:

No duplicate titles in the pool for that day.

Per-user cap: MAX_POOL_ENTRIES_PER_USER entries.

Normalizes the title to canonical casing in movie_titles.

Adds (user_id, movie_title) to request_pool[guild.id].

Saves pool and updates public pool embed.

Replies ephemerally with updated user count in the pool.

Slash commands:

If ENABLE_TV_IN_PICK is False (current default in code):

/pick — opens a MediaPagerView("movies") for the requester.

Library Search and Replace

Autocomplete:

movie_autocomplete — suggests titles from the loaded library matching the query.

my_pool_movie_autocomplete — suggests only the current user’s pool entries.

Commands:

/search:

Autocomplete movie title from library.

Validates that the movie exists in movie_titles.

Enforces:

No duplicate titles in pool.

Per-user cap.

Adds the pick, saves, updates pool embed, and acknowledges ephemerally.

/replace:

old_title: autocomplete over user’s existing pool picks.

new_title: autocomplete over library.

Replaces that single entry in the pool for this user.

Saves and updates pool embed.

Quick “Add to Pool” Buttons

MovieEntryView:

Used on each per-movie message in the movie storage channel.

Button “Add to Pool”:

Reads the movie title from the first line of the message.

Validates it against current movie_titles.

Enforces same rules as /search:

No duplicates.

Per-user cap.

Adds pick, saves, updates public pool embed.

Pool Administration

/pool_remove (admin only):

Remove pool entries based on:

a specific user

or a specific title

or both combined.

Supports partial removal:

Example: all entries for a user or just one specific title for that user.

Saves and updates pool embed.

Winner Selection (Random Movie Night Pick)

/random:

Ephemeral to the user but announces publicly:

Requires a non-empty pool.

Picks a random index winner_idx from the pool.

Removes that one entry from the pool; all other movies roll over.

Saves pool and updates pool embed.

Announcements:

In MOVIE_NIGHT_ANNOUNCEMENT_CHANNEL_ID:

Post includes:

Pool Winner: **Title**

Winner’s mention

How many movies rolled over.

In SECOND_MOVIE_ANNOUNCEMENT_CHANNEL_ID:

Posts just **Title**.

Adds reactions for quick rating:

😍 😃 🙂 🫤 😒 🤢

Responds to the invoker ephemerally confirming that the winner was announced.

# 4. QOTD (Question of the Day) System
Google Sheets Integration

Uses same SHEET_ID and credentials as movie library but different worksheets/tabs.

Seasonal tab selection:

"Fall Season" tab for October–November.

"Christmas" tab for December.

"Regular" tab for all other months.

If the chosen tab does not exist, falls back to the first sheet.

Question Selection & Posting

post_daily_qotd():

Reads all rows from the active tab.

Uses columns A and B as “used” markers, and B (primarily) or A for question text.

Constructs an unused list of questions where at least one status cell is empty.

If no unused questions remain:

Resets all A/B cells from row 2 down to empty.

Treats all questions as unused again.

Randomly picks one unused question.

Builds an embed:

Title: “Question of the Day”

Description: selected question text

Color depends on tab/season

Footer: <season> • Reply below!

Posts the embed into QOTD_CHANNEL_ID.

Writes a “Used <YYYY-MM-DD>” stamp in column A or B depending on which side was used.

Scheduling & Manual Trigger

qotd_scheduler:

Background loop.

At 17:00 UTC (once per day), calls post_daily_qotd().

/qotd_send (admin only):

Manual immediate QOTD post with the same logic.

# 5. Holiday Theme System (Roles, Emojis, Icons)
Holiday Role Themes (Halloween / Christmas)

Role mapping (from env):

For each holiday, maps special “color” roles (like “Cranberry”, “Grinch”) to a base keyword (“Admin”, “Member”, “Bots”, etc.).

apply_holiday_theme(guild, holiday):

For each special color role:

Iterates over all members.

If a member has a role whose name contains the base keyword, adds the special color role.

Updates:

Bot avatar.

Guild icon.

Icon URLs come from holiday-specific env vars.

clear_holiday_theme(guild):

Removes all Christmas & Halloween color roles from any member.

Restores default icon for bot + server.

Holiday Emoji Themes

Emoji config provided via env JSON (CHRISTMAS_EMOJIS, HALLOWEEN_EMOJIS).

apply_holiday_emojis(guild, holiday):

Reads configured emojis (name + URL).

Checks existing emoji names and guild emoji limit.

Downloads emoji images and creates discord custom emojis.

clear_holiday_emojis(guild):

Deletes all emojis with names that are defined in either holiday config.

Holiday Scheduler

holiday_scheduler:

Runs at 09:00 UTC daily.

Based on today ("%m-%d"):

10-01 to 10-31: Halloween theme:

Clear previous theme + emojis.

Apply Halloween theme + emojis.

12-01 to 12-26: Christmas theme:

Clear previous theme + emojis.

Apply Christmas theme + emojis.

Any other date:

Clear holiday theme and emojis entirely.

# 6. Dead Chat Role Color Changer

Not the full dead-chat game; just visual customization.

DEAD_CHAT_ROLE_ID or DEAD_CHAT_ROLE_NAME is used to identify the Dead Chat role.

Color cycle list: DEAD_CHAT_COLORS (eight preset discord colors).

/color command:

Requires the caller to have the Dead Chat role.

Determines the current color index in the cycle, advances to the next color.

Edits the role color.

Responds ephemerally with the progress step (index/total).

# 7. Misc Member-Facing Features
DM On Join (Birthday Funnel)

on_member_join:

Sends a direct message with a link to the birthday channel/message so users can add their birthday to the shared list.

Voice Channel Role Toggle

on_voice_state_update:

Watches a specific voice channel (vc_id constant in code).

Assigns or removes a specific role when a member joins or leaves that VC.

Behaves as an “in VC” indicator role.

# 8. Admin Utility Commands
Message Editing

/editbotmsg:

Admin-only.

Allows editing a bot-sent message by ID in the current channel.

Accepts up to four lines; ignores blank lines.

Validates:

Message is found.

Message was authored by the bot.

Movie Library Maintenance

/media_reload:

Admin-only.

Reloads movie_titles from Google Sheets.

/library_sync:

Admin-only.

Reloads movie list then syncs all messages in MOVIE_STORAGE_CHANNEL_ID with the sheets (and attaches MovieEntryView).

Simple Admin Say

/say:

Admin-only.

Sends arbitrary text via the bot in the current channel.

Confirms ephemerally.

# 9. Background Tasks Overview

Started in on_ready:

birthday_checker():

Daily at 15:00 UTC: maintain birthday roles.

qotd_scheduler():

Daily at 17:00 UTC: post QOTD.

holiday_scheduler():

Daily at 09:00 UTC: adjust holiday themes and emojis.

Plus on startup:

Loads storage messages.

Loads movie library.

Loads request pools.

Registers persistent MovieEntryView.

# 10. Storage Architecture

Uses one storage channel: BIRTHDAY_STORAGE_CHANNEL_ID.

Two bot messages live there:

Birthdays and birthday public message info (plain JSON).

Request pool data prefixed with POOL_DATA:.

All persistent features rely on these:

Birthdays per user per guild.

Public birthday message location.

Movie request pools and pool public message locations.

COMPLETE FEATURE SUMMARY (BULLET LIST)

Per-guild birthday storage (mm-dd per user).

Daily birthday role assignment and removal at fixed UTC time.

Birthday embeds and an updatable public birthday list message.

Self-service birthday registration (/set).

Admin birthday controls (/set_for, /remove_for, /birthdays_public).

DM funnel on member join to direct them to the birthday system.

Movie library loaded from Google Sheets.

Movie library channel sync (one message per movie) with “Add to Pool” buttons.

Per-guild movie request pool with persistence.

Ephemeral view of today’s pool (/pool) and a public pool message (/pool_public).

Movie browser with pagination and dropdown selection (/pick via MediaPagerView).

Library search and selection with autocompletes (/search).

Per-user replacement of pool picks (/replace).

Per-user cap on pool picks and per-title uniqueness per day.

Admin removal of pool entries (/pool_remove).

Random winner selection from pool (/random), removing the winner and rolling over others.

Winner announcement to two separate channels, including rating reactions.

Question-of-the-Day system powered by Google Sheets with seasonal tabs.

Daily scheduled QOTD posting and manual QOTD trigger (/qotd_send).

Holiday theming for roles: Halloween and Christmas roles layered on top of base roles.

Daily automatic switching/clearing of holiday themes based on date.

Holiday emoji sets created and cleared based on configured JSON.

Holiday icon theming for both bot avatar and guild icon.

Dead Chat role color cycle command (/color) for role holders.

Voice channel role toggle when joining/leaving a specific VC.

Admin editing of bot messages (/editbotmsg).

Admin reload and sync of movie library from Sheets (/media_reload, /library_sync).

Admin broadcast via /say.

Robust persistent storage via two messages in a storage channel for birthdays and movie pools.
