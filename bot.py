import os
import re
import time
import json
import random
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict, deque

import aiohttp
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

# =========================================================
# ENV
# =========================================================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]

PORT = int(os.environ.get("PORT", "10000"))
HF_API_TOKEN = os.environ.get("HF_API_TOKEN", "").strip()

# задержка перед реакцией / ответом
MIN_DELAY = float(os.environ.get("MIN_DELAY", "0.25"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "0.9"))

# частота действий
REACTION_CHANCE = float(os.environ.get("REACTION_CHANCE", "0.98"))
TEXT_REPLY_CHANCE = float(os.environ.get("TEXT_REPLY_CHANCE", "0.30"))
MENTION_REPLY_CHANCE = float(os.environ.get("MENTION_REPLY_CHANCE", "0.95"))

# лимиты на всякий случай
TEXT_COOLDOWN = int(os.environ.get("TEXT_COOLDOWN", "20"))
REACTION_COOLDOWN = int(os.environ.get("REACTION_COOLDOWN", "0"))

MAX_TEXTS_PER_HOUR = int(os.environ.get("MAX_TEXTS_PER_HOUR", "25"))
MAX_REACTIONS_PER_HOUR = int(os.environ.get("MAX_REACTIONS_PER_HOUR", "160"))

# память
RECENT_MSGS_LIMIT = int(os.environ.get("RECENT_MSGS_LIMIT", "35"))
RECENT_BOT_TEXTS_LIMIT = int(os.environ.get("RECENT_BOT_TEXTS_LIMIT", "12"))
MAX_CONTEXT = int(os.environ.get("MAX_CONTEXT", "8"))

# инициативные сообщения
ENABLE_INIT_MESSAGES = os.environ.get("ENABLE_INIT_MESSAGES", "true").lower() == "true"
INACTIVITY_TRIGGER = int(os.environ.get("INACTIVITY_TRIGGER", "1200"))  # 20 мин
INACTIVITY_CHECK_INTERVAL = int(os.environ.get("INACTIVITY_CHECK_INTERVAL", "60"))
INIT_MESSAGE_CHANCE = float(os.environ.get("INIT_MESSAGE_CHANCE", "0.60"))
INIT_MIN_GAP = int(os.environ.get("INIT_MIN_GAP", "1800"))  # между инициативными сообщениями 30 мин

# ИИ-классификация
USE_AI_CLASSIFICATION = os.environ.get("USE_AI_CLASSIFICATION", "true").lower() == "true"

# общие
ENABLE_REACTIONS = True
ENABLE_TEXT_REPLIES = True
MIN_TEXT_LEN = 1
QUIET_HOURS = {1, 2, 3, 4, 5, 6}
BOT_NAME_HINTS = ["бот", "bot"]

# =========================================================
# CLIENT
# =========================================================
client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)

# =========================================================
# HEALTH SERVER
# =========================================================
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

# =========================================================
# MEMORY
# =========================================================
recent_messages = defaultdict(lambda: deque(maxlen=RECENT_MSGS_LIMIT))
recent_bot_texts = defaultdict(lambda: deque(maxlen=RECENT_BOT_TEXTS_LIMIT))
last_message_time = defaultdict(lambda: time.time())

chat_state = defaultdict(lambda: {
    "last_text_at": 0,
    "last_reaction_at": 0,
    "last_init_at": 0,
    "texts_in_last_hour": 0,
    "reactions_in_last_hour": 0,
    "hour_bucket": int(time.time()) // 3600,
})

last_used_reaction = defaultdict(lambda: None)
last_used_reply = defaultdict(lambda: None)

# =========================================================
# DATA
# =========================================================
BLACKLIST_CONTAINS = [
    "http://",
    "https://",
    "t.me/",
]

GREETING_WORDS = [
    "привет", "здарова", "здравствуй", "салам", "ку",
    "хай", "hello", "hi", "hey", "yo"
]

CANDIDATE_LABELS = [
    "funny",
    "shock",
    "hype",
    "sad",
    "love",
    "anger",
    "question",
    "agreement",
    "disagreement",
    "greeting",
    "neutral"
]

