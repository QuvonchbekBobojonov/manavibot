"""Telegram Stars access gate and isolated per-user library routers."""
import asyncio
import logging
import secrets
import time

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError

from .handlers import create_library_router, keyboard

PRICE = 20
TERMS = ('📜 Manavi — foydalanish shartlari\n\n'
         '⭐ Barcha funksiyalar uchun bir martalik 20 Telegram Stars. Avtomatik yoki oylik yechib olish yo‘q. '
         'Kirish xizmat faol bo‘lgan davrda amal qiladi.\n'
         '🔒 Har kim faqat o‘z kutubxonasini boshqaradi. Inline orqali yuborgan nusxani qabul qiluvchi ko‘radi. '
         'Fayllar Telegramda, ularning identifikatorlari bot bazasida saqlanadi.\n'
         '🗑 Savatdagi yozuvlar 30 kundan keyin o‘chadi. Eksport va zaxira imkoniyatlari mavjud.\n'
         '💬 To‘lov yoki xizmat muammolari: /paysupport va murojaat matni. Murojaat bot egasiga yetkaziladi; '
         'Telegram yordami bu bot xaridlarini hal qilmaydi. To‘lov qaytarilsa pullik kirish bekor bo‘ladi.\n\n'
         'Quyidagi tugma bilan shartlarga rozilik bildirasiz va to‘lov oynasini ochasiz.')
GATE = ('👋 Manavi — Saqla va ulash!\n\n'
        '📚 Matn va fayllaringizni shaxsiy kutubxonada saqlang, qidiring va inline orqali ulashing.\n'
        '⭐ Kirish: bir martalik 20 Stars. Oylik to‘lov yo‘q.\n'
        '🔒 Sizning ma’lumotlaringiz boshqa foydalanuvchilarga ko‘rinmaydi.\n\n'
        'Boshlash uchun to‘lov shartlarini oching. /paysupport — yordam.')


