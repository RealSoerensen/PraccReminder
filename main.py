import discord
from discord.ext import commands
import pickle
from API import TOKEN
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import week
from datetime import datetime as date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Prefix for commands
prefix = "."
bot = commands.Bot(
    command_prefix=prefix, activity=discord.Game("Jeg holder øje med jer!")
)
try:
    with open("db.txt", "rb") as f:
        db = pickle.load(f)
        print(db)
except FileNotFoundError or EOFError:
    db = []


def get_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("auth.json", scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open("CS:GO Team Schedule")
    return spreadsheet.worksheet(week.get_week())


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


async def remind():
    await bot.wait_until_ready()
    ctx = bot.get_channel(655128550030049323)
    csv = get_sheet()
    day_today = date.today().strftime("%A")
    days = csv.get("B2:H2")
    for x in days[0]:
        if x == day_today:
            cell = csv.find(day_today)
            break
    else:
        return await ctx.send("Der er ikke noget tilgængeligt i denne uge.")

    booking = csv.col_values(cell.col)
    time = csv.col_values(1)

    lst = []
    for i, x in enumerate(booking):
        if x == "Træning" or x == "Officals":
            lst.append(f"{time[i]} - {x}")

    if len(lst) == 0:
        return await ctx.send("Der er ikke træning eller officials i dag.")

    mentions = ", ".join(f"<@{x}>" for x in db)
    hours = "\n".join(lst)
    return await ctx.send(f"Husk træning {mentions}\n{hours}")


@bot.command()
async def add(ctx, user: discord.Member):
    if user.id in db:
        return await ctx.send(f"{user} is already in the database")
    db.append(user.id)
    with open("db.txt", "wb") as f:
        pickle.dump(db, f)
    return await ctx.send(f"{user} have been added to be reminded")


@bot.command()
async def list(ctx):
    if len(db) == 0:
        return await ctx.send("No members in list")
    member_list = []
    for x in db:
        user = await bot.fetch_user(x)
        member_list.append(f"{user.name}#{user.discriminator}")
    members = ", ".join(member_list)
    return await ctx.send(f"Current members in the list: {members}")


@bot.command()
async def remove(ctx, user: discord.Member):
    if db == None or len(db) == 0:
        return await ctx.send("No users are registered to be reminded")
    if user.id not in db:
        return await ctx.send("User is not in registered to be reminded")
    db.remove(user.id)
    with open("db.txt", "wb") as f:
        pickle.dump(db, f)
    return await ctx.send("User has been removed from the reminder")

if "__main__" == __name__:
    #initializing scheduler
    scheduler = AsyncIOScheduler()

    #sends "Your Message" at 12PM and 18PM (Local Time)
    scheduler.add_job(remind, CronTrigger(hour="10")) 

    #starting the scheduler
    scheduler.start()
    bot.run(TOKEN)
