import asyncio, logging, os, sqlite3, tempfile, sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, UTC

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, BusinessConnection, BusinessMessagesDeleted,
    InlineKeyboardMarkup, FSInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = "8836240355:AAFD7H2ZbqSVjjcFI677GSdSTQISv1MNv_k"
OWNER_ID = 1723294753
DB_PATH = "archive.db"
PROXY_URL = None
BOT_STARTED = datetime.now(UTC)

def _get_log_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent

    log_dir = base / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def _cleanup_old_logs(log_dir: Path, days: int = 7) -> None:
    import time as _time
    cutoff = _time.time() - days * 86400
    for f in log_dir.glob("silfy_saver_*.log*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass

log = logging.getLogger()

log.setLevel(logging.DEBUG)
log.propagate = False

fmt = logging.Formatter(
    "[%(asctime)s][%(name)s/%(levelname)s] %(message)s",
    datefmt="%d.%m.%Y %H:%M:%S",
)

console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.DEBUG)
console.setFormatter(fmt)
log.addHandler(console)

log_dir = _get_log_dir()
timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
log_file = log_dir / f"{timestamp}.log"
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(fmt)
log.addHandler(file_handler)
_cleanup_old_logs(log_dir, days=14)

MD_SPECIAL = set(r"_*[]()~`>#+-=|{}.!")


def esc(text) -> str:
    if text is None:
        return ""
    s = str(text)
    out = []
    for ch in s:
        if ch in MD_SPECIAL:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def b(text) -> str:
    return f"*{esc(text)}*"


def strike(text) -> str:
    return f"~{esc(text)}~"


def code(text) -> str:
    return f"`{esc(text)}`"


def quote(text) -> str:
    if text is None:
        text = ""
    lines = str(text).split("\n")
    return "\n".join(">" + esc(line) for line in lines)


async def safe_answer(message: Message, text: str, **kwargs):
    try:
        return await message.answer(text, **kwargs)
    except Exception as e:
        if "can't parse entities" in str(e):
            log.warning("MarkdownV2 сломался, шлю как plain: %s", e)
            kwargs.pop("parse_mode", None)
            return await message.answer(text, parse_mode=None, **kwargs)
        raise


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                business_connection_id  TEXT    NOT NULL,
                chat_id                 INTEGER NOT NULL,
                message_id              INTEGER NOT NULL,
                sender_id               INTEGER,
                sender_name             TEXT,
                text                    TEXT,
                media_type              TEXT,
                file_id                 TEXT,
                file_unique_id          TEXT,
                caption                 TEXT,
                date                    TEXT,
                is_deleted              INTEGER NOT NULL DEFAULT 0,
                is_edited               INTEGER NOT NULL DEFAULT 0,
                UNIQUE(business_connection_id, chat_id, message_id)
            );

            CREATE INDEX IF NOT EXISTS idx_msg_chat
                ON messages(business_connection_id, chat_id, message_id);
            CREATE INDEX IF NOT EXISTS idx_msg_deleted
                ON messages(is_deleted);
            CREATE INDEX IF NOT EXISTS idx_msg_edited
                ON messages(is_edited);

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id           INTEGER PRIMARY KEY,
                notify_deleted    INTEGER NOT NULL DEFAULT 1,
                notify_edited     INTEGER NOT NULL DEFAULT 1,
                notify_media      INTEGER NOT NULL DEFAULT 1,
                forward_media     INTEGER NOT NULL DEFAULT 0,
                notify_new        INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS connections (
                connection_id  TEXT PRIMARY KEY,
                user_id        INTEGER,
                is_enabled     INTEGER NOT NULL DEFAULT 1,
                created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bot_stats (
                key    TEXT PRIMARY KEY,
                value  INTEGER NOT NULL DEFAULT 0
            );
            """
        )

        cols = {r["name"] for r in conn.execute("PRAGMA table_info(user_settings)")}
        if "notify_new" not in cols:
            conn.execute(
                "ALTER TABLE user_settings "
                "ADD COLUMN notify_new INTEGER NOT NULL DEFAULT 0"
            )
            log.info("Миграция: добавлена колонка notify_new")

    log.info("База данных инициализирована: %s", DB_PATH)


def stat_inc(key: str, amount: int = 1) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO bot_stats (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = value + excluded.value
            """,
            (key, amount),
        )


def stat_get(key: str) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM bot_stats WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else 0


def user_stat_inc(user_id: int, key: str, amount: int = 1) -> None:
    stat_inc(f"u:{user_id}:{key}", amount)


def user_stat_get(user_id: int, key: str) -> int:
    return stat_get(f"u:{user_id}:{key}")


SETTING_KEYS = {
    "notify_deleted", "notify_edited", "notify_media",
    "forward_media", "notify_new",
}

