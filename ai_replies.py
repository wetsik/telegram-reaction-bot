import json

import aiohttp

from settings import ENABLE_OPENAI_REPLIES, OPENAI_API_KEY, OPENAI_MODEL


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_NOT_CONFIGURED_REPLY = "openai не настроен: нет OPENAI_API_KEY"
OPENAI_EMPTY_REPLY = "openai вернул пустой ответ"


def _clean_reply(text: str) -> str:
    text = " ".join(text.strip().split())
    if not text:
        return ""

    if len(text) > 120:
        text = text[:117].rstrip() + "..."

    return text.strip("\"' ")


async def generate_context_reply(
    *,
    text: str,
    context_messages: list[str],
    label: str,
    mentioned: bool,
) -> str | None:
    if not ENABLE_OPENAI_REPLIES or not OPENAI_API_KEY:
        return OPENAI_NOT_CONFIGURED_REPLY

    recent = context_messages[-6:]
    context = "\n".join(f"- {message}" for message in recent if message.strip())

    system_prompt = (
        "You are a funny casual Telegram group regular, not an assistant. "
        "Reply in the same language as the chat, usually Russian. "
        "Sound like a real person: chill, playful, sarcastic, sometimes toxic, with natural slang. "
        "Prefer short reactions, jokes, roasts, light insults, and conversational one-liners. "
        "Maximum 10 words. Often 2-6 words is best. "
        "Never explain, teach, summarize, give detailed advice, or sound helpful/corporate. "
        "Do not mention being an AI, bot, model, or assistant. "
        "No markdown, hashtags, quotes, or formal punctuation. "
        "Do not be cruel, hateful, sexual, threatening, or target protected traits. "
        "Make toxicity contextual: roast the message, take, or situation, not identity. "
        "If a sharp tease fits, keep it low-stakes and funny. "
        "If directly mentioned, always reply. "
        "If not mentioned and there is no funny or natural reply, return an empty string."
    )
    user_prompt = (
        f"Recent chat messages:\n{context}\n\n"
        f"New message:\n{text}\n\n"
        f"Detected mood: {label}\n"
        f"Bot was mentioned: {mentioned}\n\n"
        "Write one short slangy chat reply. If mentioned, do not return empty."
    )

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_completion_tokens": 48,
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
                    return f"openai ошибка {response.status}: {raw[:160]}"

        try:
            data = json.loads(raw)
        except Exception as parse_error:
            print(f"OpenAI reply JSON parse error: {repr(parse_error)} | body={raw[:500]}")
            return f"openai json сломался: {type(parse_error).__name__}"

        choices = data.get("choices") or []
        if not choices:
            return "openai не вернул choices"

        message = choices[0].get("message") or {}
        reply = _clean_reply(message.get("content") or "")
        return reply or OPENAI_EMPTY_REPLY

    except Exception as error:
        print(f"OpenAI reply failed: {type(error).__name__}: {repr(error)}")
        return f"openai упал: {type(error).__name__}"
