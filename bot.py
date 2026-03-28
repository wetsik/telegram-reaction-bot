import os
import re
import time
import random
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict, deque

from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

# =========================
# ENV
# =========================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]

PORT = int(os.environ.get("PORT", "10000"))

MIN_DELAY = float(os.environ.get("MIN_DELAY", "0.5"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "1.5"))

REACTION_CHANCE = float(os.environ.get("REACTION_CHANCE", "0.55"))
MENTION_REPLY_CHANCE = float(os.environ.get("MENTION_REPLY_CHANCE", "0.9"))

TEXT_COOLDOWN = int(os.environ.get("TEXT_COOLDOWN", "90"))
REACTION_COOLDOWN = int(os.environ.get("REACTION_COOLDOWN", "10"))

MAX_TEXTS_PER_HOUR = int(os.environ.get("MAX_TEXTS_PER_HOUR", "12"))
MAX_REACTIONS_PER_HOUR = int(os.environ.get("MAX_REACTIONS_PER_HOUR", "35"))

# каждые примерно 5 сообщений бот может писать
MESSAGE_INTERVAL_MIN = int(os.environ.get("MESSAGE_INTERVAL_MIN", "5"))
MESSAGE_INTERVAL_MAX = int(os.environ.get("MESSAGE_INTERVAL_MAX", "7"))

# RAM limits
RECENT_MSGS_LIMIT = int(os.environ.get("RECENT_MSGS_LIMIT", "25"))
RECENT_BOT_TEXTS_LIMIT = int(os.environ.get("RECENT_BOT_TEXTS_LIMIT", "6"))
LEARNED_PER_CHAT_LIMIT = int(os.environ.get("LEARNED_PER_CHAT_LIMIT", "80"))

# =========================
# CLIENT
# =========================
client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)

# =========================
# SETTINGS
# =========================
ENABLE_REACTIONS = True
ENABLE_TEXT_REPLIES = True

MIN_TEXT_LEN = 2
MAX_LEARN_LEN = 80

QUIET_HOURS = {1, 2, 3, 4, 5, 6}
BOT_NAME_HINTS = ["бот", "bot"]

EMOJIS = [
    "😂", "🤣", "💀", "😭", "😹", "😆",
    "😳", "😱", "👀", "🤯", "😮",
    "🔥", "💯", "⚡", "😎", "🚀", "👏",
    "😢", "💔", "🥲",
    "❤️", "🥰", "💖", "🙏",
    "😡", "🤦", "👍", "🙂", "🗿"
]

DEFAULT_PHRASES = {
    "agree": [
        "real", "facts", "жиза", "согл", "база",
        "именно", "в точку", "ну это правда", "да да"
    ],
    "disagree": [
        "неа", "сомнительно", "не думаю", "да ну",
        "спорно", "не факт", "ну нет", "вряд ли"
    ],
    "funny": [
        "ахах", "хорош", "убило", "жестко",
        "легенда", "сильно", "я не могу", "это мощно"
    ],
    "neutral": [
        "интересно", "бывает", "понятно", "ну ок",
        "ммм", "ладно", "неожиданно", "возможно",
        "сильный тейк", "бывает же"
    ],
    "greeting": [
        "привет", "йо", "здарова", "ку", "хай",
        "приветик", "салам", "hello"
    ]
}

TRIGGERS = {
    "agree": ["да", "ага", "реально", "правда", "true", "exactly", "same", "соглас"],
    "disagree": ["нет", "wrong", "бред", "сомневаюсь", "ошибка"],
    "funny": ["ахах", "лол", "ржу", "смешно", "😂", "🤣", "💀"]
}

GREETING_WORDS = [
    "привет", "здарова", "здравствуй", "салам", "ку",
    "хай", "hello", "hi", "hey", "yo"
]

BLACKLIST_CONTAINS = [
    "http://",
    "https://",
    "t.me/",
]

# =========================
# HEALTH SERVER
# =========================
class HealthHandler(BaseHTTPRequestHandler):
    def _send_ok(self, body=False):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        if body:
            self.wfile.write(b"ok")

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._send_ok(body=True)
        else:
            self.send_response(404)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"not found")

    def do_HEAD(self):
        if self.path in ("/", "/health"):
            self._send_ok(body=False)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Health server started on port {PORT}")
    server.serve_forever()

# =========================
# RAM MEMORY
# =========================
recent_messages = defaultdict(lambda: deque(maxlen=RECENT_MSGS_LIMIT))
recent_bot_texts = defaultdict(lambda: deque(maxlen=RECENT_BOT_TEXTS_LIMIT))
learned_phrases = defaultdict(lambda: deque(maxlen=LEARNED_PER_CHAT_LIMIT))