PATTERNS = {
    "greeting": [
        r"\bприв(ет)?\b", r"\bку\b", r"\bздарова\b", r"\bсалам\b",
        r"\bhello\b", r"\bhi\b", r"\bhey\b", r"\byo\b"
    ],
    "question": [
        r"\?$", r"\bпочему\b", r"\bзачем\b", r"\bкак\b", r"\bчто\b",
        r"\bкогда\b", r"\bгде\b", r"\bкто\b", r"\bразве\b"
    ],
    "agreement": [
        r"\bреал\b", r"\bжиза\b", r"\bсогл\b", r"\bбаза\b",
        r"\bфакт\b", r"\bименно\b", r"\btrue\b", r"\breal\b"
    ],
    "disagreement": [
        r"\bнеа\b", r"\bне думаю\b", r"\bсомнительно\b",
        r"\bспорно\b", r"\bвряд ли\b", r"\bnope\b", r"\bне факт\b"
    ],
    "funny": [
        r"\бах+а*х*\b", r"\bхаха+\b", r"\bахах+\b", r"\bлол\b",
        r"\bору\b", r"\bубило\b", r"\bржака\b", r"\blol\b", r"\blmao\b"
    ],
    "sad": [
        r"\bжалко\b", r"\bгрустно\b", r"\bпечально\b",
        r"\bобидно\b", r"\bэх\b", r"\bжаль\b"
    ],
    "anger": [
        r"\bбесит\b", r"\bзлит\b", r"\bненавижу\b",
        r"\bужас\b", r"\bвыбесил\b", r"\bгорит\b"
    ],
    "love": [
        r"\bлюблю\b", r"\bмило\b", r"\bкайф\b",
        r"\bимба\b", r"\bтоп\b", r"\bлучший\b"
    ],
    "shock": [
        r"\bчего\b", r"\bничего себе\b", r"\bофигеть\b",
        r"\bв шоке\b", r"\bomg\b", r"\bwtf\b", r"\bкапец\b"
    ],
    "hype": [
        r"\bхарош\b", r"\bжестко\b", r"\bжёстко\b",
        r"\bмощно\b", r"\bлегенда\b", r"\bразнос\b", r"\bfire\b"
    ]
}

REACTIONS = {
    "funny": ["😂", "🤣", "💀"],
    "shock": ["😱", "👀", "💀", "🔥"],
    "hype": ["🔥", "💯", "⚡", "🗿"],
    "sad": ["😢", "💔", "🥀"],
    "love": ["❤️", "😍", "🔥"],
    "anger": ["😡", "🤡", "💀"],
    "question": ["🤔", "👀", "🗿"],
    "agreement": ["💯", "🗿", "🔥"],
    "disagreement": ["🤨", "😏", "🗿"],
    "greeting": ["👋", "😎", "❤️"],
    "neutral": ["👀", "🗿", "🙂", "🔥"]
}

TEXT_REPLIES = {
    "funny": [
        "ахах это сильно",
        "не ну это разнос",
        "я выпал",
        "убило",
        "жесткий вброс",
        "это было мощно"
    ],
    "shock": [
        "чегооо",
        "вот это поворот",
        "я сейчас выпал",
        "неожиданно конечно",
        "это уже жестко",
        "ничего себе"
    ],
    "hype": [
        "легенда",
        "это разнос",
        "мощно",
        "сильно",
        "имба",
        "харош"
    ],
    "sad": [
        "блин жаль",
        "обидно конечно",
        "печальная тема",
        "эх",
        "неприятно"
    ],
    "love": [
        "кайф",
        "это мило",
        "имба вообще",
        "согл это топ",
        "приятно"
    ],
    "anger": [
        "вот это бесит реально",
        "не ну тут понять можно",
        "жесть конечно",
        "да это уже перебор",
        "сильно горит"
    ],
    "question": [
        "хороший вопрос",
        "вопрос с подвохом",
        "вот тут уже интересно",
        "ммм спорно",
        "надо подумать"
    ],
    "agreement": [
        "база",
        "реал",
        "в точку",
        "согл",
        "чистые факты"
    ],
    "disagreement": [
        "неа тут спорно",
        "не ну я бы не сказал",
        "сомнительно",
        "не факт",
        "спорный тейк"
    ],
    "greeting": [
        "йо",
        "ку",
        "здарова",
        "приветик",
        "о привет"
    ],
    "neutral": [
        "интересно",
        "бывает",
        "сильный тейк",
        "ладно",
        "ммм",
        "понятно",
        "Котенька масюня"
    ]
}

LIGHT_ROAST_REPLIES = [
    "ты серьёзно щас?",
    "брат ты чего",
    "ну ты выдал конечно",
    "гений наоборот",
    "не ты гонишь",
    "хорош уже",
    "ну это мощный тейк",
    "ты прикалываешься?",
    "сильное заявление конечно",
    "ну ты и персонаж",
    "логика вышла из чата",
    "это было смело"
]

INIT_START = [
    "все резко стали занятыми да",
    "сильный онлайн конечно",
    "ну вы и актив конечно",
    "актив умер моментально",
    "чат в спящем режиме",
]

INIT_CORE = [
    "че притихли",
    "чат умер или мне кажется",
    "вы там живы вообще",
    "тишина подозрительная",
    "кто нибудь еще тут",
    "ну и тишина",
    "я один тут сижу или как",
    "что за молчание",
    "кто первый напишет тот легенда",
    "проснулись"
]

