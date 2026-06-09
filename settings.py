import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv()


API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]

PORT = int(os.environ.get("PORT", "10000"))

WESTFORGE_API_URL = os.environ.get(
    "WESTFORGE_API_URL", "http://159.65.49.149:8000/ai/chat"
)
WESTFORGE_API_KEY = os.environ.get("WESTFORGE_API_KEY", "")
WESTFORGE_TIMEOUT = float(os.environ.get("WESTFORGE_TIMEOUT", "25"))
ENABLE_AI_REPLIES = os.environ.get("ENABLE_AI_REPLIES", "true").lower() == "true"
# Доля ответов, которые идут через ИИ. Остальное — лёгкие тексты-помощники
# (шаблонные банки), чтобы не перегружать медленную модель.
AI_REPLY_CHANCE = float(os.environ.get("AI_REPLY_CHANCE", "0.5"))
# Классификация эмоции по смыслу через модель (для реакций/настроения ответа).
ENABLE_AI_EMOTION = os.environ.get("ENABLE_AI_EMOTION", "true").lower() == "true"
AI_EMOTION_CHANCE = float(os.environ.get("AI_EMOTION_CHANCE", "0.35"))
# Когда к боту обращаются напрямую (реплай/упоминание) — всегда отвечать через ИИ.
AI_ALWAYS_WHEN_MENTIONED = os.environ.get(
    "AI_ALWAYS_WHEN_MENTIONED", "true"
).lower() == "true"

OUTPUTS_DIR = Path("outputs")

# База усвоенных сообщений: бот сохраняет случайные реальные тексты людей
# (в т.ч. с эмодзи) и переиспользует их для контекстных ответов и реакций.
ENABLE_MESSAGE_DB = os.environ.get("ENABLE_MESSAGE_DB", "true").lower() == "true"
DB_PATH = Path(os.environ.get("DB_PATH", str(OUTPUTS_DIR / "learned.db")))
MESSAGE_SAVE_CHANCE = float(os.environ.get("MESSAGE_SAVE_CHANCE", "0.6"))
MAX_MESSAGES_PER_CHAT = int(os.environ.get("MAX_MESSAGES_PER_CHAT", "2000"))
# Шанс ответить «выученной» фразой из БД (когда ответ не через ИИ).
LEARNED_REPLY_CHANCE = float(os.environ.get("LEARNED_REPLY_CHANCE", "0.35"))
# Шанс реагировать эмодзи в стиле самого чата (по статистике из БД).
CHAT_EMOJI_CHANCE = float(os.environ.get("CHAT_EMOJI_CHANCE", "0.5"))

MIN_DELAY = float(os.environ.get("MIN_DELAY", "0.25"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "0.9"))

RECENT_MSGS_LIMIT = int(os.environ.get("RECENT_MSGS_LIMIT", "35"))
RECENT_BOT_TEXTS_LIMIT = int(os.environ.get("RECENT_BOT_TEXTS_LIMIT", "12"))
USER_MEMORY_LIMIT = int(os.environ.get("USER_MEMORY_LIMIT", "8"))

BOT_NAME = "westik"
BOT_VERSION = "v1.0.0"
BOT_STAGE = "stable"
OWNER_USERNAME = "pooreshechqa"

ENABLE_REACTIONS = True
ENABLE_TEXT_REPLIES = True
BOT_NAME_HINTS = ["bot"]