SETTING_DEFAULTS = {
    "notify_deleted": 1,
    "notify_edited": 1,
    "notify_media": 1,
    "forward_media": 0,
    "notify_new": 0,
}


def ensure_settings(user_id: int) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)",
            (user_id,),
        )


def get_setting(user_id: int, key: str):
    if key not in SETTING_KEYS:
        raise ValueError(f"Недопустимый ключ: {key}")
    ensure_settings(user_id)
    with db() as conn:
        row = conn.execute(
            f"SELECT {key} FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row is None:
        return SETTING_DEFAULTS[key]
    value = row[key]
    if value is None:
        return SETTING_DEFAULTS[key]
    return value


def set_setting(user_id: int, key: str, value) -> None:
    if key not in SETTING_KEYS:
        raise ValueError(f"Недопустимый ключ: {key}")
    ensure_settings(user_id)
    with db() as conn:
        conn.execute(
            f"UPDATE user_settings SET {key} = ? WHERE user_id = ?",
            (value, user_id),
        )


def get_all_settings(user_id: int) -> dict:
    ensure_settings(user_id)
    with db() as conn:
        row = conn.execute(
            "SELECT notify_deleted, notify_edited, notify_media, "
            "forward_media, notify_new FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return dict(SETTING_DEFAULTS)
    return {
        "notify_deleted": row["notify_deleted"],
        "notify_edited": row["notify_edited"],
        "notify_media": row["notify_media"],
        "forward_media": row["forward_media"],
        "notify_new": row["notify_new"],
    }


def save_message(
    business_connection_id: str, chat_id: int, message_id: int,
    sender_id: int | None, sender_name: str,
    text: str | None, media_type: str | None,
    file_id: str | None, file_unique_id: str | None,
    caption: str | None,
) -> bool:
    with db() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO messages (
                business_connection_id, chat_id, message_id,
                sender_id, sender_name, text, media_type,
                file_id, file_unique_id, caption, date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                business_connection_id, chat_id, message_id,
                sender_id, sender_name, text, media_type,
                file_id, file_unique_id, caption,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        return cur.rowcount > 0


def get_message(business_connection_id: str, chat_id: int, message_id: int):
    with db() as conn:
        return conn.execute(
            """
            SELECT sender_name, text, media_type, file_id, caption
            FROM messages
            WHERE business_connection_id = ? AND chat_id = ? AND message_id = ?
            """,
            (business_connection_id, chat_id, message_id),
        ).fetchone()


def mark_deleted(bc_id: str, chat_id: int, message_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE messages SET is_deleted = 1
            WHERE business_connection_id = ? AND chat_id = ? AND message_id = ?
            """,
            (bc_id, chat_id, message_id),
        )


def update_edited(bc_id: str, chat_id: int, message_id: int,
                  new_text: str | None, new_caption: str | None) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE messages
            SET text = ?, caption = ?, is_edited = 1
            WHERE business_connection_id = ? AND chat_id = ? AND message_id = ?
            """,
            (new_text, new_caption, bc_id, chat_id, message_id),
        )


def get_archive_stats(user_id: int | None = None) -> dict:
    with db() as conn:
        if user_id is None:
            total = conn.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0]
            deleted = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE is_deleted = 1"
            ).fetchone()[0]
            edited = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE is_edited = 1"
            ).fetchone()[0]
            media = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE media_type IS NOT NULL"
            ).fetchone()[0]
            chats = conn.execute(
                "SELECT COUNT(DISTINCT chat_id) FROM messages"
            ).fetchone()[0]
        else:
            total = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE business_connection_id IN "
                "(SELECT connection_id FROM connections WHERE user_id = ?)",
                (user_id,),
            ).fetchone()[0]
            deleted = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE is_deleted = 1 "
                "AND business_connection_id IN "
                "(SELECT connection_id FROM connections WHERE user_id = ?)",
                (user_id,),
            ).fetchone()[0]
            edited = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE is_edited = 1 "
                "AND business_connection_id IN "
                "(SELECT connection_id FROM connections WHERE user_id = ?)",
                (user_id,),
            ).fetchone()[0]
            media = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE media_type IS NOT NULL "
                "AND business_connection_id IN "
                "(SELECT connection_id FROM connections WHERE user_id = ?)",
                (user_id,),
            ).fetchone()[0]
            chats = conn.execute(
                "SELECT COUNT(DISTINCT chat_id) FROM messages "
                "WHERE business_connection_id IN "
                "(SELECT connection_id FROM connections WHERE user_id = ?)",
                (user_id,),
            ).fetchone()[0]
    return {
        "total": total, "deleted": deleted, "edited": edited,
        "media": media, "chats": chats,
    }


