import logging
from typing import Awaitable, Callable

import discord
from discord.ext import commands

from database import add_user, get_all_users, remove_user, user_exists


logger = logging.getLogger(__name__)


def register_commands(
    bot: commands.Bot,
    command_prefix: str,
    send_reminder_callback: Callable[[int], Awaitable[None]],
) -> None:
    @bot.command()
    async def remind(ctx):
        """Manually trigger a reminder in the current channel."""
        logger.info(
            f"Manual reminder triggered by {ctx.author} (ID: {ctx.author.id}) in channel {ctx.channel.name}"
        )
        await send_reminder_callback(ctx.channel.id)

    @bot.command()
    async def add(ctx, user: discord.Member):
        """Add a user to the reminder list."""
        logger.info(f"Attempting to add user {user} (ID: {user.id}) by {ctx.author}")

        if user_exists(user.id):
            logger.info(f"User {user} already exists in database")
            await ctx.send(f"{user.mention} er allerede i databasen.")
            return

        add_user(user.id)
        logger.info(f"Successfully added user {user} (ID: {user.id}) to database")
        await ctx.send(f"{user.mention} er blevet tilføjet til påmindelseslisten.")

    @bot.command()
    async def list(ctx):
        """List all users in the reminder list."""
        logger.info(f"List command invoked by {ctx.author} (ID: {ctx.author.id})")
        users = get_all_users()

        if not users:
            logger.info("No users in database")
            await ctx.send("Der er ingen medlemmer på listen.")
            return

        logger.info(f"Fetching details for {len(users)} user(s)")
        member_list = []
        for user_id in users:
            try:
                user = await bot.fetch_user(user_id)
                member_list.append(f"{user.name}#{user.discriminator}")
            except discord.NotFound:
                logger.warning(f"User {user_id} not found in Discord")
                member_list.append(f"Ukendt bruger ({user_id})")
            except Exception as e:
                logger.error(f"Error fetching user {user_id}: {e}")
                member_list.append(f"Fejl ved bruger ({user_id})")

        members = ", ".join(member_list)
        await ctx.send(f"Medlemmer på påmindelseslisten: {members}")
        logger.info(f"Listed {len(member_list)} user(s)")

    @bot.command()
    async def remove(ctx, user: discord.Member):
        """Remove a user from the reminder list."""
        logger.info(f"Attempting to remove user {user} (ID: {user.id}) by {ctx.author}")
        users = get_all_users()

        if not users:
            logger.info("No users in database to remove")
            await ctx.send("Der er ingen registrerede brugere til påmindelser.")
            return

        if user.id not in users:
            logger.warning(f"User {user} (ID: {user.id}) not found in database")
            await ctx.send(f"{user.mention} er ikke registreret til påmindelser.")
            return

        remove_user(user.id)
        logger.info(f"Successfully removed user {user} (ID: {user.id}) from database")
        await ctx.send(f"{user.mention} er blevet fjernet fra påmindelseslisten.")

    @bot.command()
    async def commands(ctx):
        """Display help information about bot commands."""
        logger.info(f"Help command invoked by {ctx.author} (ID: {ctx.author.id})")
        help_text = (
            "Tilgængelige kommandoer:\n"
            f"`{command_prefix}remind` - Send en påmindelse i den nuværende kanal.\n"
            f"`{command_prefix}add @bruger` - Tilføj en bruger til påmindelseslisten.\n"
            f"`{command_prefix}remove @bruger` - Fjern en bruger fra påmindelseslisten.\n"
            f"`{command_prefix}list` - Vis alle brugere på påmindelseslisten.\n"
            f"`{command_prefix}commands` - Vis denne hjælpetekst."
        )
        await ctx.send(help_text)