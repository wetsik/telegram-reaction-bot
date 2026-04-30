import asyncio
import contextlib
import json
import random

from telethon import TelegramClient, events, functions, types
from telethon.errors import RPCError
from telethon.sessions import StringSession

from greeting_texts import build_greeting_text
from settings import API_HASH, API_ID, BOT_NAME, BOT_STAGE, BOT_TOKEN, BOT_VERSION, OUTPUTS_DIR


GREETED_USERS_FILE = OUTPUTS_DIR / "business_greeted_users.json"
GREETED_USER_IDS: set[int] = set()
BUSINESS_CONNECTIONS: dict[str, types.BotBusinessConnection] = {}
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


async def _get_business_connection(connection_id: str) -> types.BotBusinessConnection | None:
    connection = BUSINESS_CONNECTIONS.get(connection_id)
    if connection is not None:
        return connection

    try:
        connection = await client(functions.account.GetBotBusinessConnectionRequest(connection_id))
    except Exception as error:
        print(f"Business connection fetch failed for {connection_id}: {type(error).__name__}: {error}")
        return None

    BUSINESS_CONNECTIONS[connection_id] = connection
    return connection


async def _resolve_input_peer(message, connection: types.BotBusinessConnection):
    peer = getattr(message, "peer_id", None)
    if peer is not None:
        with contextlib.suppress(Exception):
            return await client.get_input_entity(peer)

    user_id = getattr(connection, "user_id", None)
    if user_id is not None:
        with contextlib.suppress(Exception):
            return await client.get_input_entity(types.PeerUser(int(user_id)))

    return None


async def _send_business_reply(connection_id: str, message, text: str) -> None:
    connection = await _get_business_connection(connection_id)
    if connection is None:
        raise RuntimeError("business connection not available")

    input_peer = await _resolve_input_peer(message, connection)
    if input_peer is None:
        raise RuntimeError("could not resolve business peer for reply")

    request = functions.messages.SendMessageRequest(
        peer=input_peer,
        message=text,
        random_id=random.getrandbits(63),
        reply_to=types.InputReplyToMessage(reply_to_msg_id=getattr(message, "id", 0)),
    )
    sender = await client._borrow_exported_sender(connection.dc_id)
    try:
        await sender.send(functions.InvokeWithBusinessConnectionRequest(connection_id=connection_id, query=request))
    finally:
        await client._return_exported_sender(sender)


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
        await _send_business_reply(connection_id, message, greeting)
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
        if connection is not None:
            BUSINESS_CONNECTIONS[getattr(connection, "connection_id", "")] = connection
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


async def run_business_bot_forever():
    if not BOT_TOKEN:
        print("BOT_TOKEN is missing, business bot is disabled.")
        return

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
    asyncio.run(run_business_bot_forever())