def clear_archive(user_id: int | None = None) -> None:
    with db() as conn:
        if user_id is None:
            conn.execute("DELETE FROM messages")
        else:
            conn.execute(
                "DELETE FROM messages WHERE business_connection_id IN "
                "(SELECT connection_id FROM connections WHERE user_id = ?)",
                (user_id,),
            )
        conn.execute("VACUUM")


def export_archive(user_id: int | None = None) -> str:
    tmp = os.path.join(
        tempfile.gettempdir(),
        f"archive_{int(datetime.now().timestamp())}.db",
    )
    if user_id is None:
        with db() as conn:
            conn.execute(f"VACUUM INTO '{tmp}'")
    else:
        with db() as conn:
            conn2 = sqlite3.connect(tmp)
            try:
                conn2.executescript(
                    """
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        business_connection_id TEXT,
                        chat_id INTEGER,
                        message_id INTEGER,
                        sender_id INTEGER,
                        sender_name TEXT,
                        text TEXT,
                        media_type TEXT,
                        file_id TEXT,
                        file_unique_id TEXT,
                        caption TEXT,
                        date TEXT,
                        is_deleted INTEGER DEFAULT 0,
                        is_edited INTEGER DEFAULT 0
                    );
                    """
                )
                rows = conn.execute(
                    """
                    SELECT business_connection_id, chat_id, message_id,
                           sender_id, sender_name, text, media_type,
                           file_id, file_unique_id, caption, date,
                           is_deleted, is_edited
                    FROM messages
                    WHERE business_connection_id IN (
                        SELECT connection_id FROM connections WHERE user_id = ?
                    )
                    """,
                    (user_id,),
                ).fetchall()
                conn2.executemany(
                    """
                    INSERT INTO messages (
                        business_connection_id, chat_id, message_id,
                        sender_id, sender_name, text, media_type,
                        file_id, file_unique_id, caption, date,
                        is_deleted, is_edited
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [tuple(r) for r in rows],
                )
                conn2.commit()
            finally:
                conn2.close()
    return tmp


def save_connection(connection_id: str, user_id: int, is_enabled: bool) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO connections (connection_id, user_id, is_enabled)
            VALUES (?, ?, ?)
            ON CONFLICT(connection_id) DO UPDATE SET
                is_enabled = excluded.is_enabled,
                user_id = excluded.user_id
            """,
            (connection_id, user_id, 1 if is_enabled else 0),
        )


def get_connection_user(connection_id: str) -> int | None:
    with db() as conn:
        row = conn.execute(
            "SELECT user_id FROM connections WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()
    return row["user_id"] if row else None


def user_has_connection(user_id: int) -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM connections WHERE user_id = ? AND is_enabled = 1 LIMIT 1",
            (user_id,),
        ).fetchone()
    return row is not None


session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else AiohttpSession()
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
)
dp = Dispatcher()


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def m(v) -> str:
    return "🟢" if v else "🔴"


def human_delta(td) -> str:
    total = int(td.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if mins:
        parts.append(f"{mins}м")
    if not parts:
        parts.append(f"{secs}с")
    return " ".join(parts)


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Настройки", callback_data="menu:settings")
    kb.button(text="📊 Статистика", callback_data="menu:stats")
    kb.button(text="🌍 Общая статистика", callback_data="menu:gstats")
    kb.button(text="📥 Экспорт архива", callback_data="menu:export")
    kb.button(text="🗑 Очистить архив", callback_data="menu:clear")
    kb.button(text="ℹ️ О боте", callback_data="menu:about")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def user_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Мои настройки",
              callback_data=f"umenu:{user_id}:settings")
    kb.button(text="📊 Моя статистика",
              callback_data=f"umenu:{user_id}:stats")
    kb.button(text="📥 Экспорт архива",
              callback_data=f"umenu:{user_id}:export")
    kb.button(text="ℹ️ О боте",
              callback_data=f"umenu:{user_id}:about")
    kb.adjust(2, 2)
    return kb.as_markup()


def settings_kb(user_id: int) -> InlineKeyboardMarkup:
    s = get_all_settings(user_id)

    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"{m(s['notify_deleted'])} Уведомления об удалении",
        callback_data=f"toggle:{user_id}:notify_deleted",
    )
    kb.button(
        text=f"{m(s['notify_edited'])} Уведомления об изменении",
        callback_data=f"toggle:{user_id}:notify_edited",
    )
    kb.button(
        text=f"{m(s['notify_new'])} Уведомления о новых",
        callback_data=f"toggle:{user_id}:notify_new",
    )
    kb.button(
        text=f"{m(s['notify_media'])} Логировать медиа",
        callback_data=f"toggle:{user_id}:notify_media",
    )
    kb.button(
        text=f"{m(s['forward_media'])} Пересылать файлы при удалении",
        callback_data=f"toggle:{user_id}:forward_media",
    )
    kb.button(text="🔙 Назад", callback_data=f"back:{user_id}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_clear_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да, удалить всё",
              callback_data=f"clear:{user_id}:yes")
    kb.button(text="🔙 Отмена", callback_data=f"back:{user_id}")
    kb.adjust(2)
    return kb.as_markup()


