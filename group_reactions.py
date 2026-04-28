import asyncio
import json
import random
import time

from telethon import functions, types
from telethon.errors import FloodWaitError

from ai_replies import generate_context_reply
from group_data import (
    BLACKLIST_CONTAINS,
    GREETING_WORDS,
    INIT_CORE,
    INIT_END,
    INIT_START,
    REACTIONS,
    SAFE_EMOJIS,
)
from group_state import (
    build_chat_memory,
    chat_state,
    last_message_time,
    last_used_reaction,
    mark_init_sent,
    mark_reaction_sent,
    mark_text_sent,
    remember_user_message,
    reaction_memory_by_chat,
    recent_bot_texts,
    recent_messages,
    refresh_hour_bucket,
)
from settings import (
    BOT_NAME,
    BOT_NAME_HINTS,
    ENABLE_INIT_MESSAGES,
    ENABLE_REACTIONS,
    ENABLE_TEXT_REPLIES,
    HF_API_TOKEN,
    INACTIVITY_CHECK_INTERVAL,
    INACTIVITY_TRIGGER,
    INIT_MESSAGE_CHANCE,
    INIT_MIN_GAP,
    MAX_REACTIONS_PER_HOUR,
    MAX_TEXTS_PER_HOUR,
    MENTION_REPLY_CHANCE,
    MIN_DELAY,
    MIN_TEXT_LEN,
    MAX_DELAY,
    REACTION_CHANCE,
    REACTION_COOLDOWN,
    TEST_INIT_PRIVATE_ONLY,
    TEXT_COOLDOWN,
    TEXT_REPLY_CHANCE,
    USE_AI_CLASSIFICATION,
)
from text_classifier import build_ai_input, classify_with_hf, clean_text, score_with_rules
from time_utils import get_activity_multiplier, get_local_hour


client = None

# Each chat gets a random reaction budget per message window.
# This keeps the bot lively without letting reactions become spammy.
# Most windows get 1-2 reactions, some get none, and only rare lively windows get 3-4.
REACTION_WINDOW_SIZE = 60
REACTION_BUDGET_WEIGHTS = ((0, 0.12), (1, 0.52), (2, 0.25), (3, 0.09), (4, 0.02))
REACTION_MIN_MESSAGES_GAP = 8
REACTION_MIN_TEXT_LEN = 4
REACTION_LABEL_CHANCE = {
    "funny": 0.95,
    "shock": 0.90,
    "hype": 0.86,
    "love": 0.80,
    "agreement": 0.55,
    "sad": 0.48,
    "anger": 0.38,
    "disagreement": 0.34,
    "question": 0.28,
    "greeting": 0.22,
    "neutral": 0.08,
}
reaction_windows = {}

TEXT_LABEL_CHANCE = {
    "funny": 0.36,
    "shock": 0.30,
    "question": 0.90,
    "hype": 0.28,
    "agreement": 0.18,
    "disagreement": 0.24,
    "anger": 0.20,
    "sad": 0.22,
    "love": 0.16,
    "greeting": 0.14,
    "neutral": 0.03,
}


def _pick_reaction_budget() -> int:
    budgets, weights = zip(*REACTION_BUDGET_WEIGHTS)
    return random.choices(budgets, weights=weights, k=1)[0]


def _pick_slots(budget: int, window_size: int) -> list[int]:
    if budget <= 0:
        return []

    return sorted(random.sample(range(1, window_size + 1), budget))


def _pick_reaction_slots(budget: int) -> list[int]:
    return _pick_slots(budget, REACTION_WINDOW_SIZE)


def _new_reaction_window() -> dict:
    budget = _pick_reaction_budget()
    return {
        "messages": 0,
        "sent": 0,
        "budget": budget,
        "slots": _pick_reaction_slots(budget),
        "last_sent_at_message": -REACTION_MIN_MESSAGES_GAP,
    }


def _advance_reaction_window(chat_id: int) -> dict:
    window = reaction_windows.setdefault(chat_id, _new_reaction_window())

    if window["messages"] >= REACTION_WINDOW_SIZE:
        window = _new_reaction_window()
        reaction_windows[chat_id] = window

    window["messages"] += 1
    return window


def _reaction_fit_score(text: str, label: str, confidence: float, mentioned: bool) -> float:
    stripped = text.strip()
    if len(stripped) < REACTION_MIN_TEXT_LEN:
        return 0.0

    word_count = len(stripped.split())
    if word_count <= 1 and len(stripped) < 7:
        return 0.0

    base = REACTION_LABEL_CHANCE.get(label, REACTION_LABEL_CHANCE["neutral"])

    if label == "neutral" and confidence <= 1.0 and len(stripped) < 25:
        return 0.0

    if confidence >= 1.4:
        base += 0.10
    elif confidence < 1.0:
        base *= 0.65

    if 8 <= len(stripped) <= 140:
        base += 0.05
    elif len(stripped) > 280:
        base *= 0.75

    if mentioned:
        base *= 0.65

    return max(0.0, min(base, 1.0))


