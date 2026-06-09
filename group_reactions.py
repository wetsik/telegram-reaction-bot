import asyncio
import random
import re
import time
from collections import defaultdict

from telethon import functions, types
from telethon.errors import FloodWaitError

from emotions import detect_emotion, detect_label
from group_data import BLACKLIST_CONTAINS, GREETING_WORDS, REACTIONS, SAFE_EMOJIS
from group_state import build_chat_memory, chat_state, recent_bot_texts, recent_messages, remember_user_message
from message_db import popular_emojis, save_message
from reply_templates import choose_delivery_mode, describe_image_for_chat, generate_context_reply
from settings import (
    BOT_NAME,
    BOT_NAME_HINTS,
    CHAT_EMOJI_CHANCE,
    ENABLE_MESSAGE_DB,
    ENABLE_REACTIONS,
    ENABLE_TEXT_REPLIES,
    MAX_DELAY,
    MESSAGE_SAVE_CHANCE,
    MIN_DELAY,
)


client = None
message_counts: dict[int, int] = defaultdict(int)
reaction_state_by_chat: dict[int, dict[str, int]] = defaultdict(
    lambda: {"next_reaction_at": random.randint(3, 8), "burst_remaining": 0}
)
available_reaction_emojis: list[str] = list(dict.fromkeys(SAFE_EMOJIS))

REACTION_GAP_MIN = 3
REACTION_GAP_MAX = 8
REACTION_BURST_CHANCE = 0.28
REACTION_BURST_EXTRA_MIN = 1
REACTION_BURST_EXTRA_MAX = 2


def _spontaneous_reply_chance(label: str) -> float:
    if label == "question":
        return 0.35
    if label in {"funny", "hype", "greeting", "shock", "agreement"}:
        return 0.28
    if label in {"disagreement", "sad", "love", "anger"}:
        return 0.24
    return 0.20


def configure_group_services(telegram_client):
    global client
    client = telegram_client


def _normalize_reaction_emoji(emoji: str) -> str:
    return (emoji or "").replace("\ufe0f", "").strip()


def _refresh_available_reaction_emojis(emojis: list[str]) -> None:
    global available_reaction_emojis
    cleaned = []
    seen = set()
    for emoji in emojis:
        normalized = _normalize_reaction_emoji(emoji)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    if cleaned:
        available_reaction_emojis = cleaned


async def load_available_reactions(telegram_client) -> int:
    """Глобальный список валидных реакций Telegram. В отличие от GetTopReactions,
    обычно доступен и бот-аккаунтам. Гарантирует, что мы шлём только настоящие
    реакции (а не любой эмодзи) — это убирает 'Invalid reaction provided'."""
    try:
        result = await telegram_client(functions.messages.GetAvailableReactionsRequest(hash=0))
        reactions = getattr(result, "reactions", None) or []
        emojis: list[str] = []
        for reaction in reactions:
            if getattr(reaction, "inactive", False):
                continue
            emoticon = getattr(reaction, "reaction", None)
            emoticon = getattr(emoticon, "emoticon", None) or getattr(reaction, "emoticon", None)
            if emoticon:
                emojis.append(emoticon)
        _refresh_available_reaction_emojis(emojis)
        print(f"Loaded {len(available_reaction_emojis)} available reactions from Telegram")
        return len(available_reaction_emojis)
    except Exception as error:
        print(f"Available reactions load failed: {type(error).__name__}: {error}")
        return len(available_reaction_emojis)


async def load_top_reactions(telegram_client, limit: int = 100) -> int:
    try:
        result = await telegram_client(functions.messages.GetTopReactionsRequest(limit=limit, hash=0))
        reactions = getattr(result, "reactions", None) or []
        emojis: list[str] = []
        for reaction in reactions:
            if isinstance(reaction, types.ReactionEmoji):
                emojis.append(reaction.emoticon)
        _refresh_available_reaction_emojis(emojis)
        print(f"Loaded {len(available_reaction_emojis)} top reactions from Telegram")
        return len(available_reaction_emojis)
    except Exception as error:
        print(f"Top reactions load failed: {type(error).__name__}: {error}")
        return len(available_reaction_emojis)


