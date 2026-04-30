import asyncio
import contextlib
import json
import random
import threading

from telethon import TelegramClient, events, functions, types
from telethon.errors import RPCError
from telethon.sessions import StringSession

from greeting_texts import build_greeting_text
from health_server import run_health_server
from settings import API_HASH, API_ID, BOT_NAME, BOT_STAGE, BOT_TOKEN, BOT_VERSION, OUTPUTS_DIR


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add a BotFather token for the connected business bot.")


GREETED_USERS_FILE = OUTPUTS_DIR / "business_greeted_users.json"
GREETED_USER_IDS: set[int] = set()
client = TelegramClient(StringSession(), API_ID, API_HASH)


def _ensure_outputs_dir() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_seen_users() -> None:
    try:
        if GREETED_USERS_FILE.exists():
            data = json.loads(GREETED_USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, int):
                        GREETED_USER_IDS.add(item)
    except Exception as error:
        print(f"Business greeting load error: {error}")


def _save_seen_users() -> None:
    try:
        _ensure_outputs_dir()
        payload = sorted(GREETED_USER_IDS)
        tmp_file = GREETED_USERS_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(GREETED_USERS_FILE)
    except Exception as error:
        print(f"Business greeting save error: {error}")


def _peer_user_id(peer) -> int | None:
    if peer is None:
        return None
    return getattr(peer, "user_id", None)


async def _send_business_reply(connection_id: str, peer, message_id: int, text: str) -> None:
    input_peer = await client.get_input_entity(peer)
    request = functions.messages.SendMessageRequest(
        peer=input_peer,
        message=text,
        random_id=random.getrandbits(63),
        reply_to=types.InputReplyToMessage(reply_to_msg_id=message_id),
    )
    await client(functions.InvokeWithBusinessConnectionRequest(connection_id=connection_id, query=request))


async def _handle_new_business_message(update) -> None:
    connection_id = getattr(update, "connection_id", None)
    message = getattr(update, "message", None)
    if not connection_id or message is None:
        return

    sender_id = _peer_user_id(getattr(message, "from_id", None))
    if sender_id is None:
        sender_id = _peer_user_id(getattr(message, "peer_id", None))

    if sender_id is None or sender_id in GREETED_USER_IDS:
        return

    text = (getattr(message, "message", None) or "").strip()
    if text.startswith(("/", ".")):
        return

    sender = None
    with contextlib.suppress(Exception):
        sender = await client.get_entity(message.from_id)

    lang_code = getattr(sender, "lang_code", None)
    greeting = build_greeting_text(lang_code, text)

    try:
        await _send_business_reply(connection_id, message.peer_id, message.id, greeting)
    except RPCError as error:
        print(f"Business reply error: {error.__class__.__name__}: {error}")
        return
    except Exception as error:
        print(f"Business reply failed: {type(error).__name__}: {error}")
        return

    GREETED_USER_IDS.add(int(sender_id))
    _save_seen_users()
    print(
        json.dumps(
            {
                "event": "business_greeted",
                "connection_id": connection_id,
                "sender_id": sender_id,
                "lang_code": lang_code,
                "text": text,
            },
            ensure_ascii=False,
        )
    )


@client.on(events.Raw())
async def handle_raw(event):
    update = getattr(event, "update", None) or getattr(event, "_raw", None)
    if update is None:
        return

    if isinstance(update, types.UpdateBotBusinessConnect):
        connection = getattr(update, "connection", None)
        print(
            json.dumps(
                {
                    "event": "business_connect",
                    "connection_id": getattr(connection, "connection_id", None),
                    "user_id": getattr(connection, "user_id", None),
                    "disabled": bool(getattr(connection, "disabled", False)),
                },
                ensure_ascii=False,
            )
        )
        return

    if isinstance(update, types.UpdateBotNewBusinessMessage):
        await _handle_new_business_message(update)
        return


async def run_bot_forever():
    while True:
        try:
            print(f"Starting {BOT_NAME} {BOT_VERSION} [{BOT_STAGE}] business bot...")
            await client.start(bot_token=BOT_TOKEN)

            me = await client.get_me()
            print(
                f"{BOT_NAME} {BOT_VERSION} [{BOT_STAGE}] business bot logged in as: "
                f"{me.first_name} (@{me.username})"
            )

            await client.run_until_disconnected()

        except Exception as error:
            print(f"BUSINESS BOT ERROR: {type(error).__name__}: {error}")

        print("Restarting business bot in 5 seconds...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    _load_seen_users()
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(run_bot_forever())
