import json
import sqlite3
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from aiogram import types
from aiogram.methods import SendMessage
from aiogram.exceptions import TelegramNetworkError

import test_bot
from yordamchibot.content import extract, inline_result
from yordamchibot.handlers import item_markup
from yordamchibot.reminders import deliver_due, parse_time
from yordamchibot.storage import Store, TRASH_SECONDS
from yordamchibot.transfer import export_data, validate_import


class FeatureTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_bot.BotTests.asyncSetUp
    asyncTearDown = test_bot.BotTests.asyncTearDown
    send = test_bot.BotTests.send
    query = test_bot.BotTests.query
    click = test_bot.BotTests.click

    async def test_private_share_and_trash(self):
        i = self.store.add('secret', dict(kind='text', text='body'))
        self.assertTrue(item_markup(self.store.get(i)).inline_keyboard[0][0].switch_inline_query)
        await self.click(f'private:{i}')
        self.assertEqual((await self.query(text=f'#id:{i}')).results, [])
        self.assertEqual((await self.query()).results, [])
        self.assertTrue(self.store.search())  # Owner's library still includes private records.
        self.assertFalse(any(b.switch_inline_query for row in item_markup(self.store.get(i)).inline_keyboard for b in row))
        with self.assertRaises(ValueError):
            inline_result(self.store.get(i))
        await self.click(f'private:{i}')
        self.assertEqual(len((await self.query(text=f'#id:{i}')).results), 1)
        self.store.set_reminder(i, int(time.time()) + 3600)
        await self.click(f'confirm:{i}')
        self.assertEqual((await self.query(text=f'#id:{i}')).results, [])
        self.assertEqual(self.store.reminders(), [])
        await self.click(f'restore:{i}')
        self.assertIsNotNone(self.store.get(i))
        self.store.delete(i)
        self.store.db.execute('UPDATE items SET deleted_at=? WHERE id=?', (int(time.time()) - TRASH_SECONDS - 1, i))
        self.store.db.commit()
        self.assertFalse(self.store.restore(i))

    async def test_categories_tags_favorite_search_stats(self):
        i = self.store.add('Ўзбекистон ҳужжатлари', dict(kind='text', text='Muhim hujjat'))
        self.store.add('Other', dict(kind='text', text='unrelated'))
        await self.click(f'category:{i}')
        await self.send('Ish')
        await self.click(f'tags:{i}')
        await self.send('#muhim, loyiha, muhim')
        await self.click(f'favorite:{i}')
        self.assertEqual(self.store.get(i)['tags'], ['muhim', 'loyiha'])
        self.assertEqual(self.store.categories()[0]['category'], 'Ish')
        self.assertEqual(self.store.search()[0]['id'], i)
        for query in ["O‘zbekiston", 'hujatlar', 'лойиҳа', 'иш']:
            self.assertEqual(self.store.search(query)[0]['id'], i)
        self.assertEqual(len(self.store.search(favorites=True)), 1)
        self.assertEqual(len(self.store.search(category='Ish')), 1)
        await self.send('/search ҳужжат')
        self.assertIn('Qidiruv', self.bot.session.make_request.call_args.args[1].text)
        await self.send('📊 Statistika')
        self.assertIn('Faol yozuvlar: 2', self.bot.session.make_request.call_args.args[1].text)
        await self.send('🗂 Kategoriyalar')
        self.assertIn('Ish', self.bot.session.make_request.call_args.args[1].reply_markup.inline_keyboard[0][0].text)

    async def test_all_media_extraction_and_results(self):
        cases = [('voice', dict(duration=1)), ('audio', dict(duration=1)),
                 ('animation', dict(duration=1, width=32, height=32, mime_type='image/gif')),
                 ('animation', dict(duration=1, width=32, height=32, mime_type='video/mp4'))]
        for n, (kind, fields) in enumerate(cases):
            await self.send(**{kind: dict(file_id=f'file{n}', file_unique_id=f'unique{n}', **fields)},
                            caption='Izoh', caption_entities=[dict(type='bold', offset=0, length=4)])
            await self.send(f'media{n}')
        found = await self.query()
        self.assertEqual({r.type for r in found.results}, {'voice', 'audio', 'gif', 'mpeg4_gif'})
        for result in found.results:
            self.assertEqual(result.caption, 'Izoh')
            self.assertEqual(result.caption_entities[0].type, 'bold')
        await self.click('view:1')  # Voice preview and controls.
        methods = [type(call.args[1]).__name__ for call in self.bot.session.make_request.call_args_list]
        self.assertIn('SendVoice', methods)

    async def test_legacy_migration_preserves_data(self):
        path = self.path.parent / 'legacy.db'
        db = sqlite3.connect(path)
        db.execute('''CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,
            payload TEXT NOT NULL,search_text TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        payload = {'kind': 'text', 'text': 'Ўзбекистон', 'entities': []}
        db.execute('INSERT INTO items(title,payload,search_text) VALUES(?,?,?)', ('Old', json.dumps(payload), 'old'))
        db.commit()
        db.close()
        migrated = Store(path)
        try:
            first = migrated.get(1)
            self.assertEqual(first['payload'], payload)
            self.assertEqual(first['private'], 0)
            self.assertTrue(first['uid'])
            self.assertEqual(migrated.search("o'zbekiston")[0]['id'], 1)
        finally:
            migrated.close()
        reopened = Store(path)
        self.assertEqual(reopened.get(1)['uid'], first['uid'])
        reopened.close()

    async def test_export_import_roundtrip_atomic_and_no_duplicates(self):
        i = self.store.add('private', dict(kind='text', text='😀bold', entities=[dict(type='bold', offset=2, length=4)]),
                           category='Ish', tags=['tag'], private=True, favorite=True)
        removed = self.store.add('deleted', dict(kind='photo', file_id='photo', caption=''))
        self.store.delete(removed)
        raw = export_data(self.store, self.bot.id)
        entries = validate_import(raw, self.bot.id)
        self.assertEqual(self.store.import_items(entries), 0)
        imported = Store(self.path.parent / 'imported.db')
        try:
            self.assertEqual(imported.import_items(entries), 2)
            self.assertTrue(imported.get(i)['private'])
            self.assertEqual(imported.get(i)['category'], 'Ish')
            self.assertEqual(len(imported.search(trash=True)), 1)
            self.assertEqual(imported.import_items(entries), 0)
        finally:
            imported.close()
        with self.assertRaises(ValueError):
            validate_import(raw, 999)
        malformed = json.loads(raw)
        malformed['items'][1]['payload']['kind'] = 'unsupported'
        with self.assertRaises(ValueError):
            validate_import(json.dumps(malformed).encode(), self.bot.id)
        self.assertEqual(self.store.stats()['total'], 1)
        self.assertEqual(self.store.stats()['trash'], 1)

    async def test_import_requires_confirmation_cancel_and_permissions(self):
        i = self.store.add('Title', dict(kind='text', text='Body'))
        exported = json.loads(export_data(self.store, self.bot.id))
        exported['items'][0]['uid'] = '22222222-2222-4222-8222-222222222222'
        raw = json.dumps(exported).encode()
        async def download(_bot, file, destination):
            destination.write(raw)
        await self.send('/import')
        with patch('aiogram.Bot.download', new=download):
            await self.send(document=dict(file_id='json', file_unique_id='j', file_name='data.json', file_size=len(raw)))
        result = self.bot.session.make_request.call_args.args[1]
        data = result.reply_markup.inline_keyboard[0][0].callback_data
        self.assertEqual(self.store.stats()['total'], 1)
        await self.click(data, owner=99)
        self.assertEqual(self.store.stats()['total'], 1)
        await self.click(data)
        self.assertEqual(self.store.stats()['total'], 2)
        await self.click(data)
        self.assertEqual(self.store.stats()['total'], 2)
        await self.send('/import')
        with patch('aiogram.Bot.download', new=download):
            await self.send(document=dict(file_id='json', file_unique_id='j', file_name='data.json'))
        data = self.bot.session.make_request.call_args.args[1].reply_markup.inline_keyboard[0][0].callback_data
        await self.send('/cancel')
        await self.click(data)
        self.assertEqual(self.store.stats()['total'], 2)
        await self.send('/export', owner=99)
        self.assertEqual(self.store.get(i)['title'], 'Title')

    async def test_reminder_time_delivery_retry_and_restart(self):
        now = datetime(2026, 10, 17, 7, tzinfo=timezone.utc).timestamp()
        self.assertEqual(parse_time('17.10.2026 12:10', now), now + 600)
        self.assertEqual(parse_time('2 soat', now), now + 7200)
        with self.assertRaises(ValueError):
            parse_time('0 daqiqa', now)
        with self.assertRaises(ValueError):
            parse_time('17.10.2026 11:59', now)
        i = self.store.add('Reminder', dict(kind='text', text='Body'), private=True)
        await self.click(f'remind:{i}')
        await self.send('10 daqiqa')
        self.assertEqual(len(self.store.reminders()), 1)
        await self.click(f'unremind:{i}')
        self.assertEqual(self.store.reminders(), [])
        due = int(time.time()) - 60
        self.store.db.execute('INSERT INTO reminders(item_id,due_at,next_attempt) VALUES(?,?,?)', (i, due, due))
        self.store.db.commit()
        self.store.close()
        self.store = Store(self.path)
        reopened = self.store
        bot = AsyncMock()
        bot.send_message.side_effect = TelegramNetworkError(method=SendMessage(chat_id=42, text='x'), message='offline')
        await deliver_due(bot, reopened, 42)
        self.assertEqual(reopened.reminders()[0]['attempts'], 1)
        self.assertGreater(reopened.reminders()[0]['next_attempt'], time.time())
        reopened.db.execute('UPDATE reminders SET next_attempt=?', (due,))
        reopened.db.commit()
        bot.send_message.side_effect = None
        await deliver_due(bot, reopened, 42)
        self.assertEqual(reopened.reminders(), [])
        bot.send_message.assert_awaited_with(42, unittest.mock.ANY, reply_markup=unittest.mock.ANY)
        await deliver_due(bot, reopened, 42)
        self.assertEqual(bot.send_message.await_count, 2)

    async def test_old_keyboard_and_new_menu_dont_get_saved(self):
        await self.send('content')
        await self.send('Ma’lumotlarim')
        await self.send('📚 Ma’lumotlarim')
        await self.send('title')
        self.assertEqual(self.store.stats()['total'], 1)
        await self.send('/start')
        result = self.bot.session.make_request.call_args.args[1]
        self.assertEqual(len(result.reply_markup.keyboard), 5)

    async def test_reminders_rescheduled_or_cancelled_during_delivery(self):
        ids = [self.store.add(str(n), dict(kind='text', text='Body')) for n in range(2)]
        due = int(time.time()) - 60
        for i in ids:
            self.store.db.execute('INSERT INTO reminders(item_id,due_at,next_attempt) VALUES(?,?,?)', (i, due, due))
        self.store.db.commit()
        future = int(time.time()) + 3600
        async def send(*args, **kwargs):
            self.store.set_reminder(ids[0], future)
            self.store.cancel_reminder(ids[1])
        bot = AsyncMock()
        bot.send_message.side_effect = send
        await deliver_due(bot, self.store, 42)
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(self.store.reminders()[0]['due_at'], future)