def sync_bot_identity(me):
    if me.username:
        BOT_NAME_HINTS.append(me.username.lower())
    if me.first_name:
        BOT_NAME_HINTS.append(me.first_name.lower())
    BOT_NAME_HINTS[:] = list(dict.fromkeys(BOT_NAME_HINTS))


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def contains_blacklisted(text: str) -> bool:
    lowered = clean_text(text)
    return any(item in lowered for item in BLACKLIST_CONTAINS)


def get_image_mime_type(event) -> str | None:
    message = getattr(event, "message", None)
    if not message:
        return None
    if getattr(message, "photo", None):
        return "image/jpeg"
    document = getattr(message, "document", None)
    mime = (getattr(document, "mime_type", "") or "").lower() if document else ""
    if mime in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        return mime
    return None


def is_animated_sticker(event) -> bool:
    document = getattr(getattr(event, "message", None), "document", None)
    if not document:
        return False
    mime = (getattr(document, "mime_type", "") or "").lower()
    for attribute in getattr(document, "attributes", []):
        if getattr(attribute, "stickerset", None) and mime in {"application/x-tgsticker", "video/webm"}:
            return True
    return False


async def describe_message_media(event) -> str | None:
    if is_animated_sticker(event):
        return "стикер"

    mime_type = get_image_mime_type(event)
    if not mime_type:
        return None

    try:
        media_bytes = await event.message.download_media(file=bytes)
        if not media_bytes:
            return None
        return await describe_image_for_chat(media_bytes, mime_type)
    except Exception as error:
        print(f"Media description failed: {type(error).__name__}: {repr(error)}")
        return None


def is_greeting_for_bot(text: str, mentioned: bool) -> bool:
    if not mentioned:
        return False
    return any(word in clean_text(text) for word in GREETING_WORDS)


def pick_reaction_by_label(label: str) -> str:
    pool = REACTIONS.get(label) or REACTIONS.get("neutral") or SAFE_EMOJIS
    # prefer context emojis that Telegram actually allows in this account
    allowed = [
        emoji for emoji in pool
        if _normalize_reaction_emoji(emoji) in available_reaction_emojis
    ]
    if allowed:
        return random.choice(allowed)
    if pool:
        return random.choice(pool)
    return random.choice(available_reaction_emojis or SAFE_EMOJIS)


ALL_REACTIONS = object()  # сентинел: чат разрешает все реакции
allowed_reactions_by_chat: dict[int, object] = {}


async def get_allowed_reactions(event):
    """Что разрешает конкретный чат: ALL_REACTIONS / множество эмодзи / set()
    (реакции выключены). Результат кешируется по чату."""
    chat_id = event.chat_id
    if chat_id in allowed_reactions_by_chat:
        return allowed_reactions_by_chat[chat_id]

    result: object = ALL_REACTIONS
    try:
        if not event.is_private:
            entity = await event.get_chat()
            if isinstance(entity, types.Channel):
                full = await client(functions.channels.GetFullChannelRequest(entity))
            else:
                full = await client(functions.messages.GetFullChatRequest(chat_id=entity.id))
            avail = getattr(getattr(full, "full_chat", None), "available_reactions", None)
            if isinstance(avail, types.ChatReactionsSome):
                result = {
                    _normalize_reaction_emoji(r.emoticon)
                    for r in avail.reactions
                    if isinstance(r, types.ReactionEmoji)
                }
            elif isinstance(avail, types.ChatReactionsNone):
                result = set()
            # ChatReactionsAll или поле отсутствует -> ALL_REACTIONS
    except Exception as error:
        print(f"Allowed reactions fetch failed: {type(error).__name__}: {error}")
        result = ALL_REACTIONS

    allowed_reactions_by_chat[chat_id] = result
    return result


