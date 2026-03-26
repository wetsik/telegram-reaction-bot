import os
import time
import random
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telethon import TelegramClient, events, functions, types
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]

client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)

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


def pick_reaction(text: str):
    if not text or len(text.strip()) < 2:
        return None, "neutral", 0

    text = text.lower().strip().replace("ё", "е")

    score = {
        "funny": 0,
        "shock": 0,
        "hype": 0,
        "sad": 0,
        "love": 0,
        "anger": 0,
        "neutral": 0
    }

    # Смех / рофл
    if any(x in text for x in ["аха", "ахах", "хаха", "лол", "ору", "ржу", "угар", "rofl", "lol", "lmao"]):
        score["funny"] += 3

    # Шок / удивление
    if "??" in text or "!!" in text or "!?" in text:
        score["shock"] += 2
    if any(x in text for x in ["жесть", "капец", "офиг", "нифига", "серьезно", "реально", "what", "wtf", "omg", "no way"]):
        score["shock"] += 2

    # Хайп / одобрение
    if any(x in text for x in ["круто", "топ", "имба", "кайф", "мощно", "сильно", "best", "cool", "nice", "great", "awesome"]):
        score["hype"] += 3

    # Грусть
    if any(x in text for x in ["груст", "печал", "жалко", "обидно", "плохо", "sad", "sorry", "unfortunately"]):
        score["sad"] += 3

    # Тепло / благодарность
    if any(x in text for x in ["спасибо", "благодар", "thanks", "thank you", "ty", "love you", "люблю"]):
        score["love"] += 3

    # Злость / раздражение
    if any(x in text for x in ["бесит", "злит", "ненавижу", "достал", "hate", "annoying", "angry", "mad"]):
        score["anger"] += 3

    # Эмодзи в сообщении тоже учитываем
    if any(x in text for x in ["😂", "🤣", "😭"]):
        score["funny"] += 2
    if any(x in text for x in ["🔥", "💯", "😎"]):
        score["hype"] += 2
    if any(x in text for x in ["😢", "💔", "🥲"]):
        score["sad"] += 2
    if any(x in text for x in ["😡", "🤬"]):
        score["anger"] += 2
    if any(x in text for x in ["😳", "😱", "👀"]):
        score["shock"] += 2
    if any(x in text for x in ["❤️", "🥰", "🙏"]):
        score["love"] += 2

    # Капс и длинные знаки препинания
    if len(text) > 4 and text.upper() == text and any(ch.isalpha() for ch in text):
        score["shock"] += 2

    best_label = max(score, key=score.get)
    best_score = score[best_label]

    if best_score == 0:
        return None, "neutral", 0

    skip_chances = {
        "funny": 0.20,
        "shock": 0.25,
        "hype": 0.20,
        "sad": 0.30,
        "love": 0.35,
        "anger": 0.40,
        "neutral": 0.85
    }

    if random.random() < skip_chances.get(best_label, 0.30):
        return None, best_label, best_score

    emoji = random.choice(REACTION_POOLS[best_label])
    return emoji, best_label, best_score


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
        print(f"reacted {emoji} | label={label} | score={score}")

    except FloodWaitError as e:
        print(f"FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print("ERROR:", e)


async def main():
    print("Starting Telegram client...")
    await client.start()
    print("Userbot started...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(main())