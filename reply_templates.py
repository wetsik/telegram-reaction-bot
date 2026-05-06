from __future__ import annotations

import random
import re
from collections import Counter

from mock_knowledge import SMART_DATABASE


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

QUESTION_HINTS = {
    "почему",
    "зачем",
    "как",
    "что",
    "кто",
    "где",
    "когда",
    "сколько",
    "куда",
    "откуда",
    "чем",
    "чё",
    "че",
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


def _choose_from_bank(bank: list[str], recent_replies: list[str] | None = None) -> str:
    if not bank:
        return ""

    recent_set = {_clean_reply(item).lower() for item in (recent_replies or []) if item}
    candidates = [item for item in bank if _clean_reply(item).lower() not in recent_set]
    pool = candidates or bank
    return random.choice(pool)


def _add_topic_phrase(base: str, topic: str | None, label: str, text: str) -> str:
    if not topic:
        return base

    if label == "question":
        templates = [
            f"если про {topic}, то тут важен контекст",
            f"по {topic} я бы не отвечал в лоб",
            f"если коротко про {topic}, то не всё так просто",
        ]
        if "?" in text or any(hint in text.lower() for hint in QUESTION_HINTS):
            return f"{random.choice(templates)}, {base}"
        return f"{base}, если смотреть на {topic}"

    if label in {"agreement", "hype"}:
        templates = [
            f"по {topic} это уже выглядит логично",
            f"{topic} тут реально решает",
            f"вокруг {topic} как раз и крутится смысл",
        ]
        return f"{base}. {random.choice(templates)}"

    if label in {"disagreement", "sad", "anger"}:
        templates = [
            f"с {topic} тут легко промахнуться",
            f"по {topic} лучше не торопиться с выводами",
            f"в {topic} как раз и прячется подвох",
        ]
        return f"{base}. {random.choice(templates)}"

    if label == "neutral":
        templates = [
            f"по {topic} это уже отдельный разговор",
            f"{topic} сам по себе многое меняет",
            f"в {topic} часто и сидит суть",
        ]
        if random.random() < 0.45:
            return f"{base}. {random.choice(templates)}"

    return base


def _smart_build_reply(
    *,
    label: str,
    text: str,
    context_messages: list[str],
    chat_memory: str,
    speaker_name: str,
    recent_bot_texts: list[str] | None = None,
) -> str:
    recent_context = context_messages[-5:]
    topic = _extract_topic(text, chat_memory, *recent_context)

    if label == "question":
        bank = SMART_DATABASE["explanation"]
        base = _choose_from_bank(bank, recent_bot_texts)
        if random.random() < 0.35:
            base = _choose_from_bank(SMART_DATABASE["practical"], recent_bot_texts)
    elif label == "agreement":
        base = _choose_from_bank(SMART_DATABASE["social"], recent_bot_texts)
    elif label == "disagreement":
        base = _choose_from_bank(SMART_DATABASE["deep"], recent_bot_texts)
    elif label == "funny":
        base = _choose_from_bank(
            [
                "ахах, норм вынесло",
                "тут уже почти стендап",
                "ну да, это сильно",
                "чату такое заходит",
            ],
            recent_bot_texts,
        )
    elif label == "shock":
        base = _choose_from_bank(SMART_DATABASE["social"], recent_bot_texts)
    elif label == "hype":
        base = _choose_from_bank(SMART_DATABASE["practical"], recent_bot_texts)
    elif label in {"sad", "anger", "love"}:
        base = _choose_from_bank(SMART_DATABASE["deep"], recent_bot_texts)
    elif label == "greeting":
        base = _choose_from_bank(
            [
                "йо",
                "привет",
                "ку",
                "да, я на связи",
                f"йо, {speaker_name}",
            ],
            recent_bot_texts,
        )
    else:
        base = _choose_from_bank(SMART_DATABASE["neutral"], recent_bot_texts)

    if label in {"question", "agreement", "disagreement", "hype", "neutral"}:
        base = _add_topic_phrase(base, topic, label, text)

    if label == "question" and random.random() < 0.4:
        base = f"{base}. {random.choice(SMART_DATABASE['deep'])}"
    elif label == "neutral" and random.random() < 0.25:
        base = f"{base}. {random.choice(SMART_DATABASE['social'])}"

    if speaker_name and label in {"greeting", "question"} and random.random() < 0.2:
        base = f"{speaker_name}, {base}"

    return _clean_reply(base)


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

    reply = _smart_build_reply(
        label=detected,
        text=text,
        context_messages=context_messages,
        chat_memory=chat_memory,
        speaker_name=speaker_name,
        recent_bot_texts=recent_bot_texts,
    )
    if not reply:
        return None
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
