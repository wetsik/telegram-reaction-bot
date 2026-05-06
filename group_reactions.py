import asyncio
import random
import re
from collections import defaultdict

from telethon import functions, types
from telethon.errors import FloodWaitError

from group_data import BLACKLIST_CONTAINS, GREETING_WORDS, REACTIONS, SAFE_EMOJIS
from reply_templates import choose_delivery_mode, describe_image_for_chat, generate_context_reply
from settings import BOT_NAME, BOT_NAME_HINTS, ENABLE_REACTIONS, ENABLE_TEXT_REPLIES, MAX_DELAY, MIN_DELAY
from time_utils import get_local_hour as _get_local_hour


client = None
message_counts: dict[int, int] = defaultdict(int)


def configure_group_services(telegram_client):
    global client
    client = telegram_client


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


def detect_label(text: str) -> str:
    lowered = clean_text(text)
    if any(word in lowered for word in ("?", "почему", "как", "что", "кто", "где", "когда")):
        return "question"
    if any(word in lowered for word in ("ахах", "лол", "ржу", "шут", "прикол", "lol", "lmao")):
        return "funny"
    if any(word in lowered for word in ("жесть", "мощно", "топ", "огонь", "база", "🔥")):
        return "hype"
    if any(word in lowered for word in ("груст", "жалк", "обидн", "sad")):
        return "sad"
    if any(word in lowered for word in ("люби", "мил", "❤️", "love")):
        return "love"
    if any(word in lowered for word in ("злой", "бесит", "злит", "rage")):
        return "anger"
    if any(word in lowered for word in GREETING_WORDS):
        return "greeting"
    return "neutral"


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
    pool = REACTIONS.get(label) or REACTIONS["neutral"]
    return random.choice(pool or SAFE_EMOJIS)


async def human_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


async def send_reaction(event, emoji: str, label: str):
    try:
        await human_delay()
        await client(functions.messages.SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.id,
            big=random.random() < 0.35,
            add_to_recent=True,
            reaction=[types.ReactionEmoji(emoticon=emoji)]
        ))
        print(f"Reacted {emoji} to message {event.id} in chat {event.chat_id}")
    except FloodWaitError as e:
        print(f"FloodWait on reaction: sleeping for {e.seconds} seconds")
        await asyncio.sleep(e.seconds)
    except Exception as e:
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
    label = detect_label(cleaned)

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

    if ENABLE_REACTIONS and message_counts[chat_id] % 10 == 0:
        await send_reaction(event, pick_reaction_by_label(label), label)

    if not ENABLE_TEXT_REPLIES or not reply_to_bot:
        return

    reply = await generate_context_reply(
        text=text,
        context_messages=[],
        chat_memory="",
        speaker_name=getattr(sender, "first_name", None) or getattr(sender, "username", None) or "unknown",
        bot_names=[BOT_NAME, *BOT_NAME_HINTS],
        label=label,
        mentioned=mentioned,
    )
    if not reply:
        return

    reply_mode = choose_delivery_mode(
        text=text,
        label=label,
        mentioned=True,
        direct_address=True,
    )
    if reply_mode is None:
        return

    await send_text(event, reply, reply_mode=reply_mode)


def maybe_start_inactivity_loop(current_task):
    return current_task


def get_local_hour() -> int:
    return _get_local_hour()
