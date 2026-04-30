import random
import re

from telethon import functions, types
from settings import OWNER_USERNAME


BUSINESS_COMMAND_RE = re.compile(r"^\s*[/.]biz(?:\s+(?P<sub>\S+))?(?:\s+(?P<rest>.*))?\s*$", re.IGNORECASE | re.DOTALL)


def _all_private_recipients() -> types.InputBusinessRecipients:
    return types.InputBusinessRecipients(
        existing_chats=True,
        new_chats=True,
        contacts=True,
        non_contacts=True,
    )


def _help_text() -> str:
    return (
        "Команды бизнес-режима:\n"
        "/biz status - показать текущие настройки\n"
        "/biz away <text> - поставить away-сообщение для всех приватных чатов\n"
        "/biz away off - выключить away-сообщение\n"
        "/biz greet <text> - поставить greeting-сообщение для новых/неактивных чатов\n"
        "/biz greet off - выключить greeting-сообщение\n"
    )


def _is_authorized_sender(event, sender) -> bool:
    if getattr(event, "out", False):
        return True

    username = getattr(sender, "username", None)
    return bool(username and username.lower() == OWNER_USERNAME.lower())


async def _ensure_quick_reply_shortcut_id(client, shortcut_name: str, text: str) -> int:
    await client(
        functions.messages.SendMessageRequest(
            peer=types.InputPeerSelf(),
            message=text,
            random_id=random.getrandbits(63),
            quick_reply_shortcut=types.InputQuickReplyShortcut(shortcut_name),
        )
    )

    quick_replies = await client(functions.messages.GetQuickRepliesRequest(hash=0))
    for shortcut in getattr(quick_replies, "quick_replies", []):
        if getattr(shortcut, "shortcut", None) == shortcut_name:
            shortcut_id = getattr(shortcut, "shortcut_id", None)
            if shortcut_id is not None:
                return int(shortcut_id)

    raise RuntimeError(f"quick reply shortcut '{shortcut_name}' was not created")


def _business_status_lines(full_user, quick_replies) -> list[str]:
    lines: list[str] = []

    away = getattr(full_user, "business_away_message", None)
    greeting = getattr(full_user, "business_greeting_message", None)
    work_hours = getattr(full_user, "business_work_hours", None)
    location = getattr(full_user, "business_location", None)
    intro = getattr(full_user, "business_intro", None)

    lines.append(f"Away: {'включено' if away else 'выключено'}")
    lines.append(f"Greeting: {'включено' if greeting else 'выключено'}")
    lines.append(f"Рабочие часы: {'настроены' if work_hours else 'не настроены'}")
    lines.append(f"Локация: {'настроена' if location else 'не настроена'}")
    lines.append(f"Intro: {'настроен' if intro else 'не настроен'}")

    shortcuts = getattr(quick_replies, "quick_replies", []) or []
    if shortcuts:
        rendered = ", ".join(
            f"{getattr(item, 'shortcut', '?')}#{getattr(item, 'shortcut_id', '?')}"
            for item in shortcuts
        )
        lines.append(f"Быстрые ответы: {rendered}")
    else:
        lines.append("Быстрые ответы: нет")

    return lines


async def _send_business_status(event, client) -> None:
    me = await client.get_me()
    full_user = await client(functions.users.GetFullUserRequest(me))
    quick_replies = await client(functions.messages.GetQuickRepliesRequest(hash=0))

    lines = ["Статус бизнес-режима:", *_business_status_lines(full_user, quick_replies)]
    await event.respond("\n".join(lines))


async def _set_business_away(event, client, message_text: str) -> None:
    shortcut_id = await _ensure_quick_reply_shortcut_id(client, "biz-away", message_text)
    await client(
        functions.account.UpdateBusinessAwayMessageRequest(
            message=types.InputBusinessAwayMessage(
                shortcut_id=shortcut_id,
                schedule=types.BusinessAwayMessageScheduleAlways(),
                recipients=_all_private_recipients(),
                offline_only=False,
            )
        )
    )
    await event.respond("Away-сообщение сохранено.")


async def _disable_business_away(event, client) -> None:
    await client(functions.account.UpdateBusinessAwayMessageRequest())
    await event.respond("Away-сообщение выключено.")


async def _set_business_greeting(event, client, message_text: str) -> None:
    shortcut_id = await _ensure_quick_reply_shortcut_id(client, "biz-greet", message_text)
    await client(
        functions.account.UpdateBusinessGreetingMessageRequest(
            message=types.InputBusinessGreetingMessage(
                shortcut_id=shortcut_id,
                recipients=_all_private_recipients(),
                no_activity_days=7,
            )
        )
    )
    await event.respond("Greeting-сообщение сохранено.")


async def _disable_business_greeting(event, client) -> None:
    await client(functions.account.UpdateBusinessGreetingMessageRequest())
    await event.respond("Greeting-сообщение выключено.")


async def handle_private_business_command(event, client) -> bool:
    text = (event.raw_text or "").strip()
    if not text:
        return False

    sender = await event.get_sender()
    if not _is_authorized_sender(event, sender):
        return False

    match = BUSINESS_COMMAND_RE.match(text)
    if not match:
        return False

    sub = (match.group("sub") or "").lower()
    rest = (match.group("rest") or "").strip()

    if not sub or sub in {"help", "h", "?"}:
        await event.respond(_help_text())
        return True

    if sub == "status":
        await _send_business_status(event, client)
        return True

    if sub == "away":
        if not rest or rest.lower() in {"off", "disable", "disabled", "stop"}:
            await _disable_business_away(event, client)
            return True
        await _set_business_away(event, client, rest)
        return True

    if sub in {"greet", "greeting"}:
        if not rest or rest.lower() in {"off", "disable", "disabled", "stop"}:
            await _disable_business_greeting(event, client)
            return True
        await _set_business_greeting(event, client, rest)
        return True

    await event.respond(_help_text())
    return True
