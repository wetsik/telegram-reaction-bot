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

MIN_DELAY = float(os.environ.get("MIN_DELAY", "0.3"))
MAX_DELAY = float(os.environ.get("MAX_DELAY", "1.2"))
REACTION_CHANCE = float(os.environ.get("REACTION_CHANCE", "1.0"))
PORT = int(os.environ.get("PORT", "10000"))

EMOJIS = [
    "😂", "🤣", "💀", "😭", "😹", "😆",
    "😳", "😱", "👀", "🤯", "😮",
    "🔥", "💯", "⚡", "😎", "🚀", "👏",
    "😢", "💔", "🥲",
    "❤️", "🥰", "💖", "🙏",
    "😡", "🤦", "👍", "🙂", "🗿"
]

client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"not found")

    def log_message(self, format, *args):
        return


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Health server started on port {PORT}")
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

        print(f"Reacted {emoji} to message {event.id} in chat {event.chat_id}")

    except FloodWaitError as e:
        print(f"FloodWait: sleeping for {e.seconds} seconds")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print(f"ERROR while reacting: {e}")


async def run_bot_forever():
    while True:
        try:
            print("Starting Telegram client...")
            await client.start()
            print("Userbot started and listening for new messages...")
            await client.run_until_disconnected()

        except Exception as e:
            print(f"MAIN ERROR: {e}")

        print("Restarting in 5 seconds...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(run_bot_forever())