import json
import re
from pathlib import Path

from settings import OUTPUTS_DIR


GREETED_USERS_FILE = OUTPUTS_DIR / "private_greeted_users.json"
GREETED_USER_IDS: set[int] = set()


RU_TEMPLATE = "Привет! Спасибо за сообщение. Владелец этого аккаунта скоро ответит."
EN_TEMPLATE = "Hi! Thanks for your message. The owner of this account will reply soon."
UZ_LATN_TEMPLATE = "Salom! Xabaringiz uchun rahmat. Bu akkaunt egasi tez orada javob beradi."
UZ_CYR_TEMPLATE = "Салом! Хабариңиз учун раҳмат. Бу аккаунт эгаси тез орада жавоб беради."
TR_TEMPLATE = "Merhaba! Mesajın için teşekkürler. Hesap sahibi yakında cevap verecek."
ES_TEMPLATE = "Hola! Gracias por tu mensaje. El dueño de esta cuenta responderá pronto."
FR_TEMPLATE = "Salut ! Merci pour votre message. Le propriétaire de ce compte répondra bientôt."
DE_TEMPLATE = "Hallo! Danke für deine Nachricht. Der Besitzer dieses Kontos antwortet bald."
PT_TEMPLATE = "Olá! Obrigado pela mensagem. O dono desta conta vai responder em breve."
AR_TEMPLATE = "مرحباً! شكراً لرسالتك. سيقوم صاحب هذا الحساب بالرد قريباً."


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


def _normalize_lang_code(lang_code: str | None) -> str:
    return (lang_code or "").strip().lower().replace("_", "-")


def _detect_script(text: str) -> str:
    if re.search(r"[\u0600-\u06ff]", text):
        return "ar"
    if re.search(r"[\u0400-\u04ff]", text):
        return "ru"
    if re.search(r"[a-zA-Z]", text):
        return "en"
    return "ru"


def _pick_template(lang_code: str | None, text: str) -> str:
    code = _normalize_lang_code(lang_code)
    if not code:
        code = _detect_script(text)

    family = code[:2]
    if family in {"ru", "uk", "be", "kk", "ky", "mn", "tg"}:
        return RU_TEMPLATE
    if family == "en":
        return EN_TEMPLATE
    if family == "uz":
        return UZ_CYR_TEMPLATE if "cyrl" in code else UZ_LATN_TEMPLATE
    if family == "tr":
        return TR_TEMPLATE
    if family == "es":
        return ES_TEMPLATE
    if family == "fr":
        return FR_TEMPLATE
    if family == "de":
        return DE_TEMPLATE
    if family == "pt":
        return PT_TEMPLATE
    if family == "ar":
        return AR_TEMPLATE

    if "cyrl" in code:
        return RU_TEMPLATE
    if "latn" in code:
        return EN_TEMPLATE

    return EN_TEMPLATE


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
    greeting = _pick_template(lang_code, text)
    await event.respond(greeting)

    GREETED_USER_IDS.add(int(sender_id))
    _save_seen_users()
    return True


_load_seen_users()
