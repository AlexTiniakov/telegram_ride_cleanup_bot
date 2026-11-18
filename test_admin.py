import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import GetChatMember
from test_moderation import ModerationTests
from parser import parse_ride_datetime
import bot

class AdminTests(unittest.IsolatedAsyncioTestCase):
    async def test_admins_never_deleted_or_scheduled(self):
        for status in ('creator','administrator'):
            for text in ('#Водій Київ', '#Водій 06:30'):
                m=ModerationTests().message(text)
                m.bot.get_chat_member.return_value=SimpleNamespace(status=status)
                with patch.object(bot,'remove_schedule') as remove, patch.object(bot,'upsert_schedule') as upsert:
                    await bot.process_post(m)
                m.delete.assert_not_awaited()
                upsert.assert_not_called()
                remove.assert_called_once_with(-123,12)

    async def test_permission_error_does_not_delete(self):
        m=ModerationTests().message()
        m.bot.get_chat_member.side_effect=TelegramForbiddenError(method=GetChatMember(chat_id=-123,user_id=456),message='unavailable')
        with patch.object(bot,'remove_schedule'):
            await bot.process_post(m)
        m.delete.assert_not_awaited()

    async def test_due_permissions(self):
        for status, deleted, removed in [('creator',False,True),('administrator',False,True),('member',True,True), (None,False,False)]:
            client=SimpleNamespace(delete_message=AsyncMock())
            with patch.object(bot,'get_due',return_value=[(-123,12,'due',456)]), patch.object(bot,'admin_status',new=AsyncMock(return_value=None if status is None else status in ('creator','administrator'))) as lookup, patch.object(bot,'remove_schedule') as remove:
                await bot.cleanup_once(client)
            lookup.assert_awaited_once_with(client,-123,456)
            self.assertEqual(client.delete_message.await_count, int(deleted))
            self.assertEqual(remove.call_count, int(removed))

    async def test_legacy_jobs_still_execute(self):
        client=SimpleNamespace(delete_message=AsyncMock())
        with patch.object(bot,'get_due',return_value=[(-123,12,'due',None)]), patch.object(bot,'remove_schedule') as remove:
            await bot.cleanup_once(client)
        client.delete_message.assert_awaited_once_with(chat_id=-123, message_id=12)
        remove.assert_called_once()

    def test_migration_and_author_persistence(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bot,'DB_PATH',Path(directory)/'test.sqlite3'):
            with sqlite3.connect(bot.DB_PATH) as con:
                con.execute('CREATE TABLE scheduled_messages (chat_id INTEGER, message_id INTEGER, trip_start TEXT, trip_end TEXT, delete_at TEXT, source_text TEXT, PRIMARY KEY(chat_id,message_id))')
                con.execute("INSERT INTO scheduled_messages VALUES (1,2,'old','old','old','old')")
            bot.init_db()
            with bot.db_connect() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM scheduled_messages').fetchone()[0],1)
                self.assertIsNone(con.execute('SELECT author_id FROM scheduled_messages').fetchone()[0])
                con.execute('DELETE FROM scheduled_messages')
            m=ModerationTests().message('#Водій 04.10 06:30')
            parsed=parse_ride_datetime(m.text,m.date)
            bot.upsert_schedule(m,parsed)
            bot.init_db()  # Repeated migrations preserve identified authors.
            self.assertEqual(bot.get_due(parsed.delete_at),[(-123,12,parsed.delete_at.isoformat(),456)])
            m.from_user.id=789
            bot.upsert_schedule(m,parsed)
            self.assertEqual(bot.get_due(parsed.delete_at)[0][3],789)

if __name__=='__main__':
    unittest.main()
