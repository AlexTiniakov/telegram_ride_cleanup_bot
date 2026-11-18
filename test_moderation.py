import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage, DeleteMessage
import bot
from parser import has_ride_time, TZ

class ModerationTests(unittest.IsolatedAsyncioTestCase):
    def message(self, text='#Водій Борова — Київ', **kwargs):
        fields = dict(content_type="text", text=text, caption=None, date=datetime(2026,10,3,18,tzinfo=TZ),
                      edit_date=None, chat=SimpleNamespace(id=-123,type='supergroup'),
                      message_id=12, from_user=SimpleNamespace(id=456,is_bot=False),
                      sender_chat=None, delete=AsyncMock(), bot=SimpleNamespace(send_message=AsyncMock(),
                          get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member"))))
        fields.update(kwargs)
        return SimpleNamespace(**fields)

    async def test_silent_delete(self):
        m=self.message()
        with patch.object(bot,'remove_schedule') as remove:
            await bot.process_post(m)
        m.delete.assert_awaited_once()
        remove.assert_called_once_with(-123,12)
        m.bot.send_message.assert_not_awaited()

    async def test_delete_failed_no_notice(self):
        m=self.message()
        m.delete.side_effect=TelegramForbiddenError(method=DeleteMessage(chat_id=-123,message_id=12),message='forbidden')
        with patch.object(bot,'remove_schedule'):
            await bot.process_post(m)
        m.bot.send_message.assert_not_awaited()

    async def test_anonymous(self):
        m=self.message(sender_chat=SimpleNamespace(id=-123))
        with patch.object(bot,'remove_schedule'):
            await bot.process_post(m)
        m.delete.assert_not_awaited()
        m.bot.send_message.assert_not_awaited()

    async def test_regular_chat_and_private_messages_untouched(self):
        for m in [self.message(chat=SimpleNamespace(id=456,type='private')), self.message(content_type='new_chat_members', text=None)]:
            await bot.process_post(m)
            m.delete.assert_not_awaited()
            m.bot.send_message.assert_not_awaited()

    async def test_caption_and_edit(self):
        m=self.message(text=None,caption='#Пасажир 03.10,2026',edit_date=datetime.now(TZ))
        with patch.object(bot,'remove_schedule') as remove:
            await bot.process_post(m)
        m.delete.assert_awaited_once()
        remove.assert_called_once_with(-123,12)

    async def test_dated_time_scheduled(self):
        m=self.message('#Водій 04.10 06.30')
        with patch.object(bot,'upsert_schedule') as upsert:
            await bot.process_post(m)
        m.delete.assert_not_awaited()
        self.assertEqual(upsert.call_args.args[1].delete_at.isoformat(), '2026-10-04T06:35:00+03:00')

    def test_time_detection(self):
        ref=datetime(2026,10,3,18,tzinfo=TZ)
        for text in ['#Водій 03.10,2026', '#Водій 03.10.26', '#Водій 25.09', '#Водій 31.02.2026', '#Водій 3 жовтня 2026', '#Водій 130грн 096 882 32 17']:
            self.assertFalse(has_ride_time(text,ref),text)
        for text in ['#Водій 06.30', '#Водій 17.05', '#Водій 03.10,2026 5:30', '#Водій 31.02.2026 5:30', '#Водій 23.30–00.15']:
            self.assertTrue(has_ride_time(text,ref),text)

if __name__=='__main__':
    unittest.main()
