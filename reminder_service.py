import logging
from datetime import datetime
from typing import Callable, List, Optional

import discord
import gspread
import pytz

from database import get_all_users


logger = logging.getLogger(__name__)


def _parse_time_range(time_label: str) -> Optional[tuple[str, str]]:
    """Parse labels like 'Klokken 18-19' into ('18', '19')."""
    cleaned = time_label.strip()
    prefix = "Klokken "
    if not cleaned.startswith(prefix):
        return None

    hours = cleaned[len(prefix):].strip()
    if "-" not in hours:
        return None

    start, end = [part.strip() for part in hours.split("-", 1)]
    if not start or not end:
        return None
    return start, end


def _build_consolidated_sessions(booking: List[str], times: List[str]) -> List[str]:
    sessions = []
    for index, booking_type in enumerate(booking):
        booking_value = booking_type.strip()
        time_str = times[index].strip() if index < len(times) else ""
        parsed_time = _parse_time_range(time_str)

        # Ignore headers and empty rows; only process actual scheduled slots.
        if not booking_value or parsed_time is None:
            continue

        start_time, end_time = parsed_time
        sessions.append(
            {
                "start": start_time,
                "end": end_time,
                "type": booking_value,
                "index": index,
            }
        )

    if not sessions:
        return []

    consolidated = []
    position = 0
    while position < len(sessions):
        current = sessions[position]
        start_time = current["start"]
        end_time = current["end"]
        session_type = current["type"]

        lookahead = position + 1
        while (
            lookahead < len(sessions)
            and sessions[lookahead]["type"] == session_type
            and sessions[lookahead]["index"] == sessions[lookahead - 1]["index"] + 1
        ):
            end_time = sessions[lookahead]["end"]
            lookahead += 1

        consolidated.append(f"Klokken {start_time}-{end_time} - {session_type}")

        logger.debug(f"Consolidated session: {start_time}-{end_time} - {session_type}")
        position = lookahead

    return consolidated


async def send_reminder(
    bot: discord.Client,
    default_channel_id: int,
    get_sheet: Callable[[], Optional[gspread.Worksheet]],
    channel_id: Optional[int] = None,
) -> None:
    """
    Send reminder to a Discord channel.

    Args:
        bot: Discord bot client.
        default_channel_id: Channel ID used when channel_id is None.
        get_sheet: Callable that returns the active worksheet.
        channel_id: Optional override target channel.
    """
    logger.info("Starting reminder process")
    await bot.wait_until_ready()

    target_channel_id = channel_id or default_channel_id
    channel = bot.get_channel(target_channel_id)

    if not channel:
        logger.error(f"Channel {target_channel_id} not found")
        return

    logger.info(f"Sending reminder to channel: {channel.name} (ID: {channel.id})")

    worksheet = get_sheet()
    if worksheet is None:
        logger.error("Failed to get worksheet, aborting reminder")
        await channel.send("Kunne ikke finde regnearket for denne uge.")
        return

    denmark_tz = pytz.timezone("Europe/Copenhagen")
    day_today = datetime.now(denmark_tz).strftime("%A")
    logger.info(f"Checking schedule for: {day_today} (Danish time)")

    try:
        days = worksheet.get("B2:H2")
        if not days or not days[0]:
            logger.warning("No days found in worksheet header")
            await channel.send("Der er ikke noget tilgængeligt i denne uge.")
            return

        days_row = [day.strip() for day in days[0]]
        logger.debug(f"Days in worksheet: {days_row}")

        if day_today not in days_row:
            logger.info(f"Today ({day_today}) not found in schedule")
            await channel.send("Der er ikke noget tilgængeligt i denne uge.")
            return

        day_col = 2 + days_row.index(day_today)
        logger.info(f"Found today's column at position: {day_col}")

        booking = worksheet.col_values(day_col)
        times = worksheet.col_values(1)
        logger.debug(f"Retrieved {len(booking)} bookings for today")

        consolidated = _build_consolidated_sessions(booking, times)
        if not consolidated:
            logger.info("No training or officials sessions found for today")
            await channel.send("Der er ikke træning eller officials i dag.")
            return

        logger.info(f"Found {len(consolidated)} session(s) for today")

        users = get_all_users()
        logger.info(f"Notifying {len(users)} user(s)")

        hours = "\n".join(consolidated)
        message = f"Her er dagens agenda:\n{hours}"
        if users:
            mentions = ", ".join(f"<@{user_id}>" for user_id in users)
            message += f"\n\n{mentions}"

        await channel.send(message)
    except Exception as e:
        logger.error(f"Error sending reminder: {e}", exc_info=True)
        await channel.send("Der opstod en fejl ved hentning af træningsdata.")