MEDIA_EMOJI = {
    "photo": "🖼", "video": "🎬", "document": "📄",
    "voice": "🎤", "audio": "🎵", "sticker": "🩹",
    "animation": "🎞", "video_note": "📹",
}


def inline_diff(old: str, new: str, ctx: int = 40) -> str:
    if not old and not new:
        return ""
    old = old or ""
    new = new or ""

    i = 0
    minlen = min(len(old), len(new))
    while i < minlen and old[i] == new[i]:
        i += 1
    j = 0
    while j < (minlen - i) and old[len(old) - 1 - j] == new[len(new) - 1 - j]:
        j += 1

    prefix_raw = old[max(0, i - ctx):i]
    removed = old[i:len(old) - j] if j else old[i:]
    added = new[i:len(new) - j] if j else new[i:]
    suffix_raw = new[len(new) - j:len(new) - j + ctx] if j else ""

    parts = []
    if prefix_raw:
        parts.append("…" + esc(prefix_raw) if i > ctx else esc(prefix_raw))
    if removed:
        parts.append(strike(removed))
    if added:
        parts.append(b(added))
    if suffix_raw:
        parts.append(esc(suffix_raw) + ("…" if j > ctx else ""))

    return " ".join(parts)


def format_deleted(chat_id: int, sender_name: str,
                   text: str | None, media_type: str | None,
                   found: bool = True) -> str:
    lines = [
        "🗑 " + b("Сообщение удалено"),
        "",
        "👤 " + b("От:") + " " + esc(sender_name or "\\-"),
        "💬 " + b("Чат:") + " " + code(chat_id),
    ]

    if not found:
        lines.append("")
        lines.append("_Копия не найдена в архиве_")
        return "\n".join(lines)

    if media_type:
        emoji = MEDIA_EMOJI.get(media_type, "📎")
        lines.append(f"{emoji} " + b("Медиа:") + f" {esc(media_type)}")

    if text:
        preview = text if len(text) <= 900 else text[:900] + "…"
        lines.append("")
        lines.append("📝 " + b("Текст:"))
        lines.append(quote(preview))

    return "\n".join(lines)


def format_edited(chat_id: int, sender_name: str,
                  old_text: str | None, new_text: str | None) -> str:
    old_text = old_text or ""
    new_text = new_text or ""

    lines = [
        "✏️ " + b("Сообщение изменено"),
        "👤 " + b("От:") + " " + esc(sender_name or "\\-"),
        "💬 " + b("Чат:") + " " + code(chat_id),
    ]

    lines.append(b("Было:"))
    lines.append(quote(old_text) if old_text else "_- пусто -_")
    lines.append(b("Стало:"))
    lines.append(quote(new_text) if new_text else "_- пусто -_")

    diff = inline_diff(old_text, new_text)
    if diff:
        lines.append(b("Изменения:"))
        lines.append("> " + diff)

    return "\n".join(lines)


def format_new(chat_id: int, sender_name: str,
               text: str | None, media_type: str | None) -> str:
    lines = [
        "🆕 " + b("Новое сообщение"),
        "👤 " + b("От:") + " " + esc(sender_name or "\\-"),
        "💬 " + b("Чат:") + " " + code(chat_id),
    ]
    if media_type:
        emoji = MEDIA_EMOJI.get(media_type, "📎")
        lines.append(f"{emoji} " + b("Медиа:") + f" {esc(media_type)}")
    if text:
        preview = text if len(text) <= 400 else text[:400] + "…"
        lines.append("")
        lines.append(quote(preview))
    return "\n".join(lines)


def extract_media(message: Message):
    if message.photo:
        p = message.photo[-1]
        return "photo", p.file_id, p.file_unique_id
    if message.video:
        return "video", message.video.file_id, message.video.file_unique_id
    if message.document:
        return "document", message.document.file_id, message.document.file_unique_id
    if message.voice:
        return "voice", message.voice.file_id, message.voice.file_unique_id
    if message.audio:
        return "audio", message.audio.file_id, message.audio.file_unique_id
    if message.sticker:
        return "sticker", message.sticker.file_id, message.sticker.file_unique_id
    if message.animation:
        return "animation", message.animation.file_id, message.animation.file_unique_id
    if message.video_note:
        return "video_note", message.video_note.file_id, message.video_note.file_unique_id
    return None, None, None


