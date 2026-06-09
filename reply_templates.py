from __future__ import annotations

import random
import re

from ai_client import ask_westforge
from emotions import detect_label as _detect_label
from message_db import random_learned_reply
from settings import (
    AI_ALWAYS_WHEN_MENTIONED,
    AI_REPLY_CHANCE,
    ENABLE_AI_REPLIES,
    ENABLE_MESSAGE_DB,
    LEARNED_REPLY_CHANCE,
)


def _clean_reply(text: str) -> str:
    return " ".join((text or "").strip().split())


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
    "joy": ["кайф", "класс", "топ"],
    "gratitude": ["не за что", "обращайся", "всегда рад"],
    "curiosity": ["интересно", "а расскажи", "любопытно"],
    "sarcasm": ["ну да, конечно", "ага", "как скажешь"],
    "support": ["держись", "ты сможешь", "всё получится"],
    "pride": ["красава", "сила", "уважение"],
    "boredom": ["скучно", "ну такое", "вяло"],
    "fear": ["жутковато", "страшно", "ну его"],
    "celebration": ["поздравляю", "ура", "красава"],
    "cringe": ["ну это кринж", "жесть", "фу"],
    "cool": ["круто", "стильно", "найс"],
}


def choose_delivery_mode(*, text: str, label: str, mentioned: bool, direct_address: bool) -> str | None:
    if direct_address or mentioned:
        return "reply"
    if _detect_label(text) == "funny" and random.random() < 0.45:
        return "message"
    return "reply"


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U0000FE0F\U00002190-\U000021FF]"
)


def _strip_for_chat(text: str) -> str:
    """Make the model output look like a casual chat line: no quotes, no emoji,
    no markdown, single short phrase."""
    text = _EMOJI_RE.sub("", text or "")
    text = text.replace("*", "").replace("`", "").replace("#", "")
    text = " ".join(text.split())
    text = text.strip().strip("\"'«»“”").strip()
    # keep it to a single short line
    for sep in ("\n", ". ", "! ", "? "):
        if sep in text:
            head = text.split(sep)[0]
            if sep != "\n":
                head += sep.strip()
            text = head.strip()
            break
    if len(text) > 120:
        text = text[:117].rstrip() + "..."
    return text


_ECHO_MARKERS = (
    "твой короткий ответ",
    "новое сообщение от",
    "последние сообщения чата",
    "не ассистент",
    "telegram-чата",
    "без кавычек",
    "по-русски",
)


def _looks_like_prompt_echo(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _ECHO_MARKERS)


# qwen — китайская модель и иногда «уплывает» в иероглифы/кану/хангыль.
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def _has_bad_script(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _build_prompt(
    *,
    text: str,
    context_messages: list[str],
    speaker_name: str,
    bot_names: list[str],
) -> str:
    recent = [m for m in context_messages[-6:] if m.strip()]
    context = "\n".join(recent)
    bot_identity = ", ".join(name for name in bot_names if name) or "westik"

    parts = [
        f"Ты — {bot_identity}, свой парень в Telegram-чате. Не ассистент и не помощник.",
        "Пиши по-русски, коротко и по-простому, как пишут друзья в чате.",
        "Максимум 8 слов, обычно одна фраза. Можно с маленькой буквы и без точки в конце.",
        "Без вежливых форм (никаких 'пожалуйста', 'рекомендую', 'здравствуйте'), без официоза.",
        "Без эмодзи, без кавычек, без списков, без форматирования.",
        "Только русский язык. Никаких иероглифов и английских слов.",
        "Никогда не говори, что ты бот, ИИ, модель или помощник. Не предлагай помощь.",
        "Отвечай спокойно и по сути, не растекайся.",
    ]
    if context:
        parts.append(f"\nПоследние сообщения чата:\n{context}")
    parts.append(f"\nНовое сообщение от {speaker_name}: {text}")
    parts.append("\nТвой короткий ответ:")
    return "\n".join(parts)


async def generate_context_reply(
    *,
    text: str,
    context_messages: list[str],
    chat_memory: str,
    speaker_name: str,
    bot_names: list[str],
    label: str,
    mentioned: bool,
    chat_id: int | None = None,
    recent_bot_texts: list[str] | None = None,
) -> str | None:
    detected = label if label and label != "neutral" else _detect_label(text)
    recent_set = {_clean_reply(item).lower() for item in (recent_bot_texts or []) if item}

    # Решаем, тратить ли медленную модель на этот ответ. Прямое обращение —
    # всегда ИИ; спонтанный трёп — только с шансом AI_REPLY_CHANCE, иначе
    # лёгкий текст-помощник из шаблонов.
    use_ai = ENABLE_AI_REPLIES and (
        (mentioned and AI_ALWAYS_WHEN_MENTIONED) or random.random() < AI_REPLY_CHANCE
    )

    if use_ai:
        prompt = _build_prompt(
            text=text,
            context_messages=context_messages,
            speaker_name=speaker_name,
            bot_names=bot_names,
        )
        answer = await ask_westforge(prompt)
        if answer and not _looks_like_prompt_echo(answer) and not _has_bad_script(answer):
            cleaned = _strip_for_chat(answer)
            if cleaned and not _looks_like_prompt_echo(cleaned):
                return cleaned

    # «Выученная» фраза: реальный текст людей из этого чата (с эмодзи) —
    # делает бота своим в чате. Только когда не отвечаем через ИИ.
    if ENABLE_MESSAGE_DB and chat_id is not None and random.random() < LEARNED_REPLY_CHANCE:
        learned = await random_learned_reply(chat_id, label=detected, exclude=recent_set)
        if learned:
            return learned

    # Тексты-помощники: короткий шаблонный банк (когда ИИ выключен/не выпал по
    # шансу/недоступен/пустой ответ).
    bank = SHORT_BANKS.get(detected, SHORT_BANKS["neutral"])
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