INIT_END = [
    "",
    "или я что то пропустил",
    "алло",
    "ау",
    "непонятно",
    "мне одному скучно",
    "кто нибудь проснулся",
]

# =========================================================
# HELPERS
# =========================================================
def clean_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text

def contains_blacklisted(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in BLACKLIST_CONTAINS)

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

def mark_reaction_sent(chat_id: int):
    refresh_hour_bucket(chat_id)
    chat_state[chat_id]["last_reaction_at"] = int(time.time())
    chat_state[chat_id]["reactions_in_last_hour"] += 1

def mark_init_sent(chat_id: int):
    chat_state[chat_id]["last_init_at"] = int(time.time())

def recent_activity_bonus(chat_id: int) -> float:
    count = len(recent_messages[chat_id])
    if count >= 15:
        return 0.04
    if count >= 8:
        return 0.02
    return 0.0

def should_roast(text: str, category: str) -> bool:
    t = clean_text(text)
    if category not in {"disagreement", "shock", "question", "anger", "neutral"}:
        return False
    if any(x in t for x in ["жалко", "грустно", "умер", "болит", "обидно", "плохо"]):
        return False
    if len(t) < 4:
        return False
    return random.random() < 0.22

def pick_from_pool_avoiding_repeat(chat_id: int, pool: list[str], storage: dict) -> str:
    last = storage[chat_id]
    choices = pool[:]
    if last in choices and len(choices) > 1:
        choices.remove(last)
    picked = random.choice(choices)
    storage[chat_id] = picked
    return picked

def pick_reaction_by_label(chat_id: int, label: str) -> str:
    pool = REACTIONS.get(label, REACTIONS["neutral"])
    return pick_from_pool_avoiding_repeat(chat_id, pool, last_used_reaction)

def pick_reply_by_label(chat_id: int, label: str, text: str) -> str:
    if should_roast(text, label):
        return pick_from_pool_avoiding_repeat(chat_id, LIGHT_ROAST_REPLIES, last_used_reply)

    pool = TEXT_REPLIES.get(label, TEXT_REPLIES["neutral"])
    return pick_from_pool_avoiding_repeat(chat_id, pool, last_used_reply)

def score_with_rules(text: str, context_messages):
    t = clean_text(text)
    joined = " ".join(context_messages[-4:]).lower()
    scores = {label: 0.0 for label in CANDIDATE_LABELS}

    for label, patterns in PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, t):
                scores[label] += 1.4

    if t.endswith("?"):
        scores["question"] += 1.2

    if len(t) <= 3:
        scores["neutral"] += 0.8

    if any(x in t for x in ["ахах", "хаха", "лол", "ору"]):
        scores["funny"] += 1.5

    if any(x in t for x in ["капец", "пипец", "жесть"]):
        scores["shock"] += 0.8
        scores["anger"] += 0.3

    if any(x in t for x in ["имба", "кайф", "топ", "сильно"]):
        scores["hype"] += 0.7
        scores["love"] += 0.4

    if any(x in joined for x in ["ахах", "лол", "ору"]):
        scores["funny"] += 0.2

    if all(v == 0 for v in scores.values()):
        scores["neutral"] = 1.0

    best = max(scores, key=scores.get)
    confidence = scores[best]
    return best, confidence, scores

def build_ai_input(text: str, context_messages):
    recent = list(context_messages)[-3:]
    if not recent:
        return text
    context_part = "\n".join(recent)
    return f"Контекст:\n{context_part}\n\nНовое сообщение:\n{text}"

async def classify_with_hf(text: str):
    if not USE_AI_CLASSIFICATION or not HF_API_TOKEN:
        return None

    url = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"
    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": text,
        "parameters": {
            "candidate_labels": CANDIDATE_LABELS,
            "multi_label": False
        }
    }

    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print("HF API error:", resp.status, body[:300])
                    return None
                data = await resp.json()

        labels = data.get("labels", [])
        scores = data.get("scores", [])
        if not labels or not scores:
            return None

        return labels[0], float(scores[0])

    except Exception as e:
        print("HF classify error:", e)
        return None

def is_greeting_for_bot(text: str, mentioned: bool) -> bool:
    if not mentioned:
        return False
    t = clean_text(text)
    return any(word in t for word in GREETING_WORDS)

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
        chance *= 0.7

    return random.random() < min(chance, 1.0)