async def choose_reaction(event, label: str) -> str | None:
    """Выбирает эмодзи под контекст/стиль чата и СТРОГО из разрешённых в чате,
    чтобы не словить 'Invalid reaction provided'. None — если реагировать нельзя."""
    chat_id = event.chat_id
    allowed = await get_allowed_reactions(event)
    if allowed is not ALL_REACTIONS and not allowed:
        return None  # реакции в чате выключены — даже не пытаемся

    # Предпочтительный набор: иногда в стиле чата (из БД), иначе по настроению.
    pool: list[str] = []
    if ENABLE_MESSAGE_DB and random.random() < CHAT_EMOJI_CHANCE:
        pool = [_normalize_reaction_emoji(e) for e in await popular_emojis(chat_id, limit=10)]
    if not pool:
        base = REACTIONS.get(label) or REACTIONS.get("neutral") or SAFE_EMOJIS
        pool = [_normalize_reaction_emoji(e) for e in base]

    if allowed is ALL_REACTIONS:
        # чат разрешает всё — оставляем только настоящие реакции Telegram
        candidates = [e for e in pool if e in available_reaction_emojis] or [
            e for e in available_reaction_emojis if e in pool
        ]
        if not candidates:
            candidates = list(available_reaction_emojis) or list(SAFE_EMOJIS)
    else:
        # чат разрешает только конкретный список
        candidates = [e for e in pool if e in allowed] or list(allowed)

    return random.choice(candidates) if candidates else None


def _schedule_next_reaction(state: dict[str, int], current_count: int) -> None:
    state["next_reaction_at"] = current_count + random.randint(REACTION_GAP_MIN, REACTION_GAP_MAX)


def _maybe_start_burst(state: dict[str, int]) -> None:
    if random.random() < REACTION_BURST_CHANCE:
        state["burst_remaining"] = random.randint(
            REACTION_BURST_EXTRA_MIN,
            REACTION_BURST_EXTRA_MAX,
        )
    else:
        state["burst_remaining"] = 0


async def human_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