def user_stats_text(user_id: int) -> str:
    a = get_archive_stats(user_id)
    uptime = human_delta(datetime.now(UTC) - BOT_STARTED)
    connected = user_has_connection(user_id)

    return "\n".join([
        "📊 " + b("Моя статистика"),
        "",
        "👤 " + b("Профиль"),
        f"├ ID: {code(user_id)}",
        f"├ Статус подключения: {'🟢 активно' if connected else '🔴 нет'}",
        f"└ Аптайм бота: {esc(uptime)}",
        "",
        "📨 " + b("Мои сообщения"),
        f"├ Всего обработано: {esc(user_stat_get(user_id, 'messages_seen'))}",
        f"├ Сохранено в архив: {esc(a['total'])}",
        f"├ Медиа: {esc(a['media'])}",
        f"└ Уникальных чатов: {esc(a['chats'])}",
        "",
        "📝 " + b("Мои события"),
        f"├ Удалений: {esc(a['deleted'])}",
        f"├ Изменений: {esc(a['edited'])}",
        f"└ Уведомлений отправлено: {esc(user_stat_get(user_id, 'notifications_sent'))}",
        "",
        "🤖 " + b("Использование"),
        f"└ Команд выполнено: {esc(user_stat_get(user_id, 'commands_total'))}",
    ])


def user_settings_text(user_id: int) -> str:
    s = get_all_settings(user_id)

    def mark(v):
        return "🟢 включено" if v else "🔴 выключено"

    return "\n".join([
        "⚙️ " + b("Мои настройки"),
        "",
        "Персональные параметры архиватора для вашего аккаунта\\.",
        "",
        "🔔 " + b("Уведомления"),
        f"├ Удаление: {esc(mark(s['notify_deleted']))}",
        f"├ Изменение: {esc(mark(s['notify_edited']))}",
        f"└ Новые сообщения: {esc(mark(s['notify_new']))}",
        "",
        "📎 " + b("Медиа"),
        f"├ Логировать: {esc(mark(s['notify_media']))}",
        f"└ Пересылать файлы при удалении: {esc(mark(s['forward_media']))}",
        "",
        "Нажмите на кнопку ниже, чтобы изменить параметр\\.",
    ])


def global_stats_text() -> str:
    a = get_archive_stats(None)
    uptime = human_delta(datetime.now(UTC) - BOT_STARTED)

    return "\n".join([
        "🌍 " + b("Общая статистика"),
        "",
        "🕐 " + b("Сессия бота"),
        f"├ Аптайм: {esc(uptime)}",
        f"├ Обработано апдейтов: {esc(stat_get('updates_total'))}",
        f"└ Подключений Business: {esc(stat_get('connections_total'))}",
        "",
        "📨 " + b("Сообщения"),
        f"├ Всего обработано: {esc(stat_get('messages_seen'))}",
        f"├ Сохранено в архив: {esc(a['total'])}",
        f"├ Медиа: {esc(a['media'])}",
        f"└ Уникальных чатов: {esc(a['chats'])}",
        "",
        "📝 " + b("События"),
        f"├ Удалений: {esc(a['deleted'])}",
        f"├ Изменений: {esc(a['edited'])}",
        f"└ Уведомлений отправлено: {esc(stat_get('notifications_sent'))}",
        "",
        "🤖 " + b("Использование"),
        f"└ Команд выполнено: {esc(stat_get('commands_total'))}",
    ])


def about_text() -> str:
    return "\n".join([
        "ℹ️ " + b("О боте"),
        b("Silfy Saver") + " \\- архиватор сообщений через " + b("Telegram Business") + "\\.",
        "",
        "• Работает без входа в аккаунт",
        "• При удалении \\- достаёт копию",
        "• При редактировании \\- показывает разницу",
    ])


@dp.message(Command("start"))
async def cmd_start(message: Message):
    stat_inc("commands_total")
    uid = message.from_user.id
    user_stat_inc(uid, "commands_total")
    ensure_settings(uid)

    if is_owner(uid):
        await safe_answer(message,
            "\n".join([
                "🛡 " + b("Silfy Saver") + " \\- архиватор бизнес\\-сообщений",
                "",
                "Бот сохраняет все сообщения подключённого Telegram Business "
                "аккаунта и уведомляет об удалении и редактировании\\.",
            ]),
            reply_markup=main_menu_kb(),
        )
    else:
        await safe_answer(message,
            "\n".join([
                "🛡 " + b("Silfy Saver") + " \\- архиватор бизнес\\-сообщений",
                "",
                "Подключите бота к своему Telegram Business аккаунту "
                "в настройках Telegram, и он начнёт архивировать ваши "
                "сообщения\\.",
                "",
                "Все настройки персональные \\- управляйте ими в разделе "
                + b("Мои настройки") + "\\.",
            ]),
            reply_markup=user_menu_kb(uid),
        )


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    stat_inc("commands_total")
    uid = message.from_user.id
    user_stat_inc(uid, "commands_total")
    kb = main_menu_kb() if is_owner(uid) else user_menu_kb(uid)
    await safe_answer(message, user_stats_text(uid), reply_markup=kb)


