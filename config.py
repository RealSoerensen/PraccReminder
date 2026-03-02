import os

from dotenv import load_dotenv


load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "955980756960809013"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1SeHReR2AuaBPJXBvvhhg7ulCB_DCVQGdfoRKxWKb248")
SCHEDULER_HOUR = os.getenv("SCHEDULER_HOUR", "10")
AUTH_FILE = "auth.json"
COMMAND_PREFIX = "."