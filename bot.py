import asyncio
import threading

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from group_reactions import (
    configure_group_services,
    get_local_hour,
    handle_group_message,
    maybe_start_inactivity_loop,
    sync_bot_identity,
)
from health_server import run_health_server
from settings import (
    API_HASH,
    API_ID,
    BOT_NAME,
    BOT_STAGE,
    BOT_VERSION,
    ENABLE_INIT_MESSAGES,
    INACTIVITY_CHECK_INTERVAL,
    INACTIVITY_TRIGGER,
    INIT_MESSAGE_CHANCE,
    INIT_MIN_GAP,
    SESSION_STRING,
    TEST_INIT_PRIVATE_ONLY,
    TZ_OFFSET,
)
from vocal_remover import handle_private_vocal_remover


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

        if event.is_private:
            await handle_private_vocal_remover(event, client)
        else:
            await handle_group_message(event)

    except Exception as e:
        print(f"HANDLER ERROR: {e}")


async def run_bot_forever():
    inactivity_task = None

    while True:
        try:
            print(f"Starting {BOT_NAME} {BOT_VERSION} [{BOT_STAGE}]...")
            await client.start()

            me = await client.get_me()
            sync_bot_identity(me)
            print(
                f"{BOT_NAME} {BOT_VERSION} [{BOT_STAGE}] logged in as: "
                f"{me.first_name} (@{me.username})"
            )

            print("TZ_OFFSET =", TZ_OFFSET)
            print("LOCAL_HOUR =", get_local_hour())
            print("ENABLE_INIT_MESSAGES =", ENABLE_INIT_MESSAGES)
            print("INACTIVITY_TRIGGER =", INACTIVITY_TRIGGER)
            print("INACTIVITY_CHECK_INTERVAL =", INACTIVITY_CHECK_INTERVAL)
            print("INIT_MESSAGE_CHANCE =", INIT_MESSAGE_CHANCE)
            print("INIT_MIN_GAP =", INIT_MIN_GAP)
            print("TEST_INIT_PRIVATE_ONLY =", TEST_INIT_PRIVATE_ONLY)

            inactivity_task = maybe_start_inactivity_loop(inactivity_task)

            print("Userbot started and listening for new messages...")
            await client.run_until_disconnected()

        except Exception as e:
            print(f"MAIN ERROR: {e}")

        print("Restarting in 5 seconds...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(run_bot_forever())
