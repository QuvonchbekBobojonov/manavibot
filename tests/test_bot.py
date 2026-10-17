import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher, types
from yordamchibot.__main__ import create_router
from yordamchibot.storage import Store
from yordamchibot.content import inline_result
from yordamchibot.backup import backup


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'bot.db'
        self.store = Store(self.path, owner_id=42)
        self.bot = Bot('123456:abcdefghijklmnopqrstuvwxyz123456789')
        self.bot.session.make_request = AsyncMock(return_value=True)
        self.dp = Dispatcher()
        self.dp.include_router(create_router(self.store, 42))
        self.seq = 0

    async def asyncTearDown(self):
        self.store.close()
        await self.bot.session.close()
        self.tmp.cleanup()

    async def send(self, text=None, owner=42, **extra):
        self.seq += 1
        msg = dict(message_id=self.seq, date=0, chat={'id': owner, 'type': 'private'},
                   from_user={'id': owner, 'is_bot': False, 'first_name': 'Test'}, **extra)
        if text is not None:
            msg['text'] = text
        await self.dp.feed_update(self.bot, types.Update(update_id=self.seq, message=types.Message(**msg)))

    async def query(self, owner=42, text='', offset=''):
        await self.dp.feed_update(self.bot, types.Update(update_id=1000, inline_query=types.InlineQuery(
            id='query', from_user=types.User(id=owner, is_bot=False, first_name='Test'), query=text, offset=offset)))
        return self.bot.session.make_request.call_args.args[1]

    async def click(self, data, owner=42):
        await self.dp.feed_update(self.bot, types.Update(update_id=2000, callback_query=types.CallbackQuery(
            id='callback', chat_instance='test', data=data,
            from_user=types.User(id=owner, is_bot=False, first_name='Test'),
            message=types.Message(message_id=1, date=0, chat=types.Chat(id=owner, type='private')))))

    async def test_save_cancel_permissions(self):
        await self.send('secret', owner=99)
        await self.send('title', owner=99)
        self.assertEqual(self.store.search(), [])
        await self.send('hello')
        await self.send('Greeting')
        self.assertEqual(self.store.search('HELLO')[0]['title'], 'Greeting')
        await self.send('discard')
        await self.send('/cancel')
        self.assertEqual(len(self.store.search()), 1)
        result = await self.query(owner=99)
        self.assertEqual(result.results, [])
        self.assertTrue(result.is_personal)
        self.assertEqual(result.cache_time, 0)
        await self.click('confirm:1', owner=99)
        self.assertIsNotNone(self.store.get(1))

    async def test_edit_delete(self):
        await self.send('old')
        await self.send('title')
        await self.click('rename:1')
        await self.send('new title')
        await self.click('replace:1')
        await self.send('new content')
        self.assertEqual(self.store.search('new content')[0]['title'], 'new title')
        self.assertEqual(self.store.search('old'), [])
        await self.click('delete:1')
        self.assertIsNotNone(self.store.get(1))
        await self.click('confirm:1')
        self.assertIsNone(self.store.get(1))

    async def test_album_and_inline_types(self):
        for n in range(2):
            await self.send(photo=[dict(file_id=f'photo{n}', file_unique_id=f'u{n}', width=20, height=20)], media_group_id='album')
        await self.send('one')
        await self.send('two')
        self.assertEqual(self.store.get(1)['payload']['file_id'], 'photo0')
        self.assertEqual(self.store.get(2)['payload']['file_id'], 'photo1')
        for kind in ('video', 'document'):
            self.store.add(kind, dict(kind=kind, file_id='cached', caption='caption', caption_entities=[]))
        self.store.add('text', dict(kind='text', text='bold', entities=[dict(type='bold', offset=0, length=4)]))
        result = await self.query()
        self.assertEqual({r.type for r in result.results}, {'article', 'photo', 'video', 'document'})
        self.assertEqual(result.results[0].input_message_content.entities[0].type, 'bold')

    async def test_pagination_and_empty(self):
        for n in range(25):
            self.store.add(str(n), dict(kind='text', text='body'))
        first = await self.query()
        second = await self.query(offset=first.next_offset)
        self.assertEqual(len(first.results), 20)
        self.assertEqual(len(second.results), 5)
        self.assertEqual(second.next_offset, '')
        self.assertEqual((await self.query(text='absent')).results, [])
        self.assertEqual(len((await self.query(offset='invalid')).results), 20)

    async def test_persistence_backup_retention_restore(self):
        self.store.add('persistent', dict(kind='text', text='kept'))
        self.store.close()
        self.store = Store(self.path, owner_id=42)
        self.assertEqual(self.store.get(1)['title'], 'persistent')
        for _ in range(9):
            target = backup(self.path)
        self.assertEqual(len(list(target.parent.glob('*.db'))), 7)
        restored = Store(target, owner_id=42)
        self.assertEqual(restored.get(1)['payload']['text'], 'kept')
        restored.close()


if __name__ == '__main__':
    unittest.main()
