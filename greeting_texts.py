import re


RU_TEMPLATE = "Привет! Спасибо за сообщение. Владелец этого аккаунта скоро ответит."
EN_TEMPLATE = "Hi! Thanks for your message. The owner of this account will reply soon."
UZ_LATN_TEMPLATE = "Salom! Xabaringiz uchun rahmat. Bu akkaunt egasi tez orada javob beradi."
UZ_CYR_TEMPLATE = "Салом! Хабарингиз учун раҳмат. Бу аккаунт эгаси тез орада жавоб беради."
TR_TEMPLATE = "Merhaba! Mesajın için teşekkürler. Hesap sahibi yakında cevap verecek."
ES_TEMPLATE = "Hola! Gracias por tu mensaje. El dueño de esta cuenta responderá pronto."
FR_TEMPLATE = "Salut ! Merci pour votre message. Le propriétaire de ce compte répondra bientôt."
DE_TEMPLATE = "Hallo! Danke für deine Nachricht. Der Besitzer dieses Kontos antwortet bald."
PT_TEMPLATE = "Olá! Obrigado pela mensagem. O dono desta conta vai responder em breve."
AR_TEMPLATE = "مرحباً! شكراً لرسالتك. سيقوم صاحب هذا الحساب بالرد قريباً."


def normalize_lang_code(lang_code: str | None) -> str:
    return (lang_code or "").strip().lower().replace("_", "-")


def detect_script(text: str) -> str:
    if re.search(r"[\u0600-\u06ff]", text):
        return "ar"
    if re.search(r"[\u0400-\u04ff]", text):
        return "ru"
    if re.search(r"[a-zA-Z]", text):
        return "en"
    return "ru"


def build_greeting_text(lang_code: str | None, text: str = "") -> str:
    code = normalize_lang_code(lang_code)
    if not code:
        code = detect_script(text)

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
