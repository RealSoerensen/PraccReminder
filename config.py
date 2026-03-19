import os

from dotenv import load_dotenv


load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "1356375075208691937"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1corGGS-H2WE_nhg5Sa80dHPpVcrl2jNzawxXxpniPDc")
SCHEDULER_HOUR = os.getenv("SCHEDULER_HOUR", "10")
AUTH_FILE = "auth.json"
COMMAND_PREFIX = "."