import asyncio
import json
import re

import aiohttp

from group_data import CANDIDATE_LABELS, PATTERNS
from settings import HF_API_TOKEN, USE_AI_CLASSIFICATION


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


def build_ai_input(text: str, context_messages):
    recent = list(context_messages)[-3:]
    if not recent:
        return text

    context_part = "\n".join(recent)
    return f"Контекст:\n{context_part}\n\nНовое сообщение:\n{text}"


async def classify_with_hf(text: str):
    if not USE_AI_CLASSIFICATION or not HF_API_TOKEN:
        return None

    url = "https://router.huggingface.co/hf-inference/models/facebook/bart-large-mnli"
    headers = {
        "Authorization": f"Bearer {HF_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": text,
        "parameters": {
            "candidate_labels": CANDIDATE_LABELS,
            "multi_label": False,
        },
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20, connect=10, sock_read=20)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                raw_text = await resp.text()

                if resp.status != 200:
                    print(f"HF API error: status={resp.status}, body={raw_text[:500]}")
                    return None

                try:
                    data = json.loads(raw_text)
                except Exception as parse_error:
                    print(f"HF JSON parse error: {repr(parse_error)} | body={raw_text[:500]}")
                    return None

        if isinstance(data, dict):
            labels = data.get("labels", [])
            scores = data.get("scores", [])
            if labels and scores:
                return labels[0], float(scores[0])

        if isinstance(data, list) and data and isinstance(data[0], dict):
            if "label" in data[0] and "score" in data[0]:
                best_item = max(data, key=lambda x: float(x.get("score", 0)))
                return best_item["label"], float(best_item["score"])

            first = data[0]
            labels = first.get("labels", [])
            scores = first.get("scores", [])
            if labels and scores:
                return labels[0], float(scores[0])

        print(f"HF unexpected response format: type={type(data).__name__}, data={str(data)[:500]}")
        return None

    except asyncio.TimeoutError as e:
        print(f"HF classify timeout: {repr(e)}")
        return None

    except aiohttp.ClientError as e:
        print(f"HF classify client error: {repr(e)}")
        return None

    except Exception as e:
        print(f"HF classify error: {type(e).__name__}: {repr(e)}")
        return None
