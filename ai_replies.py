import base64
import json

import aiohttp

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
        "If the chat is actively discussing something and your reaction fits, join the conversation like a person. "
        "In debates, make one short point, do not justify yourself at length. "
        "Sometimes respond even when you were not directly addressed, if it feels socially natural. "
        "Light sarcasm is ok when it fits, but do not force jokes or roasts. "
        "No cringe phrases like 'botik', 'living bot', 'what will you tell me', theatrical hype, or fake enthusiasm. "
        "Do not sound like customer support or a textbook. "
        "Do not mention being an AI, bot, model, or assistant. "
        "No markdown, hashtags, quotes, or emojis. "
        "Do not be cruel, hateful, sexual, threatening, or target protected traits. "
        "Avoid long self-defense. Avoid explaining why you replied unless asked. "
        "If directly mentioned, always reply. "
        "If not mentioned, join only when you have a natural reaction to the ongoing discussion. "
        "Pay attention to who said what. Short follow-ups like 'and what' or 'so what' often refer to the previous bot reply."
    )
    user_prompt = (
        f"Recent chat messages:\n{context}\n\n"
        f"People memory for this chat:\n{chat_memory or 'no memory yet'}\n\n"
        f"Current speaker:\n{speaker_name}\n\n"
        f"New message:\n{text}\n\n"
        f"Detected mood: {label}\n"
        f"Bot was mentioned: {mentioned}\n\n"
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
    if not ENABLE_OPENAI_REPLIES or not OPENAI_API_KEY:
        return False

    recent = context_messages[-8:]
    context = "\n".join(f"- {message}" for message in recent if message.strip())
    bot_identity = ", ".join(name for name in bot_names if name)

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Decide if a casual Telegram participant should reply now. "
                    f"The participant aliases are: {bot_identity}. "
                    "Return only YES or NO. "
                    "Say YES for direct questions, replies to the participant, good news, "
                    "clear insults/challenges, or active debates where the participant has a useful short line. "
                    "Do not join just to make a negative joke about someone's work or plans. "
                    "Say YES unprompted only when joining would feel clearly natural and not annoying. "
                    "Say NO for random background chatter where joining would feel forced."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Recent chat messages:\n{context}\n\n"
                    f"People memory:\n{chat_memory or 'no memory yet'}\n\n"
                    f"Current speaker:\n{speaker_name}\n"
                    f"New message:\n{text}\n"
                    f"Detected mood: {label}\n"
                ),
            },
        ],
        "max_completion_tokens": 4,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=8, connect=4, sock_read=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    raw = await response.text()
                    print(f"OpenAI join check error: status={response.status}, body={raw[:300]}")
                    return False
                data = await response.json()

        choices = data.get("choices") or []
        if not choices:
            return False

        answer = ((choices[0].get("message") or {}).get("content") or "").strip().upper()
        return answer.startswith("YES")

    except Exception as error:
        print(f"OpenAI join check failed: {type(error).__name__}: {repr(error)}")
        return False
