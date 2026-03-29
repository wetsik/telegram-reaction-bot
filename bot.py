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

# твой сдвиг по времени (Узбекистан = +5)
TZ_OFFSET = int(os.environ.get("TZ_OFFSET", "5"))

# задержка перед реакцией / ответом
MIN_DELAY = float(os.environ.get("MIN_DELAY", "0.25"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "0.9"))

# частота действий
REACTION_CHANCE = float(os.environ.get("REACTION_CHANCE", "0.98"))
TEXT_REPLY_CHANCE = float(os.environ.get("TEXT_REPLY_CHANCE", "0.55"))
MENTION_REPLY_CHANCE = float(os.environ.get("MENTION_REPLY_CHANCE", "8"))

# лимиты
TEXT_COOLDOWN = int(os.environ.get("TEXT_COOLDOWN", "20"))
REACTION_COOLDOWN = int(os.environ.get("REACTION_COOLDOWN", "0"))

MAX_TEXTS_PER_HOUR = int(os.environ.get("MAX_TEXTS_PER_HOUR", "40"))
MAX_REACTIONS_PER_HOUR = int(os.environ.get("MAX_REACTIONS_PER_HOUR", "160"))

# память
RECENT_MSGS_LIMIT = int(os.environ.get("RECENT_MSGS_LIMIT", "35"))
RECENT_BOT_TEXTS_LIMIT = int(os.environ.get("RECENT_BOT_TEXTS_LIMIT", "12"))
MAX_CONTEXT = int(os.environ.get("MAX_CONTEXT", "8"))

# инициативные сообщения
ENABLE_INIT_MESSAGES = os.environ.get("ENABLE_INIT_MESSAGES", "true").lower() == "true"

# для теста можно поставить 30 / 5 / 1.0 / 60
INACTIVITY_TRIGGER = int(os.environ.get("INACTIVITY_TRIGGER", "1200"))  # 20 минут
INACTIVITY_CHECK_INTERVAL = int(os.environ.get("INACTIVITY_CHECK_INTERVAL", "60"))
INIT_MESSAGE_CHANCE = float(os.environ.get("INIT_MESSAGE_CHANCE", "0.35"))
INIT_MIN_GAP = int(os.environ.get("INIT_MIN_GAP", "3600"))  # 1 час

# писать инициативные сообщения только в личку
TEST_INIT_PRIVATE_ONLY = os.environ.get("TEST_INIT_PRIVATE_ONLY", "false").lower() == "false"

# AI-классификация
USE_AI_CLASSIFICATION = os.environ.get("USE_AI_CLASSIFICATION", "true").lower() == "true"

# общие
ENABLE_REACTIONS = True
ENABLE_TEXT_REPLIES = True
MIN_TEXT_LEN = 1
QUIET_HOURS = set()
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
    def _send_ok(self, body: bool = False):
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
# TIME / ACTIVITY
# =========================================================
def get_local_hour() -> int:
    return (time.localtime().tm_hour + TZ_OFFSET) % 24


def get_activity_multiplier(hour: int | None = None) -> float:
    if hour is None:
        hour = get_local_hour()

    # глубокая ночь
    if 1 <= hour <= 6:
        return 0.05

    # утро
    if 7 <= hour <= 11:
        return 0.45

    # день
    if 12 <= hour <= 18:
        return 0.75

    # вечер
    if 19 <= hour <= 23:
        return 1.0

    # 00:00
    return 0.25


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

reaction_memory_by_chat = defaultdict(lambda: {
    "allowed": set(),
    "blocked": set(),
})

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
        r"\bфакт\b", r"\bименно\b", r"\btrue\b", r"\breal\b",
        r"\bв точку\b"
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
        r"\bужас\b", r"\bвыбесил\b", r"\bгорит\b", r"\bбред\b"
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

SAFE_EMOJIS = [
    "👍", "👎", "❤️", "🔥", "🥰",
    "👏", "😁", "🤔", "🤯", "😱",
    "😢", "😡", "🤩", "🤮", "💩",
    "🙏", "👌", "🤡", "🎉", "🥳",
    "💯", "⚡", "🏆", "💔", "🤨",
    "😐", "💋", "😈", "😴", "😭",
    "🤓", "👻", "👀", "🙈", "😇",
    "😨", "🤝", "🤗", "🗿", "🆒",
    "😂", "🤣", "💀", "😎"
]

