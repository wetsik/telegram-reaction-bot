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

    if len(text) > 500:
        text = text[:497].rstrip() + "..."

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
        "You are a normal Telegram chat participant, not an assistant. "
        "Reply in the same language as the chat, usually Russian. "
        "Write naturally, like a smart friend in chat. "
        "Use casual slang, but do not overdo it. "
        "For simple chat, keep it short. "
        "For real questions, answer normally and explain in simple casual words. "
        "For educational questions, give a clear useful answer in 1-4 short sentences. "
        "Light sarcasm is ok when it fits, but do not force jokes or roasts. "
        "No cringe phrases like 'botik', 'living bot', 'what will you tell me', theatrical hype, or fake enthusiasm. "
        "Do not sound like customer support or a textbook. "
        "Do not mention being an AI, bot, model, or assistant. "
        "No markdown, hashtags, quotes, or emojis. "
        "Do not be cruel, hateful, sexual, threatening, or target protected traits. "
        "If directly mentioned, always reply. "
        "If not mentioned and there is no natural reply, return an empty string."
    )
    user_prompt = (
        f"Recent chat messages:\n{context}\n\n"
        f"New message:\n{text}\n\n"
        f"Detected mood: {label}\n"
        f"Bot was mentioned: {mentioned}\n\n"
        "Write a natural chat reply. If this is a question, answer it clearly."
    )

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_completion_tokens": 140,
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
