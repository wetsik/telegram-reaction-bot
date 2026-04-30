import re


RU_TEMPLATE = "Привет! Спасибо за сообщение. Владелец этого аккаунта сейчас не на связи, но ответит позже."
EN_TEMPLATE = "Hi! Thanks for your message. The owner of this account is not available right now, but will reply later."
UZ_LATN_TEMPLATE = "Salom! Xabaringiz uchun rahmat. Bu akkaunt egasi hozircha band, keyinroq javob beradi."
UZ_CYR_TEMPLATE = "Салом! Хабарингиз учун раҳмат. Бу аккаунт эгаси ҳозирча банд, кейинроқ жавоб беради."
TR_TEMPLATE = "Merhaba! Mesajın için teşekkürler. Hesap sahibi şu anda müsait değil, sonra dönecek."
ES_TEMPLATE = "Hola! Gracias por tu mensaje. El dueño de esta cuenta no está disponible ahora, pero responderá más tarde."
FR_TEMPLATE = "Salut ! Merci pour votre message. Le propriétaire de ce compte n'est pas disponible pour le moment, mais répondra plus tard."
DE_TEMPLATE = "Hallo! Danke für deine Nachricht. Der Besitzer dieses Kontos ist gerade nicht erreichbar, antwortet aber später."
PT_TEMPLATE = "Olá! Obrigado pela mensagem. O dono desta conta não está disponível agora, mas responderá mais tarde."
AR_TEMPLATE = "مرحبا! شكرا لرسالتك. صاحب هذا الحساب غير متاح الآن، لكنه سيرد لاحقاً."


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
