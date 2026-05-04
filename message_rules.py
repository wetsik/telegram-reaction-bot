import re

from group_data import CANDIDATE_LABELS, PATTERNS


def clean_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def score_with_rules(text: str, context_messages):
    t = clean_text(text)
    joined = " ".join(context_messages[-4:]).lower()
    scores = {label: 0.0 for label in CANDIDATE_LABELS}

    for label, patterns in PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, t):
                scores[label] += 1.4

    if t.endswith("?"):
        scores["question"] += 1.2

    if len(t) <= 3:
        scores["neutral"] += 0.8

    if any(x in t for x in ["ахах", "хаха", "лол", "ору"]):
        scores["funny"] += 1.5

    if any(x in t for x in ["капец", "пипец", "жесть"]):
        scores["shock"] += 0.8
        scores["anger"] += 0.3

    if any(x in t for x in ["имба", "кайф", "топ", "сильно"]):
        scores["hype"] += 0.7
        scores["love"] += 0.4

    if scores["funny"] > 0 and any(x in joined for x in ["ахах", "лол", "ору"]):
        scores["funny"] += 0.2

    best = max(scores.values())
    if best < 1.0:
        scores["neutral"] = max(scores["neutral"], 1.0)

    best_label = max(scores, key=scores.get)
    confidence = scores[best_label]
    return best_label, confidence, scores
