import asyncio

import aiohttp

from settings import WESTFORGE_API_KEY, WESTFORGE_API_URL, WESTFORGE_TIMEOUT


async def ask_westforge(message: str) -> str | None:
    """Send a single prompt to the WestForge AI model and return its answer.

    The API accepts only one string field ("message") and replies with
    {"success": true, "answer": "..."}. Returns None on any failure so the
    caller can fall back gracefully — the model is slow and not always up.
    """
    message = (message or "").strip()
    if not message or not WESTFORGE_API_KEY:
        return None

    headers = {
        "Content-Type": "application/json",
        "x-api-key": WESTFORGE_API_KEY,
    }
    timeout = aiohttp.ClientTimeout(total=WESTFORGE_TIMEOUT, connect=8)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                WESTFORGE_API_URL,
                headers=headers,
                json={"message": message},
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    print(f"WestForge error: status={response.status}, body={body[:300]}")
                    return None
                data = await response.json(content_type=None)
    except asyncio.TimeoutError:
        print("WestForge timeout")
        return None
    except Exception as error:
        print(f"WestForge request failed: {type(error).__name__}: {error}")
        return None

    if not isinstance(data, dict) or not data.get("success"):
        print(f"WestForge unexpected payload: {str(data)[:300]}")
        return None

    answer = (data.get("answer") or "").strip()
    return answer or None
