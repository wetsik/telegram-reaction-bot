# Telegram Reaction Bot

A lightweight Telegram bot built with Python and Telethon that reacts to messages, responds to mentions, and keeps group chats active through automated interactions.

## Features

- Automatic emoji reactions
- Smart message categorization
- Mention detection and replies
- Greeting responses
- Inactivity monitoring
- Initiative messages to keep chats active
- Quiet hours support
- Configurable reaction probability
- Lightweight rule-based classification
- Render deployment support

## Technologies

- Python 3.11+
- Telethon
- AsyncIO
- Render
- HTTP Health Check Server

## How It Works

The bot monitors messages in Telegram chats and:

1. Detects message categories.
2. Selects an appropriate reaction.
3. Reacts with emojis.
4. Replies when mentioned.
5. Sends initiative messages after long inactivity periods.
6. Respects configured quiet hours.

## Installation

Clone the repository:

```bash
git clone https://github.com/wetsik/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```env
API_ID=your_api_id
API_HASH=your_api_hash
STRING_SESSION=your_session
BOT_NAME=WestikBot
```

Run the bot:

```bash
python main.py
```

## Configuration

Example settings:

```python
REACTION_CHANCE = 1.0
INIT_MESSAGE_CHANCE = 0.35
INIT_MIN_GAP = 86400
QUIET_HOURS = {1,2,3,4,5,6}
```

## Deployment

The bot can be deployed on:

- Render
- VPS
- Docker
- Linux servers

## Roadmap

- AI-powered message understanding
- Personalized reactions
- Context-aware conversations
- Advanced analytics
- Database support
- Multi-chat management

## License

MIT License

## Author

Westik

GitHub: https://github.com/wetsik
