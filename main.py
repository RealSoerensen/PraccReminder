import discord
from discord.ext import commands

from config import COMMAND_PREFIX, DISCORD_TOKEN, logger
from reminder import configure_scheduler, register_commands
from services import ReminderService
from sheets_schedule import SheetsScheduleProvider
from user_repository import DatabaseUserRepository


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    activity=discord.Game("Jeg holder øje med jer! - .commands"),
)

schedule_provider = SheetsScheduleProvider()
user_repository = DatabaseUserRepository()
reminder_service = ReminderService(
    schedule_provider=schedule_provider,
    user_repository=user_repository,
)


@bot.event
async def on_ready():
    logger.info("Bot logged in as %s (ID: %s)", bot.user, bot.user.id)
    logger.info("Connected to %d guild(s)", len(bot.guilds))
    configure_scheduler(bot, reminder_service)


@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        logger.warning("Unknown command attempted: %s", ctx.message.content)
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        logger.warning("Missing argument in command: %s", ctx.command)
        await ctx.send(f"Manglende parameter. Brug: `{COMMAND_PREFIX}help {ctx.command}`")
    elif isinstance(error, commands.BadArgument):
        logger.warning("Bad argument in command: %s", ctx.command)
        await ctx.send(f"Ugyldig parameter. Brug: `{COMMAND_PREFIX}help {ctx.command}`")
    else:
        logger.error("Command error in %s: %s", ctx.command, error, exc_info=True)
        await ctx.send("Der opstod en fejl ved udførelse af kommandoen.")

register_commands(bot, reminder_service)

if __name__ == "__main__":
    logger.info("=== Starting PraccReminder Bot ===")
    
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN not found in .env file - Cannot start bot")
        exit(1)
    
    logger.info("Starting Discord connection...")
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("Failed to login - Invalid Discord token")
        exit(1)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        exit(1)
