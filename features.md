# 1. Birthday System
Birthday Storage

Stores per-member birthdays in a persistent JSON message.

Supports adding, updating, removing, and reading birthdays per guild.

Maintains a saved location for a public birthday list message.

Birthday Role Automation

A scheduled daily check assigns the birthday role to users whose birthday matches the current date.

Removes the role automatically when the date no longer matches.

Birthday Embeds & Public List

Builds a unified birthday list embed for the server.

Updates a persistent public message when birthdays change.

Provides self-service and admin controls for maintaining entries.

# 2. Movie Library System
Google Sheets Integration

Loads the movie library from a Google Sheet at startup.

Retrieves titles, posters, and trailer links from the sheet.

Library Message Sync

Syncs the library to a designated channel, one message per movie.

Keeps messages aligned with the sheet and attaches an “Add to Pool” button to each.

# 3. Movie Request Pool
Pool Storage

Stores all movie picks in persistent JSON.

Tracks the location of a public pool display message.

Pool Management

Users can add movies via browsing, searching, or using message buttons.

Enforces:

No duplicate titles

Per-user pick limits

Allows users to replace one of their own picks.

Pool Display

Generates a pool embed listing all current picks.

Updates a persistent public pool message when changes occur.

Admin Controls

Allows administrators to remove specific picks by user or title.

Supports creating or updating the public pool embed.

Provides a full library reload and channel sync from Sheets.

# 4. Movie Night Selection
Random Winner

Selects a random movie from the pool.

Removes the winning entry and rolls over the rest.

Announces the winner in two configured channels.

Provides reaction emojis for rating the movie.

# 5. QOTD System (Question of the Day)
Sheet-Driven Questions

Pulls daily questions from a seasonal worksheet.

Tracks which questions have been used and resets when exhausted.

Automated Posting

Posts the QOTD once per day at a scheduled UTC time.

Builds a themed embed based on season: Regular, Fall, or Christmas.

Manual Controls

Allows administrators to trigger QOTD immediately.

# 6. Holiday Theme System
Holiday Roles

Applies seasonal color roles (Halloween/Christmas) based on members’ existing roles.

Clears and reapplies roles automatically as holidays start and end.

Holiday Emojis

Creates custom emojis from configured URLs for each holiday.

Removes them when the holiday ends.

Server & Bot Icons

Updates both the server icon and bot avatar to holiday versions.

Daily Scheduling

Automatically applies or clears themes based on the current date.

# 7. Dead Chat Role Enhancements
Color Cycling

Allows Dead Chat role holders to cycle the role’s color through a preset sequence.

Enforces that only role holders can use the command.

# 8. Member Interaction Features
Join DM

Sends new members a direct message linking them to the birthday registration system.

Voice Channel Role Toggle

Grants or removes a specific role when users join or leave a designated voice channel.

# 9. Administrative Utilities
Message Editing

Admins can edit any bot-authored message in a channel.

Supports rewriting messages with up to four lines of text.

Bot Messaging

Admins can make the bot send arbitrary messages in the current channel.

# 10. Persistent Storage Architecture
Storage Messages

Uses two hidden storage messages:

Birthday data

Movie pool data

All stateful systems (birthdays, public list locations, pool entries, pool message locations) persist through restarts.

# COMPLETE FEATURE SUMMARY

Persistent birthday tracking system

Daily birthday role assignment

Public, auto-updating birthday list

Google Sheets-based movie library

Library message synchronization

Movie request pool with saved state

Pool browsing, search, replace, and button-based adding

User pick limits and duplicate prevention

Public pool embed with auto-updates

Admin pool controls and library refresh tools

Random movie night selection with multi-channel announcements

Daily seasonal QOTD posting from Sheets

Holiday role themes and emoji sets

Automatic holiday start/end detection

Server and bot icon theming

Dead Chat role color cycling

DM onboarding message

Voice channel role automation

Admin message editing and broadcast command

Full JSON-based persistent storage for all systems
