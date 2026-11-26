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
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "1356375033374576731"))
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


Session = tuple[str, str, str]  # (start hour, end hour, kind), e.g. ("19", "22", "Træning")


def day_sessions(rows: list[list[str]], day: date) -> list[Session] | None:
    """Merged sessions for a day. None if the tab isn't for that date."""
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
    return [(start, end, kind) for start, end, kind, _ in sessions]


def fmt(session: Session) -> str:
    return f"Klokken {session[0]}-{session[1]} - {session[2]}"


def session_window(day: date, session: Session) -> tuple[datetime, datetime]:
    start, end = int(session[0]), int(session[1])
    midnight = datetime.combine(day, time(), TZ)
    return midnight + timedelta(hours=start), midnight + timedelta(hours=end + 24 * (end <= start))  # "23-01" ends tomorrow


# checkins.status values: the two buttons below, plus "joined" once the bot has seen the user in voice that day.
STATUS_BUTTONS = {
    "not-coming": ("Jeg kommer ikke", discord.ButtonStyle.danger, "Noteret – du er meldt fra d. {:%d/%m}."),
    "on-the-way": ("Jeg er på vej", discord.ButtonStyle.success, "Fedt – du får ikke flere påmindelser d. {:%d/%m}."),
}


class StatusButton(ui.DynamicItem[ui.Button], template=r"(?P<status>not-coming|on-the-way):(?P<day>\d{4}-\d{2}-\d{2})"):
    """Persistent button; status and date live in the custom_id so it keeps working after restarts."""

    def __init__(self, status: str, day: str):
        label, style, _ = STATUS_BUTTONS[status]
        super().__init__(ui.Button(label=label, style=style, custom_id=f"{status}:{day}"))
        self.status, self.day = status, day

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: ui.Button, match: re.Match[str]):
        return cls(match["status"], match["day"])

    async def callback(self, interaction: discord.Interaction):
        with db:  # last button press wins, so "på vej" can undo "kommer ikke" and vice versa
            db.execute("INSERT OR REPLACE INTO checkins VALUES (?, ?, ?)", (interaction.user.id, self.day, self.status))
        await interaction.response.send_message(STATUS_BUTTONS[self.status][2].format(date.fromisoformat(self.day)), ephemeral=True)
        await refresh_reminder(self.day)


async def fetch_week(week: int) -> list[list[str]]:
    async with aiohttp.ClientSession() as s, s.get(SHEET_CSV + quote(f"uge {week}")) as resp:
        resp.raise_for_status()
        return list(csv.reader(io.StringIO(await resp.text(encoding="utf-8"))))


def card(text: str, ping: bool = False, colour: discord.Colour = discord.Colour.blurple()) -> ui.LayoutView:
    container = ui.Container(ui.TextDisplay(text), accent_colour=colour)
    users = [row[0] for row in db.execute("SELECT user_id FROM users ORDER BY added_at")] if ping else []
    if users:
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(" ".join(f"<@{u}>" for u in users)))
    view = ui.LayoutView()
    view.add_item(container)
    return view


def reminder_view(day: str, lines: str, changed: bool) -> ui.LayoutView:
    """lines: today's formatted sessions joined by newlines, "" if there are none.
    changed: posted because the sheet changed after the daily reminder, shown as an orange "times changed" box."""
    colour = discord.Colour.orange() if changed else discord.Colour.blurple()
    header = "### Tiderne for i dag har ændret sig!" if changed else f"### Dagens agenda ({date.fromisoformat(day):%d/%m})"
    if not lines:  # quiet unless it's news that today's sessions were removed
        text = f"{header}\nDer er ikke længere træning eller officials i dag." if changed else "Der er ikke træning eller officials i dag."
        return card(text, ping=changed, colour=colour)
    text = f"{header}\n{lines}"
    absent = [uid for (uid,) in db.execute("SELECT user_id FROM checkins WHERE day = ? AND status = 'not-coming'", (day,))]
    if absent:
        text += "\n\n**Kommer ikke:** " + ", ".join(f"<@{u}>" for u in absent)
    view = card(text, ping=True, colour=colour)
    view.add_item(ui.ActionRow(StatusButton("not-coming", day)))
    return view


async def send_reminder(channel: discord.abc.Messageable, day: str, lines: str, changed: bool = False) -> None:
    msg = await channel.send(view=reminder_view(day, lines, changed))
    with db:  # remembered so button presses can edit it and the minute check can spot schedule changes
        db.execute("INSERT OR REPLACE INTO reminders VALUES (?, ?, ?, ?, ?)", (day, msg.channel.id, msg.id, lines, changed))


async def post_reminder(channel: discord.abc.Messageable) -> None:
    today = datetime.now(TZ).date()
    week = today.isocalendar().week
    try:
        sessions = day_sessions(await fetch_week(week), today)
    except Exception:
        log.exception("Failed to read the spreadsheet")
        await channel.send(view=card(FETCH_ERROR))
        return
    if sessions is None:
        await channel.send(view=card(f"Kunne ikke finde dagens skema i fanen `uge {week}`."))
        return
    await send_reminder(channel, today.isoformat(), "\n".join(map(fmt, sessions)))


async def refresh_reminder(day: str) -> None:
    row = db.execute("SELECT channel_id, message_id, sessions, changed FROM reminders WHERE day = ?", (day,)).fetchone()
    if not row:
        return
    try:
        await bot.get_partial_messageable(row[0]).get_partial_message(row[1]).edit(view=reminder_view(day, row[2], bool(row[3])))
    except discord.HTTPException:
        log.exception("Could not update the reminder for %s", day)


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
    lines = [f"**{WEEKDAYS[d.weekday()]} {d:%d/%m}**\n" + "\n".join(map(fmt, sessions)) for d, sessions in days if sessions]
    if not lines:
        return card(f"Der er ingen planlagte træninger i uge {week}.")
    return card(f"### Ugens træninger (uge {week})\n" + "\n\n".join(lines), ping=True)


