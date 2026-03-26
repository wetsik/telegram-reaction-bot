import os
import time
import random
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telethon import TelegramClient, events, functions, types
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from transformers import pipeline

# =========================
# ENV
# =========================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]

# =========================
# TELEGRAM CLIENT
# =========================
client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)

# =========================
# LIGHTER MODEL FOR CLOUD
# =========================
# Более лёгкая многоязычная zero-shot модель
classifier = pipeline(
    task="zero-shot-classification",
    model="joeddav/xlm-roberta-large-xnli",
    device=-1
)

# =========================
# LOGIC
# =========================
CANDIDATE_LABELS = [
    "funny",
    "shock",
    "hype",
    "sad",
    "love",
    "anger",
    "neutral"
]

REACTION_POOLS = {
    "funny": ["😂", "🤣", "💀", "😭", "😹", "😆"],
    "shock": ["😳", "😱", "👀", "🤯", "😮"],
    "hype": ["🔥", "💯", "⚡", "😎", "🚀", "👏"],
    "sad": ["😭", "😢", "💔", "🥲"],
    "love": ["❤️", "🥰", "💖", "🙏"],
    "anger": ["😡", "💀", "👀", "🤦"],
    "neutral": ["👀", "👍", "🙂"]
}

MIN_DELAY = float(os.environ.get("MIN_DELAY", "1.0"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "3.0"))
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "7"))
GLOBAL_REACTION_CHANCE = float(os.environ.get("GLOBAL_REACTION_CHANCE", "0.70"))

last_reaction_time = 0.0


def pick_reaction(text: str):
    if not text or len(text.strip()) < 2:
        return None, None, None

    result = classifier(
        text,
        candidate_labels=CANDIDATE_LABELS,
        multi_label=False
    )

    top_label = result["labels"][0]
    top_score = float(result["scores"][0])

    if top_score < 0.45:
        return None, top_label, top_score

    thresholds = {
        "funny": 0.52,
        "shock": 0.50,
        "hype": 0.50,
        "sad": 0.50,
        "love": 0.55,
        "anger": 0.55,
        "neutral": 0.60
    }

    if top_score < thresholds.get(top_label, 0.50):
        return None, top_label, top_score

    skip_chances = {
        "funny": 0.20,
        "shock": 0.25,
        "hype": 0.20,
        "sad": 0.30,
        "love": 0.35,
        "anger": 0.40,
        "neutral": 0.85
    }

    if random.random() < skip_chances.get(top_label, 0.30):
        return None, top_label, top_score

    emoji = random.choice(REACTION_POOLS[top_label])
    return emoji, top_label, top_score


@client.on(events.NewMessage)
async def handle_new_message(event):
    global last_reaction_time

    if event.out:
        return

    if not event.raw_text:
        return

    if random.random() > GLOBAL_REACTION_CHANCE:
        return

    now = time.time()
    if now - last_reaction_time < COOLDOWN_SECONDS:
        return

    try:
        emoji, label, score = pick_reaction(event.raw_text)

        if not emoji:
            print(f"skip | label={label} | score={score}")
            return

        await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        await client(functions.messages.SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.id,
            big=False,
            add_to_recent=True,
            reaction=[types.ReactionEmoji(emoticon=emoji)]
        ))

        last_reaction_time = time.time()
        print(f"reacted {emoji} | label={label} | score={score:.3f}")

    except FloodWaitError as e:
        print(f"FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print("ERROR:", e)


# =========================
# SIMPLE HTTP SERVER FOR RENDER
# =========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server started on port {port}")
    server.serve_forever()


async def main():
    print("Userbot started...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    client.start()
    client.loop.run_until_complete(main())