from __future__ import annotations

import random
import re


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


SHORT_BANKS = {
    "greeting": ["йо", "привет", "ку", "на связи"],
    "question": ["не факт", "зависит", "возможно", "не уверен"],
    "agreement": ["согласен", "да", "точно", "база"],
    "disagreement": ["неа", "сомнительно", "вряд ли", "не факт"],
    "funny": ["ахах", "жёстко", "ору", "ну да"],
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

    bank = SHORT_BANKS.get(detected, SHORT_BANKS["neutral"])
    recent_set = {_clean_reply(item).lower() for item in (recent_bot_texts or []) if item}
    choices = [item for item in bank if item.lower() not in recent_set] or bank
    reply = random.choice(choices)

    if speaker_name and detected == "greeting" and random.random() < 0.15:
        reply = f"{speaker_name}, {reply}"

    reply = _clean_reply(reply)
    if len(reply) > 18:
        reply = reply[:18].rstrip()
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
