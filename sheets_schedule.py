from __future__ import annotations

from typing import List

from config import logger
from sheets import get_sheet


class SheetsScheduleProvider:
    """Google Sheets–backed implementation of ScheduleProvider."""

    def get_sessions_for_day(self, day_name: str) -> List[dict]:
        worksheet = get_sheet()
        if worksheet is None:
            logger.error("No worksheet available for schedule lookup")
            raise RuntimeError("Worksheet not available")

        days = worksheet.get("B2:H2")
        if not days or not days[0]:
            logger.warning("No days found in worksheet header")
            return []

        cell = None
        for day in days[0]:
            if day == day_name:
                cell = worksheet.find(day_name)
                break

        if not cell:
            logger.info("Day %s not found in schedule", day_name)
            return []

        booking = worksheet.col_values(cell.col)
        time_values = worksheet.col_values(1)
        booking_types = worksheet.get("I7:I12")

        valid_types = {row[0] for row in booking_types if row}

        sessions: List[dict] = []
        for index, booking_type in enumerate(booking):
            if booking_type in valid_types:
                time_str = time_values[index] if index < len(time_values) else ""
                sessions.append({"time": time_str, "type": booking_type, "index": index})

        return sessions
