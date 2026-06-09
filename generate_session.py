"""Одноразовый скрипт для генерации SESSION_STRING обычного аккаунта (userbot).

Запусти:  python generate_session.py
Введи номер телефона (в формате +7999...), затем код из Telegram (и пароль 2FA,
если включён). В конце скопируй выведенную строку в .env как SESSION_STRING.

ВАЖНО: это вход под аккаунтом-ЧЕЛОВЕКОМ, не под ботом. Не вводи bot token.
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

from settings import API_HASH, API_ID


def main() -> None:
    with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        me = client.get_me()
        if getattr(me, "bot", False):
            print("Ты вошёл как БОТ. Нужен обычный аккаунт. Перезапусти и войди по номеру телефона.")
            return
        print("\nВошёл как:", me.first_name, f"(@{me.username})")
        print("\n=== Твой SESSION_STRING (вставь в .env) ===\n")
        print(client.session.save())
        print("\n===========================================")


if __name__ == "__main__":
    main()
