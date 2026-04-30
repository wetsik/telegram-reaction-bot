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
from business_tools import handle_private_business_command
from business_bot import run_business_bot_forever
from business_state import mark_business_chat_responded
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
from private_greeting import maybe_send_private_greeting
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

        if event.out and event.is_private:
            mark_business_chat_responded(event.chat_id)

        if event.is_private:
            await maybe_send_private_greeting(event, client)

            handled = await handle_private_business_command(event, client)
            if handled:
                return

            handled = await handle_private_vocal_remover(event, client)
            if handled:
                return

        if event.out:
            return

        await handle_group_message(event)

    except Exception as e:
        print(f"HANDLER ERROR: {e}")


async def run_bot_forever():
    inactivity_task = None
    business_task = None

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
            if business_task is None or business_task.done():
                business_task = asyncio.create_task(run_business_bot_forever())

            print("Userbot started and listening for new messages...")
            await client.run_until_disconnected()

        except Exception as e:
            print(f"MAIN ERROR: {e}")

        print("Restarting in 5 seconds...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(run_bot_forever())