@dp.message(Command("globalstats"))
async def cmd_globalstats(message: Message):
    if not is_owner(message.from_user.id):
        return
    stat_inc("commands_total")
    user_stat_inc(message.from_user.id, "commands_total")
    await safe_answer(message, global_stats_text(), reply_markup=main_menu_kb())


@dp.message(Command("settings"))
async def cmd_settings(message: Message):
    stat_inc("commands_total")
    uid = message.from_user.id
    user_stat_inc(uid, "commands_total")
    ensure_settings(uid)
    kb = settings_kb(uid)
    if is_owner(uid):
        await safe_answer(message, user_settings_text(uid), reply_markup=kb)
    else:
        await safe_answer(message, user_settings_text(uid), reply_markup=kb)


@dp.message(Command("mysettings"))
async def cmd_mysettings(message: Message):
    await cmd_settings(message)


@dp.message(Command("about"))
async def cmd_about(message: Message):
    stat_inc("commands_total")
    uid = message.from_user.id
    user_stat_inc(uid, "commands_total")
    kb = main_menu_kb() if is_owner(uid) else user_menu_kb(uid)
    await safe_answer(message, about_text(), reply_markup=kb)


@dp.message(Command("export"))
async def cmd_export(message: Message):
    stat_inc("commands_total")
    uid = message.from_user.id
    user_stat_inc(uid, "commands_total")
    try:
        path = export_archive(uid)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        await message.answer_document(
            FSInputFile(path, filename="archive.db"),
            caption="📥 " + b("Экспорт архива")
                    + f"\nРазмер: {esc(f'{size_mb:.2f}')} МБ",
        )
        os.remove(path)
    except Exception as e:
        log.exception("Ошибка экспорта")
        await message.answer("⚠️ Ошибка экспорта: " + esc(e))