async def reminder_channel() -> discord.abc.Messageable:
    return bot.get_channel(CHANNEL_ID) or await bot.fetch_channel(CHANNEL_ID)


@tasks.loop(time=time(hour=REMINDER_HOUR, tzinfo=TZ))
async def daily_reminder():
    await post_reminder(await reminder_channel())


@tasks.loop(time=time(hour=0, tzinfo=TZ))
async def weekly_overview():
    day = (datetime.now(TZ) + timedelta(minutes=1)).date()  # the timer can fire a few ms before midnight
    if day.weekday() == 0:
        await (await reminder_channel()).send(view=await build_week_overview(day), silent=True)


CHANGE_SETTLE = timedelta(minutes=3)  # a changed schedule must stay put this long, so editing several cells pings once
pending_changes: dict[str, tuple[str, datetime]] = {}  # day -> (new sessions, first seen)


async def repost_if_changed(day: str, lines: str, now: datetime) -> None:
    row = db.execute("SELECT channel_id, sessions, message_id FROM reminders WHERE day = ?", (day,)).fetchone()
    if not row or row[1] == lines:  # no reminder yet today (the 10:00 one will be current), or nothing changed
        pending_changes.pop(day, None)
        return
    seen, since = pending_changes.get(day, (None, now))
    if seen != lines:
        pending_changes[day] = (lines, now)
    elif now - since >= CHANGE_SETTLE:
        del pending_changes[day]
        channel = bot.get_partial_messageable(row[0])
        await send_reminder(channel, day, lines, changed=True)  # new box first, so a failed post leaves the old one
        try:
            await channel.get_partial_message(row[2]).delete()
        except discord.HTTPException as e:  # e.g. someone already deleted it by hand
            log.warning("Could not delete the old reminder for %s: %s", day, e)


@tasks.loop(minutes=1)
async def every_minute():
    """Repost the reminder if today's times changed, and during a session DM everyone on the list every minute
    until they join voice or press a button."""
    # ponytail: only today's column, so a session after midnight ("24-01") is never nagged and "23-01" stops at 00:00.
    # ponytail: check-ins are per day, so joining the first of two separate sessions also silences the second.
    now = datetime.now(TZ)
    today = now.date()
    try:
        sessions = day_sessions(await fetch_week(today.isocalendar().week), today)
    except Exception:
        log.exception("Failed to read the spreadsheet")
        return
    if sessions is None:  # this week's tab is missing
        return
    await repost_if_changed(today.isoformat(), "\n".join(map(fmt, sessions)), now)
    active = next((s for s in sessions if session_window(today, s)[0] <= now < session_window(today, s)[1]), None)
    if not active:
        return
    voice = bot.get_channel(VOICE_CHANNEL_ID)
    if not isinstance(voice, discord.VoiceChannel):
        log.warning("Voice channel %s not visible to the bot; skipping DMs", VOICE_CHANNEL_ID)
        return
    day = today.isoformat()
    with db:  # once seen in voice, leaving again doesn't restart the DMs; OR IGNORE keeps an earlier button press
        db.executemany("INSERT OR IGNORE INTO checkins VALUES (?, ?, 'joined')", [(uid, day) for uid in voice.voice_states])
    users = {uid for (uid,) in db.execute("SELECT user_id FROM users")}
    checked_in = {uid for (uid,) in db.execute("SELECT user_id FROM checkins WHERE day = ?", (day,))}
    for uid in users - checked_in:
        view = ui.View(timeout=None)
        view.add_item(StatusButton("on-the-way", day))
        view.add_item(StatusButton("not-coming", day))
        try:
            dm = await bot.create_dm(discord.Object(id=uid))
            await dm.send(f"**{fmt(active)}** er startet – hop på {voice.mention}!", view=view)
        except discord.HTTPException as e:
            log.warning("Could not DM %s: %s", uid, e)


@every_minute.before_loop
async def wait_for_cache():
    await bot.wait_until_ready()  # voice states are only known once the guild cache is loaded


@bot.event
async def setup_hook():
    global db
    os.makedirs(DB_DIR, exist_ok=True)
    db = sqlite3.connect(os.path.join(DB_DIR, "reminder.db"))
    db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    db.execute("CREATE TABLE IF NOT EXISTS checkins (user_id INTEGER, day TEXT, status TEXT, PRIMARY KEY (user_id, day))")
    db.execute("CREATE TABLE IF NOT EXISTS reminders (day TEXT PRIMARY KEY, channel_id INTEGER, message_id INTEGER, sessions TEXT, changed INTEGER)")
    db.execute("DROP TABLE IF EXISTS absences")  # replaced by checkins
    bot.add_dynamic_items(StatusButton)
    daily_reminder.start()
    weekly_overview.start()
    every_minute.start()
    await tree.sync()


@tree.error
async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.error("Command /%s failed", interaction.command and interaction.command.name, exc_info=error)
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send("Der opstod en fejl ved udførelse af kommandoen.", ephemeral=True)


@tree.command(description="Send dagens påmindelse i denne kanal")
@app_commands.guild_only()
async def remind(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await post_reminder(interaction.channel)  # a normal bot message, so button presses can edit it later
    await interaction.followup.send("Påmindelsen er sendt.", ephemeral=True)


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
