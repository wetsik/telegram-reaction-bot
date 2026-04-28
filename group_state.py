import time
from collections import defaultdict, deque

from settings import RECENT_BOT_TEXTS_LIMIT, RECENT_MSGS_LIMIT, USER_MEMORY_LIMIT


recent_messages = defaultdict(lambda: deque(maxlen=RECENT_MSGS_LIMIT))
recent_bot_texts = defaultdict(lambda: deque(maxlen=RECENT_BOT_TEXTS_LIMIT))
user_memory_by_chat = defaultdict(dict)
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


def get_sender_display_name(sender) -> str:
    if not sender:
        return "unknown"

    username = getattr(sender, "username", None)
    first_name = getattr(sender, "first_name", None)
    last_name = getattr(sender, "last_name", None)

    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    if full_name and username:
        return f"{full_name} (@{username})"
    if full_name:
        return full_name
    if username:
        return f"@{username}"

    sender_id = getattr(sender, "id", None)
    return f"user_{sender_id}" if sender_id else "unknown"


def remember_user_message(chat_id: int, sender, text: str) -> str:
    sender_id = getattr(sender, "id", None)
    if sender_id is None:
        return "unknown"

    display_name = get_sender_display_name(sender)
    users = user_memory_by_chat[chat_id]
    profile = users.setdefault(sender_id, {
        "name": display_name,
        "messages": deque(maxlen=USER_MEMORY_LIMIT),
        "last_seen_at": 0,
    })

    profile["name"] = display_name
    profile["last_seen_at"] = int(time.time())
    if text:
        profile["messages"].append(text)

    return display_name


def build_chat_memory(chat_id: int, limit: int = 6) -> str:
    users = sorted(
        user_memory_by_chat[chat_id].values(),
        key=lambda item: item.get("last_seen_at", 0),
        reverse=True,
    )

    lines = []
    for profile in users[:limit]:
        messages = list(profile["messages"])[-3:]
        if messages:
            lines.append(f"{profile['name']}: {' | '.join(messages)}")

    return "\n".join(lines)
