import random
import re

from group_data import LIGHT_ROAST_REPLIES, SPECIAL_PRAISE_ALIASES, SPECIAL_PRAISE_REPLIES


GREETING_BANK = [
    "йо",
    "ку",
    "здарова",
    "приветик",
    "о, привет",
    "привет, живые",
    "ну здарова",
    "всем привет",
    "нормально зашли",
    "о, это уже контакт",
    "привет, народ",
    "ага, привет",
    "ну привет",
    "салам, если что",
    "добрый, короче",
]

QUESTION_BANK = [
    "хороший вопрос",
    "вопрос с подводкой",
    "вот тут уже надо подумать",
    "по-честному, зависит от контекста",
    "если коротко, то да",
    "если без лишнего шума, то нет",
    "тут можно развернуть, но суть простая",
    "я бы смотрел на это шире",
    "логика тут есть, но не вся",
    "это уже интересный поворот",
    "вопрос норм, ответ не самый короткий",
    "можно ответить и просто, и по-взрослому",
    "тут лучше не спешить с выводом",
    "есть нюанс, и он заметный",
    "короткий ответ тут был бы слишком грубым",
]

DEBATE_BANK = [
    "ну тут уже спорно",
    "не, я бы так не сказал",
    "вот здесь я не соглашусь",
    "в логике есть трещина",
    "звучит уверенно, но не факт",
    "можно и по-другому это увидеть",
    "не самая сильная позиция, честно",
    "тут есть что покрутить",
    "спорный тейк, но не пустой",
    "я бы встал немного в сторону",
    "это уже разговор на вкус и на факты",
    "не всё так ровно, как звучит",
    "тут бы я не ставил точку",
    "есть смысл, но не железный",
    "вот именно поэтому и спорно",
]

SUPPORT_BANK = [
    "обидно, да",
    "ну это неприятно",
    "жаль, конечно",
    "бывает, но ситуация так себе",
    "неприятная история",
    "это уже реально тяжело",
    "понимаю, почему это цепляет",
    "ну да, такое выматывает",
    "держись, тут без шуток",
    "сочувствую, честно",
    "не самый приятный расклад",
    "в таком месте и правда напрягает",
    "да, это может выбить из колеи",
    "тут уже не до красивых слов",
    "ситуация мутная, согласен",
]

HYPE_BANK = [
    "вот это уже хорошо",
    "мощно вообще",
    "красава",
    "ну это разнос",
    "сильно, очень сильно",
    "так и надо",
    "это уже уровень",
    "база",
    "жёстко, но в хорошем смысле",
    "ну вот это красиво",
    "легендарно",
    "прям плотный ход",
    "я это уважаю",
    "вот здесь прям плюс",
    "с кайфом зашло",
]

FUNNY_BANK = [
    "ахах, сильный вброс",
    "я с этого выпал",
    "ну ты выдал",
    "ржал немного, не скрою",
    "это уже почти стендап",
    "жёстко, но смешно",
    "вот это шутка на скорости",
    "я прям завис на секунду",
    "убило аккуратно",
    "тут был момент",
    "это можно в архив",
    "не, ну это смешно",
    "выдали на ровном месте",
    "сцена закончилась",
    "всё, чат проиграл",
]

SARCASM_BANK = [
    "ну да, конечно",
    "логика мощная, ничего не скажешь",
    "как же без этого",
    "ну прям эталонный ход",
    "да, звучит уверенно",
    "смело, очень смело",
    "вот это заявление",
    "сильно, но мимо",
    "интересная картина",
    "по уровню дерзко",
    "ну такое я уважаю только частично",
    "ну это уже слишком красиво, чтобы быть правдой",
]

OBSERVATION_BANK = [
    "похоже, тема уже разогрелась",
    "чат сегодня живой",
    "тут уже пошёл разгон",
    "это можно слушать дальше",
    "ситуация интересная",
    "сейчас будет поворот",
    "тут уже пошёл нормальный ритм",
    "вот это уже разговор",
    "похоже, суть постепенно вылезает",
    "хороший темп у беседы",
    "вот теперь стало веселее",
    "тут есть за что зацепиться",
]

SHORT_BANK = [
    "понятно",
    "интересно",
    "бывает",
    "ладно",
    "ясно",
    "ну да",
    "окей",
    "мда",
    "согласен",
    "похоже на правду",
    "в целом да",
    "ну и ну",
    "без лишнего шума",
    "тоже вариант",
    "сойдет",
]

