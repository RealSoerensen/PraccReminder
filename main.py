import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from functools import partial
import logging

from bot_commands import register_commands
from config import AUTH_FILE, CHANNEL_ID, COMMAND_PREFIX, DISCORD_TOKEN, SCHEDULER_HOUR, SPREADSHEET_ID
from database import init_db
from reminder_service import send_reminder
from sheets_service import get_sheet

# Setup logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

logger.info(f"Configuration loaded - Channel ID: {CHANNEL_ID}, Scheduler Hour: {SCHEDULER_HOUR}")

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    activity=discord.Game("Jeg holder øje med jer! - .commands")
)
logger.info("Discord bot initialized")

# Initialize database
init_db()
logger.info("Database initialized")

sheet_provider = partial(get_sheet, AUTH_FILE, SPREADSHEET_ID)


async def send_reminder_for_channel(channel_id: int | None = None) -> None:
    await send_reminder(bot=bot, default_channel_id=CHANNEL_ID, get_sheet=sheet_provider, channel_id=channel_id)


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")
    
    # Start scheduler when bot is ready
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminder_for_channel, CronTrigger(hour=SCHEDULER_HOUR))
    scheduler.start()
    logger.info(f"Scheduler started - daily reminders at {SCHEDULER_HOUR}:00")


@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        logger.warning(f"Unknown command attempted: {ctx.message.content}")
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        logger.warning(f"Missing argument in command: {ctx.command}")
        await ctx.send(f"Manglende parameter. Brug: `{COMMAND_PREFIX}help {ctx.command}`")
    elif isinstance(error, commands.BadArgument):
        logger.warning(f"Bad argument in command: {ctx.command}")
        await ctx.send(f"Ugyldig parameter. Brug: `{COMMAND_PREFIX}help {ctx.command}`")
    else:
        logger.error(f"Command error in {ctx.command}: {error}", exc_info=True)
        await ctx.send("Der opstod en fejl ved udførelse af kommandoen.")
register_commands(bot, COMMAND_PREFIX, send_reminder_for_channel)

if __name__ == "__main__":
    logger.info("=== Starting PraccReminder Bot ===")
    
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN not found in .env file - Cannot start bot")
        exit(1)
    
    logger.info("Starting Discord connection...")
    logger.info(f"Using Spreadsheet ID: {SPREADSHEET_ID}")
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("Failed to login - Invalid Discord token")
        exit(1)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        exit(1)
