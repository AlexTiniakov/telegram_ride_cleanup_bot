import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bot
from parser import TZ, parse_ride_datetime, is_ride_date_allowed
from test_moderation import ModerationTests


def at(day, hour, minute=0, month=11):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


class RideDateWindow(unittest.TestCase):
    def test_window(self):
        cases = [
            # (posted at, ride text date, allowed)
            (at(18, 8), '18.11', True),     # today, any time
            (at(18, 23, 59), '18.11', True),
            (at(18, 14, 59), '19.11', False),  # tomorrow before 15:00
            (at(18, 15, 0), '19.11', True),    # tomorrow from 15:00
            (at(18, 22), '19.11', True),
            (at(18, 22), '20.11', False),      # day after tomorrow: never
            (at(18, 22), '25.12', False),
            (at(18, 10), '17.11', True),       # past: cleaned up right away
        ]
        for posted, date_text, allowed in cases:
            parsed = parse_ride_datetime(f'#Водій {date_text} 07:30', posted)
            self.assertIsNotNone(parsed, date_text)
            self.assertEqual(is_ride_date_allowed(parsed.trip_start.date(), posted),
                             allowed, (posted, date_text))

    def test_new_year_rollover(self):
        self.assertTrue(is_ride_date_allowed(
            parse_ride_datetime('#Водій 01.01 07:30', at(31, 16, month=12)).trip_start.date(),
            at(31, 16, month=12)))
        self.assertFalse(is_ride_date_allowed(
            parse_ride_datetime('#Водій 01.01 07:30', at(31, 10, month=12)).trip_start.date(),
            at(31, 10, month=12)))

    def test_utc_message_date_uses_kyiv_time(self):
        # Telegram sends UTC: 13:00 UTC is 15:00 in Kyiv (winter, UTC+2).
        from datetime import timezone
        posted = datetime(2026, 11, 18, 13, 0, tzinfo=timezone.utc)
        ride = parse_ride_datetime('#Водій 19.11 07:30', posted).trip_start.date()
        self.assertTrue(is_ride_date_allowed(ride, posted))
        posted = datetime(2026, 11, 18, 12, 59, tzinfo=timezone.utc)
        self.assertFalse(is_ride_date_allowed(ride, posted))


class WindowModeration(unittest.IsolatedAsyncioTestCase):
    async def run_post(self, text, date, **kwargs):
        m = ModerationTests().message(text, date=date, **kwargs)
        with patch.object(bot, 'upsert_schedule') as upsert, patch.object(bot, 'remove_schedule'):
            await bot.process_post(m)
        return m, upsert

    async def test_tomorrow_too_early_deleted(self):
        m, upsert = await self.run_post('#Пасажир 19.11 07:30', at(18, 9))
        m.delete.assert_awaited_once()
        upsert.assert_not_called()

    async def test_tomorrow_after_15_scheduled(self):
        m, upsert = await self.run_post('#Пасажир 19.11 07:30', at(18, 15, 1))
        m.delete.assert_not_awaited()
        upsert.assert_called_once()

    async def test_edit_keeps_original_send_time(self):
        # Posted at 09:00, edited at 16:00: still too early.
        m, upsert = await self.run_post('#Пасажир 19.11 07:30', at(18, 9), edit_date=at(18, 16))
        m.delete.assert_awaited_once()

    async def test_admin_exempt_from_window(self):
        m = ModerationTests().message('#Водій 25.11 07:30', date=at(18, 9))
        m.bot.get_chat_member.return_value = SimpleNamespace(
            status='administrator', user=SimpleNamespace(is_bot=False))
        with patch.object(bot, 'remove_schedule'):
            await bot.process_post(m)
        m.delete.assert_not_awaited()


class BotAuthors(unittest.IsolatedAsyncioTestCase):
    def bot_message(self, text, status='administrator'):
        m = ModerationTests().message(
            text, date=at(18, 10),
            from_user=SimpleNamespace(id=777, is_bot=True, username='inbox_77bot'))
        m.bot.get_chat_member.return_value = SimpleNamespace(
            status=status, user=SimpleNamespace(id=777, is_bot=True))
        return m

    async def test_admin_bot_spam_deleted(self):
        for status in ('administrator', 'creator', 'member'):
            m = self.bot_message('Анонімне повідомлення', status)
            with patch.object(bot, 'remove_schedule'):
                await bot.process_post(m)
            m.delete.assert_awaited_once()

    async def test_admin_bot_valid_post_scheduled_and_deleted_later(self):
        m = self.bot_message('#Водій 18.11 17:00')
        with patch.object(bot, 'upsert_schedule') as upsert, patch.object(bot, 'remove_schedule'):
            await bot.process_post(m)
        m.delete.assert_not_awaited()
        upsert.assert_called_once()

        client = SimpleNamespace(
            delete_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(
                status='administrator', user=SimpleNamespace(is_bot=True))))
        with patch.object(bot, 'get_due', return_value=[(-123, 12, 'due', 777)]), \
                patch.object(bot, 'remove_schedule'):
            await bot.cleanup_once(client)
        client.delete_message.assert_awaited_once_with(chat_id=-123, message_id=12)

    async def test_own_messages_ignored(self):
        m = self.bot_message('Анонімне повідомлення')
        m.bot.id = 777
        with patch.object(bot, 'remove_schedule'):
            await bot.process_post(m)
        m.delete.assert_not_awaited()

    async def test_human_admin_still_exempt(self):
        m = ModerationTests().message('Оголошення адміна')
        m.bot.get_chat_member.return_value = SimpleNamespace(
            status='administrator', user=SimpleNamespace(is_bot=False))
        with patch.object(bot, 'remove_schedule'):
            await bot.process_post(m)
        m.delete.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
