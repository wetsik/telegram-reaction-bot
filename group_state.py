import time
from collections import defaultdict, deque

from settings import RECENT_BOT_TEXTS_LIMIT, RECENT_MSGS_LIMIT


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