def should_send_text(chat_id: int, text: str, mentioned: bool, label: str) -> bool:
    now = int(time.time())
    hour = time.localtime(now).tm_hour
    refresh_hour_bucket(chat_id)

    state = chat_state[chat_id]

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

    chance = MENTION_REPLY_CHANCE if mentioned else TEXT_REPLY_CHANCE
    if label in {"funny", "shock", "question", "hype", "agreement", "disagreement"}:
        chance += 0.12

    chance += recent_activity_bonus(chat_id)

    if hour in QUIET_HOURS:
        chance *= 0.6

    return random.random() < min(chance, 1.0)

def generate_init_message():
    start = random.choice(INIT_START)
    core = random.choice(INIT_CORE)
    end = random.choice(INIT_END)

    if random.random() < 0.5:
        text = f"{start}, {core}"
    else:
        text = core

    if end and random.random() < 0.5:
        text = f"{text} {end}"

    if random.random() < 0.15:
        text += " 💀"

    return text

async def human_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

async def send_reaction(event, emoji: str):
    try:
        await human_delay()
        await client(functions.messages.SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.id,
            big=random.random() < 0.45,
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

async def send_init_message(chat_id: int):
    try:
        text = generate_init_message()
        await client.send_message(chat_id, text)
        recent_bot_texts[chat_id].append(text)
        mark_text_sent(chat_id)
        mark_init_sent(chat_id)
        print(f"Sent initiative text '{text}' to chat {chat_id}")

    except FloodWaitError as e:
        print(f"FloodWait on init message: sleeping for {e.seconds} seconds")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print(f"ERROR while sending init message: {e}")

async def inactivity_loop():
    while True:
        try:
            await asyncio.sleep(INACTIVITY_CHECK_INTERVAL)
            if not ENABLE_INIT_MESSAGES:
                continue

            now = time.time()
            current_hour = time.localtime(now).tm_hour

            for chat_id, last_time in list(last_message_time.items()):
                if current_hour in QUIET_HOURS:
                    continue

                silent_for = now - last_time
                if silent_for < INACTIVITY_TRIGGER:
                    continue

                if now - chat_state[chat_id]["last_init_at"] < INIT_MIN_GAP:
                    continue

                if random.random() > INIT_MESSAGE_CHANCE:
                    continue

                await send_init_message(chat_id)
                last_message_time[chat_id] = time.time()

        except Exception as e:
            print("Inactivity loop error:", e)

# =========================================================
# MAIN HANDLER
# =========================================================
@client.on(events.NewMessage(incoming=True))
async def handle_new_message(event):
    try:
        if not event.message:
            return

        if event.out:
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

        if contains_blacklisted(cleaned):
            last_message_time[chat_id] = time.time()
            recent_messages[chat_id].append(cleaned)
            return

        last_message_time[chat_id] = time.time()
        recent_messages[chat_id].append(cleaned)

        mentioned = any(name and name.lower() in cleaned for name in BOT_NAME_HINTS)
        context_messages = list(recent_messages[chat_id])

        # 1) локальная классификация
        rule_label, rule_confidence, _ = score_with_rules(text, context_messages)
        final_label = rule_label
        final_confidence = rule_confidence

        # 2) AI-классификация только если сообщение чуть сложнее
        use_ai_now = (
            USE_AI_CLASSIFICATION
            and HF_API_TOKEN
            and (
                rule_confidence < 1.5
                or len(text) > 18
                or text.endswith("?")
            )
        )

        if use_ai_now:
            ai_input = build_ai_input(text, context_messages)
            ai_result = await classify_with_hf(ai_input)
            if ai_result:
                ai_label, ai_score = ai_result
                if ai_score >= 0.45:
                    final_label = ai_label
                    final_confidence = ai_score

        # 3) реакция
        if ENABLE_REACTIONS and should_send_reaction(chat_id, text):
            emoji = pick_reaction_by_label(chat_id, final_label)
            await send_reaction(event, emoji)

        # 4) текстовый ответ
        if ENABLE_TEXT_REPLIES and should_send_text(chat_id, text, mentioned, final_label):
            reply = pick_reply_by_label(chat_id, final_label, text)
            await send_text(event, reply)

        print(json.dumps({
            "chat_id": chat_id,
            "text": text,
            "label": final_label,
            "confidence": round(float(final_confidence), 3),
            "mentioned": mentioned
        }, ensure_ascii=False))

    except Exception as e:
        print(f"HANDLER ERROR: {e}")

# =========================================================
# RUN LOOP
# =========================================================
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

            if ENABLE_INIT_MESSAGES:
                asyncio.create_task(inactivity_loop())

            print("Userbot started and listening for new messages...")
            await client.run_until_disconnected()

        except Exception as e:
            print(f"MAIN ERROR: {e}")

        print("Restarting in 5 seconds...")
        await asyncio.sleep(5)

# =========================================================
# START
# =========================================================
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(run_bot_forever())