import os
import re
import time
import random
import sqlite3
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
PORT = int(os.environ.get("PORT", 10000))

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

REACTION_CHANCE = 0.65          # шанс поставить реакцию
TEXT_REPLY_CHANCE = 0.10        # шанс написать сообщение
MENTION_REPLY_CHANCE = 0.45     # если упомянули бота/аккаунт
TEXT_COOLDOWN = 120             # минимум секунд между текстовыми сообщениями в чате
REACTION_COOLDOWN = 12          # минимум секунд между реакциями в чате
MAX_TEXTS_PER_HOUR = 8          # лимит сообщений бота в чат за час
MAX_REACTIONS_PER_HOUR = 40     # лимит реакций в чат за час
MIN_TEXT_LEN = 2
MAX_LEARN_LEN = 80
RECENT_MSGS_LIMIT = 20
QUIET_HOURS = {1, 2, 3, 4, 5, 6}

BOT_NAME_HINTS = ["бот", "bot"]  # позже автоматически добавится username/first_name

REACTIONS = [
    "😂", "💀", "🔥", "😎", "🤡", "👀", "💯", "🗿", "😭", "⚡", "🥶", "❤️"
]

DEFAULT_PHRASES = {
    "agree": [
        "real",
        "facts",
        "жиза",
        "согл",
        "база",
        "именно",
        "в точку",
        "ну это правда"
    ],
    "disagree": [
        "неа",
        "сомнительно",
        "не думаю",
        "да ну",
        "спорно",
        "не факт"
    ],
    "funny": [
        "ахах",
        "хорош",
        "убило",
        "жестко",
        "легенда",
        "сильно"
    ],
    "neutral": [
        "интересно",
        "бывает",
        "понятно",
        "ну ок",
        "ммм",
        "ладно",
        "неожиданно",
        "возможно",
        "сильный тейк"
    ]
}

TRIGGERS = {
    "agree": ["да", "ага", "реально", "правда", "true", "exactly", "same", "соглас"],
    "disagree": ["нет", "не", "wrong", "бред", "сомневаюсь", "ошибка"],
    "funny": ["ахах", "лол", "ржу", "смешно", "😂", "🤣", "💀"]
}

BLACKLIST_CONTAINS = [
    "http://",
    "https://",
    "t.me/",
    "@",
]

# =========================
# SIMPLE HEALTH SERVER
# =========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot is alive")

    def log_message(self, format, *args):
        return

def run_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

