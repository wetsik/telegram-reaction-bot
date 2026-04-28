import json

import aiohttp

from settings import ENABLE_OPENAI_REPLIES, OPENAI_API_KEY, OPENAI_MODEL


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


def _clean_reply(text: str) -> str:
    text = " ".join(text.strip().split())
    if not text:
        return ""

    if len(text) > 160:
        text = text[:157].rstrip() + "..."

    return text.strip("\"' ")


async def generate_context_reply(
    *,
    text: str,
    context_messages: list[str],
    label: str,
    mentioned: bool,
) -> str | None:
    if not ENABLE_OPENAI_REPLIES or not OPENAI_API_KEY:
        return None

    recent = context_messages[-6:]
    context = "\n".join(f"- {message}" for message in recent if message.strip())

    developer_prompt = (
        "You write as a casual Telegram group participant. "
        "Reply in the same language as the chat, usually Russian. "
        "Be short: 1 sentence, maximum 14 words. "
        "Use natural slang only when it fits. "
        "Do not explain yourself. Do not mention that you are an AI or bot. "
        "Do not use quotes, hashtags, markdown, or emojis unless the chat clearly uses them. "
        "If there is nothing useful to say, return an empty string."
    )
    user_prompt = (
        f"Recent chat messages:\n{context}\n\n"
        f"New message:\n{text}\n\n"
        f"Detected mood: {label}\n"
        f"Bot was mentioned: {mentioned}\n\n"
        "Write one fitting reply."
    )

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "developer", "content": developer_prompt},
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
                    return None

        try:
            data = json.loads(raw)
        except Exception as parse_error:
            print(f"OpenAI reply JSON parse error: {repr(parse_error)} | body={raw[:500]}")
            return None

        choices = data.get("choices") or []
        if not choices:
            return None

        message = choices[0].get("message") or {}
        reply = _clean_reply(message.get("content") or "")
        return reply or None

    except Exception as error:
        print(f"OpenAI reply failed: {type(error).__name__}: {repr(error)}")
        return None
