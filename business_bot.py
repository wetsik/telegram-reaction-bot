import asyncio
import contextlib
import json
import random
from collections import defaultdict, deque
from pathlib import Path

from telethon import TelegramClient, events, functions, types
from telethon.errors import RPCError
from telethon.sessions import StringSession

from greeting_texts import build_greeting_text
from settings import API_HASH, API_ID, BOT_NAME, BOT_STAGE, BOT_TOKEN, BOT_VERSION, OUTPUTS_DIR


BUSINESS_CONNECTIONS: dict[str, types.BotBusinessConnection] = {}
BUSINESS_CONTEXT: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=12))
BUSINESS_GREETED_USERS_FILE = OUTPUTS_DIR / "business_greeted_users.json"
BUSINESS_GREETED_USER_IDS: set[int] = set()
client = TelegramClient(StringSession(), API_ID, API_HASH)


def _ensure_outputs_dir() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _peer_user_id(peer) -> int | None:
    if peer is None:
        return None
    return getattr(peer, "user_id", None)


def _load_greeted_users() -> None:
    try:
        if BUSINESS_GREETED_USERS_FILE.exists():
            data = json.loads(BUSINESS_GREETED_USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, int):
                        BUSINESS_GREETED_USER_IDS.add(item)
    except Exception as error:
        print(f"Business greeting load error: {error}")


def _save_greeted_users() -> None:
    try:
        _ensure_outputs_dir()
        payload = sorted(BUSINESS_GREETED_USER_IDS)
        tmp_file = BUSINESS_GREETED_USERS_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(BUSINESS_GREETED_USERS_FILE)
    except Exception as error:
        print(f"Business greeting save error: {error}")


def _tl_debug(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_tl_debug(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            pass
    result = {}
    for key in dir(value):
        if key.startswith("_"):
            continue
        try:
            item = getattr(value, key)
        except Exception:
            continue
        if callable(item):
            continue
        if key in {"stringify", "to_dict", "serialize"}:
            continue
        result[key] = _tl_debug(item)
    return result


async def _get_business_connection(connection_id: str) -> types.BotBusinessConnection | None:
    connection = BUSINESS_CONNECTIONS.get(connection_id)
    if connection is not None:
        return connection

    try:
        result = await client(functions.account.GetBotBusinessConnectionRequest(connection_id))
    except Exception as error:
        print(f"Business connection fetch failed for {connection_id}: {type(error).__name__}: {error}")
        return None

    connection = None
    if isinstance(result, types.BotBusinessConnection):
        connection = result
    else:
        for update in getattr(result, "updates", []) or []:
            if isinstance(update, types.UpdateBotBusinessConnect):
                connection = getattr(update, "connection", None)
                if connection is not None:
                    break

    if connection is None:
        print(f"Business connection fetch returned unexpected payload for {connection_id}: {type(result).__name__}")
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
    target_dc_id = getattr(connection, "dc_id", None)
    current_dc_id = getattr(getattr(client, "session", None), "dc_id", None)
    wrapped_request = functions.InvokeWithBusinessConnectionRequest(connection_id=connection_id, query=request)

    if target_dc_id is None or target_dc_id == current_dc_id:
        await client(wrapped_request)
        return

    sender = await client._borrow_exported_sender(target_dc_id)
    try:
        await sender.send(wrapped_request)
    finally:
        await client._return_exported_sender(sender)


def _push_context(connection_id: str, role: str, text: str) -> None:
    text = " ".join((text or "").split()).strip()
    if not text:
        return

    BUSINESS_CONTEXT[connection_id].append(f"{role}: {text}")


def _can_reply(connection: types.BotBusinessConnection | None) -> bool:
    if connection is None:
        return False
    if getattr(connection, "disabled", False):
        return False
    rights = getattr(connection, "rights", None)
    return bool(getattr(rights, "reply", False) or getattr(rights, "can_reply", False))


async def _handle_new_business_message(update) -> None:
    connection_id = getattr(update, "connection_id", None)
    message = getattr(update, "message", None)
    if not connection_id or message is None:
        return

    connection = await _get_business_connection(connection_id)
    if not _can_reply(connection):
        print(
            json.dumps(
                {
                    "event": "business_skip_no_reply_rights",
                    "connection_id": connection_id,
                    "has_connection": bool(connection),
                    "can_reply": bool(getattr(getattr(connection, "rights", None), "reply", False) or getattr(getattr(connection, "rights", None), "can_reply", False)) if connection else False,
                    "disabled": bool(getattr(connection, "disabled", False)) if connection else None,
                    "rights": _tl_debug(getattr(connection, "rights", None)) if connection else None,
                    "recipients": _tl_debug(getattr(connection, "recipients", None)) if connection else None,
                },
                ensure_ascii=False,
            )
        )
        return

    sender_id = _peer_user_id(getattr(message, "from_id", None))
    if sender_id is None:
        sender_id = _peer_user_id(getattr(message, "peer_id", None))

    if sender_id is None:
        return

    if sender_id in BUSINESS_GREETED_USER_IDS:
        return

    text = (getattr(message, "message", None) or "").strip()
    if text.startswith(("/", ".")):
        return

    reply_to_message = getattr(update, "reply_to_message", None)
    if reply_to_message is not None:
        _push_context(connection_id, "reply", getattr(reply_to_message, "message", None) or "")

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

    print(
        json.dumps(
            {
                "event": "business_greeted_once",
                "connection_id": connection_id,
                "sender_id": sender_id,
                "lang_code": lang_code,
                "text": text,
            },
            ensure_ascii=False,
        )
    )
    BUSINESS_GREETED_USER_IDS.add(int(sender_id))
    _save_greeted_users()
    _push_context(connection_id, "user", text)


@client.on(events.Raw())
async def handle_raw(event):
    update = event

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
                    "rights": _tl_debug(getattr(connection, "rights", None)),
                    "recipients": _tl_debug(getattr(connection, "recipients", None)),
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


_load_greeted_users()


if __name__ == "__main__":
    asyncio.run(run_business_bot_forever())
