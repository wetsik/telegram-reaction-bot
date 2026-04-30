import json
from pathlib import Path

from settings import OUTPUTS_DIR


BUSINESS_RESPONDED_CHATS_FILE = OUTPUTS_DIR / "business_responded_chats.json"
BUSINESS_RESPONDED_CHAT_IDS: set[int] = set()


def _ensure_outputs_dir() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def load_business_responded_chats() -> None:
    try:
        if BUSINESS_RESPONDED_CHATS_FILE.exists():
            data = json.loads(BUSINESS_RESPONDED_CHATS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, int):
                        BUSINESS_RESPONDED_CHAT_IDS.add(item)
    except Exception as error:
        print(f"Business responded chats load error: {error}")


def save_business_responded_chats() -> None:
    try:
        _ensure_outputs_dir()
        payload = sorted(BUSINESS_RESPONDED_CHAT_IDS)
        tmp_file = BUSINESS_RESPONDED_CHATS_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(BUSINESS_RESPONDED_CHATS_FILE)
    except Exception as error:
        print(f"Business responded chats save error: {error}")


def mark_business_chat_responded(chat_id: int) -> None:
    if chat_id <= 0:
        return

    if chat_id not in BUSINESS_RESPONDED_CHAT_IDS:
        BUSINESS_RESPONDED_CHAT_IDS.add(int(chat_id))
        save_business_responded_chats()


def has_business_chat_responded(chat_id: int) -> bool:
    return chat_id in BUSINESS_RESPONDED_CHAT_IDS


load_business_responded_chats()
