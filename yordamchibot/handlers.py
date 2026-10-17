import asyncio
import io
import re
import secrets
from collections import deque

from aiogram import BaseMiddleware, Router, types
from aiogram.exceptions import TelegramAPIError

from .content import ICONS, LABELS, extract, inline_result, preview
from .reminders import format_time, parse_time
from .transfer import MAX_BYTES, export_data, validate_import

MENU = [
    ['📚 Ma’lumotlarim', '⭐ Sevimlilar'],
    ['🗂 Kategoriyalar', '🔎 Qidirish'],
    ['⏰ Eslatmalar', '🗑 Savat'],
    ['📦 Eksport', '📥 Import'],
    ['📊 Statistika', '💡 Yordam'],
]
HELP = ('👋 Manavi — Saqla va ulash!\n\n'
        '📥 Matn, havola, rasm, video, hujjat, ovoz, audio yoki GIF yuboring va nom bering.\n'
        '🗂 Yozuv ichida kategoriya va teglar qo‘shing.\n'
        '⭐ Sevimlilar qidiruv boshida chiqadi.\n'
        '🔘 «Ulashish» bilan chat tanlang yoki @manavibot qidiruv yozing.\n'
        '🔎 Lotin/kirill va kichik imlo xatolari bilan qidirish mumkin.\n'
        '🔐 Maxfiy yozuvlar inline orqali chiqmaydi.\n'
        '⏰ Eslatmalar Toshkent vaqti bilan ishlaydi.\n'
        '🗑 Savatdan 30 kun ichida tiklash mumkin.\n'
        '📦 Eksport / 📥 Import — JSON orqali ko‘chirish.\n\n'
        '↩️ /cancel — tugallanmagan amalni bekor qilish.\n'
        '🖼 Albomdagi har bir faylga alohida nom bering.')
COMMANDS = [('start', '👋 Boshlash'), ('list', '📚 Ma’lumotlarim'), ('favorites', '⭐ Sevimlilar'),
            ('categories', '🗂 Kategoriyalar'), ('search', '🔎 Qidirish'), ('reminders', '⏰ Eslatmalar'),
            ('trash', '🗑 Savat'), ('export', '📦 Eksport'), ('import', '📥 Import'),
            ('stats', '📊 Statistika'), ('cancel', '↩️ Amalni bekor qilish'), ('help', '💡 Yordam')]


class OwnerOnly(BaseMiddleware):
    def __init__(self, owner_id):
        self.owner_id = owner_id

    async def __call__(self, handler, event, data):
        user = getattr(event, 'from_user', None)
        allowed = user and user.id == self.owner_id
        if isinstance(event, types.Message):
            allowed = allowed and event.chat.type == 'private'
        if isinstance(event, types.CallbackQuery):
            allowed = allowed and isinstance(event.message, types.Message) and event.message.chat.type == 'private'
        if not allowed:
            if isinstance(event, types.InlineQuery):
                await event.answer([], is_personal=True, cache_time=0)
            elif isinstance(event, types.CallbackQuery):
                await event.answer('🔒 Ruxsat yo‘q.', show_alert=True)
            return
        return await handler(event, data)


def keyboard(rows):
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows])


def item_markup(item):
    i = item['id']
    if item['deleted_at'] is not None:
        return keyboard([[('♻️ Tiklash', f'restore:{i}'), ('🗑 Savat', 'page:trash:0:0')]])
    markup = keyboard([
        [('✏️ Nom', f'rename:{i}'), ('🔄 Mazmun', f'replace:{i}')],
        [('🗂 Kategoriya', f'category:{i}'), ('🏷 Teglar', f'tags:{i}')],
        [('⭐ Sevimlidan olish' if item['favorite'] else '☆ Sevimliga qo‘shish', f'favorite:{i}')],
        [('🔓 Inline’da ko‘rsatish' if item['private'] else '🔐 Maxfiy qilish', f'private:{i}')],
        [('⏰ Eslatma', f'remind:{i}'), ('🔕 Eslatmani bekor qilish', f'unremind:{i}')],
        [('🗑 O‘chirish', f'delete:{i}'), ('📚 Ro‘yxat', 'list:0')],
    ])
    if not item['private']:
        markup.inline_keyboard.insert(0, [types.InlineKeyboardButton(text='↗️ Ulashish', switch_inline_query=f'#id:{i}')])
    return markup


