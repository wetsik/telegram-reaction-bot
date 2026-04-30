import json

from greeting_texts import build_greeting_text
from settings import OUTPUTS_DIR


GREETED_USERS_FILE = OUTPUTS_DIR / "private_greeted_users.json"
GREETED_USER_IDS: set[int] = set()


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
        print(f"Private greeting load error: {error}")


def _save_seen_users() -> None:
    try:
        _ensure_outputs_dir()
        payload = sorted(GREETED_USER_IDS)
        tmp_file = GREETED_USERS_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(GREETED_USERS_FILE)
    except Exception as error:
        print(f"Private greeting save error: {error}")


def _should_skip_message(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and stripped.startswith(("/", "."))


async def maybe_send_private_greeting(event, client) -> bool:
    if getattr(event, "out", False) or not getattr(event, "is_private", False):
        return False

    text = event.raw_text or ""
    if _should_skip_message(text):
        return False

    sender = await event.get_sender()
    if not sender:
        return False

    if getattr(sender, "bot", False):
        return False

    sender_id = getattr(sender, "id", None)
    if sender_id is None or sender_id in GREETED_USER_IDS:
        return False

    if getattr(sender, "contact", False) or getattr(sender, "mutual_contact", False):
        return False

    lang_code = getattr(sender, "lang_code", None)
    greeting = build_greeting_text(lang_code, text)
    await event.respond(greeting)

    GREETED_USER_IDS.add(int(sender_id))
    _save_seen_users()
    return True


_load_seen_users()
