from telethon import TelegramClient
from telethon.sessions import StringSession

api_id = 22649873
api_hash = "f53a5170f5a73698f85ffc587b1d2c6a"

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print(client.session.save())