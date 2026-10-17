import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import types
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

# Uzbekistan uses UTC+5; fixed offset also works on Windows without tzdata.
TASHKENT = timezone(timedelta(hours=5), 'Asia/Tashkent')


def format_time(timestamp):
    return datetime.fromtimestamp(timestamp, TASHKENT).strftime('%d.%m.%Y %H:%M')


def parse_time(text, now=None):
    now = time.time() if now is None else now
    text = text.strip().casefold()
    relative = re.fullmatch(r'(\d{1,6})\s*(m|min|daqiqa|h|soat|d|kun)', text)
    if relative:
        unit = relative.group(2)
        seconds = 60 if unit in ('m', 'min', 'daqiqa') else 3600 if unit in ('h', 'soat') else 86400
        due = int(now) + int(relative.group(1)) * seconds
    else:
        try:
            due = int(datetime.strptime(text, '%d.%m.%Y %H:%M').replace(tzinfo=TASHKENT).timestamp())
        except ValueError as exc:
            raise ValueError('Masalan: 10 daqiqa, 2 soat, 1 kun yoki 25.12.2026 09:00.') from exc
    if due <= now or due > now + 5 * 366 * 86400:
        raise ValueError('Vaqt kelajakda va 5 yil ichida bo‘lsin.')
    return due


async def deliver_due(bot, store, owner_id):
    store.purge()
    now = time.time()
    due = [r for r in store.reminders() if r['next_attempt'] <= now][:20]
    for reminder in due:
        item_id, due_at = reminder['item_id'], reminder['due_at']
        # Earlier sends yielded control; a later reminder may have been cancelled or changed.
        current = next((r for r in store.reminders() if r['item_id'] == item_id), None)
        if not current or current['due_at'] != due_at or current['next_attempt'] > time.time():
            continue
        reminder = current
        markup = types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text='📖 Yozuvni ochish', callback_data=f'view:{item_id}')]])
        try:
            await bot.send_message(owner_id, f"⏰ Eslatma: {reminder['title']}\n🕒 {format_time(due_at)}",
                                   reply_markup=markup)
        except TelegramRetryAfter as exc:
            store.finish_reminder(item_id, due_at, max(60, int(exc.retry_after)))
        except TelegramAPIError as exc:
            logging.warning('Reminder delivery failed: %s', type(exc).__name__)
            store.finish_reminder(item_id, due_at, min(3600, 60 * 2 ** min(reminder['attempts'], 6)))
        else:
            store.finish_reminder(item_id, due_at)


async def reminder_loop(bot, store, owner_id):
    while True:
        try:
            await deliver_due(bot, store, owner_id)
        except Exception as exc:
            logging.error('Reminder worker failed: %s', type(exc).__name__)
        await asyncio.sleep(15)
