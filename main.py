import discord
from discord.ext import commands
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import week
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from database import init_db, get_all_users, add_user, remove_user, user_exists
from typing import Optional
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants from environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "955980756960809013"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1SeHReR2AuaBPJXBvvhhg7ulCB_DCVQGdfoRKxWKb248")
SCHEDULER_HOUR = os.getenv("SCHEDULER_HOUR", "10")
AUTH_FILE = "auth.json"
COMMAND_PREFIX = "."

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    activity=discord.Game("Jeg holder øje med jer!")
)

# Initialize database
init_db()


def get_sheet() -> Optional[gspread.Worksheet]:
    """
    Get the worksheet for the current week.
    
    Returns:
        The worksheet if found, None otherwise.
    """
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(AUTH_FILE, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        
        week_name = week.get_week()
        logger.info(f"Looking for worksheet: {week_name}")
        
        return spreadsheet.worksheet(week_name)
    except gspread.exceptions.WorksheetNotFound:
        logger.error(f"Worksheet '{week_name}' not found!")
        worksheets = spreadsheet.worksheets()
        logger.info(f"Available worksheets: {[ws.title for ws in worksheets]}")
        return None
    except Exception as e:
        logger.error(f"Error accessing spreadsheet: {e}")
        return None


@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f"Logged in as {bot.user}")
    
    # Start scheduler when bot is ready
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminder, CronTrigger(hour=SCHEDULER_HOUR))
    scheduler.start()
    logger.info(f"Scheduler started - reminders will be sent at {SCHEDULER_HOUR}:00")


async def send_reminder(channel_id: Optional[int] = None) -> None:
    """
    Send reminder to the channel.
    
    Args:
        channel_id: Discord channel ID. If None, uses default channel.
    """
    await bot.wait_until_ready()
    
    target_channel_id = channel_id or CHANNEL_ID
    channel = bot.get_channel(target_channel_id)
    
    if not channel:
        logger.error(f"Channel {target_channel_id} not found")
        return
    
    # Get worksheet
    worksheet = get_sheet()
    if worksheet is None:
        await channel.send("Kunne ikke finde regnearket for denne uge.")
        return
    
    # Get today's day name
    day_today = datetime.today().strftime("%A")
    
    try:
        days = worksheet.get("B2:H2")
        if not days or not days[0]:
            await channel.send("Der er ikke noget tilgængeligt i denne uge.")
            return
        
        # Find today's column
        cell = None
        for day in days[0]:
            if day == day_today:
                cell = worksheet.find(day_today)
                break
        
        if not cell:
            await channel.send("Der er ikke noget tilgængeligt i denne uge.")
            return
        
        # Get bookings and times
        booking = worksheet.col_values(cell.col)
        time = worksheet.col_values(1)
        
        # Find training/officials sessions
        sessions = []
        for i, booking_type in enumerate(booking):
            if booking_type in ["Træning", "Officals"]:
                sessions.append(f"{time[i]} - {booking_type}")
        
        if not sessions:
            await channel.send("Der er ikke træning eller officials i dag.")
            return
        
        # Get users to mention
        users = get_all_users()
        if users:
            mentions = ", ".join(f"<@{user_id}>" for user_id in users)
            hours = "\n".join(sessions)
            await channel.send(f"Husk træning {mentions}\n{hours}")
        else:
            hours = "\n".join(sessions)
            await channel.send(f"Træning i dag:\n{hours}")
            
    except Exception as e:
        logger.error(f"Error sending reminder: {e}")
        await channel.send("Der opstod en fejl ved hentning af træningsdata.")


@bot.command()
async def remind(ctx):
    """Manually trigger a reminder in the current channel."""
    await send_reminder(ctx.channel.id)


@bot.command()
async def add(ctx, user: discord.Member):
    """Add a user to the reminder list."""
    if user_exists(user.id):
        await ctx.send(f"{user.mention} er allerede i databasen.")
        return
    
    add_user(user.id)
    await ctx.send(f"{user.mention} er blevet tilføjet til påmindelseslisten.")


@bot.command()
async def list(ctx):
    """List all users in the reminder list."""
    users = get_all_users()
    
    if not users:
        await ctx.send("Der er ingen medlemmer på listen.")
        return
    
    member_list = []
    for user_id in users:
        try:
            user = await bot.fetch_user(user_id)
            member_list.append(f"{user.name}#{user.discriminator}")
        except discord.NotFound:
            logger.warning(f"User {user_id} not found")
            member_list.append(f"Ukendt bruger ({user_id})")
    
    members = ", ".join(member_list)
    await ctx.send(f"Medlemmer på påmindelseslisten: {members}")


@bot.command()
async def remove(ctx, user: discord.Member):
    """Remove a user from the reminder list."""
    users = get_all_users()
    
    if not users:
        await ctx.send("Der er ingen registrerede brugere til påmindelser.")
        return
    
    if user.id not in users:
        await ctx.send(f"{user.mention} er ikke registreret til påmindelser.")
        return
    
    remove_user(user.id)
    await ctx.send(f"{user.mention} er blevet fjernet fra påmindelseslisten.")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not found in .env file")
        exit(1)
    bot.run(DISCORD_TOKEN)
