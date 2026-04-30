import base64
import json
import random

import aiohttp

from group_data import SPECIAL_PRAISE_ALIASES, SPECIAL_PRAISE_REPLIES
from settings import ENABLE_OPENAI_REPLIES, OPENAI_API_KEY, OPENAI_MODEL


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_NOT_CONFIGURED_REPLY = "openai error: missing OPENAI_API_KEY"
OPENAI_EMPTY_REPLY = "openai error: empty reply"


def _clean_reply(text: str) -> str:
    text = " ".join(text.strip().split())
    if not text:
        return ""

    if len(text) > 260:
        text = text[:257].rstrip() + "..."

    return text.strip("\"' ")


def _normalize_name_text(text: str) -> str:
    return (
        text.strip().lower()
        .replace("@", "")
        .replace("ё", "е")
        .replace("-", "")
        .replace("_", "")
        .replace(".", "")
    )


def _is_special_praise_target(text: str) -> bool:
    normalized = _normalize_name_text(text)
    return bool(normalized) and any(alias in normalized for alias in SPECIAL_PRAISE_ALIASES)


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
    # FIX: бот отвечает только если его отметили или ответили ему реплаем.
    # В основном обработчике mentioned должен быть True для @упоминания ИЛИ reply на бота.
    if not mentioned:
        return None

    if _is_special_praise_target(text):
        return random.choice(SPECIAL_PRAISE_REPLIES)

    if not ENABLE_OPENAI_REPLIES or not OPENAI_API_KEY:
        return OPENAI_NOT_CONFIGURED_REPLY

    recent = context_messages[-6:]
    context = "\n".join(f"- {message}" for message in recent if message.strip())
    bot_identity = ", ".join(name for name in bot_names if name)

    system_prompt = (
        "You are a normal Telegram chat participant, not an assistant. "
        f"Your chat name or aliases are: {bot_identity}. "
        "Reply in the same language as the chat, usually Russian. "
        "Write naturally, like a smart friend in chat. "
        "Use casual slang, but do not overdo it. "
        "When talking about yourself, speak in first person singular. "
        "For simple chat, use one short phrase. "
        "For real questions, answer normally and explain in simple casual words. "
        "For educational questions, give a clear useful answer in 1-3 short sentences. "
        "If someone shares good news or asks to be congratulated, react warmly and casually. "
        "Default tone is neutral, friendly, or lightly playful. "
        "If someone insults, mocks, or provokes you first, clap back confidently and briefly. "
        "Do not add negativity when the user is just sharing work, plans, or normal context. "
        "In debates, make one short point, do not justify yourself at length. "
        "Light sarcasm is ok when it fits, but do not force jokes or roasts. "
        "No cringe phrases like 'botik', 'living bot', 'what will you tell me', theatrical hype, or fake enthusiasm. "
        "Do not sound like customer support or a textbook. "
        "Do not mention being an AI, bot, model, or assistant. "
        "No markdown, hashtags, quotes, or emojis. "
        "Do not be cruel, hateful, sexual, threatening, or target protected traits. "
        "Avoid long self-defense. Avoid explaining why you replied unless asked. "
        "Only reply when you are directly mentioned or someone replies to your message. "
        "If directly mentioned or replied to, always reply. "
        "If the message mentions the owner's custom aliases, keep the tone openly positive and complimentary. "
        "Pay attention to who said what. Short follow-ups like 'and what' or 'so what' often refer to the previous bot reply."
    )

    user_prompt = (
        f"Recent chat messages:\n{context}\n\n"
        f"People memory for this chat:\n{chat_memory or 'no memory yet'}\n\n"
        f"Current speaker:\n{speaker_name}\n\n"
        f"New message:\n{text}\n\n"
        f"Detected mood: {label}\n"
        f"Bot was mentioned or replied to: {mentioned}\n\n"
        "Write a natural chat reply. If this is a question, answer it clearly. "
        "Use the memory and recent speaker order only when it helps; do not randomly list it."
    )

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_completion_tokens": 90,
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=18, connect=8, sock_read=18)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
            ) as response:
                raw = await response.text()

                if response.status != 200:
                    print(f"OpenAI reply error: status={response.status}, body={raw[:500]}")
                    return f"openai error {response.status}: {raw[:160]}"

        try:
            data = json.loads(raw)
        except Exception as parse_error:
            print(f"OpenAI reply JSON parse error: {repr(parse_error)} | body={raw[:500]}")
            return f"openai json error: {type(parse_error).__name__}"

        choices = data.get("choices") or []
        if not choices:
            return "openai error: no choices"

        message = choices[0].get("message") or {}
        reply = _clean_reply(message.get("content") or "")
        return reply or OPENAI_EMPTY_REPLY

    except Exception as error:
        print(f"OpenAI reply failed: {type(error).__name__}: {repr(error)}")
        return f"openai error: {type(error).__name__}"