REACTIONS = {
    "funny": ["😂", "🤣", "💀", "😁"],
    "shock": ["😱", "👀", "🤯", "🔥"],
    "hype": ["🔥", "💯", "⚡", "🏆", "🗿"],
    "sad": ["😢", "💔", "😭"],
    "love": ["❤️", "🥰", "💋"],
    "anger": ["😡", "🤨", "💀"],
    "question": ["🤔", "👀", "😐", "🗿"],
    "agreement": ["💯", "🔥", "👍", "🗿"],
    "disagreement": ["🤨", "👎", "😐", "🤔", "🤡"],
    "greeting": ["😎", "❤️", "👍", "🔥"],
    "neutral": ["👀", "🗿", "🔥", "👍", "😐"]
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
        "мда...",
        "понятно",
        "котенька масюня"
    ]
}

LIGHT_ROAST_REPLIES = [
    "ты серьёзно щас?",
    "брат ты чего",
    "ну ты выдал",
    "не ты гонишь",
    "хорош уже",
    "ну это мощный тейк",
    "ты прикалываешься?",
    "сильное заявление конечно",
    "ну ты и персонаж",
    "логика вышла из чата",
    "это было смело",
    "интересная логика конечно"
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
    "или я что то пропустил",
    "алло",
    "ау",
    "непонятно",
    "мне одному скучно",
    "кто нибудь проснулся?",
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

    return random.random() < 0.18


def pick_from_pool_avoiding_repeat(chat_id: int, pool: list[str], storage: dict) -> str:
    if not pool:
        return "👍"

    last = storage[chat_id]
    choices = pool[:]

    if last in choices and len(choices) > 1:
        choices.remove(last)

    picked = random.choice(choices)
    storage[chat_id] = picked
    return picked


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

    if scores["funny"] > 0 and any(x in joined for x in ["ахах", "лол", "ору"]):
        scores["funny"] += 0.2

    best = max(scores.values())
    if best < 1.0:
        scores["neutral"] = max(scores["neutral"], 1.0)

    best_label = max(scores, key=scores.get)
    confidence = scores[best_label]
    return best_label, confidence, scores


def build_ai_input(text: str, context_messages):
    recent = list(context_messages)[-3:]
    if not recent:
        return text

    context_part = "\n".join(recent)
    return f"Контекст:\n{context_part}\n\nНовое сообщение:\n{text}"


async def classify_with_hf(text: str):
    if not USE_AI_CLASSIFICATION or not HF_API_TOKEN:
        return None

    url = "https://router.huggingface.co/hf-inference/models/facebook/bart-large-mnli"
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
        timeout = aiohttp.ClientTimeout(total=20, connect=10, sock_read=20)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                raw_text = await resp.text()

                if resp.status != 200:
                    print(f"HF API error: status={resp.status}, body={raw_text[:500]}")
                    return None

                try:
                    data = json.loads(raw_text)
                except Exception as parse_error:
                    print(f"HF JSON parse error: {repr(parse_error)} | body={raw_text[:500]}")
                    return None

        if isinstance(data, dict):
            labels = data.get("labels", [])
            scores = data.get("scores", [])
            if labels and scores:
                return labels[0], float(scores[0])

        if isinstance(data, list) and data and isinstance(data[0], dict):
            if "label" in data[0] and "score" in data[0]:
                best_item = max(data, key=lambda x: float(x.get("score", 0)))
                return best_item["label"], float(best_item["score"])

            first = data[0]
            labels = first.get("labels", [])
            scores = first.get("scores", [])
            if labels and scores:
                return labels[0], float(scores[0])

        print(f"HF unexpected response format: type={type(data).__name__}, data={str(data)[:500]}")
        return None

    except asyncio.TimeoutError as e:
        print(f"HF classify timeout: {repr(e)}")
        return None

    except aiohttp.ClientError as e:
        print(f"HF classify client error: {repr(e)}")
        return None

    except Exception as e:
        print(f"HF classify error: {type(e).__name__}: {repr(e)}")
        return None


def is_greeting_for_bot(text: str, mentioned: bool) -> bool:
    if not mentioned:
        return False

    t = clean_text(text)
    return any(word in t for word in GREETING_WORDS)


def should_send_reaction(chat_id: int, text: str) -> bool:
    now = int(time.time())
    hour = get_local_hour()
    refresh_hour_bucket(chat_id)

    state = chat_state[chat_id]

    if now - state["last_reaction_at"] < REACTION_COOLDOWN:
        return False

    if state["reactions_in_last_hour"] >= MAX_REACTIONS_PER_HOUR:
        return False

    if len(text.strip()) < 1:
        return False

    chance = REACTION_CHANCE + recent_activity_bonus(chat_id)

    # живой режим: ночью чуть менее активен
    chance *= (0.65 + 0.35 * get_activity_multiplier(hour))

    return random.random() < min(chance, 1.0)


def should_send_text(chat_id: int, text: str, mentioned: bool, label: str) -> bool:
    now = int(time.time())
    hour = get_local_hour()
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

    # живой режим: текст ночью заметно реже
    chance *= (0.75 + 0.25 * get_activity_multiplier(hour))

    return random.random() < min(chance, 1.0)


def generate_init_message() -> str:
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


def build_reaction_candidates(chat_id: int, label: str, preferred_emoji: str | None):
    memory = reaction_memory_by_chat[chat_id]
    allowed = memory["allowed"]
    blocked = memory["blocked"]

    category_pool = REACTIONS.get(label, REACTIONS["neutral"])

    allowed_category = [e for e in category_pool if e in allowed and e not in blocked]
    unknown_category = [e for e in category_pool if e not in allowed and e not in blocked]

    allowed_fallback = [e for e in SAFE_EMOJIS if e in allowed and e not in blocked and e not in allowed_category]
    unknown_fallback = [e for e in SAFE_EMOJIS if e not in allowed and e not in blocked and e not in unknown_category]

    random.shuffle(allowed_category)
    random.shuffle(unknown_category)
    random.shuffle(allowed_fallback)
    random.shuffle(unknown_fallback)

    candidates = []

    if preferred_emoji and preferred_emoji not in blocked:
        candidates.append(preferred_emoji)

    for emoji in unknown_category:
        if emoji not in candidates:
            candidates.append(emoji)

    for emoji in allowed_category:
        if emoji not in candidates:
            candidates.append(emoji)

    for emoji in unknown_fallback:
        if emoji not in candidates:
            candidates.append(emoji)

    for emoji in allowed_fallback:
        if emoji not in candidates:
            candidates.append(emoji)

    if not candidates:
        candidates = ["👍", "🔥", "👀"]

    return candidates


def pick_reaction_by_label(chat_id: int, label: str) -> str:
    category_pool = REACTIONS.get(label, REACTIONS["neutral"])
    memory = reaction_memory_by_chat[chat_id]
    allowed = memory["allowed"]
    blocked = memory["blocked"]

    allowed_category = [e for e in category_pool if e in allowed and e not in blocked]
    unknown_category = [e for e in category_pool if e not in allowed and e not in blocked]

    if unknown_category and random.random() < 0.80:
        return pick_from_pool_avoiding_repeat(chat_id, unknown_category, last_used_reaction)

    if allowed_category:
        return pick_from_pool_avoiding_repeat(chat_id, allowed_category, last_used_reaction)

    if unknown_category:
        return pick_from_pool_avoiding_repeat(chat_id, unknown_category, last_used_reaction)

    fallback_pool = [e for e in SAFE_EMOJIS if e not in blocked]
    return pick_from_pool_avoiding_repeat(chat_id, fallback_pool, last_used_reaction)


async def human_delay():
    base = random.uniform(MIN_DELAY, MAX_DELAY)

    hour = get_local_hour()
    if 1 <= hour <= 6:
        base *= 2.0
    elif 7 <= hour <= 11:
        base *= 1.25

    await asyncio.sleep(base)


async def send_reaction(event, emoji: str, label: str):
    chat_id = event.chat_id
    memory = reaction_memory_by_chat[chat_id]
    candidates = build_reaction_candidates(chat_id, label, emoji)

    try:
        await human_delay()

        for candidate in candidates:
            try:
                await client(functions.messages.SendReactionRequest(
                    peer=chat_id,
                    msg_id=event.id,
                    big=random.random() < 0.45,
                    add_to_recent=True,
                    reaction=[types.ReactionEmoji(emoticon=candidate)]
                ))

                memory["allowed"].add(candidate)
                mark_reaction_sent(chat_id)
                print(f"Reacted {candidate} to message {event.id} in chat {chat_id}")
                return

            except FloodWaitError:
                raise

            except Exception as inner_error:
                memory["blocked"].add(candidate)
                print(f"Reaction {candidate} failed in chat {chat_id}: {inner_error}")
                continue

        print(f"Skipping reaction for message {event.id} in chat {chat_id}: no valid emoji worked")

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
            hour = get_local_hour()
            activity_multiplier = get_activity_multiplier(hour)

            for chat_id, last_time in list(last_message_time.items()):
                # только личка для теста
                if TEST_INIT_PRIVATE_ONLY and chat_id < 0:
                    continue

                silent_for = now - last_time
                if silent_for < INACTIVITY_TRIGGER:
                    continue

                if now - chat_state[chat_id]["last_init_at"] < INIT_MIN_GAP:
                    continue

                final_chance = INIT_MESSAGE_CHANCE * activity_multiplier
                roll = random.random()

                print(
                    f"INIT CHECK | chat={chat_id} | hour={hour} | "
                    f"silent_for={int(silent_for)} | "
                    f"activity={activity_multiplier} | "
                    f"chance={round(final_chance, 3)} | roll={round(roll, 3)}"
                )

                if roll > final_chance:
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

        rule_label, rule_confidence, _ = score_with_rules(text, context_messages)
        final_label = rule_label
        final_confidence = rule_confidence

        use_ai_now = (
            USE_AI_CLASSIFICATION
            and bool(HF_API_TOKEN)
            and len(text.strip()) >= 20
            and len(text.split()) >= 4
            and (
                rule_confidence < 1.2
                or len(text) > 35
                or (
                    "но" in cleaned
                    or "хотя" in cleaned
                    or "зато" in cleaned
                    or "если" in cleaned
                    or "потому" in cleaned
                    or "либо" in cleaned
                )
            )
        )

        if use_ai_now:
            ai_input = build_ai_input(text, context_messages)
            ai_result = await classify_with_hf(ai_input)
            if ai_result:
                ai_label, ai_score = ai_result
                if ai_score >= 0.60:
                    final_label = ai_label
                    final_confidence = ai_score

        if ENABLE_REACTIONS and should_send_reaction(chat_id, text):
            emoji = pick_reaction_by_label(chat_id, final_label)
            await send_reaction(event, emoji, final_label)

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
    inactivity_task = None

    while True:
        try:
            print("Starting Telegram client...")
            await client.start()

            me = await client.get_me()
            print(f"Logged in as: {me.first_name} (@{me.username})")
            print("TZ_OFFSET =", TZ_OFFSET)
            print("LOCAL_HOUR =", get_local_hour())
            print("ENABLE_INIT_MESSAGES =", ENABLE_INIT_MESSAGES)
            print("INACTIVITY_TRIGGER =", INACTIVITY_TRIGGER)
            print("INACTIVITY_CHECK_INTERVAL =", INACTIVITY_CHECK_INTERVAL)
            print("INIT_MESSAGE_CHANCE =", INIT_MESSAGE_CHANCE)
            print("INIT_MIN_GAP =", INIT_MIN_GAP)
            print("TEST_INIT_PRIVATE_ONLY =", TEST_INIT_PRIVATE_ONLY)

            if me.username:
                BOT_NAME_HINTS.append(me.username.lower())
            if me.first_name:
                BOT_NAME_HINTS.append(me.first_name.lower())

            BOT_NAME_HINTS[:] = list(dict.fromkeys(BOT_NAME_HINTS))

            if ENABLE_INIT_MESSAGES and (inactivity_task is None or inactivity_task.done()):
                inactivity_task = asyncio.create_task(inactivity_loop())

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