@dp.callback_query(F.data == "menu:main")
async def cb_main(cb: CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    stat_inc("commands_total")
    await cb.message.edit_text(
        "🛡 " + b("Silfy Saver") + " \\- панель управления",
        reply_markup=main_menu_kb(),
    )
    await cb.answer()


@dp.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    stat_inc("commands_total")
    uid = cb.from_user.id
    ensure_settings(uid)
    await cb.message.edit_text(user_settings_text(uid),
                               reply_markup=settings_kb(uid))
    await cb.answer()


@dp.callback_query(F.data == "menu:stats")
async def cb_stats(cb: CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    stat_inc("commands_total")
    await cb.message.edit_text(user_stats_text(cb.from_user.id),
                               reply_markup=main_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:gstats")
async def cb_gstats(cb: CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    stat_inc("commands_total")
    await cb.message.edit_text(global_stats_text(),
                               reply_markup=main_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:about")
async def cb_about(cb: CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    stat_inc("commands_total")
    await cb.message.edit_text(about_text(), reply_markup=main_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:export")
async def cb_export(cb: CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    stat_inc("commands_total")
    await cb.answer("Готовлю файл…")
    try:
        path = export_archive(cb.from_user.id)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        await cb.message.answer_document(
            FSInputFile(path, filename="archive.db"),
            caption="📥 " + b("Экспорт архива")
                    + f"\nРазмер: {esc(f'{size_mb:.2f}')} МБ",
        )
        os.remove(path)
    except Exception as e:
        log.exception("Ошибка экспорта")
        await cb.message.answer("⚠️ Ошибка экспорта: " + esc(e))


@dp.callback_query(F.data == "menu:clear")
async def cb_clear(cb: CallbackQuery):
    if not is_owner(cb.from_user.id):
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    stat_inc("commands_total")
    await cb.message.edit_text(
        "🗑 " + b("Очистка архива") + "\n\n"
        "Вы уверены? Все сохранённые сообщения будут удалены "
        + b("без возможности восстановления") + "\\.",
        reply_markup=confirm_clear_kb(cb.from_user.id),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("umenu:"))
async def cb_user_menu(cb: CallbackQuery):
    _, target_uid, action = cb.data.split(":", 2)
    target_uid = int(target_uid)

    if cb.from_user.id != target_uid:
        await cb.answer("Доступ запрещён", show_alert=True)
        return

    user_stat_inc(target_uid, "commands_total")
    ensure_settings(target_uid)

    if action == "main":
        await cb.message.edit_text(
            "🛡 " + b("Silfy Saver") + " \\- меню пользователя",
            reply_markup=user_menu_kb(target_uid),
        )
        await cb.answer()
    elif action == "settings":
        await cb.message.edit_text(
            user_settings_text(target_uid),
            reply_markup=settings_kb(target_uid),
        )
        await cb.answer()
    elif action == "stats":
        await cb.message.edit_text(
            user_stats_text(target_uid),
            reply_markup=user_menu_kb(target_uid),
        )
        await cb.answer()
    elif action == "about":
        await cb.message.edit_text(
            about_text(),
            reply_markup=user_menu_kb(target_uid),
        )
        await cb.answer()
    elif action == "export":
        await cb.answer("Готовлю файл…")
        try:
            path = export_archive(target_uid)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            await cb.message.answer_document(
                FSInputFile(path, filename="archive.db"),
                caption="📥 " + b("Экспорт архива")
                        + f"\nРазмер: {esc(f'{size_mb:.2f}')} МБ",
            )
            os.remove(path)
        except Exception as e:
            log.exception("Ошибка экспорта")
            await cb.message.answer("⚠️ Ошибка экспорта: " + esc(e))


@dp.callback_query(F.data.startswith("back:"))
async def cb_back(cb: CallbackQuery):
    target_uid = int(cb.data.split(":", 1)[1])
    if cb.from_user.id != target_uid:
        await cb.answer("Доступ запрещён", show_alert=True)
        return

    if is_owner(target_uid):
        await cb.message.edit_text(
            "🛡 " + b("Silfy Saver") + " \\- панель управления",
            reply_markup=main_menu_kb(),
        )
    else:
        await cb.message.edit_text(
            "🛡 " + b("Silfy Saver") + " \\- меню пользователя",
            reply_markup=user_menu_kb(target_uid),
        )
    await cb.answer()


@dp.callback_query(F.data.startswith("clear:"))
async def cb_clear_yes(cb: CallbackQuery):
    _, target_uid, action = cb.data.split(":")
    target_uid = int(target_uid)

    if cb.from_user.id != target_uid:
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    if not is_owner(target_uid):
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    if action != "yes":
        await cb.answer()
        return
    try:
        clear_archive(None)
        await cb.message.edit_text(
            "✅ " + b("Архив очищен\\."),
            reply_markup=main_menu_kb(),
        )
    except Exception as e:
        log.exception("Ошибка очистки")
        await cb.message.edit_text("⚠️ Ошибка: " + esc(e))
    await cb.answer()


@dp.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(cb: CallbackQuery):
    _, target_uid, key = cb.data.split(":", 2)
    target_uid = int(target_uid)

    if cb.from_user.id != target_uid:
        await cb.answer("Доступ запрещён", show_alert=True)
        return
    if key not in SETTING_KEYS:
        await cb.answer("Неизвестная настройка", show_alert=True)
        return

    current = get_setting(target_uid, key)
    set_setting(target_uid, key, 0 if current else 1)

    try:
        await cb.message.edit_text(
            user_settings_text(target_uid),
            reply_markup=settings_kb(target_uid),
        )
    except Exception:
        await cb.message.edit_reply_markup(
            reply_markup=settings_kb(target_uid)
        )
    await cb.answer("Сохранено ✅")


@dp.business_connection()
async def on_business_connection(connection: BusinessConnection):
    save_connection(connection.id, connection.user.id, connection.is_enabled)
    ensure_settings(connection.user.id)

    uid = connection.user.id

    if connection.is_enabled:
        stat_inc("connections_total")
        user_stat_inc(uid, "connections_total")

    try:
        if connection.is_enabled:
            text = "\n".join([
                "✅ " + b("Подключение установлено"),
                "",
                "Бот начал архивировать сообщения из вашего "
                "Telegram Business аккаунта\\.",
                "",
                "Управляйте настройками в разделе "
                + b("Мои настройки") + "\\.",
            ])
            kb = main_menu_kb() if is_owner(uid) else user_menu_kb(uid)
            await bot.send_message(uid, text, reply_markup=kb)
        else:
            text = "\n".join([
                "🔌 " + b("Подключение разорвано"),
                "",
                "Архивирование приостановлено\\.",
            ])
            await bot.send_message(uid, text)
    except Exception as e:
        log.warning("Не удалось уведомить владельца: %s", e)


@dp.business_message()
async def on_business_message(message: Message):
    bc_id = message.business_connection_id
    if not bc_id:
        return

    uid = get_connection_user(bc_id) or OWNER_ID
    ensure_settings(uid)

    stat_inc("messages_seen")
    user_stat_inc(uid, "messages_seen")

    media_type, file_id, file_uid = extract_media(message)
    sender = message.from_user
    sender_name = sender.full_name if sender else "Unknown"

    inserted = save_message(
        business_connection_id=bc_id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        sender_id=sender.id if sender else None,
        sender_name=sender_name,
        text=message.text,
        media_type=media_type,
        file_id=file_id,
        file_unique_id=file_uid,
        caption=message.caption,
    )
    if not inserted:
        return

    if get_setting(uid, "notify_new"):
        text = format_new(
            chat_id=message.chat.id,
            sender_name=sender_name,
            text=message.text or message.caption,
            media_type=media_type,
        )
        try:
            await bot.send_message(uid, text)
            stat_inc("notifications_sent")
            user_stat_inc(uid, "notifications_sent")
        except Exception as e:
            log.warning("Ошибка уведомления о новом: %s", e)


@dp.edited_business_message()
async def on_edited_business_message(message: Message):
    bc_id = message.business_connection_id
    if not bc_id:
        return

    uid = get_connection_user(bc_id) or OWNER_ID
    ensure_settings(uid)

    old_row = get_message(bc_id, message.chat.id, message.message_id)
    old_text = None
    if old_row is not None:
        old_text = old_row["text"] or old_row["caption"]

    new_text = message.text or message.caption

    update_edited(
        bc_id, message.chat.id, message.message_id,
        message.text, message.caption,
    )

    if not get_setting(uid, "notify_edited"):
        return

    sender_name = message.from_user.full_name if message.from_user else "\\-"
    text = format_edited(
        chat_id=message.chat.id,
        sender_name=sender_name,
        old_text=old_text,
        new_text=new_text,
    )
    try:
        await bot.send_message(uid, text)
        stat_inc("notifications_sent")
        user_stat_inc(uid, "notifications_sent")
    except Exception as e:
        log.warning("Ошибка уведомления об изменении: %s", e)


@dp.deleted_business_messages()
async def on_deleted_business_messages(event: BusinessMessagesDeleted):
    bc_id = event.business_connection_id
    chat_id = event.chat.id

    uid = get_connection_user(bc_id) or OWNER_ID
    ensure_settings(uid)

    if not get_setting(uid, "notify_deleted"):
        return

    for msg_id in event.message_ids:
        row = get_message(bc_id, chat_id, msg_id)
        mark_deleted(bc_id, chat_id, msg_id)

        if row is None:
            text = format_deleted(
                chat_id=chat_id, sender_name="\\-",
                text=None, media_type=None, found=False,
            )
            try:
                await bot.send_message(uid, text)
                stat_inc("notifications_sent")
                user_stat_inc(uid, "notifications_sent")
            except Exception as e:
                log.warning("Ошибка уведомления об удалении: %s", e)
            continue

        sender_name = row["sender_name"] or "\\-"
        body = row["text"] or row["caption"]
        media_type = row["media_type"]
        file_id = row["file_id"]
        caption = row["caption"]

        text = format_deleted(
            chat_id=chat_id, sender_name=sender_name,
            text=body, media_type=media_type, found=True,
        )
        try:
            await bot.send_message(uid, text)
            stat_inc("notifications_sent")
            user_stat_inc(uid, "notifications_sent")
        except Exception as e:
            log.warning("Ошибка отправки уведомления: %s", e)

        if media_type and file_id and get_setting(uid, "forward_media"):
            await send_media(uid, file_id, media_type, caption)


async def send_media(uid: int, file_id: str, media_type: str,
                     caption: str | None) -> None:
    try:
        if media_type == "photo":
            await bot.send_photo(uid, file_id, caption=caption)
        elif media_type == "video":
            await bot.send_video(uid, file_id, caption=caption)
        elif media_type == "document":
            await bot.send_document(uid, file_id, caption=caption)
        elif media_type == "voice":
            await bot.send_voice(uid, file_id)
        elif media_type == "audio":
            await bot.send_audio(uid, file_id)
        elif media_type == "sticker":
            await bot.send_sticker(uid, file_id)
        elif media_type == "animation":
            await bot.send_animation(uid, file_id, caption=caption)
        elif media_type == "video_note":
            await bot.send_video_note(uid, file_id)
    except Exception as e:
        log.warning("Не удалось переслать медиа (%s): %s", media_type, e)
        try:
            await bot.send_message(
                uid,
                "⚠️ Не удалось переслать медиа: " + esc(e),
            )
        except Exception:
            pass


async def main():
    init_db()
    ensure_settings(OWNER_ID)

    me = await bot.get_me()
    log.info("Бот запущен: @%s (id=%s)", me.username, me.id)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен.")