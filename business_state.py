import json

from settings import OUTPUTS_DIR


BUSINESS_RESPONDED_CONNECTIONS_FILE = OUTPUTS_DIR / "business_responded_connections.json"
BUSINESS_CHAT_CONNECTIONS_FILE = OUTPUTS_DIR / "business_chat_connections.json"
BUSINESS_RESPONDED_CHATS_FILE = OUTPUTS_DIR / "business_responded_chats.json"

BUSINESS_RESPONDED_CONNECTION_IDS: set[str] = set()
BUSINESS_CHAT_TO_CONNECTION_ID: dict[int, str] = {}
BUSINESS_RESPONDED_CHAT_IDS: set[int] = set()


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


def load_business_state() -> None:
    try:
        responded = _load_json_file(BUSINESS_RESPONDED_CONNECTIONS_FILE)
        if isinstance(responded, list):
            for item in responded:
                if isinstance(item, str) and item.strip():
                    BUSINESS_RESPONDED_CONNECTION_IDS.add(item.strip())

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
        if isinstance(responded_chats, list):
            for item in responded_chats:
                if isinstance(item, int):
                    BUSINESS_RESPONDED_CHAT_IDS.add(item)
    except Exception as error:
        print(f"Business state load error: {error}")


def save_business_responded_connections() -> None:
    try:
        payload = sorted(BUSINESS_RESPONDED_CONNECTION_IDS)
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
        payload = sorted(BUSINESS_RESPONDED_CHAT_IDS)
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

    connection_id = BUSINESS_CHAT_TO_CONNECTION_ID.get(int(chat_id))
    if connection_id:
        mark_business_connection_responded(connection_id)
        return

    if chat_id not in BUSINESS_RESPONDED_CHAT_IDS:
        BUSINESS_RESPONDED_CHAT_IDS.add(int(chat_id))
        save_business_responded_chats()


def mark_business_connection_responded(connection_id: str) -> None:
    connection_id = (connection_id or "").strip()
    if not connection_id:
        return

    if connection_id not in BUSINESS_RESPONDED_CONNECTION_IDS:
        BUSINESS_RESPONDED_CONNECTION_IDS.add(connection_id)
        save_business_responded_connections()


def has_business_connection_responded(connection_id: str) -> bool:
    connection_id = (connection_id or "").strip()
    return bool(connection_id) and connection_id in BUSINESS_RESPONDED_CONNECTION_IDS


def has_business_chat_responded(chat_id: int) -> bool:
    if chat_id <= 0:
        return False

    if chat_id in BUSINESS_RESPONDED_CHAT_IDS:
        return True

    connection_id = BUSINESS_CHAT_TO_CONNECTION_ID.get(int(chat_id))
    return bool(connection_id) and connection_id in BUSINESS_RESPONDED_CONNECTION_IDS


load_business_state()
