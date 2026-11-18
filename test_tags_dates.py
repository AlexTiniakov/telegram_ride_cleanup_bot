import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
import bot
from parser import TZ, has_ride_time, parse_ride_datetime
from test_moderation import ModerationTests

EXAMPLES = [
    ('#пасажир\n05.10\n7:30 - 8:00\nМотовилівка ( маленька школа) - Теремки ( Звіринецька)\n0500000000', '2026-10-05T08:05:00+03:00'),
    ('#пасажир\n1 людина\n04.10.\n21:00 ...21:30\nТеремки - Борова Білки\n0670000000', '2026-10-04T21:35:00+03:00'),
]
REF=datetime(2026,10,4,17,5,tzinfo=TZ)

class TagsAndDates(unittest.IsolatedAsyncioTestCase):
    def test_dates_and_ranges(self):
        for text,expected in EXAMPLES:
            for variant in (text,text.replace('\n','\r\n'),text.replace('...','…'),text.replace('05.10\n','05.10.\n'),text.replace('7:30 - 8:00','7.30 - 8.00')):
                self.assertTrue(has_ride_time(variant,REF),variant)
                parsed=parse_ride_datetime(variant,REF)
                self.assertIsNotNone(parsed,variant)
                self.assertEqual(parsed.delete_at.isoformat(),expected,variant)
        for text in ['#Водій 04.10. 21:00 ...21:30', '#Водій 04.10.\n21.00…21.30']:
            self.assertEqual(parse_ride_datetime(text,REF).delete_at.isoformat(),EXAMPLES[1][1])

    async def test_examples_are_scheduled_not_deleted(self):
        for text,expected in EXAMPLES:
            m=ModerationTests().message(text,date=REF)
            with patch.object(bot,'upsert_schedule') as schedule:
                await bot.process_post(m)
            m.delete.assert_not_awaited()
            self.assertEqual(schedule.call_args.args[1].delete_at.isoformat(),expected)

    async def test_missing_or_wrong_tag_deleted(self):
        for text in ['Дякую!', '#поїздка 17:30', 'Водій 17:30', None]:
            m=ModerationTests().message(text,content_type='photo' if text is None else 'text')
            with patch.object(bot,'remove_schedule') as remove:
                await bot.process_post(m)
            m.delete.assert_awaited_once()
            m.bot.send_message.assert_not_awaited()
            remove.assert_called_once()

    async def test_admin_without_tag_or_time_preserved(self):
        for status in ['administrator','creator']:
            m=ModerationTests().message('Важлива інформація')
            m.bot.get_chat_member.return_value=SimpleNamespace(status=status)
            with patch.object(bot,'remove_schedule'):
                await bot.process_post(m)
            m.delete.assert_not_awaited()

    async def test_missing_date_deleted_silently(self):
        for text in ('#Водій 17:30', '#Водій завтра 17:30', '#Водій 31.02 17:30'):
            m=ModerationTests().message(text)
            with patch.object(bot,'remove_schedule'):
                await bot.process_post(m)
            m.delete.assert_awaited_once()
            m.bot.send_message.assert_not_awaited()

    async def test_edit_removing_tag(self):
        m=ModerationTests().message('17:30',edit_date=REF)
        with patch.object(bot,'remove_schedule') as remove:
            await bot.process_post(m)
        remove.assert_called_once_with(-123,12)
        m.delete.assert_awaited_once()

    async def test_caption_allowed(self):
        m=ModerationTests().message(None,caption='#ПАСАЖИР 03.10 17:30',content_type='photo')
        with patch.object(bot,'upsert_schedule') as schedule:
            await bot.process_post(m)
        schedule.assert_called_once()
        m.delete.assert_not_awaited()

if __name__=='__main__':
    unittest.main()
