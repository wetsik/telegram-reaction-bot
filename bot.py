import os
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

EMOJIS = [
    "😂", "🤣", "💀", "😭", "😹", "😆",
    "😳", "😱", "👀", "🤯", "😮",
    "🔥", "💯", "⚡", "😎", "🚀", "👏",
    "😢", "💔", "🥲",
    "❤️", "🥰", "💖", "🙏",
    "😡", "🤦", "👍", "🙂", "🗿"
]

MIN_DELAY = float(os.environ.get("MIN_DELAY", "0.3"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "1.2"))
REACTION_CHANCE = float(os.environ.get("REACTION_CHANCE", "1.0"))


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


@client.on(events.NewMessage)
async def handle_new_message(event):
    if event.out:
        return

    if random.random() > REACTION_CHANCE:
        return

    try:
        emoji = random.choice(EMOJIS)

        await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        await client(functions.messages.SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.id,
            big=False,
            add_to_recent=True,
            reaction=[types.ReactionEmoji(emoticon=emoji)]
        ))

        print(f"reacted {emoji} to message {event.id}")

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