def _text_fit_score(text: str, label: str, confidence: float, mentioned: bool) -> float:
    stripped = text.strip()
    if mentioned:
        return 1.0

    if len(stripped) < MIN_TEXT_LEN:
        return 0.0

    if len(stripped.split()) < 3 and not stripped.endswith("?"):
        return 0.0

    base = TEXT_LABEL_CHANCE.get(label, TEXT_LABEL_CHANCE["neutral"])

    if label == "neutral":
        return 0.0

    if confidence >= 1.4:
        base += 0.08
    elif confidence < 1.0:
        base *= 0.45

    if stripped.endswith("?"):
        base += 0.10

    if len(stripped) > 220:
        base *= 0.65

    return max(0.0, min(base, 1.0))


def configure_group_services(telegram_client):
    global client
    client = telegram_client


def sync_bot_identity(me):
    if me.username:
        BOT_NAME_HINTS.append(me.username.lower())
    if me.first_name:
        BOT_NAME_HINTS.append(me.first_name.lower())

    BOT_NAME_HINTS[:] = list(dict.fromkeys(BOT_NAME_HINTS))


def contains_blacklisted(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in BLACKLIST_CONTAINS)


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
    return ""


def is_greeting_for_bot(text: str, mentioned: bool) -> bool:
    if not mentioned:
        return False

    t = clean_text(text)
    return any(word in t for word in GREETING_WORDS)


def looks_like_question(text: str) -> bool:
    t = clean_text(text)
    if t.endswith("?"):
        return True

    question_words = (
        "как",
        "что",
        "чо",
        "че",
        "почему",
        "зачем",
        "когда",
        "где",
        "куда",
        "кто",
        "сколько",
        "какой",
        "какая",
        "какие",
        "можно",
        "надо",
    )
    words = set(t.replace(",", " ").replace(".", " ").split())
    return any(word in words for word in question_words)


def looks_like_followup(text: str) -> bool:
    t = clean_text(text)
    followups = {
        "и че",
        "и чо",
        "и что",
        "ну и",
        "дальше",
        "пон",
        "понял",
        "ясно",
        "ок",
        "ладно",
        "а дальше",
    }
    return t in followups or t.startswith(("и че ", "и чо ", "и что ", "а дальше "))


def looks_like_insult(text: str) -> bool:
    t = clean_text(text)
    insult_words = (
        "лох",
        "тупой",
        "тупая",
        "тупица",
        "долбаеб",
        "долбоеб",
        "дурак",
        "идиот",
        "кринж",
        "ботяра",
        "плохой бот",
        "говно",
        "хуйня",
        "слабый",
        "заткнись",
    )
    return any(word in t for word in insult_words)


def should_send_reaction(
    chat_id: int,
    text: str,
    label: str,
    confidence: float,
    mentioned: bool,
) -> bool:
    now = int(time.time())
    hour = get_local_hour()
    refresh_hour_bucket(chat_id)

    state = chat_state[chat_id]

    if len(text.strip()) < 1:
        return False

    window = _advance_reaction_window(chat_id)

    if window["sent"] >= window["budget"]:
        return False

    if window["messages"] - window["last_sent_at_message"] < REACTION_MIN_MESSAGES_GAP:
        return False

    next_slot = window["slots"][window["sent"]]
    if window["messages"] < next_slot:
        return False

    if now - state["last_reaction_at"] < REACTION_COOLDOWN:
        return False

    if state["reactions_in_last_hour"] >= MAX_REACTIONS_PER_HOUR:
        return False

    fit_score = _reaction_fit_score(text, label, confidence, mentioned)
    if fit_score <= 0:
        return False

    chance = REACTION_CHANCE * fit_score
    chance += recent_activity_bonus(chat_id)

    chance *= (0.65 + 0.35 * get_activity_multiplier(hour))

    return random.random() < min(chance, 1.0)


