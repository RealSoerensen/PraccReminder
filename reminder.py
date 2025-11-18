from __future__ import annotations

from typing import Optional

import discord

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import CHANNEL_ID, COMMAND_PREFIX, SCHEDULER_HOUR, logger
from database import add_user, get_all_users, remove_user, user_exists, init_db
from services import ReminderService


def configure_scheduler(bot: discord.Client, reminder_service: ReminderService) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    
    async def scheduled_reminder():
        await send_reminder(bot, reminder_service)
    
    scheduler.add_job(scheduled_reminder, CronTrigger(hour=SCHEDULER_HOUR))
    scheduler.start()
    logger.info("Scheduler started - daily reminders at %s:00", SCHEDULER_HOUR)
    return scheduler

async def send_reminder(
    bot: discord.Client, reminder_service: ReminderService, channel_id: Optional[int] = None
) -> None:
    await bot.wait_until_ready()

    target_channel_id = channel_id or CHANNEL_ID
    channel = bot.get_channel(target_channel_id)
    if not channel:
        logger.error("Channel %s not found", target_channel_id)
        return

    await reminder_service.send_today_overview(channel)


def register_commands(bot: discord.ext.commands.Bot, reminder_service: ReminderService) -> None:
    init_db()

    @bot.command()
    async def remind(ctx):  # type: ignore[unused-ignore]
        await send_reminder(bot, reminder_service, ctx.channel.id)

    @bot.command()
    async def add(ctx, user: discord.Member):  # type: ignore[unused-ignore]
        if user_exists(user.id):
            await ctx.send(f"{user.mention} er allerede i databasen.")
            return
        add_user(user.id)
        await ctx.send(f"{user.mention} er blevet tilføjet til påmindelseslisten.")

    @bot.command()
    async def list(ctx):  # type: ignore[unused-ignore]
        users = get_all_users()
        if not users:
            await ctx.send("Der er ingen medlemmer på listen.")
            return

        member_list: list[str] = []
        for user_id in users:
            try:
                user = await bot.fetch_user(user_id)
                member_list.append(f"{user.name}#{user.discriminator}")
            except discord.NotFound:
                member_list.append(f"Ukendt bruger ({user_id})")
            except Exception:
                member_list.append(f"Fejl ved bruger ({user_id})")

        members = ", ".join(member_list)
        await ctx.send(f"Medlemmer på påmindelseslisten: {members}")

    @bot.command()
    async def remove(ctx, user: discord.Member):  # type: ignore[unused-ignore]
        users = get_all_users()
        if not users:
            await ctx.send("Der er ingen registrerede brugere til påmindelser.")
            return
        if user.id not in users:
            await ctx.send(f"{user.mention} er ikke registreret til påmindelser.")
            return
        remove_user(user.id)
        await ctx.send(f"{user.mention} er blevet fjernet fra påmindelseslisten.")

    @bot.command(name="commands")
    async def commands_command(ctx):  # type: ignore[unused-ignore]
        help_text = (
            "Tilgængelige kommandoer:\n"
            f"`{COMMAND_PREFIX}remind` - Send en påmindelse i den nuværende kanal.\n"
            f"`{COMMAND_PREFIX}add @bruger` - Tilføj en bruger til påmindelseslisten.\n"
            f"`{COMMAND_PREFIX}remove @bruger` - Fjern en bruger fra påmindelseslisten.\n"
            f"`{COMMAND_PREFIX}list` - Vis alle brugere på påmindelseslisten.\n"
            f"`{COMMAND_PREFIX}commands` - Vis denne hjælpetekst."
        )
        await ctx.send(help_text)
