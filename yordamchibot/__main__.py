import asyncio
import logging
import os
from collections import deque

from aiogram import BaseMiddleware, Bot, Dispatcher, Router, types
from aiogram.exceptions import TelegramAPIError

from .content import extract, inline_result, preview
from .storage import Store


class OwnerOnly(BaseMiddleware):
    def __init__(self, owner_id):
        self.owner_id = owner_id

    async def __call__(self, handler, event, data):
        user = getattr(event, 'from_user', None)
        allowed = user and user.id == self.owner_id
        if isinstance(event, types.Message):
            allowed = allowed and event.chat.type == 'private'
        if isinstance(event, types.CallbackQuery):
            allowed = allowed and event.message and event.message.chat.type == 'private'
        if not allowed:
            if isinstance(event, types.InlineQuery):
                await event.answer([], is_personal=True, cache_time=0)
            elif isinstance(event, types.CallbackQuery):
                await event.answer('Ruxsat yo‘q.', show_alert=True)
            return
        return await handler(event, data)


def keyboard(rows):
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows])


def create_router(store, owner_id):
    router = Router()
    for observer in (router.message, router.callback_query, router.inline_query):
        observer.outer_middleware(OwnerOnly(owner_id))
    # Pending uploads are a queue so album messages cannot overwrite one another.
    pending = deque()
    editing = None
    lock = asyncio.Lock()

    async def listing(message, offset=0):
        items = store.search(offset=offset)
        rows = [[(item['title'], f"view:{item['id']}")] for item in items[:20]]
        nav = []
        if offset:
            nav.append(('← Oldingi', f'list:{max(0, offset-20)}'))
        if len(items) > 20:
            nav.append(('Keyingi →', f'list:{offset+20}'))
        if nav:
            rows.append(nav)
        await message.answer('Ma’lumotlarim:' if items else 'Hozircha ma’lumot yo‘q.',
                             reply_markup=keyboard(rows) if rows else None)

    @router.inline_query()
    async def inline(query: types.InlineQuery):
        try:
            offset = max(0, int(query.offset or '0'))
        except ValueError:
            offset = 0
        items = store.search(query.query, offset)
        await query.answer([inline_result(item) for item in items[:20]], cache_time=0,
                           is_personal=True, next_offset=str(offset + 20) if len(items) > 20 else '')

    @router.callback_query()
    async def callback(query: types.CallbackQuery):
        nonlocal editing
        async with lock:
            try:
                action, raw_id = (query.data or '').split(':', 1)
                item_id = int(raw_id)
            except ValueError:
                await query.answer('Noto‘g‘ri tugma.')
                return
            if action == 'list':
                await query.answer()
                await listing(query.message, max(0, item_id))
                return
            item = store.get(item_id)
            if not item:
                await query.answer('Yozuv topilmadi.', show_alert=True)
                return
            await query.answer()
            if action == 'view':
                await preview(query.message, item, keyboard([
                    [('Nomini o‘zgartirish', f'rename:{item_id}'), ('Mazmunini almashtirish', f'replace:{item_id}')],
                    [('O‘chirish', f'delete:{item_id}'), ('Ro‘yxat', 'list:0')]]))
            elif action in ('rename', 'replace'):
                if pending:
                    await query.message.answer('Avval saqlashni tugating yoki /cancel yuboring.')
                    return
                editing = (action, item_id)
                await query.message.answer('Yangi nom yuboring.' if action == 'rename' else 'Yangi matn yoki fayl yuboring.')
            elif action == 'delete':
                await query.message.answer('Ushbu yozuvni o‘chirasizmi?', reply_markup=keyboard([
                    [('Ha, o‘chirish', f'confirm:{item_id}'), ('Bekor qilish', f'view:{item_id}')]]))
            elif action == 'confirm':
                store.delete(item_id)
                if editing and editing[1] == item_id:
                    editing = None
                await query.message.answer('O‘chirildi.')

    @router.message()
    async def message(message: types.Message):
        nonlocal editing
        async with lock:
            text = message.text or ''
            words = text.split()
            command = words[0].split('@')[0] if words else ''
            if command == '/cancel':
                pending.clear()
                editing = None
                await message.answer('Amal bekor qilindi.')
                return
            if command in ('/start', '/help'):
                await message.answer('Matn, havola, rasm, video yoki hujjat yuboring, keyin unga nom bering. '
                    'Boshqa chatda @manavibot qidiruv yozib ulashing. /cancel — amalni bekor qilish. '
                    'Albom fayllari alohida saqlanadi.', reply_markup=types.ReplyKeyboardMarkup(
                        keyboard=[[types.KeyboardButton(text='Ma’lumotlarim')]], resize_keyboard=True))
                return
            if command == '/list' or text == 'Ma’lumotlarim':
                await listing(message)
                return
            if text.startswith('/'):
                await message.answer('Noma’lum buyruq. /help — yordam.')
                return
            if editing:
                action, item_id = editing
                value = text.strip() if action == 'rename' else extract(message)
                if not value or (action == 'rename' and len(value) > 100):
                    await message.answer('1–100 belgili nom yuboring.' if action == 'rename' else 'Matn, rasm, video yoki hujjat yuboring.')
                    return
                ok = store.update(item_id, **({'title': value} if action == 'rename' else {'payload': value}))
                editing = None
                await message.answer('Yangilandi.' if ok else 'Yozuv topilmadi.')
                return
            if pending and text and not message.forward_origin:
                if not text.strip() or len(text.strip()) > 100:
                    await message.answer('Nom 1–100 belgidan iborat bo‘lsin.')
                    return
                store.add(text.strip(), pending[0])
                pending.popleft()
                await message.answer('Saqlandi.' + (' Navbatdagi fayl uchun nom yuboring.' if pending else ''))
                return
            payload = extract(message)
            if not payload:
                await message.answer('Bu xabar turi qo‘llanmaydi. Matn, rasm, video yoki hujjat yuboring.')
                return
            if len(pending) >= 100:
                await message.answer('Navbat to‘ldi. Avval yozuvlarga nom bering yoki /cancel yuboring.')
                return
            pending.append(payload)
            await message.answer(f'Qabul qilindi. Navbatda {len(pending)} ta. Birinchi yozuv uchun nom yuboring.')

    @router.errors()
    async def error(event: types.ErrorEvent):
        # Exception text can contain request data; only log its class.
        logging.error('Handler failure: %s', type(event.exception).__name__)
        message = event.update.message or (event.update.callback_query.message if event.update.callback_query else None)
        if message and message.chat.id == owner_id:
            try:
                await message.answer('Amal bajarilmadi. Qayta urinib ko‘ring yoki /cancel yuboring.')
            except TelegramAPIError:
                pass
        return True

    return router


async def main():
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
    # Prevent third-party errors from printing request URLs or message bodies.
    framework_logger = logging.getLogger('aiogram')
    framework_logger.addHandler(logging.NullHandler())
    framework_logger.propagate = False
    token = os.environ.get('BOT_TOKEN', '')
    try:
        owner = int(os.environ.get('OWNER_ID', '0'))
        if not token or owner <= 0:
            raise ValueError
    except ValueError:
        raise SystemExit('BOT_TOKEN va musbat OWNER_ID sozlanishi kerak.')
    store = Store(os.environ.get('DB_PATH', 'data/bot.db'))
    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(create_router(store, owner))
    try:
        await bot.set_my_commands([types.BotCommand(command=c, description=d) for c, d in
            [('start', 'Boshlash'), ('list', 'Ma’lumotlarim'), ('cancel', 'Amalni bekor qilish'), ('help', 'Yordam')]])
        await dp.start_polling(bot)
    finally:
        store.close()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        logging.error('Startup failure: %s', type(exc).__name__)
        raise SystemExit(1)