async def send_reaction(event, emoji: str, label: str):
    try:
        emoji = _normalize_reaction_emoji(emoji)
        if emoji not in available_reaction_emojis:
            emoji = random.choice(available_reaction_emojis or SAFE_EMOJIS)
        await human_delay()
        await client(
            functions.messages.SendReactionRequest(
                peer=event.chat_id,
                msg_id=event.id,
                big=random.random() < 0.35,
                add_to_recent=True,
                reaction=[types.ReactionEmoji(emoticon=emoji)],
            )
        )
        print(f"Reacted {emoji} to message {event.id} in chat {event.chat_id}")
    except FloodWaitError as e:
        print(f"FloodWait on reaction: sleeping for {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        if "Invalid reaction provided" in str(e):
            bad_emoji = _normalize_reaction_emoji(emoji)
            if bad_emoji in available_reaction_emojis and len(available_reaction_emojis) > 1:
                available_reaction_emojis.remove(bad_emoji)
                replacement = random.choice(available_reaction_emojis or SAFE_EMOJIS)
                try:
                    await client(
                        functions.messages.SendReactionRequest(
                            peer=event.chat_id,
                            msg_id=event.id,
                            big=random.random() < 0.35,
                            add_to_recent=True,
                            reaction=[types.ReactionEmoji(emoticon=replacement)],
                        )
                    )
                    print(f"Reacted {replacement} to message {event.id} in chat {event.chat_id}")
                    return
                except Exception as retry_error:
                    print(f"ERROR while reacting: {retry_error}")
                    return
        print(f"ERROR while reacting: {e}")


async def send_text(event, text: str, reply_mode: str = "reply"):
    try:
        await human_delay()
        if reply_mode == "message":
            await client.send_message(event.chat_id, text)
        else:
            try:
                await event.reply(text)
            except Exception:
                await client.send_message(event.chat_id, text)
        recent_bot_texts[event.chat_id].append(text)
        print(f"Sent text '{text}' to chat {event.chat_id}")
    except FloodWaitError as e:
        print(f"FloodWait on text: sleeping for {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"ERROR while sending text: {e}")


async def handle_group_message(event):
    if event.out:
        return

    text = event.raw_text or ""
    sender = await event.get_sender()
    me = await client.get_me()

    if sender and me and getattr(sender, "id", None) == me.id:
        return

    chat_id = event.chat_id
    cleaned = clean_text(text)
    media_description = await describe_message_media(event)
    if media_description:
        cleaned = clean_text(f"{cleaned} [media: {media_description}]") if cleaned else f"[media: {media_description}]"

    if not cleaned:
        return

    if contains_blacklisted(cleaned):
        return

    message_counts[chat_id] += 1
    reaction_state = reaction_state_by_chat[chat_id]
    label = detect_label(cleaned)  # дешёвый детект по словам; ИИ — ниже, если нужен
    speaker_name = remember_user_message(chat_id, sender, cleaned)
    recent_messages[chat_id].append(f"{speaker_name}: {cleaned}")

    # Сохраняем случайный реальный текст человека (как есть, с эмодзи) в БД,
    # чтобы бот учился стилю чата и переиспользовал фразы.
    if ENABLE_MESSAGE_DB and text.strip() and random.random() < MESSAGE_SAVE_CHANCE:
        await save_message(chat_id, speaker_name, text.strip(), label)

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

    mentioned = bool(event.is_private or reply_to_bot or any(name and name in cleaned for name in BOT_NAME_HINTS))

    should_react = False
    if ENABLE_REACTIONS:
        if reaction_state["burst_remaining"] > 0:
            should_react = True
            reaction_state["burst_remaining"] -= 1
            if reaction_state["burst_remaining"] == 0:
                _schedule_next_reaction(reaction_state, message_counts[chat_id])
        elif message_counts[chat_id] >= reaction_state["next_reaction_at"]:
            should_react = True
            _maybe_start_burst(reaction_state)
            _schedule_next_reaction(reaction_state, message_counts[chat_id])

    # Решение об ответе считаем заранее, чтобы знать, нужна ли точная эмоция.
    should_reply = False
    if ENABLE_TEXT_REPLIES:
        should_reply = bool(reply_to_bot)
        if not should_reply:
            base_chance = _spontaneous_reply_chance(label)
            last_text_at = chat_state[chat_id]["last_text_at"]
            if last_text_at and (time.time() - last_text_at) > 300:
                base_chance += 0.08

            if message_counts[chat_id] >= 4 and message_counts[chat_id] % random.randint(3, 5) == 0:
                should_reply = True
            else:
                should_reply = random.random() < base_chance

    # Уточняем эмоцию моделью (по смыслу) только когда ставим реакцию — там
    # эмоция выбирает эмодзи. Для ответа это не нужно: сам ответ генерит ИИ,
    # который и так понимает смысл, поэтому второй вызов модели не делаем.
    if should_react:
        label = await detect_emotion(cleaned)

    if should_react:
        emoji = await choose_reaction(event, label)
        if emoji:
            await send_reaction(event, emoji, label)

    if not should_reply:
        return

    reply = await generate_context_reply(
        text=text,
        context_messages=list(recent_messages[chat_id]),
        chat_memory=build_chat_memory(chat_id),
        speaker_name=speaker_name,
        bot_names=[BOT_NAME, *BOT_NAME_HINTS],
        label=label,
        chat_id=chat_id,
        mentioned=mentioned,
        recent_bot_texts=list(recent_bot_texts[chat_id]),
    )
    if not reply:
        return

    reply_mode = choose_delivery_mode(
        text=text,
        label=label,
        mentioned=bool(reply_to_bot),
        direct_address=bool(reply_to_bot),
    )
    if reply_mode is None:
        return

    await send_text(event, reply, reply_mode=reply_mode)
