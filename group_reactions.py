import asyncio
import json
import random
import time

from telethon import functions, types
from telethon.errors import FloodWaitError

from group_data import (
    BLACKLIST_CONTAINS,
    GREETING_WORDS,
    INIT_CORE,
    INIT_END,
    INIT_START,
    LIGHT_ROAST_REPLIES,
    REACTIONS,
    SAFE_EMOJIS,
    TEXT_REPLIES,
)
from group_state import (
    chat_state,
    last_message_time,
    last_used_reaction,
    last_used_reply,
    mark_init_sent,
    mark_reaction_sent,
    mark_text_sent,
    reaction_memory_by_chat,
    recent_bot_texts,
    recent_messages,
    refresh_hour_bucket,
)
from settings import (
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
    if should_roast(text, label):
        return pick_from_pool_avoiding_repeat(chat_id, LIGHT_ROAST_REPLIES, last_used_reply)

    pool = TEXT_REPLIES.get(label, TEXT_REPLIES["neutral"])
    return pick_from_pool_avoiding_repeat(chat_id, pool, last_used_reply)


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

    allowed_category = [
        e for e in category_pool if e in allowed and e not in blocked]
    unknown_category = [
        e for e in category_pool if e not in allowed and e not in blocked]

    allowed_fallback = [
        e for e in SAFE_EMOJIS if e in allowed and e not in blocked and e not in allowed_category]
    unknown_fallback = [
        e for e in SAFE_EMOJIS if e not in allowed and e not in blocked and e not in unknown_category]

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

    allowed_category = [
        e for e in category_pool if e in allowed and e not in blocked]
    unknown_category = [
        e for e in category_pool if e not in allowed and e not in blocked]

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
                print(
                    f"Reacted {candidate} to message {event.id} in chat {chat_id}")
                return

            except FloodWaitError:
                raise

            except Exception as inner_error:
                memory["blocked"].add(candidate)
                print(
                    f"Reaction {candidate} failed in chat {chat_id}: {inner_error}")
                continue

        print(
            f"Skipping reaction for message {event.id} in chat {chat_id}: no valid emoji worked")

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
        "mentioned": mentioned,
    }, ensure_ascii=False))


def maybe_start_inactivity_loop(current_task):
    if ENABLE_INIT_MESSAGES and (current_task is None or current_task.done()):
        return asyncio.create_task(inactivity_loop())

    return current_task