class PaymentStore:
    def __init__(self, db):
        self.db = db
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS purchase_orders (
                payload TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
                consent_at INTEGER NOT NULL, checkout_id TEXT, approved_at INTEGER)''')
            db.execute('''CREATE TABLE IF NOT EXISTS star_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, charge_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL, payload TEXT NOT NULL, amount INTEGER NOT NULL,
                currency TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL,
                retry_at INTEGER NOT NULL DEFAULT 0)''')
            db.execute('CREATE INDEX IF NOT EXISTS payments_user ON star_payments(user_id,status)')
            db.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                message TEXT NOT NULL, created_at INTEGER NOT NULL, resolved INTEGER NOT NULL DEFAULT 0)''')

    def paid(self, user_id):
        return bool(self.db.execute("SELECT 1 FROM star_payments WHERE user_id=? AND status='paid'", (user_id,)).fetchone())

    def order(self, user_id):
        now = int(time.time())
        row = self.db.execute('SELECT payload FROM purchase_orders WHERE user_id=? AND created_at>? ORDER BY created_at DESC LIMIT 1',
                              (user_id, now - 86400)).fetchone()
        if row:
            return row['payload']
        payload = 'manavi:' + secrets.token_hex(24)
        with self.db:
            self.db.execute('INSERT INTO purchase_orders(payload,user_id,created_at,consent_at) VALUES(?,?,?,?)',
                            (payload, user_id, now, now))
        return payload

    def checkout(self, query, owner_id):
        row = self.db.execute('SELECT * FROM purchase_orders WHERE payload=?', (query.invoice_payload,)).fetchone()
        user_id = query.from_user.id
        if user_id == owner_id or self.paid(user_id):
            return False, 'Sizda kirish allaqachon mavjud. Qayta to‘lash kerak emas.'
        if not row or row['user_id'] != user_id or query.currency != 'XTR' or query.total_amount != PRICE:
            return False, 'To‘lov ma’lumotlari mos emas. /buy orqali qayta boshlang.'
        if row['created_at'] < time.time() - 86400:
            return False, 'Hisob muddati tugagan. /buy orqali yangisini oching.'
        active = self.db.execute('''SELECT checkout_id FROM purchase_orders
            WHERE user_id=? AND approved_at>? AND checkout_id!=?
            AND NOT EXISTS(SELECT 1 FROM star_payments p WHERE p.payload=purchase_orders.payload)''',
            (user_id, int(time.time()) - 900, query.id)).fetchone()
        if active:
            return False, 'Oldingi to‘lov yakunlanmoqda. Biroz kuting; muammo bo‘lsa /paysupport.'
        with self.db:
            self.db.execute('UPDATE purchase_orders SET checkout_id=?,approved_at=? WHERE payload=?',
                            (query.id, int(time.time()), query.invoice_payload))
        return True, None

    def success(self, user_id, payment):
        existing = self.db.execute('SELECT * FROM star_payments WHERE charge_id=?',
                                   (payment.telegram_payment_charge_id,)).fetchone()
        if existing:
            return existing['status'] if existing['user_id'] == user_id else 'invalid'
        order = self.db.execute('SELECT * FROM purchase_orders WHERE payload=?', (payment.invoice_payload,)).fetchone()
        valid = (order and order['user_id'] == user_id and payment.currency == 'XTR' and payment.total_amount == PRICE)
        status = 'paid' if valid and not self.paid(user_id) else 'refund_pending'
        with self.db:
            self.db.execute('''INSERT INTO star_payments(charge_id,user_id,payload,amount,currency,status,created_at)
                VALUES(?,?,?,?,?,?,?)''', (payment.telegram_payment_charge_id, user_id, payment.invoice_payload,
                                         payment.total_amount, payment.currency, status, int(time.time())))
        return status

    def refunded(self, user_id, payment):
        # Keep a tombstone if Telegram delivers a refund before a retried success update.
        with self.db:
            self.db.execute('''INSERT INTO star_payments(charge_id,user_id,payload,amount,currency,status,created_at)
                VALUES(?,?,?,?,?,'refunded',?) ON CONFLICT(charge_id) DO UPDATE SET status='refunded'
                WHERE star_payments.user_id=excluded.user_id''',
                (payment.telegram_payment_charge_id, user_id, payment.invoice_payload,
                 payment.total_amount, payment.currency, int(time.time())))

    def ticket(self, user_id, message):
        with self.db:
            return self.db.execute('INSERT INTO support_tickets(user_id,message,created_at) VALUES(?,?,?)',
                                   (user_id, message, int(time.time()))).lastrowid


async def process_refunds(bot, payments):
    rows = payments.db.execute("SELECT * FROM star_payments WHERE status='refund_pending' AND retry_at<=? LIMIT 20",
                               (int(time.time()),)).fetchall()
    for row in rows:
        if row['currency'] != 'XTR':
            continue
        try:
            await bot.refund_star_payment(user_id=row['user_id'], telegram_payment_charge_id=row['charge_id'])
        except TelegramAPIError as exc:
            message = str(getattr(exc, 'message', '')).casefold()
            if 'charge_already_refunded' not in message and 'already refunded' not in message:
                with payments.db:
                    payments.db.execute('UPDATE star_payments SET retry_at=? WHERE id=?', (int(time.time()) + 300, row['id']))
                logging.warning('Star refund retry: %s', type(exc).__name__)
                continue
        with payments.db:
            payments.db.execute("UPDATE star_payments SET status='refunded' WHERE id=?", (row['id'],))


async def payment_maintenance(bot, payments, owner_id):
    while True:
        try:
            await process_refunds(bot, payments)
            with payments.db:
                payments.db.execute('DELETE FROM items WHERE deleted_at<=?', (int(time.time()) - 30 * 86400,))
        except Exception as exc:
            logging.error('Payment maintenance failed: %s', type(exc).__name__)
        await asyncio.sleep(30)