chat_state = defaultdict(lambda: {
    "last_text_at": 0,
    "last_reaction_at": 0,
    "texts_in_last_hour": 0,
    "reactions_in_last_hour": 0,
    "hour_bucket": int(time.time()) // 3600,
    "messages_since_text": 0,
    "next_text_after": random.randint(MESSAGE_INTERVAL_MIN, MESSAGE_INTERVAL_MAX),
})

# =========================
# HELPERS
# =========================
def clean_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text

def is_group_event(event) -> bool:
    return bool(event.is_group or event.is_channel)

def contains_blacklisted(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in BLACKLIST_CONTAINS)

def is_valid_for_learning(text: str) -> bool:
    if not text:
        return False

    t = clean_text(text)

    if len(t) < 2 or len(t) > MAX_LEARN_LEN:
        return False

    if contains_blacklisted(t):
        return False

    if t.startswith("/"):
        return False

    if "@" in t:
        return False

    if len(t.split()) > 7:
        return False

    if not re.fullmatch(r"[a-zа-яё0-9\s.,!?-]+", t, re.IGNORECASE):
        return False

    return True

def detect_category(text: str) -> str:
    t = clean_text(text)

    for greeting in GREETING_WORDS:
        if greeting in t:
            return "greeting"

    for category, words in TRIGGERS.items():
        for w in words:
            if w in t:
                return category

    return "neutral"

def save_phrase(chat_id: int, text: str):
    if not is_valid_for_learning(text):
        return

    phrase = clean_text(text)
    if phrase not in learned_phrases[chat_id]:
        learned_phrases[chat_id].append(phrase)

def refresh_hour_bucket(chat_id: int):
    current_bucket = int(time.time()) // 3600
    if chat_state[chat_id]["hour_bucket"] != current_bucket:
        chat_state[chat_id]["texts_in_last_hour"] = 0
        chat_state[chat_id]["reactions_in_last_hour"] = 0
        chat_state[chat_id]["hour_bucket"] = current_bucket

def mark_text_sent(chat_id: int):
    refresh_hour_bucket(chat_id)
    chat_state[chat_id]["last_text_at"] = int(time.time())
    chat_state[chat_id]["texts_in_last_hour"] += 1
    chat_state[chat_id]["messages_since_text"] = 0
    chat_state[chat_id]["next_text_after"] = random.randint(MESSAGE_INTERVAL_MIN, MESSAGE_INTERVAL_MAX)

def mark_reaction_sent(chat_id: int):
    refresh_hour_bucket(chat_id)
    chat_state[chat_id]["last_reaction_at"] = int(time.time())
    chat_state[chat_id]["reactions_in_last_hour"] += 1

def recent_activity_bonus(chat_id: int) -> float:
    count = len(recent_messages[chat_id])
    if count >= 12:
        return 0.05
    if count >= 6:
        return 0.02
    return 0.0

def choose_learned_phrase(chat_id: int, category: str | None = None):
    phrases = list(learned_phrases[chat_id])
    if not phrases:
        return None

    if category == "greeting":
        greeting_phrases = [p for p in phrases if any(g in p for g in GREETING_WORDS)]
        if greeting_phrases:
            return random.choice(greeting_phrases)

    filtered = [p for p in phrases if p not in recent_bot_texts[chat_id]]
    if filtered:
        return random.choice(filtered)

    return random.choice(phrases)

def mark_phrase_used(chat_id: int, phrase: str):
    recent_bot_texts[chat_id].append(phrase)

def choose_reply(text: str, chat_id: int) -> str:
    category = detect_category(text)

    if category == "greeting":
        pool = DEFAULT_PHRASES["greeting"]
        choices = [p for p in pool if p not in recent_bot_texts[chat_id]]
        if not choices:
            choices = pool
        return random.choice(choices)

    if random.random() < 0.30:
        learned = choose_learned_phrase(chat_id, category)
        if learned and learned not in recent_bot_texts[chat_id]:
            mark_phrase_used(chat_id, learned)
            return learned

    pool = DEFAULT_PHRASES.get(category, DEFAULT_PHRASES["neutral"])
    choices = [p for p in pool if p not in recent_bot_texts[chat_id]]
    if not choices:
        choices = pool

    return random.choice(choices)

def is_greeting_for_bot(text: str, mentioned: bool) -> bool:
    if not mentioned:
        return False
    t = clean_text(text)
    return any(word in t for word in GREETING_WORDS)

def should_send_text(chat_id: int, text: str, mentioned: bool) -> bool:
    now = int(time.time())
    hour = time.localtime(now).tm_hour
    refresh_hour_bucket(chat_id)

    state = chat_state[chat_id]

    # если бота упомянули и написали привет — отвечаем почти всегда
    if is_greeting_for_bot(text, mentioned):
        if now - state["last_text_at"] < 3:
            return False
        return True

    if now - state["last_text_at"] < TEXT_COOLDOWN:
        return False

    if state["texts_in_last_hour"] >= MAX_TEXTS_PER_HOUR:
        return False

    if len(text.strip()) < MIN_TEXT_LEN and not mentioned:
        return False

    # пишем примерно каждые N сообщений
    if state["messages_since_text"] < state["next_text_after"]:
        return False

    # если упомянули, шанс выше
    chance = MENTION_REPLY_CHANCE if mentioned else 1.0
    chance += recent_activity_bonus(chat_id)

    if hour in QUIET_HOURS:
        chance *= 0.5

    return random.random() < min(chance, 1.0)

