import random

from group_data import GREETING_WORDS, TEXT_REPLIES


def _clean_reply(text: str) -> str:
    return " ".join((text or "").strip().split())


def _pick_reply(label: str) -> str:
    bank = TEXT_REPLIES.get(label) or TEXT_REPLIES["neutral"]
    return _clean_reply(random.choice(bank))


def _detect_label(text: str) -> str:
    normalized = (text or "").lower()
    if any(word in normalized for word in ("?", "почему", "как", "что", "кто", "где", "когда")):
        return "question"
    if any(word in normalized for word in ("ахах", "лол", "ржу", "шут", "прикол", "lol", "lmao")):
        return "funny"
    if any(word in normalized for word in ("жесть", "мощно", "топ", "огонь", "база", "🔥")):
        return "hype"
    if any(word in normalized for word in ("привет", "здарова", "салам", "hello", "hi", "hey", "yo")):
        return "greeting"
    return "neutral"


def choose_delivery_mode(*, text: str, label: str, mentioned: bool, direct_address: bool) -> str | None:
    if direct_address or mentioned:
        return "reply"
    if _detect_label(text) == "funny" and random.random() < 0.5:
        return "message"
    return "reply"


async def generate_context_reply(
    *,
    text: str,
    context_messages: list[str],
    chat_memory: str,
    speaker_name: str,
    bot_names: list[str],
    label: str,
    mentioned: bool,
) -> str | None:
    detected = label if label and label != "neutral" else _detect_label(text)

    if not mentioned:
        if detected == "neutral" and random.random() > 0.08:
            return None
        if detected != "neutral" and random.random() > 0.35:
            return None

    return _pick_reply(detected)


async def describe_image_for_chat(image_bytes: bytes, mime_type: str) -> str | None:
    if mime_type.startswith("image/"):
        return "изображение"
    return None


async def should_join_context(
    *,
    text: str,
    context_messages: list[str],
    chat_memory: str,
    speaker_name: str,
    bot_names: list[str],
    label: str,
) -> bool:
    return False