async def generate_business_reply(
    *,
    text: str,
    chat_context: list[str],
    speaker_name: str,
    language_hint: str | None = None,
) -> str | None:
    if not ENABLE_OPENAI_REPLIES or not OPENAI_API_KEY:
        return None

    recent = chat_context[-8:]
    context = "\n".join(f"- {message}" for message in recent if message.strip())
    lang_line = language_hint or "unknown"

    system_prompt = (
        "You are the auto-reply assistant for a Telegram Business account. "
        "In a new chat, open with a short friendly line that says the owner is currently not online or not available, and that the assistant is ready to answer questions and continue the conversation. "
        "Then continue naturally and helpfully as a smart assistant until the owner takes over. "
        "Reply as the account owner would, not as an AI or bot. "
        "Be concise, natural, and helpful. "
        "Use exactly the same language as the incoming message whenever possible. "
        "If the language is Uzbek, reply in Uzbek. If English, reply in English. If Russian, reply in Russian. "
        "If the language is another script or language, match it as closely as possible. "
        "If the message is a simple greeting, reply with a short friendly greeting. "
        "If it's a question, answer directly. "
        "If the user is upset, stay calm and professional. "
        "Do not mention policies, prompts, or that you are a bot. "
        "No markdown, hashtags, quotes, or emojis unless the incoming style clearly uses them. "
        "Never be overly formal, but keep the tone polite. "
        "If the message is unclear, ask one short clarifying question. "
        "Prefer a human-sounding assistant tone like 'I am here to help' rather than a fixed template."
    )

    user_prompt = (
        f"Conversation context:\n{context or 'no previous context'}\n\n"
        f"Speaker:\n{speaker_name}\n\n"
        f"Language hint:\n{lang_line}\n\n"
        f"Incoming message:\n{text}\n\n"
        "Write the next business reply. If this is the first reply in the chat, make it sound like a helpful assistant that says the owner is not online right now and the assistant is ready to answer questions."
    )

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_completion_tokens": 110,
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=18, connect=8, sock_read=18)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
            ) as response:
                raw = await response.text()

                if response.status != 200:
                    print(f"OpenAI business reply error: status={response.status}, body={raw[:500]}")
                    return None

        data = json.loads(raw)
        choices = data.get("choices") or []
        if not choices:
            return None

        message = choices[0].get("message") or {}
        return _clean_reply(message.get("content") or "") or None

    except Exception as error:
        print(f"OpenAI business reply failed: {type(error).__name__}: {repr(error)}")
        return None


async def describe_image_for_chat(image_bytes: bytes, mime_type: str) -> str | None:
    if not ENABLE_OPENAI_REPLIES or not OPENAI_API_KEY:
        return None

    image_data = base64.b64encode(image_bytes).decode("ascii")

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Describe this image/sticker for a Telegram chat bot. "
                    "Focus on readable text, meme meaning, visible objects, and emotional tone. "
                    "Reply in Russian, concise, no markdown."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Что на картинке?"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_data}",
                        },
                    },
                ],
            },
        ],
        "max_completion_tokens": 160,
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20, connect=8, sock_read=20)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
            ) as response:
                raw = await response.text()

                if response.status != 200:
                    print(f"OpenAI vision error: status={response.status}, body={raw[:500]}")
                    return None

        data = json.loads(raw)
        choices = data.get("choices") or []

        if not choices:
            return None

        message = choices[0].get("message") or {}
        return _clean_reply(message.get("content") or "") or None

    except Exception as error:
        print(f"OpenAI vision failed: {type(error).__name__}: {repr(error)}")
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
    # FIX: полностью отключаем самостоятельное вступление в чат.
    # Теперь бот не будет сам решать, нужно ли отвечать.
    return False