def should_send_reaction(chat_id: int, text: str) -> bool:
    now = int(time.time())
    hour = time.localtime(now).tm_hour
    refresh_hour_bucket(chat_id)

    state = chat_state[chat_id]

    if now - state["last_reaction_at"] < REACTION_COOLDOWN:
        return False

    if state["reactions_in_last_hour"] >= MAX_REACTIONS_PER_HOUR:
        return False

    if len(text.strip()) < 1:
        return False

    chance = REACTION_CHANCE + recent_activity_bonus(chat_id)

    if hour in QUIET_HOURS:
        chance *= 0.5

    return random.random() < min(chance, 1.0)

def pick_reaction(text: str) -> str:
    t = clean_text(text)

    if any(x in t for x in ["ахах", "лол", "ржу", "😂", "🤣"]):
        return random.choice(["😂", "💀", "🤣"])
    if any(x in t for x in ["жест", "имба", "сильно", "мощно", "топ"]):
        return random.choice(["🔥", "💯", "⚡"])
    if any(x in t for x in ["груст", "печаль", "жалко"]):
        return random.choice(["😭", "💔", "🥲"])
    if any(x in t for x in ["люблю", "мило", "краш"]):
        return random.choice(["❤️", "🥰", "💖"])
    if any(x in t for x in ["что", "чего", "не понял"]):
        return random.choice(["👀", "🤯", "😳"])
    if any(x in t for x in GREETING_WORDS):
        return random.choice(["👋", "❤️", "🙂"])

    return random.choice(EMOJIS)

async def human_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

async def send_reaction(event, emoji: str):
    try:
        await human_delay()
        await client(functions.messages.SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.id,
            big=False,
            add_to_recent=True,
            reaction=[types.ReactionEmoji(emoticon=emoji)]
        ))
        mark_reaction_sent(event.chat_id)
        print(f"Reacted {emoji} to message {event.id} in chat {event.chat_id}")

    except FloodWaitError as e:
        print(f"FloodWait on reaction: sleeping for {e.seconds} seconds")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print(f"ERROR while reacting: {e}")

async def send_text(event, text: str):
    try:
        await human_delay()
        await event.respond(text)
        recent_bot_texts[event.chat_id].append(text)
        mark_text_sent(event.chat_id)
        print(f"Sent text '{text}' to chat {event.chat_id}")

    except FloodWaitError as e:
        print(f"FloodWait on text: sleeping for {e.seconds} seconds")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print(f"ERROR while sending text: {e}")

# =========================
# MAIN HANDLER
# =========================
@client.on(events.NewMessage)
async def handle_new_message(event):
    try:
        if not event.message:
            return

        if event.out:
            return

        if not is_group_event(event):
            return

        text = event.raw_text or ""
        if not text.strip():
            return

        sender = await event.get_sender()
        me = await client.get_me()

        if sender and me and getattr(sender, "id", None) == me.id:
            return

        chat_id = event.chat_id
        cleaned = clean_text(text)

        recent_messages[chat_id].append(cleaned)
        save_phrase(chat_id, text)

        refresh_hour_bucket(chat_id)
        chat_state[chat_id]["messages_since_text"] += 1

        mentioned = False
        for name in BOT_NAME_HINTS:
            if name and name.lower() in cleaned:
                mentioned = True
                break

        if ENABLE_REACTIONS and should_send_reaction(chat_id, text):
            emoji = pick_reaction(text)
            await send_reaction(event, emoji)

        if ENABLE_TEXT_REPLIES and should_send_text(chat_id, text, mentioned):
            reply = choose_reply(text, chat_id)
            await send_text(event, reply)

    except Exception as e:
        print(f"HANDLER ERROR: {e}")

# =========================
# RUN LOOP
# =========================
async def run_bot_forever():
    while True:
        try:
            print("Starting Telegram client...")
            await client.start()

            me = await client.get_me()
            print(f"Logged in as: {me.first_name} (@{me.username})")

            if me.username:
                BOT_NAME_HINTS.append(me.username.lower())
            if me.first_name:
                BOT_NAME_HINTS.append(me.first_name.lower())

            BOT_NAME_HINTS[:] = list(dict.fromkeys(BOT_NAME_HINTS))

            print("Userbot started and listening for new messages...")
            await client.run_until_disconnected()

        except Exception as e:
            print(f"MAIN ERROR: {e}")

        print("Restarting in 5 seconds...")
        await asyncio.sleep(5)

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(run_bot_forever())