def create_router(store, owner_id):
    router = Router()
    payments = PaymentStore(store.db)
    libraries = {}

    def allowed(user_id):
        return user_id == owner_id or payments.paid(user_id)

    async def gate(message):
        await message.answer(GATE, reply_markup=keyboard([[('📜 Shartlar va 20 ⭐ kirish', 'buy:terms')]]))

    async def dispatch(kind, event, data):
        user_id = event.from_user.id
        library = libraries.setdefault(user_id, None)
        if library is None:
            library = libraries[user_id] = create_library_router(store.for_user(user_id), user_id)
        data.pop('event_router', None)
        return await library.propagate_event(kind, event, **data)

    @router.pre_checkout_query()
    async def pre_checkout(query: types.PreCheckoutQuery):
        ok, error = payments.checkout(query, owner_id)
        await query.answer(ok=ok, error_message=error)

    @router.message(F.successful_payment)
    async def successful(message: types.Message):
        if not message.from_user or message.chat.type != 'private':
            return
        status = payments.success(message.from_user.id, message.successful_payment)
        if status == 'paid':
            await message.answer('✅ 20 ⭐ to‘lov qabul qilindi! Kirish ochildi. Qayta to‘lash kerak emas.\n/start — shaxsiy menyuingiz.')
        elif status == 'refund_pending':
            await message.answer('↩️ Bu to‘lov uchun qo‘shimcha kirish kerak emas yoki hisob mos kelmadi. Stars avtomatik qaytarish navbatiga olindi. /paysupport — yordam.')
        else:
            await message.answer('ℹ️ To‘lov avval qayta ishlangan. /start yoki /paysupport dan foydalaning.')

    @router.message(F.refunded_payment)
    async def refunded(message: types.Message):
        if message.from_user and message.chat.type == 'private':
            payments.refunded(message.chat.id, message.refunded_payment)
            await message.answer('↩️ To‘lov qaytarildi. Shu xarid bo‘yicha kirish bekor qilindi. /paysupport — yordam.')

    @router.inline_query()
    async def inline(query: types.InlineQuery, **data):
        if not allowed(query.from_user.id):
            await query.answer([], cache_time=0, is_personal=True,
                               button=types.InlineQueryResultsButton(text='⭐ 20 Stars — bir martalik kirish', start_parameter='buy'))
            return
        return await dispatch('inline_query', query, data)

    @router.callback_query()
    async def callback(query: types.CallbackQuery, **data):
        if not isinstance(query.message, types.Message) or query.message.chat.type != 'private':
            await query.answer('Botning shaxsiy chatini oching.')
            return
        user_id = query.from_user.id
        value = query.data or ''
        if value.startswith('buy:'):
            await query.answer()
            if allowed(user_id):
                await query.message.answer('✅ Sizda kirish bor. /start orqali davom eting.')
            elif value == 'buy:terms':
                await query.message.answer(TERMS, reply_markup=keyboard([[('✅ Roziman — 20 ⭐', 'buy:accept')]]))
            elif value == 'buy:accept':
                payload = payments.order(user_id)
                await query.message.answer_invoice(title='Manavi — bir martalik kirish',
                    description='Shaxsiy kutubxona, inline ulashish va barcha funksiyalar. Bir martalik 20 Stars.',
                    payload=payload, currency='XTR', prices=[types.LabeledPrice(label='Bir martalik kirish', amount=PRICE)],
                    provider_token='', start_parameter='buy')
            return
        if value.startswith('refund:') and user_id == owner_id:
            await query.answer()
            try:
                payment_id = int(value.split(':')[1])
            except (ValueError, IndexError):
                return
            with store.db:
                count = store.db.execute("UPDATE star_payments SET status='refund_pending',retry_at=0 WHERE id=? AND status='paid'", (payment_id,)).rowcount
            await query.message.answer('↩️ Qaytarish navbatiga olindi.' if count else 'ℹ️ To‘lov topilmadi yoki avval qaytarilgan.')
            return
        if not allowed(user_id):
            await query.answer('⭐ Avval bir martalik kirishni faollashtiring.', show_alert=True)
            await gate(query.message)
            return
        return await dispatch('callback_query', query, data)

    @router.message()
    async def message(message: types.Message, **data):
        if not message.from_user or message.chat.type != 'private':
            return
        user_id = message.from_user.id
        parts = (message.text or '').split(maxsplit=1)
        command = parts[0].split('@')[0] if parts else ''
        args = parts[1].strip() if len(parts) == 2 else ''
        if command in ('/terms', '/buy'):
            if allowed(user_id) and command == '/buy':
                await message.answer('✅ Kirishingiz faol. Qayta to‘lash kerak emas. /start')
            else:
                await message.answer(TERMS, reply_markup=keyboard([[('✅ Roziman — 20 ⭐', 'buy:accept')]]) if not allowed(user_id) else None)
            return
        if command in ('/support', '/paysupport'):
            if not args:
                await message.answer('💬 Murojaatni shunday yuboring:\n/paysupport To‘lovim bo‘yicha yordam kerak...\nJavob shu bot orqali keladi. Telegram yordami bu bot xaridlarini hal qilmaydi.')
            elif len(args) > 1500:
                await message.answer('Murojaat 1500 belgidan oshmasin.')
            else:
                ticket = payments.ticket(user_id, args)
                await message.answer(f'✅ Murojaat #{ticket} qabul qilindi.')
            return
        if user_id == owner_id and command in ('/payments', '/tickets', '/reply', '/refund'):
            if command == '/payments':
                rows = store.db.execute('SELECT id,user_id,amount,status FROM star_payments ORDER BY id DESC LIMIT 20').fetchall()
                await message.answer('⭐ Oxirgi to‘lovlar:\n' + ('\n'.join(f"#{r['id']} · {r['user_id']} · {r['amount']} ⭐ · {r['status']}" for r in rows) or 'Hozircha yo‘q.'))
            elif command == '/tickets':
                rows = store.db.execute('SELECT * FROM support_tickets WHERE resolved=0 ORDER BY id LIMIT 10').fetchall()
                if not rows:
                    await message.answer('💬 Ochiq murojaat yo‘q.')
                for r in rows:
                    await message.answer(f"💬 #{r['id']} · foydalanuvchi {r['user_id']}\n{r['message']}\n\nJavob: /reply {r['id']} matn")
            elif command == '/reply':
                values = args.split(maxsplit=1)
                if len(values) != 2 or not values[0].isdigit():
                    await message.answer('Namuna: /reply 1 Javob matni')
                    return
                row = store.db.execute('SELECT * FROM support_tickets WHERE id=?', (int(values[0]),)).fetchone()
                if not row:
                    await message.answer('Murojaat topilmadi.')
                    return
                await message.bot.send_message(row['user_id'], f"💬 Murojaat #{row['id']} bo‘yicha javob:\n{values[1]}")
                with store.db:
                    store.db.execute('UPDATE support_tickets SET resolved=1 WHERE id=?', (row['id'],))
                await message.answer('✅ Javob yuborildi.')
            elif command == '/refund':
                row = store.db.execute("SELECT * FROM star_payments WHERE id=? AND status='paid'", (int(args),)).fetchone() if args.isdigit() else None
                if not row:
                    await message.answer('Namuna: /refund TO‘LOV_ID. ID’ni /payments dan oling.')
                    return
                await message.answer(f"↩️ #{row['id']} · {row['user_id']} uchun {row['amount']} ⭐ qaytarilsinmi? Kirish bekor bo‘ladi.",
                                     reply_markup=keyboard([[('Tasdiqlash', f"refund:{row['id']}")]]))
            return
        if not allowed(user_id):
            await gate(message)
            return
        return await dispatch('message', message, data)

    @router.errors()
    async def error(event: types.ErrorEvent):
        logging.error('Access/payment handler failed: %s', type(event.exception).__name__)
        message = event.update.message or (event.update.callback_query.message if event.update.callback_query else None)
        if isinstance(message, types.Message) and message.chat.type == 'private':
            try:
                await message.answer('⚠️ Amal bajarilmadi. Qayta urinib ko‘ring. To‘lov uchun /paysupport orqali murojaat qiling.')
            except TelegramAPIError:
                pass
        return True

    return router
