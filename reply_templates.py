import random

from group_data import TEXT_REPLIES


def _clean_reply(text: str) -> str:
    return " ".join((text or "").strip().split())


def _detect_label(text: str) -> str:
    normalized = (text or "").lower()
    if any(word in normalized for word in ("?", "почему", "как", "что", "кто", "где", "когда", "зачем", "разве")):
        return "question"
    if any(word in normalized for word in ("ахах", "хаха", "лол", "ржу", "шут", "прикол", "lol", "lmao", "xD")):
        return "funny"
    if any(word in normalized for word in ("жесть", "мощно", "топ", "огонь", "база", "разнос", "легенда")):
        return "hype"
    if any(word in normalized for word in ("привет", "здарова", "салам", "hello", "hi", "hey", "yo", "ку")):
        return "greeting"
    if any(word in normalized for word in ("неа", "не факт", "сомнитель", "вряд", "спорно", "не думаю", "не соглаш")):
        return "disagreement"
    if any(word in normalized for word in ("согл", "реал", "именно", "в точку", "факт", "да, ", "конечно", "верно")):
        return "agreement"
    if any(word in normalized for word in ("ничего себе", "вот это", "капе", "шок", "неожидан", "wtf", "omg")):
        return "shock"
    if any(word in normalized for word in ("груст", "жалк", "обидн", "печаль", "тяжело", "сочув")):
        return "sad"
    if any(word in normalized for word in ("люби", "мил", "кайф", "❤️", "love", "тепло")):
        return "love"
    if any(word in normalized for word in ("бесит", "злит", "злой", "ненавиж", "раздраж", "rage")):
        return "anger"
    return "neutral"


def _pick_reply(label: str, text: str) -> str:
    bank = TEXT_REPLIES.get(label)
    if not bank:
        bank = TEXT_REPLIES["neutral"]

    reply = random.choice(bank)

    if label == "question" and "?" in (text or "") and random.random() < 0.3:
        reply = f"{reply}, если по-простому"
    elif label == "neutral" and random.random() < 0.15:
        reply = random.choice(TEXT_REPLIES["observation"])
    elif label in {"hype", "agreement"} and random.random() < 0.2:
        reply = random.choice(TEXT_REPLIES["practical"])
    elif label in {"sad", "anger"} and random.random() < 0.2:
        reply = random.choice(TEXT_REPLIES["deep"])

    return _clean_reply(reply)


def choose_delivery_mode(*, text: str, label: str, mentioned: bool, direct_address: bool) -> str | None:
    if direct_address or mentioned:
        return "reply"
    if _detect_label(text) == "funny" and random.random() < 0.45:
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
        if detected == "neutral" and random.random() > 0.07:
            return None
        if detected in {"question", "agreement", "disagreement", "hype"} and random.random() > 0.28:
            return None
        if detected in {"funny", "shock", "sad", "love", "anger", "greeting"} and random.random() > 0.18:
            return None

    return _pick_reply(detected, text)


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
