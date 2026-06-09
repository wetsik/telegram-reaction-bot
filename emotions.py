import random
import re

from ai_client import ask_westforge
from group_data import EMOTION_KEYWORDS, REACTIONS
from settings import AI_EMOTION_CHANCE, ENABLE_AI_EMOTION, ENABLE_AI_REPLIES


# Все валидные метки эмоций = ключи карты реакций.
EMOTION_LABELS = list(REACTIONS.keys())


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_label(text: str) -> str:
    """Быстрая эвристика по ключевым словам (без сети)."""
    lowered = _clean(text)
    if not lowered:
        return "neutral"
    for label, keywords in EMOTION_KEYWORDS:
        if any(word and word in lowered for word in keywords):
            return label
    return "neutral"


async def _classify_ai(text: str) -> str | None:
    """Просим модель определить эмоцию ПО СМЫСЛУ и вернуть одну метку из списка."""
    snippet = (text or "").strip()
    if len(snippet) < 3:
        return None

    labels = ", ".join(EMOTION_LABELS)
    prompt = (
        "Определи эмоцию/настроение сообщения по смыслу. "
        f"Ответь ОДНИМ словом строго из списка (на английском): {labels}. "
        "Без пояснений, только одно слово.\n"
        f"Сообщение: {snippet}\n"
        "Эмоция:"
    )
    answer = await ask_westforge(prompt)
    if not answer:
        return None

    low = answer.strip().lower()
    # точное совпадение слова
    for label in EMOTION_LABELS:
        if re.search(rf"\b{re.escape(label)}\b", low):
            return label
    # подстрока (на случай мусора вокруг)
    for label in EMOTION_LABELS:
        if label in low:
            return label
    return None


async def detect_emotion(text: str) -> str:
    """Гибрид: с шансом — классификация моделью по тексту, иначе ключевые слова.
    Модель слабая и медленная, поэтому ИИ-путь включается не всегда."""
    if not (text or "").strip():
        return "neutral"

    if (
        ENABLE_AI_EMOTION
        and ENABLE_AI_REPLIES
        and random.random() < AI_EMOTION_CHANCE
    ):
        label = await _classify_ai(text)
        if label:
            return label

    return detect_label(text)
