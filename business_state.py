import json
import time

from settings import OUTPUTS_DIR


BUSINESS_LOCK_TTL_SECONDS = int(12 * 60 * 60)

BUSINESS_RESPONDED_CONNECTIONS_FILE = OUTPUTS_DIR / "business_responded_connections.json"
BUSINESS_CHAT_CONNECTIONS_FILE = OUTPUTS_DIR / "business_chat_connections.json"
BUSINESS_RESPONDED_CHATS_FILE = OUTPUTS_DIR / "business_responded_chats.json"

BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS: dict[str, float] = {}
BUSINESS_CHAT_TO_CONNECTION_ID: dict[int, str] = {}
BUSINESS_RESPONDED_CHAT_TIMESTAMPS: dict[int, float] = {}


def _ensure_outputs_dir() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json_file(path):
    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))


def _save_json_file(path, payload) -> None:
    _ensure_outputs_dir()
    tmp_file = path.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(path)


def _normalize_timestamp(value) -> float | None:
    try:
        value = float(value)
    except Exception:
        return None

    if value <= 0:
        return None
    return value


def _is_timestamp_fresh(timestamp: float | None) -> bool:
    if timestamp is None:
        return False
    return (time.time() - timestamp) <= BUSINESS_LOCK_TTL_SECONDS


def _purge_stale_connection(connection_id: str) -> None:
    if connection_id in BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS and not _is_timestamp_fresh(
        BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS.get(connection_id)
    ):
        BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS.pop(connection_id, None)
        save_business_responded_connections()


def _purge_stale_chat(chat_id: int) -> None:
    if chat_id in BUSINESS_RESPONDED_CHAT_TIMESTAMPS and not _is_timestamp_fresh(
        BUSINESS_RESPONDED_CHAT_TIMESTAMPS.get(chat_id)
    ):
        BUSINESS_RESPONDED_CHAT_TIMESTAMPS.pop(chat_id, None)
        save_business_responded_chats()


def load_business_state() -> None:
    try:
        responded = _load_json_file(BUSINESS_RESPONDED_CONNECTIONS_FILE)
        if isinstance(responded, dict):
            for connection_id, timestamp in responded.items():
                if isinstance(connection_id, str):
                    normalized = _normalize_timestamp(timestamp)
                    if normalized is not None:
                        BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS[connection_id.strip()] = normalized
        elif isinstance(responded, list):
            now = time.time()
            for item in responded:
                if isinstance(item, str) and item.strip():
                    BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS[item.strip()] = now

        chat_map = _load_json_file(BUSINESS_CHAT_CONNECTIONS_FILE)
        if isinstance(chat_map, list):
            for item in chat_map:
                if not isinstance(item, dict):
                    continue
                chat_id = item.get("chat_id")
                connection_id = item.get("connection_id")
                if isinstance(chat_id, int) and isinstance(connection_id, str) and connection_id.strip():
                    BUSINESS_CHAT_TO_CONNECTION_ID[int(chat_id)] = connection_id.strip()

        responded_chats = _load_json_file(BUSINESS_RESPONDED_CHATS_FILE)
        if isinstance(responded_chats, dict):
            for chat_id, timestamp in responded_chats.items():
                try:
                    chat_key = int(chat_id)
                except Exception:
                    continue
                normalized = _normalize_timestamp(timestamp)
                if normalized is not None:
                    BUSINESS_RESPONDED_CHAT_TIMESTAMPS[chat_key] = normalized
        elif isinstance(responded_chats, list):
            now = time.time()
            for item in responded_chats:
                if isinstance(item, int):
                    BUSINESS_RESPONDED_CHAT_TIMESTAMPS[item] = now
    except Exception as error:
        print(f"Business state load error: {error}")


def save_business_responded_connections() -> None:
    try:
        payload = dict(sorted(BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS.items()))
        _save_json_file(BUSINESS_RESPONDED_CONNECTIONS_FILE, payload)
    except Exception as error:
        print(f"Business responded connections save error: {error}")


def save_business_chat_connections() -> None:
    try:
        payload = [
            {"chat_id": chat_id, "connection_id": connection_id}
            for chat_id, connection_id in sorted(BUSINESS_CHAT_TO_CONNECTION_ID.items())
        ]
        _save_json_file(BUSINESS_CHAT_CONNECTIONS_FILE, payload)
    except Exception as error:
        print(f"Business chat connections save error: {error}")


def save_business_responded_chats() -> None:
    try:
        payload = dict(sorted(BUSINESS_RESPONDED_CHAT_TIMESTAMPS.items()))
        _save_json_file(BUSINESS_RESPONDED_CHATS_FILE, payload)
    except Exception as error:
        print(f"Business responded chats save error: {error}")


def register_business_chat_connection(chat_id: int, connection_id: str) -> None:
    if chat_id <= 0:
        return

    connection_id = (connection_id or "").strip()
    if not connection_id:
        return

    current = BUSINESS_CHAT_TO_CONNECTION_ID.get(int(chat_id))
    if current == connection_id:
        return

    BUSINESS_CHAT_TO_CONNECTION_ID[int(chat_id)] = connection_id
    save_business_chat_connections()


def mark_business_chat_responded(chat_id: int) -> None:
    if chat_id <= 0:
        return

    now = time.time()
    BUSINESS_RESPONDED_CHAT_TIMESTAMPS[int(chat_id)] = now
    save_business_responded_chats()

    connection_id = BUSINESS_CHAT_TO_CONNECTION_ID.get(int(chat_id))
    if connection_id:
        BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS[connection_id] = now
        save_business_responded_connections()


def mark_business_connection_responded(connection_id: str) -> None:
    connection_id = (connection_id or "").strip()
    if not connection_id:
        return

    now = time.time()
    BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS[connection_id] = now
    save_business_responded_connections()


def has_business_connection_responded(connection_id: str) -> bool:
    connection_id = (connection_id or "").strip()
    if not connection_id:
        return False

    _purge_stale_connection(connection_id)
    return _is_timestamp_fresh(BUSINESS_RESPONDED_CONNECTION_TIMESTAMPS.get(connection_id))


def has_business_chat_responded(chat_id: int) -> bool:
    if chat_id <= 0:
        return False

    _purge_stale_chat(int(chat_id))
    if _is_timestamp_fresh(BUSINESS_RESPONDED_CHAT_TIMESTAMPS.get(int(chat_id))):
        return True

    connection_id = BUSINESS_CHAT_TO_CONNECTION_ID.get(int(chat_id))
    return bool(connection_id) and has_business_connection_responded(connection_id)


load_business_state()