FOLLOWUP_BANK = [
    "и вот тут уже вопрос",
    "а дальше что",
    "и что по итогу",
    "вот это уже продолжение",
    "дальше картина интереснее",
    "а потом что было",
    "и на этом не всё",
    "вот это я бы не отпускал",
    "тут есть продолжение",
    "и вот здесь становится лучше",
]

PRAISE_BANK = [
    "это уже приятно слышать",
    "ну вот это красиво сказано",
    "уважаю такой тон",
    "приятно, без шуток",
    "это было по делу",
    "хорошо сказано",
    "вот это уже сильная подача",
    "приятно заходит",
    "да, тут прям в точку",
    "согласен, звучит сильно",
]

MILD_ROAST_BANK = [
    "ну ты и загнул",
    "это уже слишком уверенно",
    "тут бы я сбавил обороты",
    "не, ну это смело",
    "логика слегка убежала",
    "вот это ты дал",
    "сильное заявление, не спорю",
    "ну ты и персонаж",
    "не самый аккуратный тейк",
    "вышло громко, но спорно",
]

DEEP_BANK = [
    "если честно, тут всё упирается в контекст",
    "снаружи это выглядит проще, чем внутри",
    "иногда самый короткий ответ не самый точный",
    "тут важно не перепутать факт и ощущение",
    "в таких темах мелкие детали решают многое",
    "обычно всё ломается на одном скрытом условии",
    "я бы не резал это до одного слова",
    "тут легко промахнуться, если смотреть слишком быстро",
    "смысл обычно сидит в краях, а не в центре",
    "иногда ответ очевиден только после второго взгляда",
]

PRAISE_ALIASES = SPECIAL_PRAISE_ALIASES

REPLY_BANKS = {
    "greeting": GREETING_BANK,
    "question": QUESTION_BANK,
    "agreement": HYPE_BANK + PRAISE_BANK,
    "disagreement": DEBATE_BANK,
    "funny": FUNNY_BANK,
    "sad": SUPPORT_BANK,
    "love": [
        "ну это мило",
        "приятно слышать",
        "вот это тепло",
        "очень даже хорошо",
        "с таким настроем жить проще",
        "это уже красиво",
        "приятный вайб",
        "сильно по-доброму звучит",
        "вот это заходит",
        "мягко и по делу",
    ],
    "anger": [
        "да, это уже бесит",
        "тут реально можно вспылить",
        "неприятный момент",
        "да, это перегиб",
        "такое нормально раздражает",
        "ну это уже жёстко",
        "здесь я понимаю злость",
        "плохая сцена, согласен",
        "вот это уже через край",
        "тут бы любой напрягся",
    ],
    "shock": [
        "ничего себе",
        "вот это поворот",
        "я на секунду завис",
        "это уже неожиданно",
        "такого разворота я не ждал",
        "жёстко, без шуток",
        "вот это внезапно",
        "сценарий ушёл в другую сторону",
        "ну и расклад",
        "это уже сильно удивляет",
    ],
    "hype": HYPE_BANK,
    "neutral": SHORT_BANK + OBSERVATION_BANK,
}

SILENT_TRIGGERS = (
    "ок",
    "ладно",
    "ясно",
    "понятно",
    "ага",
    "угу",
    "ok",
)


def _normalize_name_text(text: str) -> str:
    return (
        text.strip().lower()
        .replace("@", "")
        .replace("ё", "е")
        .replace("-", "")
        .replace("_", "")
        .replace(".", "")
    )


def _is_special_praise_target(text: str) -> bool:
    normalized = _normalize_name_text(text)
    return bool(normalized) and any(alias in normalized for alias in PRAISE_ALIASES)


def _contains_hostility(text: str) -> bool:
    normalized = _normalize_name_text(text)
    return any(
        marker in normalized
        for marker in (
            "лох",
            "туп",
            "долб",
            "дурак",
            "идиот",
            "кринж",
            "говн",
            "хуй",
            "слаб",
            "заткни",
        )
    )


def _has_question_shape(text: str) -> bool:
    normalized = _normalize_name_text(text)
    if text.strip().endswith("?"):
        return True

    return any(word in normalized for word in ("почему", "зачем", "как", "что", "когда", "где", "кто", "сколько", "почему"))