# =========================
# DATABASE
# =========================
conn = sqlite3.connect("bot_memory.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS learned_phrases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase TEXT UNIQUE,
    category TEXT DEFAULT 'neutral',
    used_count INTEGER DEFAULT 0,
    created_at INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS chat_state (
    chat_id INTEGER PRIMARY KEY,
    last_text_at INTEGER DEFAULT 0,
    last_reaction_at INTEGER DEFAULT 0,
    texts_in_last_hour INTEGER DEFAULT 0,
    reactions_in_last_hour INTEGER DEFAULT 0,
    hour_bucket INTEGER DEFAULT 0
)
""")

conn.commit()

# =========================
# MEMORY
# =========================
recent_messages = defaultdict(lambda: deque(maxlen=RECENT_MSGS_LIMIT))
recent_bot_texts = defaultdict(lambda: deque(maxlen=5))

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

    if len(t.split()) > 7:
        return False

    if not re.fullmatch(r"[a-zа-яё0-9\s.,!?-]+", t, re.IGNORECASE):
        return False

    return True

def detect_category(text: str) -> str:
    t = clean_text(text)
    for category, words in TRIGGERS.items():
        for w in words:
            if w in t:
                return category
    return "neutral"

def save_phrase(text: str):
    if not is_valid_for_learning(text):
        return
    phrase = clean_text(text)
    category = detect_category(phrase)
    try:
        cur.execute(
            "INSERT OR IGNORE INTO learned_phrases (phrase, category, created_at) VALUES (?, ?, ?)",
            (phrase, category, int(time.time()))
        )
        conn.commit()
    except Exception:
        pass

def get_chat_state(chat_id: int):
    cur.execute("""
        SELECT last_text_at, last_reaction_at, texts_in_last_hour, reactions_in_last_hour, hour_bucket
        FROM chat_state
        WHERE chat_id = ?
    """, (chat_id,))
    row = cur.fetchone()

    if row:
        return {
            "last_text_at": row[0],
            "last_reaction_at": row[1],
            "texts_in_last_hour": row[2],
            "reactions_in_last_hour": row[3],
            "hour_bucket": row[4],
        }

    hour_bucket = int(time.time()) // 3600
    cur.execute("""
        INSERT OR IGNORE INTO chat_state (
            chat_id, last_text_at, last_reaction_at,
            texts_in_last_hour, reactions_in_last_hour, hour_bucket
        ) VALUES (?, 0, 0, 0, 0, ?)
    """, (chat_id, hour_bucket))
    conn.commit()

    return {
        "last_text_at": 0,
        "last_reaction_at": 0,
        "texts_in_last_hour": 0,
        "reactions_in_last_hour": 0,
        "hour_bucket": hour_bucket,
    }

def refresh_hour_bucket(chat_id: int, state: dict):
    current_bucket = int(time.time()) // 3600
    if state["hour_bucket"] != current_bucket:
        cur.execute("""
            UPDATE chat_state
            SET texts_in_last_hour = 0,
                reactions_in_last_hour = 0,
                hour_bucket = ?
            WHERE chat_id = ?
        """, (current_bucket, chat_id))
        conn.commit()
        state["texts_in_last_hour"] = 0
        state["reactions_in_last_hour"] = 0
        state["hour_bucket"] = current_bucket

def mark_text_sent(chat_id: int):
    now = int(time.time())
    state = get_chat_state(chat_id)
    refresh_hour_bucket(chat_id, state)
    cur.execute("""
        UPDATE chat_state
        SET last_text_at = ?, texts_in_last_hour = texts_in_last_hour + 1
        WHERE chat_id = ?
    """, (now, chat_id))
    conn.commit()

def mark_reaction_sent(chat_id: int):
    now = int(time.time())
    state = get_chat_state(chat_id)
    refresh_hour_bucket(chat_id, state)
    cur.execute("""
        UPDATE chat_state
        SET last_reaction_at = ?, reactions_in_last_hour = reactions_in_last_hour + 1
        WHERE chat_id = ?
    """, (now, chat_id))
    conn.commit()

def recent_activity_bonus(chat_id: int) -> float:
    count = len(recent_messages[chat_id])
    if count >= 12:
        return 0.05
    if count >= 6:
        return 0.02
    return 0.0

def choose_learned_phrase(category: str | None = None):
    try:
        if category:
            cur.execute("""
                SELECT phrase FROM learned_phrases
                WHERE category = ?
                ORDER BY RANDOM()
                LIMIT 1
            """, (category,))
            row = cur.fetchone()
            if row:
                return row[0]

        cur.execute("""
            SELECT phrase FROM learned_phrases
            ORDER BY RANDOM()
            LIMIT 1
        """)
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None

def mark_phrase_used(phrase: str):
    try:
        cur.execute(
            "UPDATE learned_phrases SET used_count = used_count + 1 WHERE phrase = ?",
            (phrase,)
        )
        conn.commit()
    except Exception:
        pass

def choose_reply(text: str, chat_id: int) -> str:
    category = detect_category(text)

    # 25% взять выученную фразу
    if random.random() < 0.25:
        learned = choose_learned_phrase(category)
        if learned and learned not in recent_bot_texts[chat_id]:
            mark_phrase_used(learned)
            return learned

    pool = DEFAULT_PHRASES.get(category, DEFAULT_PHRASES["neutral"])
    choices = [p for p in pool if p not in recent_bot_texts[chat_id]]
    if not choices:
        choices = pool

    return random.choice(choices)

def should_send_text(chat_id: int, text: str, mentioned: bool) -> bool:
    now = int(time.time())
    hour = time.localtime(now).tm_hour
    state = get_chat_state(chat_id)
    refresh_hour_bucket(chat_id, state)

    if now - state["last_text_at"] < TEXT_COOLDOWN:
        return False

    if state["texts_in_last_hour"] >= MAX_TEXTS_PER_HOUR:
        return False

    if len(text.strip()) < MIN_TEXT_LEN and not mentioned:
        return False

    chance = MENTION_REPLY_CHANCE if mentioned else TEXT_REPLY_CHANCE
    chance += recent_activity_bonus(chat_id)

    if hour in QUIET_HOURS:
        chance *= 0.35

    return random.random() < chance

def should_send_reaction(chat_id: int, text: str) -> bool:
    now = int(time.time())
    hour = time.localtime(now).tm_hour
    state = get_chat_state(chat_id)
    refresh_hour_bucket(chat_id, state)

    if now - state["last_reaction_at"] < REACTION_COOLDOWN:
        return False

    if state["reactions_in_last_hour"] >= MAX_REACTIONS_PER_HOUR:
        return False

    if len(text.strip()) < 1:
        return False

    chance = REACTION_CHANCE + recent_activity_bonus(chat_id)

    if hour in QUIET_HOURS:
        chance *= 0.5

    return random.random() < chance

def pick_reaction(text: str) -> str:
    t = clean_text(text)

    if any(x in t for x in ["ахах", "лол", "ржу", "😂", "🤣"]):
        return random.choice(["😂", "💀", "🤣"])
    if any(x in t for x in ["жест", "имба", "сильно", "мощно", "топ"]):
        return random.choice(["🔥", "💯", "⚡"])
    if any(x in t for x in ["груст", "печаль", "жалко"]):
        return random.choice(["😭", "💔"])
    if any(x in t for x in ["люблю", "мило", "краш"]):
        return random.choice(["❤️", "🥰"])
    if any(x in t for x in ["что", "чего", "не понял"]):
        return random.choice(["👀", "🤡"])

    return random.choice(REACTIONS)

async def human_delay(text: str = ""):
    delay = min(3.0, max(0.7, len(text) * 0.04 + random.uniform(0.2, 0.8)))
    await asyncio.sleep(delay)

async def send_reaction(event, emoji: str):
    try:
        await client(functions.messages.SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.message.id,
            reaction=[types.ReactionEmoji(emoticon=emoji)],
            big=random.choice([True, False]),
            add_to_recent=True
        ))
        mark_reaction_sent(event.chat_id)
        print(f"Reaction sent in chat {event.chat_id}: {emoji}")
    except FloodWaitError as e:
        print(f"FloodWait on reaction: sleep {e.seconds}s")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"Reaction error: {e}")

async def send_text(event, text: str):
    try:
        await human_delay(text)
        await event.respond(text)
        recent_bot_texts[event.chat_id].append(text)
        mark_text_sent(event.chat_id)
        print(f"Text sent in chat {event.chat_id}: {text}")
    except FloodWaitError as e:
        print(f"FloodWait on text: sleep {e.seconds}s")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"Text reply error: {e}")

# =========================
# MAIN HANDLER
# =========================
@client.on(events.NewMessage)
async def handler(event):
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
        save_phrase(text)

        mentioned = False
        lowered = cleaned
        for name in BOT_NAME_HINTS:
            if name and name.lower() in lowered:
                mentioned = True
                break

        # 1) РЕАКЦИЯ
        if ENABLE_REACTIONS and should_send_reaction(chat_id, text):
            emoji = pick_reaction(text)
            await send_reaction(event, emoji)

        # 2) ТЕКСТ
        if ENABLE_TEXT_REPLIES and should_send_text(chat_id, text, mentioned):
            reply = choose_reply(text, chat_id)
            await send_text(event, reply)

    except Exception as e:
        print(f"Handler general error: {e}")

# =========================
# START
# =========================
async def main():
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")

    if me.username:
        BOT_NAME_HINTS.append(me.username.lower())
    if me.first_name:
        BOT_NAME_HINTS.append(me.first_name.lower())

    print("Bot is running...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()

    with client:
        client.loop.run_until_complete(main())