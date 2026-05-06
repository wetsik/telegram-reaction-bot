from __future__ import annotations

import random
import re
from collections import Counter


STOPWORDS = {
    "и",
    "в",
    "во",
    "на",
    "но",
    "а",
    "к",
    "ко",
    "по",
    "из",
    "у",
    "за",
    "от",
    "до",
    "про",
    "что",
    "как",
    "почему",
    "зачем",
    "когда",
    "где",
    "кто",
    "это",
    "тут",
    "там",
    "тоже",
    "если",
    "или",
    "да",
    "нет",
    "ну",
    "же",
    "ли",
    "не",
    "ни",
    "то",
    "те",
    "мы",
    "вы",
    "он",
    "она",
    "они",
    "я",
    "ты",
    "мой",
    "твой",
    "его",
    "ее",
    "их",
}


def _clean_reply(text: str) -> str:
    return " ".join((text or "").strip().split())


def _detect_label(text: str) -> str:
    normalized = (text or "").lower()
    if any(word in normalized for word in ("?", "почему", "как", "что", "кто", "где", "когда", "зачем", "разве")):
        return "question"
    if any(word in normalized for word in ("ахах", "хаха", "лол", "ржу", "шут", "прикол", "lol", "lmao", "xd")):
        return "funny"
    if any(word in normalized for word in ("жесть", "мощно", "топ", "огонь", "база", "разнос", "легенда")):
        return "hype"
    if any(word in normalized for word in ("неа", "не факт", "сомнитель", "вряд", "спорно", "не думаю", "не соглаш")):
        return "disagreement"
    if any(word in normalized for word in ("согл", "реал", "именно", "в точку", "факт", "конечно", "верно")):
        return "agreement"
    if any(word in normalized for word in ("ничего себе", "шок", "неожидан", "wtf", "omg", "чего")):
        return "shock"
    if any(word in normalized for word in ("груст", "жалк", "обидн", "печаль", "тяжело", "сочув")):
        return "sad"
    if any(word in normalized for word in ("люби", "мил", "кайф", "❤️", "love", "тепло")):
        return "love"
    if any(word in normalized for word in ("бесит", "злит", "злой", "ненавиж", "раздраж", "rage")):
        return "anger"
    if any(word in normalized for word in ("привет", "здарова", "здравствуй", "салам", "ку", "hello", "hi", "hey", "yo")):
        return "greeting"
    return "neutral"


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zа-яё0-9]{3,}", (text or "").lower())
    return [word for word in words if word not in STOPWORDS]


def _extract_topic(*texts: str) -> str | None:
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(_tokenize(text))
    if not counter:
        return None

    topic, count = counter.most_common(1)[0]
    if count < 2 and len(topic) < 4:
        return None
    return topic


def _choose_short(bank: list[str], recent_replies: list[str] | None = None) -> str:
    if not bank:
        return ""

    recent_set = {_clean_reply(item).lower() for item in (recent_replies or []) if item}
    candidates = [item for item in bank if _clean_reply(item).lower() not in recent_set]
    pool = candidates or bank
    return random.choice(pool)


def _format_short_reply(label: str, topic: str | None, base: str) -> str:
    if not topic:
        return base

    if label == "question":
        return random.choice(
            [
                f"{base} про {topic}",
                f"{base}, если про {topic}",
                f"{base} на {topic}",
            ]
        )
    if label in {"agreement", "hype"}:
        return random.choice(
            [
                f"{base}, {topic} да",
                f"{base} по {topic}",
                f"{base} и всё",
            ]
        )
    if label in {"disagreement", "sad", "anger"}:
        return random.choice(
            [
                f"{base}, {topic} спорно",
                f"{base} по {topic}",
                f"{base} и ладно",
            ]
        )
    if label == "neutral":
        return random.choice(
            [
                f"{base} про {topic}",
                f"{base}, {topic} кстати",
                f"{base} и всё",
            ]
        )
    return base


SHORT_BANKS = {
    "greeting": ["йо", "привет", "ку", "да, на связи"],
    "question": ["не факт", "зависит", "не уверен", "тут сложнее", "возможно"],
    "agreement": ["согласен", "да", "точно", "база", "в точку"],
    "disagreement": ["неа", "сомнительно", "вряд ли", "не факт"],
    "funny": ["ахах", "жёстко", "ну да", "ору"],
    "shock": ["ого", "жесть", "ничего себе"],
    "hype": ["топ", "огонь", "жёстко", "база"],
    "sad": ["жаль", "обидно", "держись"],
    "love": ["мило", "кайф", "тепло"],
    "anger": ["жесть", "да уж", "бесит"],
    "neutral": ["понятно", "ладно", "бывает", "норм", "окей"],
}


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
    recent_bot_texts: list[str] | None = None,
) -> str | None:
    detected = label if label and label != "neutral" else _detect_label(text)

    if not mentioned:
        if detected == "neutral" and random.random() > 0.07:
            return None
        if detected in {"question", "agreement", "disagreement", "hype"} and random.random() > 0.28:
            return None
        if detected in {"funny", "shock", "sad", "love", "anger", "greeting"} and random.random() > 0.18:
            return None

    base = _choose_short(SHORT_BANKS.get(detected, SHORT_BANKS["neutral"]), recent_bot_texts)
    topic = _extract_topic(text, chat_memory, *(context_messages[-3:] if context_messages else []))
    reply = _format_short_reply(detected, topic, base)

    if speaker_name and detected == "greeting" and random.random() < 0.2:
        reply = f"{speaker_name}, {reply}"

    reply = _clean_reply(reply)
    if len(reply) > 32:
        reply = reply[:32].rstrip()
    return reply


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
