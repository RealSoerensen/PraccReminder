from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Protocol

import pytz

from config import logger


class ScheduleProvider(Protocol):
    def get_sessions_for_day(self, day_name: str) -> List[dict]:
        """Return a list of session dicts: {"time", "type", "index"}."""


class UserRepository(Protocol):
    def get_all_users(self) -> Iterable[int]: ...


class MessageChannel(Protocol):
    async def send(self, content: str) -> None: ...


@dataclass
class ReminderService:
    schedule_provider: ScheduleProvider
    user_repository: UserRepository
    timezone: str = "Europe/Copenhagen"

    async def send_today_overview(self, channel: MessageChannel) -> None:
        tz = pytz.timezone(self.timezone)
        day_today = datetime.now(tz).strftime("%A")
        logger.info("Preparing schedule for: %s", day_today)

        try:
            sessions = self.schedule_provider.get_sessions_for_day(day_today)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Error reading schedule: %s", exc, exc_info=True)
            await channel.send("Der opstod en fejl ved hentning af træningsdata.")
            return

        if not sessions:
            logger.info("No sessions found for today")
            await channel.send("Der er ikke træning eller officials i dag.")
            return

        consolidated: List[str] = []
        i = 0
        while i < len(sessions):
            current = sessions[i]
            time_str = current.get("time", "")
            if "-" in time_str:
                start_time, end_time = [part.strip() for part in time_str.split("-", 1)]
            else:
                start_time, end_time = time_str, ""

            session_type = current.get("type", "")

            j = i + 1
            while (
                j < len(sessions)
                and sessions[j].get("type") == session_type
                and sessions[j].get("index", 0) == sessions[j - 1].get("index", 0) + 1
            ):
                next_time = sessions[j].get("time", "")
                if "-" in next_time:
                    _, end_time = [part.strip() for part in next_time.split("-", 1)]
                j += 1

            if start_time and end_time:
                consolidated.append(f"Klokken {start_time}-{end_time} - {session_type}")
            else:
                consolidated.append(f"{time_str} - {session_type}")

            i = j

        users = list(self.user_repository.get_all_users())
        logger.info("Notifying %d user(s)", len(users))

        hours = "\n".join(consolidated)
        message = f"Her er dagens agenda:\n{hours}"
        if users:
            mentions = ", ".join(f"<@{user_id}>" for user_id in users)
            message += f"\n\n{mentions}"

        await channel.send(message)
