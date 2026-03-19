import logging
from datetime import datetime
from typing import Callable, List, Optional

import discord
import gspread
import pytz
from gspread.utils import rowcol_to_a1

from database import get_all_users


logger = logging.getLogger(__name__)


def _normalize_rgb_color(color: Optional[dict]) -> Optional[tuple[float, float, float]]:
    """Normalize Sheets RGB color objects to a comparable rounded tuple."""
    if not color:
        return None

    red = float(color.get("red", 0.0))
    green = float(color.get("green", 0.0))
    blue = float(color.get("blue", 0.0))
    return (round(red, 4), round(green, 4), round(blue, 4))


def _extract_cell_rgb(cell_data: dict) -> Optional[tuple[float, float, float]]:
    """Extract the effective background RGB color from a grid cell metadata object."""
    effective_format = cell_data.get("effectiveFormat", {})
    style_color = effective_format.get("backgroundColorStyle", {}).get("rgbColor")
    if style_color:
        return _normalize_rgb_color(style_color)
    return _normalize_rgb_color(effective_format.get("backgroundColor"))


def _get_column_background_colors(
    worksheet: gspread.Worksheet,
    column: int,
    row_count: int,
) -> List[Optional[tuple[float, float, float]]]:
    """Fetch effective background colors for a single column range from row 1..row_count."""
    if row_count <= 0:
        return []

    start = rowcol_to_a1(1, column)
    end = rowcol_to_a1(row_count, column)
    range_name = f"'{worksheet.title}'!{start}:{end}"

    metadata = worksheet.spreadsheet.fetch_sheet_metadata(
        params={
            "includeGridData": "true",
            "ranges": range_name,
            "fields": "sheets(data(rowData(values(effectiveFormat(backgroundColor,backgroundColorStyle)))))",
        }
    )

    colors: List[Optional[tuple[float, float, float]]] = []
    try:
        row_data = metadata["sheets"][0]["data"][0].get("rowData", [])
        for row in row_data:
            cell_values = row.get("values", [])
            colors.append(_extract_cell_rgb(cell_values[0]) if cell_values else None)
    except (KeyError, IndexError, TypeError):
        logger.warning("Unable to parse column color metadata")

    if len(colors) < row_count:
        colors.extend([None] * (row_count - len(colors)))
    return colors[:row_count]


def _get_absent_marker_colors(
    worksheet: gspread.Worksheet,
) -> set[tuple[float, float, float]]:
    """Read absent marker colors from I3:I7."""
    metadata = worksheet.spreadsheet.fetch_sheet_metadata(
        params={
            "includeGridData": "true",
            "ranges": f"'{worksheet.title}'!I3:I7",
            "fields": "sheets(data(rowData(values(effectiveFormat(backgroundColor,backgroundColorStyle)))))",
        }
    )

    colors: set[tuple[float, float, float]] = set()
    try:
        row_data = metadata["sheets"][0]["data"][0].get("rowData", [])
        for row in row_data:
            cell_values = row.get("values", [])
            if not cell_values:
                continue
            rgb = _extract_cell_rgb(cell_values[0])
            if rgb is not None:
                colors.add(rgb)
    except (KeyError, IndexError, TypeError):
        logger.warning("Unable to parse absent marker colors from I3:I7")

    return colors


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


def _build_consolidated_sessions(
    booking: List[str],
    times: List[str],
    booking_colors: Optional[List[Optional[tuple[float, float, float]]]] = None,
    absent_colors: Optional[set[tuple[float, float, float]]] = None,
) -> List[str]:
    sessions = []
    booking_colors = booking_colors or []
    absent_colors = absent_colors or set()

    for index, booking_type in enumerate(booking):
        booking_value = booking_type.strip()
        time_str = times[index].strip() if index < len(times) else ""
        parsed_time = _parse_time_range(time_str)
        cell_color = booking_colors[index] if index < len(booking_colors) else None

        # Ignore headers and empty rows; only process actual scheduled slots.
        if not booking_value or parsed_time is None:
            continue

        # Ignore absent markers identified by configured colors in I3:I7.
        if cell_color is not None and cell_color in absent_colors:
            logger.debug(f"Skipping absent-marked slot at row index {index + 1}")
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
        row_count = max(len(times), len(booking))
        absent_colors: set[tuple[float, float, float]] = set()
        booking_colors: List[Optional[tuple[float, float, float]]] = []

        try:
            absent_colors = _get_absent_marker_colors(worksheet)
            booking_colors = _get_column_background_colors(worksheet, day_col, row_count)
        except Exception as color_error:
            logger.warning(
                f"Could not load color metadata; continuing without absent-color filtering: {color_error}"
            )

        if len(booking) < row_count:
            booking.extend([""] * (row_count - len(booking)))
        if len(times) < row_count:
            times.extend([""] * (row_count - len(times)))

        logger.debug(f"Retrieved {len(booking)} bookings for today")
        logger.debug(f"Loaded {len(absent_colors)} absent marker color(s) from I3:I7")

        consolidated = _build_consolidated_sessions(booking, times, booking_colors, absent_colors)
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