def details(item):
    tags = ' '.join('#' + tag for tag in item['tags']) or '—'
    return (f"{ICONS[item['payload']['kind']]} {item['title']}\n"
            f"🗂 {item['category'] or 'Kategoriyasiz'}\n🏷 {tags}\n"
            f"{'⭐ Sevimli' if item['favorite'] else '☆ Oddiy'} · "
            f"{'🔐 Maxfiy' if item['private'] else '↗️ Ulashish mumkin'}" +
            ('\n🗑 Savatda (30 kun ichida tiklang).' if item['deleted_at'] is not None else ''))


class LimitedBuffer(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_BYTES:
            raise ValueError('Fayl 10 MB dan katta.')
        return super().write(data)


def create_router(store, owner_id):
    router = Router()
    for observer in (router.message, router.callback_query, router.inline_query):
        observer.outer_middleware(OwnerOnly(owner_id))
    pending = deque()
    editing = None
    staged_import = None
    search_query = ''
    lock = asyncio.Lock()

    async def show_item(message, item, content=True):
        if content:
            await preview(message, item, None)
        await message.answer(details(item), reply_markup=item_markup(item))

    async def listing(message, mode='all', offset=0, category_id=0):
        options = dict(favorites=mode == 'favorites', trash=mode == 'trash')
        if mode == 'category':
            anchor = store.get(category_id)
            if not anchor:
                await message.answer('🗂 Kategoriya ro‘yxatini qayta oching.')
                return
            options['category'] = anchor['category']
        items = store.search(search_query if mode == 'search' else '', offset, **options)
        rows = [[(('⭐ ' if item['favorite'] else '') + ('🔐 ' if item['private'] else '') +
                  ICONS[item['payload']['kind']] + ' ' + item['title'], f"view:{item['id']}")] for item in items[:20]]
        nav = []
        if offset:
            nav.append(('⬅️ Oldingi', f'page:{mode}:{max(0,offset-20)}:{category_id}'))
        if len(items) > 20:
            nav.append(('Keyingi ➡️', f'page:{mode}:{offset+20}:{category_id}'))
        if nav:
            rows.append(nav)
        heading = {'all': '📚 Ma’lumotlarim', 'favorites': '⭐ Sevimlilar', 'trash': '🗑 Savat — 30 kun',
                   'category': '🗂 Kategoriya', 'search': '🔎 Qidiruv natijalari'}.get(mode, '📚 Ma’lumotlarim')
        await message.answer(heading + (':' if items else '\n📭 Yozuv topilmadi.'),
                             reply_markup=keyboard(rows) if rows else None)

    async def categories(message, offset=0):
        found = store.categories()
        rows = [[(f"🗂 {row['category']} ({row['total']})", f"page:category:0:{row['id']}")]
                for row in found[offset:offset+20]]
        nav = []
        if offset:
            nav.append(('⬅️ Oldingi', f'categories:{max(0,offset-20)}'))
        if len(found) > offset + 20:
            nav.append(('Keyingi ➡️', f'categories:{offset+20}'))
        if nav:
            rows.append(nav)
        await message.answer('🗂 Kategoriyalar:' if found else '🗂 Hozircha kategoriya yo‘q. Yozuvni ochib «Kategoriya»ni tanlang.',
                             reply_markup=keyboard(rows) if rows else None)

    async def reminders(message, offset=0):
        found = store.reminders()
        rows = [[(f"⏰ {format_time(row['due_at'])} · {row['title']}", f"view:{row['item_id']}")]
                for row in found[offset:offset+20]]
        nav = []
        if offset:
            nav.append(('⬅️ Oldingi', f'reminders:{max(0,offset-20)}'))
        if len(found) > offset + 20:
            nav.append(('Keyingi ➡️', f'reminders:{offset+20}'))
        if nav:
            rows.append(nav)
        await message.answer('⏰ Eslatmalar (Toshkent vaqti):' if found else '⏰ Eslatma yo‘q. Yozuvni ochib «Eslatma»ni tanlang.',
                             reply_markup=keyboard(rows) if rows else None)

    @router.inline_query()
    async def inline(query: types.InlineQuery):
        try:
            offset = min(1000000, max(0, int(query.offset or '0')))
        except ValueError:
            offset = 0
        direct = re.fullmatch(r'#id:(\d+)', query.query.strip())
        if direct:
            item = store.get(int(direct.group(1)))
            items = [item] if item and not item['private'] and not offset else []
        else:
            items = store.search(query.query, offset, inline=True)
        await query.answer([inline_result(item) for item in items[:20]], cache_time=0,
                           is_personal=True, next_offset=str(offset + 20) if len(items) > 20 else '')

    @router.callback_query()
    async def callback(query: types.CallbackQuery):
        nonlocal editing, staged_import
        async with lock:
            parts = (query.data or '').split(':')
            try:
                action, item_id = parts[0], int(parts[1]) if parts[0] != 'page' else 0
                if action == 'page':
                    mode, offset, category_id = parts[1], max(0, int(parts[2])), int(parts[3])
            except (ValueError, IndexError):
                await query.answer('⚠️ Noto‘g‘ri tugma.')
                return
            await query.answer()
            if action == 'page':
                await listing(query.message, mode, offset, category_id)
                return
            if action in ('list', 'categories', 'reminders'):
                if action == 'list':
                    await listing(query.message, offset=max(0, item_id))
                elif action == 'categories':
                    await categories(query.message, max(0, item_id))
                else:
                    await reminders(query.message, max(0, item_id))
                return
            if action == 'importconfirm':
                if not staged_import or staged_import[0] != item_id:
                    await query.message.answer('⌛ Import tasdig‘i eskirgan. /import orqali qayta boshlang.')
                    return
                entries = staged_import[1]
                added = store.import_items(entries)
                staged_import = None
                editing = None
                await query.message.answer(f'✅ Import: {added} ta qo‘shildi, {len(entries)-added} ta mavjud yozuv o‘tkazib yuborildi.')
                return
            item = store.get(item_id, include_deleted=True)
            if not item:
                await query.message.answer('🔎 Yozuv topilmadi.')
                return
            if action == 'restore':
                await query.message.answer('♻️ Tiklandi.' if store.restore(item_id) else '🔎 Yozuv savatda emas.')
                return
            if action == 'view':
                await show_item(query.message, item)
                return
            if item['deleted_at'] is not None:
                await query.message.answer('🗑 Avval yozuvni savatdan tiklang.')
                return
            if action in ('rename', 'replace', 'category', 'tags', 'remind'):
                if pending or editing or staged_import:
                    await query.message.answer('⏳ Avval joriy amalni tugating yoki /cancel yuboring.')
                    return
                editing = (action, item_id)
                prompt = {
                    'rename': '✏️ Yangi nom yuboring (1–100 belgi).',
                    'replace': '📎 Yangi matn, fayl, ovoz, audio yoki GIF yuboring.',
                    'category': '🗂 Kategoriya nomini yuboring (40 belgigacha). Tozalash uchun - yuboring.',
                    'tags': '🏷 Teglarni vergul bilan yuboring: ish, muhim. Eng ko‘pi 10 ta, har biri 30 belgi. Tozalash: -',
                    'remind': '⏰ Qachon eslatay? Masalan: 10 daqiqa, 2 soat, 1 kun yoki 25.12.2026 09:00.\n🕒 Toshkent vaqti.',
                }[action]
                await query.message.answer(prompt)
            elif action in ('favorite', 'private'):
                store.update(item_id, **{action: not item[action]})
                await show_item(query.message, store.get(item_id), content=False)
            elif action == 'unremind':
                store.cancel_reminder(item_id)
                await query.message.answer('🔕 Eslatma bekor qilindi.')
            elif action == 'delete':
                await query.message.answer('🗑 Savatga ko‘chirilsinmi? 30 kun ichida tiklash mumkin.', reply_markup=keyboard([
                    [('🗑 Ha, o‘chirish', f'confirm:{item_id}'), ('↩️ Bekor qilish', f'view:{item_id}')]]))
            elif action == 'confirm':
                store.delete(item_id)
                if editing and editing[1] == item_id:
                    editing = None
                await query.message.answer('🗑 Savatga ko‘chirildi. Eslatma bekor qilindi. /trash orqali tiklashingiz mumkin.')

    @router.message()
    async def message(message: types.Message):
        nonlocal editing, staged_import, search_query
        async with lock:
            text = message.text or ''
            words = text.split(maxsplit=1)
            command = words[0].split('@')[0] if words else ''
            aliases = {'Ma’lumotlarim': '/list', '📚 Ma’lumotlarim': '/list', '⭐ Sevimlilar': '/favorites',
                       '🗂 Kategoriyalar': '/categories', '🔎 Qidirish': '/search', '⏰ Eslatmalar': '/reminders',
                       '🗑 Savat': '/trash', '📦 Eksport': '/export', '📥 Import': '/import',
                       '📊 Statistika': '/stats', '💡 Yordam': '/help'}
            command = aliases.get(text, command)
            if command == '/cancel':
                pending.clear()
                editing = staged_import = None
                await message.answer('↩️ Amal bekor qilindi.')
                return
            if command in ('/start', '/help'):
                await message.answer(HELP, reply_markup=types.ReplyKeyboardMarkup(keyboard=[[
                    types.KeyboardButton(text=label) for label in row] for row in MENU], resize_keyboard=True))
                return
            if command in ('/list', '/favorites', '/trash'):
                await listing(message, {'/list': 'all', '/favorites': 'favorites', '/trash': 'trash'}[command])
                return
            if command == '/categories':
                await categories(message)
                return
            if command == '/reminders':
                await reminders(message)
                return
            if command == '/stats':
                stats = store.stats()
                lines = ['📊 Kutubxona statistikasi', f"📚 Faol yozuvlar: {stats['total']}",
                         f"⭐ Sevimlilar: {stats['favorites']}", f"🔐 Maxfiy: {stats['private']}",
                         f"🗑 Savatda: {stats['trash']}", f"⏰ Eslatmalar: {stats['reminders']}", '']
                lines += [f'{ICONS[kind]} {LABELS[kind]}: {count}' for kind, count in sorted(stats['types'].items())]
                await message.answer('\n'.join(lines))
                return
            if command == '/export':
                try:
                    raw = export_data(store, message.bot.id)
                except ValueError as exc:
                    await message.answer('⚠️ ' + str(exc))
                    return
                await message.answer_document(types.BufferedInputFile(raw, filename='manavibot-export.json'),
                    caption='📦 Kutubxona eksporti. Maxfiy va savatdagi yozuvlar ham bor. Fayllarning o‘zi emas, Telegram identifikatorlari saqlanadi. Eslatmalar SQLite zaxirasida qoladi.')
                return
            if command in ('/search', '/import'):
                if pending or editing or staged_import:
                    await message.answer('⏳ Avval joriy amalni tugating yoki /cancel yuboring.')
                    return
                if command == '/search' and len(words) == 2 and text.startswith('/search'):
                    search_query = words[1]
                    await listing(message, 'search')
                else:
                    editing = ('search' if command == '/search' else 'import', 0)
                    await message.answer('🔎 Qidiruv so‘zini yuboring.' if command == '/search' else
                                         '📥 Manavibot eksport qilgan JSON faylni yuboring (10 MB gacha). Mavjud yozuvlar almashtirilmaydi.')
                return
            if text.startswith('/'):
                await message.answer('💡 Noma’lum buyruq. /help — yordam.')
                return
            if staged_import:
                await message.answer('📥 Importni tugma bilan tasdiqlang yoki /cancel yuboring.')
                return
            if editing:
                action, item_id = editing
                try:
                    if action == 'import':
                        doc = message.document
                        if not doc or not (doc.file_name or '').lower().endswith('.json'):
                            raise ValueError('JSON fayl yuboring yoki /cancel bilan bekor qiling.')
                        if doc.file_size and doc.file_size > MAX_BYTES:
                            raise ValueError('Fayl 10 MB dan katta.')
                        buffer = LimitedBuffer()
                        await message.bot.download(doc, destination=buffer)
                        entries = validate_import(buffer.getvalue(), message.bot.id)
                        nonce = secrets.randbelow(10**12)
                        staged_import = (nonce, entries)
                        editing = None
                        await message.answer(f'📥 {len(entries)} ta yozuv tekshirildi. Import qilinsinmi?',
                                             reply_markup=keyboard([[('✅ Import qilish', f'importconfirm:{nonce}')]]))
                        return
                    if action == 'search':
                        if not text.strip():
                            raise ValueError('Qidirish uchun matn yuboring.')
                        search_query = text.strip()
                        editing = None
                        await listing(message, 'search')
                        return
                    if not store.get(item_id):
                        editing = None
                        await message.answer('🔎 Yozuv topilmadi yoki savatga ko‘chirilgan.')
                        return
                    value = text.strip()
                    if action == 'rename':
                        if not 1 <= len(value) <= 100:
                            raise ValueError('Nom 1–100 belgidan iborat bo‘lsin.')
                        store.update(item_id, title=value)
                    elif action == 'replace':
                        payload = extract(message)
                        if not payload:
                            raise ValueError('Matn, fayl, ovoz, audio yoki GIF yuboring.')
                        store.update(item_id, payload=payload)
                    elif action == 'category':
                        if not value or len(value) > 40:
                            raise ValueError('Kategoriya 1–40 belgi bo‘lsin. Tozalash: -')
                        store.update(item_id, category='' if value == '-' else value)
                    elif action == 'tags':
                        tags = [] if value == '-' else list(dict.fromkeys(t.strip().lstrip('#').casefold() for t in value.split(',')))
                        if len(tags) > 10 or any(not t or len(t) > 30 for t in tags):
                            raise ValueError('Eng ko‘pi 10 teg, har biri 1–30 belgi. Tozalash: -')
                        store.update(item_id, tags=tags)
                    elif action == 'remind':
                        due = parse_time(value)
                        store.set_reminder(item_id, due)
                        editing = None
                        await message.answer(f'⏰ Eslatma belgilandi: {format_time(due)} (Toshkent).')
                        return
                except ValueError as exc:
                    # Validation exceptions from JSON/Pydantic may contain private imported content.
                    await message.answer('⚠️ Import fayli noto‘g‘ri. Manavibot eksportini yuboring (10 MB gacha).' if action == 'import' else '⚠️ ' + str(exc))
                    return
                editing = None
                await message.answer('✅ Yangilandi.', reply_markup=item_markup(store.get(item_id)))
                return
            if pending and text and not message.forward_origin:
                if not 1 <= len(text.strip()) <= 100:
                    await message.answer('✏️ Nom 1–100 belgidan iborat bo‘lsin.')
                    return
                item_id = store.add(text.strip(), pending[0])
                pending.popleft()
                await message.answer('✅ Saqlandi.' + ('\n✏️ Navbatdagi fayl uchun nom yuboring.' if pending else ''),
                                     reply_markup=item_markup(store.get(item_id)))
                return
            payload = extract(message)
            if not payload:
                await message.answer('⚠️ Matn, rasm, video, hujjat, ovoz, audio yoki GIF yuboring.')
                return
            if len(pending) >= 100:
                await message.answer('⏳ Navbat to‘ldi. Avval yozuvlarga nom bering yoki /cancel yuboring.')
                return
            pending.append(payload)
            await message.answer(f'📥 Qabul qilindi. Navbatda: {len(pending)} ta.\n✏️ Birinchi yozuv uchun nom yuboring.')

    @router.errors()
    async def error(event: types.ErrorEvent):
        import logging
        logging.error('Handler failure: %s', type(event.exception).__name__)
        message = event.update.message or (event.update.callback_query.message if event.update.callback_query else None)
        if isinstance(message, types.Message) and message.chat.id == owner_id:
            try:
                await message.answer('⚠️ Amal bajarilmadi. Qayta urinib ko‘ring yoki /cancel yuboring.')
            except TelegramAPIError:
                pass
        return True

    return router
