import asyncio
import re
import sqlite3
import threading
import time

from settings import DB_PATH, MAX_MESSAGES_PER_CHAT


# Широкий диапазон эмодзи (символы, пиктограммы, флаги, доп. символы).
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0001F000-\U0001F0FF"
    "]"
)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                sender TEXT,
                text TEXT NOT NULL,
                label TEXT,
                has_emoji INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_chat_label
                ON messages(chat_id, label);
            CREATE TABLE IF NOT EXISTS emoji_stats (
                chat_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, emoji)
            );
            """
        )
        _conn.commit()
    return _conn


def extract_emojis(text: str) -> list[str]:
    return EMOJI_PATTERN.findall(text or "")


def _save_message(chat_id: int, sender: str, text: str, label: str) -> None:
    emojis = extract_emojis(text)
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO messages (chat_id, sender, text, label, has_emoji, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, sender, text, label, 1 if emojis else 0, int(time.time())),
        )
        for emoji in emojis:
            conn.execute(
                "INSERT INTO emoji_stats (chat_id, emoji, count) VALUES (?, ?, 1) "
                "ON CONFLICT(chat_id, emoji) DO UPDATE SET count = count + 1",
                (chat_id, emoji),
            )
        # Изредка подрезаем историю чата, чтобы БД не росла бесконечно.
        cur = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,)
        )
        total = cur.fetchone()[0]
        if total > MAX_MESSAGES_PER_CHAT:
            conn.execute(
                "DELETE FROM messages WHERE chat_id = ? AND id NOT IN ("
                "  SELECT id FROM messages WHERE chat_id = ? "
                "  ORDER BY id DESC LIMIT ?"
                ")",
                (chat_id, chat_id, MAX_MESSAGES_PER_CHAT),
            )
        conn.commit()


def _random_learned_reply(
    chat_id: int,
    label: str | None,
    min_len: int,
    max_len: int,
    exclude: set[str],
) -> str | None:
    with _lock:
        conn = _connect()
        rows: list[tuple[str]] = []
        if label:
            rows = conn.execute(
                "SELECT text FROM messages "
                "WHERE chat_id = ? AND label = ? "
                "AND length(text) BETWEEN ? AND ? "
                "ORDER BY RANDOM() LIMIT 20",
                (chat_id, label, min_len, max_len),
            ).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT text FROM messages "
                "WHERE chat_id = ? AND length(text) BETWEEN ? AND ? "
                "ORDER BY RANDOM() LIMIT 20",
                (chat_id, min_len, max_len),
            ).fetchall()

    for (text,) in rows:
        candidate = (text or "").strip()
        if candidate and candidate.lower() not in exclude:
            return candidate
    return None


def _popular_emojis(chat_id: int, limit: int) -> list[str]:
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT emoji FROM emoji_stats WHERE chat_id = ? "
            "ORDER BY count DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [row[0] for row in rows]


async def save_message(chat_id: int, sender: str, text: str, label: str) -> None:
    try:
        await asyncio.to_thread(_save_message, chat_id, sender, text, label)
    except Exception as error:
        print(f"DB save failed: {type(error).__name__}: {error}")


async def random_learned_reply(
    chat_id: int,
    label: str | None = None,
    min_len: int = 2,
    max_len: int = 80,
    exclude: set[str] | None = None,
) -> str | None:
    try:
        return await asyncio.to_thread(
            _random_learned_reply, chat_id, label, min_len, max_len, exclude or set()
        )
    except Exception as error:
        print(f"DB learned reply failed: {type(error).__name__}: {error}")
        return None


async def popular_emojis(chat_id: int, limit: int = 10) -> list[str]:
    try:
        return await asyncio.to_thread(_popular_emojis, chat_id, limit)
    except Exception as error:
        print(f"DB popular emojis failed: {type(error).__name__}: {error}")
        return []
