import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))

BOTW_NOTIFY_ROLE_ID = int(os.getenv("BOTW_NOTIFY_ROLE_ID", "0"))

DATA_DIR = "data"

GIVEAWAYS_FILE = f"{DATA_DIR}/giveaways.json"
BOTW_FILE = f"{DATA_DIR}/botw.json"
COMPETITIONS_FILE = f"{DATA_DIR}/competitions.json"
BINGO_FILE = f"{DATA_DIR}/bingo.json"
CHALLENGES_FILE = f"{DATA_DIR}/challenges.json"
HALL_OF_FAME_FILE = f"{DATA_DIR}/hall_of_fame.json"
EVENT_SIGNUPS_FILE = f"{DATA_DIR}/event_signups.json"
PLAYER_PROFILES_FILE = f"{DATA_DIR}/player_profiles.json"