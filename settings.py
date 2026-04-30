import os
from pathlib import Path


API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

PORT = int(os.environ.get("PORT", "10000"))
HF_API_TOKEN = os.environ.get("HF_API_TOKEN", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip()
ENABLE_OPENAI_REPLIES = os.environ.get(
    "ENABLE_OPENAI_REPLIES", "true"
).lower() == "true"

DOWNLOADS_DIR = Path("downloads")
OUTPUTS_DIR = Path("outputs")
SUPPORTED_MEDIA_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".weba",
    ".webm",
}
VOCAL_PROCESS_ESTIMATE_SECONDS = int(os.environ.get("VOCAL_PROCESS_ESTIMATE_SECONDS", "300"))
VOCAL_PROGRESS_UPDATE_INTERVAL = int(os.environ.get("VOCAL_PROGRESS_UPDATE_INTERVAL", "10"))
VOCAL_SEPARATION_TIMEOUT_SECONDS = int(os.environ.get("VOCAL_SEPARATION_TIMEOUT_SECONDS", "3600"))
VOCAL_DEMUCS_STALL_TIMEOUT_SECONDS = int(os.environ.get("VOCAL_DEMUCS_STALL_TIMEOUT_SECONDS", "900"))
VOCAL_SEND_TIMEOUT_SECONDS = int(os.environ.get("VOCAL_SEND_TIMEOUT_SECONDS", "1800"))
VOCAL_DEMUCS_MODELS = [
    item.strip()
    for item in os.environ.get("VOCAL_DEMUCS_MODELS", "mdx_q,mdx_extra_q,htdemucs").split(",")
    if item.strip()
]

TZ_OFFSET = int(os.environ.get("TZ_OFFSET", "5"))

MIN_DELAY = float(os.environ.get("MIN_DELAY", "0.25"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "0.9"))

REACTION_CHANCE = float(os.environ.get("REACTION_CHANCE", "0.98"))
TEXT_REPLY_CHANCE = float(os.environ.get("TEXT_REPLY_CHANCE", "0.45"))
MENTION_REPLY_CHANCE = float(os.environ.get("MENTION_REPLY_CHANCE", "0.85"))

TEXT_COOLDOWN = int(os.environ.get("TEXT_COOLDOWN", "0"))
REACTION_COOLDOWN = int(os.environ.get("REACTION_COOLDOWN", "0"))

MAX_TEXTS_PER_HOUR = int(os.environ.get("MAX_TEXTS_PER_HOUR", "120"))
MAX_REACTIONS_PER_HOUR = int(os.environ.get("MAX_REACTIONS_PER_HOUR", "160"))

RECENT_MSGS_LIMIT = int(os.environ.get("RECENT_MSGS_LIMIT", "35"))
RECENT_BOT_TEXTS_LIMIT = int(os.environ.get("RECENT_BOT_TEXTS_LIMIT", "12"))
USER_MEMORY_LIMIT = int(os.environ.get("USER_MEMORY_LIMIT", "8"))
MAX_CONTEXT = int(os.environ.get("MAX_CONTEXT", "8"))

ENABLE_INIT_MESSAGES = os.environ.get(
    "ENABLE_INIT_MESSAGES", "true"
).lower() == "true"

INACTIVITY_TRIGGER = int(os.environ.get("INACTIVITY_TRIGGER", "86400"))
INACTIVITY_CHECK_INTERVAL = int(os.environ.get("INACTIVITY_CHECK_INTERVAL", "600"))
INIT_MESSAGE_CHANCE = float(os.environ.get("INIT_MESSAGE_CHANCE", "1.0"))
INIT_MIN_GAP = int(os.environ.get("INIT_MIN_GAP", "604800"))

TEST_INIT_PRIVATE_ONLY = os.environ.get(
    "TEST_INIT_PRIVATE_ONLY", "false"
).lower() == "true"

USE_AI_CLASSIFICATION = os.environ.get(
    "USE_AI_CLASSIFICATION", "true"
).lower() == "true"

BOT_NAME = "westik"
BOT_VERSION = "v1.0.0"
BOT_STAGE = "stable"
OWNER_USERNAME = "pooreshechqa"

ENABLE_REACTIONS = True
ENABLE_TEXT_REPLIES = True
MIN_TEXT_LEN = 12
QUIET_HOURS = set()
BOT_NAME_HINTS = ["bot"]
