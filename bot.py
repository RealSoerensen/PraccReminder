import csv
import io
import logging
import os
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands, ui
from discord.ext import tasks

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1356375075208691937"))
REMINDER_HOUR = int(os.getenv("SCHEDULER_HOUR", "10"))
DB_DIR = os.getenv("DB_DIR", "/app/data")
TZ = ZoneInfo("Europe/Copenhagen")
# Public sheet, one tab per ISO week named "uge <n>". gviz falls back to the first tab if the name is missing,
# which day_sessions() catches via the date row.
SHEET_CSV = "https://docs.google.com/spreadsheets/d/1aNzggPj0sHCmwLqE__UN5IuxlX6xEYLwwiGJkAjjBjY/gviz/tq?tqx=out:csv&headers=0&sheet="
SESSION_TYPES = {"træning", "official"}  # any other cell value is a player name, not a session
WEEKDAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
FETCH_ERROR = "Der opstod en fejl ved hentning af træningsdata."

log = logging.getLogger("praccreminder")
bot = discord.Client(intents=discord.Intents.default(), activity=discord.Game("Jeg holder øje med jer! - /remind"))
tree = app_commands.CommandTree(bot)
db: sqlite3.Connection


def day_sessions(rows: list[list[str]], day: date) -> list[str] | None:
    """Merged sessions for a day, e.g. ["Klokken 19-22 - Træning"]. None if the tab isn't for that date."""
    col = day.weekday() + 1  # A = times, B..H = Monday..Sunday
    cell = lambda r: r[col].strip() if len(r) > col else ""
    date_row = next((r for r in rows if re.fullmatch(r"\d{1,2}/\d{1,2}", cell(r))), None)
    if not date_row or tuple(map(int, cell(date_row).split("/"))) != (day.day, day.month):
        return None

    sessions = []  # [start, end, kind, row index]
    for i, r in enumerate(rows):
        m = r and re.fullmatch(r"Klokken (\d+)-(\d+)", r[0].strip())
        kind = cell(r).capitalize()
        if not m or kind.lower() not in SESSION_TYPES:
            continue
        if sessions and sessions[-1][2] == kind and sessions[-1][3] == i - 1:
            sessions[-1][1], sessions[-1][3] = m[2], i
        else:
            sessions.append([m[1], m[2], kind, i])
    return [f"Klokken {start}-{end} - {kind}" for start, end, kind, _ in sessions]


async def fetch_week(week: int) -> list[list[str]]:
    async with aiohttp.ClientSession() as s, s.get(SHEET_CSV + quote(f"uge {week}")) as resp:
        resp.raise_for_status()
        return list(csv.reader(io.StringIO(await resp.text(encoding="utf-8"))))


def card(text: str, ping: bool = False) -> ui.LayoutView:
    container = ui.Container(ui.TextDisplay(text), accent_colour=discord.Colour.blurple())
    users = [row[0] for row in db.execute("SELECT user_id FROM users ORDER BY added_at")] if ping else []
    if users:
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(" ".join(f"<@{u}>" for u in users)))
    view = ui.LayoutView()
    view.add_item(container)
    return view


async def build_reminder() -> ui.LayoutView:
    today = datetime.now(TZ).date()
    week = today.isocalendar().week
    try:
        sessions = day_sessions(await fetch_week(week), today)
    except Exception:
        log.exception("Failed to read the spreadsheet")
        return card(FETCH_ERROR)
    if sessions is None:
        return card(f"Kunne ikke finde dagens skema i fanen `uge {week}`.")
    if not sessions:
        return card("Der er ikke træning eller officials i dag.")
    return card(f"### Dagens agenda ({today:%d/%m})\n" + "\n".join(sessions), ping=True)


async def build_week_overview(day: date) -> ui.LayoutView:
    week = day.isocalendar().week
    monday = day - timedelta(days=day.weekday())
    try:
        rows = await fetch_week(week)
    except Exception:
        log.exception("Failed to read the spreadsheet")
        return card(FETCH_ERROR)
    days = [(d, day_sessions(rows, d)) for d in (monday + timedelta(days=i) for i in range(7))]
    if all(sessions is None for _, sessions in days):
        return card(f"Kunne ikke finde ugens skema i fanen `uge {week}`.")
    lines = [f"**{WEEKDAYS[d.weekday()]} {d:%d/%m}**\n" + "\n".join(sessions) for d, sessions in days if sessions]
    if not lines:
        return card(f"Der er ingen planlagte træninger i uge {week}.")
    return card(f"### Ugens træninger (uge {week})\n" + "\n\n".join(lines), ping=True)


async def reminder_channel() -> discord.abc.Messageable:
    return bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)


@tasks.loop(time=time(hour=REMINDER_HOUR, tzinfo=TZ))
async def daily_reminder():
    await (await reminder_channel()).send(view=await build_reminder())


@tasks.loop(time=time(hour=0, tzinfo=TZ))
async def weekly_overview():
    day = (datetime.now(TZ) + timedelta(minutes=1)).date()  # the timer can fire a few ms before midnight
    if day.weekday() == 0:
        await (await reminder_channel()).send(view=await build_week_overview(day), silent=True)


@bot.event
async def setup_hook():
    global db
    os.makedirs(DB_DIR, exist_ok=True)
    db = sqlite3.connect(os.path.join(DB_DIR, "reminder.db"))
    db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    daily_reminder.start()
    weekly_overview.start()
    await tree.sync()


@tree.error
async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.error("Command /%s failed", interaction.command and interaction.command.name, exc_info=error)
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send("Der opstod en fejl ved udførelse af kommandoen.", ephemeral=True)


@tree.command(description="Send dagens påmindelse i denne kanal")
@app_commands.guild_only()
async def remind(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(view=await build_reminder())


@tree.command(description="Vis ugens planlagte træninger i denne kanal")
@app_commands.guild_only()
async def week(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(view=await build_week_overview(datetime.now(TZ).date()))


@tree.command(description="Tilføj en bruger til påmindelseslisten")
@app_commands.guild_only()
async def add(interaction: discord.Interaction, user: discord.User):
    with db:
        added = db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user.id,)).rowcount
    msg = "er blevet tilføjet til påmindelseslisten." if added else "er allerede på listen."
    await interaction.response.send_message(f"{user.mention} {msg}", allowed_mentions=discord.AllowedMentions.none())


@tree.command(description="Fjern en bruger fra påmindelseslisten")
@app_commands.guild_only()
async def remove(interaction: discord.Interaction, user: discord.User):
    with db:
        removed = db.execute("DELETE FROM users WHERE user_id = ?", (user.id,)).rowcount
    msg = "er blevet fjernet fra påmindelseslisten." if removed else "er ikke på listen."
    await interaction.response.send_message(f"{user.mention} {msg}", allowed_mentions=discord.AllowedMentions.none())


@tree.command(name="list", description="Vis alle brugere på påmindelseslisten")
@app_commands.guild_only()
async def list_users(interaction: discord.Interaction):
    users = [f"<@{row[0]}>" for row in db.execute("SELECT user_id FROM users ORDER BY added_at")]
    msg = "Påmindelseslisten: " + ", ".join(users) if users else "Der er ingen på påmindelseslisten."
    await interaction.response.send_message(msg, allowed_mentions=discord.AllowedMentions.none())


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"], root_logger=True)
