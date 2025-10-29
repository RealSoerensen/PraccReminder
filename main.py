import discord
from discord.ext import commands
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import week
from datetime import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from database import init_db, get_all_users, add_user, remove_user, user_exists
from typing import Optional
import logging
import os
from dotenv import load_dotenv

# Setup logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
logger.info("Environment variables loaded")

# Constants from environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "955980756960809013"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1SeHReR2AuaBPJXBvvhhg7ulCB_DCVQGdfoRKxWKb248")
SCHEDULER_HOUR = os.getenv("SCHEDULER_HOUR", "10")
AUTH_FILE = "auth.json"
COMMAND_PREFIX = "."

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


def get_sheet() -> Optional[gspread.Worksheet]:
    """
    Get the worksheet for the current week.
    
    Returns:
        The worksheet if found, None otherwise.
    """
    logger.debug("Attempting to access Google Sheets")
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(AUTH_FILE, scope)
        client = gspread.authorize(creds)
        logger.debug(f"Authorized with Google Sheets API")
        
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        logger.debug(f"Opened spreadsheet: {SPREADSHEET_ID}")
        
        week_name = week.get_week()
        logger.info(f"Looking for worksheet: '{week_name}'")
        
        worksheet = spreadsheet.worksheet(week_name)
        logger.info(f"Successfully found worksheet: '{week_name}'")
        return worksheet
        
    except gspread.exceptions.WorksheetNotFound:
        week_name = week.get_week()
        logger.error(f"Worksheet '{week_name}' not found!")
        worksheets = spreadsheet.worksheets()
        available = [ws.title for ws in worksheets]
        logger.info(f"Available worksheets: {available}")
        return None
    except FileNotFoundError:
        logger.error(f"Auth file '{AUTH_FILE}' not found")
        return None
    except Exception as e:
        logger.error(f"Error accessing spreadsheet: {e}", exc_info=True)
        return None


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f"Bot logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")
    
    # Start scheduler when bot is ready
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminder, CronTrigger(hour=SCHEDULER_HOUR))
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


async def send_reminder(channel_id: Optional[int] = None) -> None:
    """
    Send reminder to the channel.
    
    Args:
        channel_id: Discord channel ID. If None, uses default channel.
    """
    logger.info("Starting reminder process")
    await bot.wait_until_ready()
    
    target_channel_id = channel_id or CHANNEL_ID
    channel = bot.get_channel(target_channel_id)
    
    if not channel:
        logger.error(f"Channel {target_channel_id} not found")
        return
    
    logger.info(f"Sending reminder to channel: {channel.name} (ID: {channel.id})")
    
    # Get worksheet
    worksheet = get_sheet()
    if worksheet is None:
        logger.error("Failed to get worksheet, aborting reminder")
        await channel.send("Kunne ikke finde regnearket for denne uge.")
        return
    
    # Get today's day name in Danish timezone
    denmark_tz = pytz.timezone('Europe/Copenhagen')
    day_today = datetime.now(denmark_tz).strftime("%A")
    logger.info(f"Checking schedule for: {day_today} (Danish time)")
    
    try:
        days = worksheet.get("B2:H2")
        if not days or not days[0]:
            logger.warning("No days found in worksheet header")
            await channel.send("Der er ikke noget tilgængeligt i denne uge.")
            return
        
        logger.debug(f"Days in worksheet: {days[0]}")
        
        # Find today's column
        cell = None
        for day in days[0]:
            if day == day_today:
                cell = worksheet.find(day_today)
                logger.info(f"Found today's column at position: {cell.col}")
                break
        
        if not cell:
            logger.info(f"Today ({day_today}) not found in schedule")
            await channel.send("Der er ikke noget tilgængeligt i denne uge.")
            return
        
        # Get bookings and times
        booking = worksheet.col_values(cell.col)
        time = worksheet.col_values(1)
        logger.debug(f"Retrieved {len(booking)} bookings for today")
        
        # Find training/officials sessions with time ranges
        sessions = []
        for i, booking_type in enumerate(booking):
            if booking_type in ["Træning", "Officals"]:
                time_str = time[i] if i < len(time) else ""
                sessions.append({"time": time_str, "type": booking_type, "index": i})
                logger.debug(f"Found session: {time_str} - {booking_type}")
        
        if not sessions:
            logger.info("No training or officials sessions found for today")
            await channel.send("Der er ikke træning eller officials i dag.")
            return
        
        logger.info(f"Found {len(sessions)} session(s) for today")
        
        # Consolidate consecutive sessions of the same type
        consolidated = []
        i = 0
        while i < len(sessions):
            current = sessions[i]
            start_time = current["time"].split("-")[0].strip() if "-" in current["time"] else current["time"]
            end_time = current["time"].split("-")[1].strip() if "-" in current["time"] else ""
            session_type = current["type"]
            
            # Look ahead for consecutive sessions of the same type
            j = i + 1
            while j < len(sessions) and sessions[j]["type"] == session_type and sessions[j]["index"] == sessions[j-1]["index"] + 1:
                end_time = sessions[j]["time"].split("-")[1].strip() if "-" in sessions[j]["time"] else ""
                j += 1
            
            # Format the consolidated time range
            if start_time and end_time:
                consolidated.append(f"Klokken {start_time}-{end_time} - {session_type}")
            else:
                consolidated.append(f"{current['time']} - {session_type}")
            
            logger.debug(f"Consolidated session: {start_time}-{end_time} - {session_type}")
            i = j
        
        # Get users to mention
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


@bot.command()
async def remind(ctx):
    """Manually trigger a reminder in the current channel."""
    logger.info(f"Manual reminder triggered by {ctx.author} (ID: {ctx.author.id}) in channel {ctx.channel.name}")
    await send_reminder(ctx.channel.id)


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
        f"`{COMMAND_PREFIX}remind` - Send en påmindelse i den nuværende kanal.\n"
        f"`{COMMAND_PREFIX}add @bruger` - Tilføj en bruger til påmindelseslisten.\n"
        f"`{COMMAND_PREFIX}remove @bruger` - Fjern en bruger fra påmindelseslisten.\n"
        f"`{COMMAND_PREFIX}list` - Vis alle brugere på påmindelseslisten.\n"
        f"`{COMMAND_PREFIX}commands` - Vis denne hjælpetekst."
    )
    await ctx.send(help_text)

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
