import sqlite3
from datetime import datetime

DB_PATH = "bot_data.db"


def get_connection() -> sqlite3.Connection:
    """اتصال به دیتابیس SQLite"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """ساخت جداول دیتابیس در صورت نبود + مهاجرت برای نسخه‌های قبلی"""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id   INTEGER PRIMARY KEY,
                blocked_at TEXT NOT NULL,
                reason    TEXT DEFAULT 'مسدود شده توسط ادمین'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id   INTEGER,
                user_id     INTEGER NOT NULL,
                username    TEXT,
                text        TEXT,
                media_type  TEXT,
                category    TEXT,
                timestamp   TEXT NOT NULL,
                replied     INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS thread_links (
                bot_message_id INTEGER NOT NULL,
                user_id        INTEGER NOT NULL,
                thread_id      INTEGER NOT NULL,
                PRIMARY KEY (bot_message_id, user_id)
            )
        """)
        # مهاجرت ستون‌های جدید برای دیتابیس‌های قدیمی‌تر
        for stmt in [
            "ALTER TABLE messages ADD COLUMN thread_id INTEGER",
            "ALTER TABLE messages ADD COLUMN category TEXT",
        ]:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        # برای پیام‌های قدیمی که thread_id ندارند، خودشان را thread می‌کنیم
        conn.execute("UPDATE messages SET thread_id = id WHERE thread_id IS NULL")
        conn.commit()


# -------- blocked_users --------

def block_user(user_id: int, reason: str = "مسدود شده توسط ادمین") -> None:
    """مسدود کردن کاربر"""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO blocked_users (user_id, blocked_at, reason) VALUES (?, ?, ?)",
            (user_id, datetime.now().isoformat(), reason)
        )
        conn.commit()


def unblock_user(user_id: int) -> bool:
    """رفع مسدودیت کاربر — True اگر کاربر واقعاً مسدود بوده"""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0


def is_blocked(user_id: int) -> bool:
    """بررسی مسدود بودن کاربر"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row is not None


def get_all_blocked() -> list[dict]:
    """لیست تمام کاربران مسدود شده"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT user_id, blocked_at, reason FROM blocked_users ORDER BY blocked_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# -------- messages & threads --------

def save_message(
    user_id: int,
    username: str,
    text: str | None,
    media_type: str | None = None,
    category: str | None = None,
    thread_id: int | None = None,
) -> tuple[int, int]:
    """ذخیره پیام در دیتابیس.

    اگر thread_id داده نشود، یک گفتگوی (thread) جدید ساخته می‌شود.
    خروجی: (شماره پیام, شماره گفتگو)
    """
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO messages (thread_id, user_id, username, text, media_type, category, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (thread_id, user_id, username, text, media_type, category, datetime.now().isoformat())
        )
        new_id = cur.lastrowid
        if thread_id is None:
            conn.execute("UPDATE messages SET thread_id = ? WHERE id = ?", (new_id, new_id))
            thread_id = new_id
        conn.commit()
        return new_id, thread_id


def mark_thread_replied(thread_id: int) -> None:
    """علامت‌گذاری تمام پیام‌های یک گفتگو به عنوان پاسخ داده شده"""
    with get_connection() as conn:
        conn.execute("UPDATE messages SET replied = 1 WHERE thread_id = ?", (thread_id,))
        conn.commit()


def save_thread_link(bot_message_id: int, user_id: int, thread_id: int) -> None:
    """ذخیره ارتباط بین پیام ارسالی ربات به کاربر و شماره گفتگو
    (برای تشخیص اینکه کاربر روی کدام گفتگو ریپلای می‌زند)"""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO thread_links (bot_message_id, user_id, thread_id) VALUES (?, ?, ?)",
            (bot_message_id, user_id, thread_id)
        )
        conn.commit()


def get_thread_link(bot_message_id: int, user_id: int) -> int | None:
    """گرفتن شماره گفتگو از روی پیامی که کاربر به آن ریپلای کرده است"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT thread_id FROM thread_links WHERE bot_message_id = ? AND user_id = ?",
            (bot_message_id, user_id)
        ).fetchone()
        return row["thread_id"] if row else None


def get_stats() -> dict:
    """آمار کلی ربات"""
    with get_connection() as conn:
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        unique_users = conn.execute("SELECT COUNT(DISTINCT user_id) FROM messages").fetchone()[0]
        blocked_count = conn.execute("SELECT COUNT(*) FROM blocked_users").fetchone()[0]
        unanswered = conn.execute("SELECT COUNT(*) FROM messages WHERE replied = 0").fetchone()[0]
        return {
            "total_messages": total_messages,
            "unique_users": unique_users,
            "blocked_count": blocked_count,
            "unanswered": unanswered,
        }


def get_category_stats() -> dict:
    """تعداد پیام‌ها به تفکیک دسته‌بندی"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM messages WHERE category IS NOT NULL GROUP BY category"
        ).fetchall()
        return {r["category"]: r["cnt"] for r in rows}
