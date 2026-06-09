import asyncio
import threading

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from group_reactions import (
    configure_group_services,
    handle_group_message,
    load_available_reactions,
    load_top_reactions,
    sync_bot_identity,
)
from health_server import run_health_server
from settings import (
    API_HASH,
    API_ID,
    BOT_NAME,
    BOT_STAGE,
    BOT_VERSION,
    SESSION_STRING,
)


client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH,
)
configure_group_services(client)


@client.on(events.NewMessage())
async def handle_new_message(event):
    try:
        if not event.message:
            return

        if event.out:
            return

        await handle_group_message(event)

    except Exception as e:
        print(f"HANDLER ERROR: {e}")


async def run_bot_forever():
    while True:
        try:
            print(f"Starting {BOT_NAME} {BOT_VERSION} [{BOT_STAGE}]...")
            await client.start()

            me = await client.get_me()
            sync_bot_identity(me)
            # Глобальный список валидных реакций — работает и для ботов.
            await load_available_reactions(client)
            if getattr(me, "bot", False):
                print(
                    "Note: BOT account — top reactions are restricted, using the "
                    "available-reactions set + per-chat allowed reactions."
                )
            else:
                # Топ-реакции (персональный порядок) — только для юзер-аккаунтов.
                await load_top_reactions(client)
            print(
                f"{BOT_NAME} {BOT_VERSION} [{BOT_STAGE}] logged in as: "
                f"{me.first_name} (@{me.username})"
            )

            print("Userbot started and listening for new messages...")
            await client.run_until_disconnected()

        except Exception as e:
            print(f"MAIN ERROR: {e}")

        print("Restarting in 5 seconds...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(run_bot_forever())