def should_send_text(
    chat_id: int,
    text: str,
    mentioned: bool,
    label: str,
    confidence: float,
) -> bool:
    now = int(time.time())
    hour = get_local_hour()
    refresh_hour_bucket(chat_id)

    state = chat_state[chat_id]

    if is_greeting_for_bot(text, mentioned):
        if now - state["last_text_at"] < 2:
            return False
        return True

    if mentioned:
        if now - state["last_text_at"] < 2:
            return False
        return True

    if state["texts_in_last_hour"] >= MAX_TEXTS_PER_HOUR:
        return False

    if TEXT_COOLDOWN > 0 and now - state["last_text_at"] < TEXT_COOLDOWN:
        return False

    if len(text.strip()) < MIN_TEXT_LEN and not mentioned:
        return False

    if (
        label == "question"
        or looks_like_question(text)
        or looks_like_followup(text)
        or looks_like_insult(text)
    ):
        if now - state["last_text_at"] < 2:
            return False
        return True

    fit_score = _text_fit_score(text, label, confidence, mentioned)
    if fit_score <= 0:
        return False

    chance = MENTION_REPLY_CHANCE if mentioned else TEXT_REPLY_CHANCE
    chance *= fit_score

    chance += recent_activity_bonus(chat_id)

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

    allowed_fallback = [
        e for e in SAFE_EMOJIS
        if e in allowed and e not in blocked and e not in allowed_category
    ]
    unknown_fallback = [
        e for e in SAFE_EMOJIS
        if e not in allowed and e not in blocked and e not in unknown_category
    ]

    random.shuffle(allowed_category)
    random.shuffle(unknown_category)
    random.shuffle(allowed_fallback)
    random.shuffle(unknown_fallback)

    candidates = []

    if preferred_emoji and preferred_emoji not in blocked:
        candidates.append(preferred_emoji)

    for emoji in unknown_category + allowed_category + unknown_fallback + allowed_fallback:
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

                window = reaction_windows.setdefault(chat_id, _new_reaction_window())
                window["sent"] += 1
                window["last_sent_at_message"] = window["messages"]

                print(
                    f"Reacted {candidate} to message {event.id} in chat {chat_id} | "
                    f"reaction_window={window['sent']}/{window['budget']} | "
                    f"message_in_window={window['messages']}/{REACTION_WINDOW_SIZE}"
                )
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
        recent_messages[event.chat_id].append(f"{BOT_NAME}: {clean_text(text)}")
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


async def handle_group_message(event):
    if event.out:
        return

    text = event.raw_text or ""
    sender = await event.get_sender()
    me = await client.get_me()

    if sender and me and getattr(sender, "id", None) == me.id:
        return

    if not text.strip():
        return

    chat_id = event.chat_id
    cleaned = clean_text(text)

    if contains_blacklisted(cleaned):
        last_message_time[chat_id] = time.time()
        recent_messages[chat_id].append(cleaned)
        return

    speaker_name = remember_user_message(chat_id, sender, cleaned)
    display_message = f"{speaker_name}: {cleaned}"

    last_message_time[chat_id] = time.time()
    recent_messages[chat_id].append(display_message)
    chat_memory = build_chat_memory(chat_id)

    reply_to_bot = False
    if event.is_reply:
        try:
            replied = await event.get_reply_message()
            reply_to_bot = bool(
                replied
                and (
                    getattr(replied, "sender_id", None) == getattr(me, "id", None)
                    or getattr(replied, "out", False)
                )
            )
        except Exception as reply_error:
            print(f"Reply context error: {reply_error}")

    is_private_chat = bool(event.is_private)
    mentioned = (
        is_private_chat
        or reply_to_bot
        or any(name and name.lower() in cleaned for name in BOT_NAME_HINTS)
    )
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

    if ENABLE_REACTIONS and should_send_reaction(
        chat_id,
        text,
        final_label,
        float(final_confidence),
        mentioned,
    ):
        emoji = pick_reaction_by_label(chat_id, final_label)
        await send_reaction(event, emoji, final_label)

    if ENABLE_TEXT_REPLIES and should_send_text(
        chat_id,
        text,
        mentioned,
        final_label,
        float(final_confidence),
    ):
        reply = await generate_context_reply(
            text=text,
            context_messages=context_messages,
            chat_memory=chat_memory,
            speaker_name=speaker_name,
            bot_names=[BOT_NAME, *BOT_NAME_HINTS],
            label=final_label,
            mentioned=mentioned,
        )
        if reply:
            await send_text(event, reply)

    print(json.dumps({
        "chat_id": chat_id,
        "text": text,
        "label": final_label,
        "confidence": round(float(final_confidence), 3),
        "mentioned": mentioned,
        "reaction_window": reaction_windows.get(chat_id),
    }, ensure_ascii=False))


def maybe_start_inactivity_loop(current_task):
    if ENABLE_INIT_MESSAGES and (current_task is None or current_task.done()):
        return asyncio.create_task(inactivity_loop())

    return current_task