def _should_join_locally(*, text: str, label: str) -> bool:
    normalized = _normalize_name_text(text)
    if not normalized:
        return False

    if normalized in SILENT_TRIGGERS:
        return False

    if _has_question_shape(text):
        return True

    if label in {"funny", "shock", "hype", "sad", "love", "agreement", "disagreement", "question", "anger"}:
        return True

    if any(word in normalized for word in ("привет", "здарова", "здравствуй", "салам", "hello", "hi", "hey", "yo")):
        return True

    if len(normalized.split()) >= 6:
        return True

    return False


def _select_bank(*, text: str, label: str, mentioned: bool) -> list[str]:
    normalized = _normalize_name_text(text)

    if _is_special_praise_target(text):
        return SPECIAL_PRAISE_REPLIES

    if _contains_hostility(text):
        return MILD_ROAST_BANK + LIGHT_ROAST_REPLIES

    if _has_question_shape(text):
        return QUESTION_BANK + DEEP_BANK

    if any(marker in normalized for marker in ("спор", "неа", "не думаю", "сомнитель", "вряд", "не факт")):
        return DEBATE_BANK

    if label in {"sad", "anger"}:
        return SUPPORT_BANK

    if label in {"funny", "shock"}:
        return FUNNY_BANK + SARCASM_BANK

    if label in {"hype", "love", "agreement"}:
        return HYPE_BANK + PRAISE_BANK

    if label == "disagreement":
        return DEBATE_BANK + SARCASM_BANK

    if label == "greeting":
        return GREETING_BANK

    if len(normalized.split()) <= 2:
        return SHORT_BANK + OBSERVATION_BANK

    if mentioned:
        return PRAISE_BANK + OBSERVATION_BANK + SHORT_BANK

    return REPLY_BANKS["neutral"] + DEEP_BANK


def _choose_delivery_mode(*, text: str, label: str, mentioned: bool, direct_address: bool) -> str | None:
    normalized = _normalize_name_text(text)
    words = normalized.split()
    short_text = len(words) <= 3
    emotional = label in {"funny", "shock", "hype", "love", "sad", "anger"}

    if normalized in SILENT_TRIGGERS:
        return None

    if direct_address:
        silent_chance = 0.08 if emotional else 0.14
        message_chance = 0.22 if short_text else 0.18
        roll = random.random()
        if roll < silent_chance:
            return None
        if roll < silent_chance + message_chance:
            return "message"
        return "reply"

    if mentioned:
        silent_chance = 0.10 if emotional else 0.18
        message_chance = 0.20 if short_text else 0.28
        roll = random.random()
        if roll < silent_chance:
            return None
        if roll < silent_chance + message_chance:
            return "message"
        return "reply"

    silent_chance = 0.22 if emotional else 0.35
    message_chance = 0.40 if not short_text else 0.30
    roll = random.random()
    if roll < silent_chance:
        return None
    if roll < silent_chance + message_chance:
        return "message"
    return "reply"


async def generate_context_reply(
    *,
    text: str,
    context_messages: list[str],
    chat_memory: str,
    speaker_name: str,
    bot_names: list[str],
    label: str,
    mentioned: bool,
) -> str | None:
    if not mentioned and not _should_join_locally(text=text, label=label):
        return None

    bank = _select_bank(text=text, label=label, mentioned=mentioned)
    if not bank:
        return None

    reply = random.choice(bank)

    if chat_memory and random.random() < 0.12:
        memory_lines = [line.strip() for line in chat_memory.splitlines() if line.strip()]
        if memory_lines:
            memory_hint = random.choice(memory_lines[:6])
            if len(memory_hint) <= 42 and random.random() < 0.5:
                reply = f"{reply}. {memory_hint}"

    return _clean_reply(reply)


async def describe_image_for_chat(image_bytes: bytes, mime_type: str) -> str | None:
    if mime_type == "image/jpeg":
        return "изображение"
    if mime_type == "image/png":
        return "картинка"
    if mime_type == "image/webp":
        return "стикер"
    if mime_type == "image/gif":
        return "анимированная картинка"
    return "медиа"


async def should_join_context(
    *,
    text: str,
    context_messages: list[str],
    chat_memory: str,
    speaker_name: str,
    bot_names: list[str],
    label: str,
) -> bool:
    return _should_join_locally(text=text, label=label)


def choose_delivery_mode(
    *,
    text: str,
    label: str,
    mentioned: bool,
    direct_address: bool,
) -> str | None:
    return _choose_delivery_mode(
        text=text,
        label=label,
        mentioned=mentioned,
        direct_address=direct_address,
    )
