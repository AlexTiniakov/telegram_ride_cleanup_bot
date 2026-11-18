import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from parser import (TZ, POST_TAG_RE, ParsedRideTime, is_ride_date_allowed,
                    normalize_text, parse_ride_datetime)

CHECK_INTERVAL_SECONDS = 2
USER_CONTENT_TYPES = {
    "text", "animation", "audio", "document", "photo", "sticker", "video",
    "video_note", "voice", "contact", "dice", "game", "location", "poll",
    "venue", "story", "paid_media",
}
DB_PATH = Path(os.getenv("DB_PATH", "rides.sqlite3"))


def db_connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=3000")
    return con


def init_db() -> None:
    with db_connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_messages (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                trip_start TEXT NOT NULL,
                trip_end TEXT NOT NULL,
                delete_at TEXT NOT NULL,
                source_text TEXT,
                author_id INTEGER,
                PRIMARY KEY (chat_id, message_id)
            )
            """
        )

        columns = {row[1] for row in con.execute("PRAGMA table_info(scheduled_messages)")}
        if "author_id" not in columns:
            con.execute("ALTER TABLE scheduled_messages ADD COLUMN author_id INTEGER")


def upsert_schedule(message: Message, parsed: ParsedRideTime) -> None:
    with db_connect() as con:
        con.execute(
            """
            INSERT INTO scheduled_messages
                (chat_id, message_id, trip_start, trip_end, delete_at, source_text, author_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                trip_start=excluded.trip_start,
                trip_end=excluded.trip_end,
                delete_at=excluded.delete_at,
                source_text=excluded.source_text,
                author_id=excluded.author_id
            """,
            (
                message.chat.id,
                message.message_id,
                parsed.trip_start.isoformat(),
                parsed.trip_end.isoformat(),
                parsed.delete_at.isoformat(),
                (message.text or message.caption or "")[:4000],
                message.from_user.id,
            ),
        )


def remove_schedule(chat_id: int, message_id: int) -> None:
    with db_connect() as con:
        con.execute(
            "DELETE FROM scheduled_messages WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        )


def get_due(now: datetime) -> list[tuple[int, int, str, int]]:
    with db_connect() as con:
        return list(
            con.execute(
                """
                SELECT chat_id, message_id, delete_at, author_id
                FROM scheduled_messages
                WHERE delete_at <= ?
                ORDER BY delete_at ASC
                LIMIT 100
                """,
                (now.isoformat(),),
            )
        )


async def admin_status(bot: Bot, chat_id: int, user_id: int) -> bool | None:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    except TelegramAPIError as exc:
        logging.warning("Cannot verify author permissions chat=%s user=%s: %s",
                        chat_id, user_id, exc)
        return None
    # Other bots (e.g. @inbox_77bot) are moderated even when they are group admins.
    user = getattr(member, "user", None)
    if user is not None and user.is_bot:
        return False
    return member.status in ("creator", "administrator")


async def delete_invalid_post(message: Message, reason: str) -> None:
    # An edit may remove the time from an already scheduled announcement.
    remove_schedule(message.chat.id, message.message_id)
    try:
        await message.delete()
    except TelegramAPIError as exc:
        logging.warning("Cannot delete invalid post %s/%s: %s",
                        message.chat.id, message.message_id, exc)
        return
    logging.info("Deleted invalid post chat=%s msg=%s reason=%s",
                 message.chat.id, message.message_id, reason)


async def process_post(message: Message) -> None:
    if message.chat.type not in ("group", "supergroup"):
        return
    # Service events (joins, pins, etc.) are not participant announcements.
    if message.content_type not in USER_CONTENT_TYPES:
        return
    text = message.text or message.caption or ""
    # sender_chat includes anonymous admins; the actual author cannot be checked.
    if message.sender_chat is not None or message.from_user is None:
        remove_schedule(message.chat.id, message.message_id)
        return
    if message.from_user.id == getattr(message.bot, "id", None):
        return
    if message.from_user.is_bot:
        logging.info("Bot message chat=%s msg=%s from=@%s",
                     message.chat.id, message.message_id,
                     getattr(message.from_user, "username", None))
    status = await admin_status(message.bot, message.chat.id, message.from_user.id)
    if status is not False:
        remove_schedule(message.chat.id, message.message_id)
        return

    if not POST_TAG_RE.search(normalize_text(text)):
        await delete_invalid_post(message, "missing ride hashtag")
        return
    parsed = parse_ride_datetime(text, message.date)
    if parsed is None:
        await delete_invalid_post(message, "missing or invalid ride date/time")
        return
    # message.date is the original send time, so editing later cannot bypass this.
    if not is_ride_date_allowed(parsed.trip_start.date(), message.date):
        await delete_invalid_post(message, "ride date outside allowed window")
        return

    upsert_schedule(message, parsed)
    logging.info(
        "Scheduled chat=%s msg=%s: %s + %s -> delete %s",
        message.chat.id,
        message.message_id,
        parsed.date_text,
        parsed.time_text,
        parsed.delete_at.isoformat(),
    )


async def cleanup_once(bot: Bot) -> None:
    now = datetime.now(TZ)
    for chat_id, message_id, delete_at, author_id in get_due(now):
        # Preserve pre-migration jobs even though their authors were not stored.
        if author_id is not None:
            status = await admin_status(bot, chat_id, author_id)
            if status is None:
                continue
            if status:
                remove_schedule(chat_id, message_id)
                continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            logging.info("Deleted chat=%s msg=%s (due %s)", chat_id, message_id, delete_at)
            remove_schedule(chat_id, message_id)
        except TelegramBadRequest as exc:
            logging.warning("Cannot delete %s/%s: %s", chat_id, message_id, exc)
            # Usually this means the message was already removed or is >48h old.
            remove_schedule(chat_id, message_id)
        except TelegramForbiddenError as exc:
            logging.error(
                "No permission to delete in chat=%s. Give bot admin delete rights. %s",
                chat_id,
                exc,
            )
            remove_schedule(chat_id, message_id)
        except Exception:
            logging.exception("Unexpected delete error for %s/%s", chat_id, message_id)


async def cleanup_loop(bot: Bot) -> None:
    while True:
        await cleanup_once(bot)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Set BOT_TOKEN environment variable")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    init_db()
    bot = Bot(token=token)
    dp = Dispatcher()

    dp.message.register(process_post)
    dp.edited_message.register(process_post)

    cleanup_task = asyncio.create_task(cleanup_loop(bot))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
