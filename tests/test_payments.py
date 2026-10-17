import json
import time
import unittest
from unittest.mock import AsyncMock

from aiogram import types
from aiogram.methods import RefundStarPayment, SendInvoice

import test_bot
from yordamchibot.payments import PaymentStore, process_refunds
from yordamchibot.reminders import deliver_due
from yordamchibot.storage import Store
from yordamchibot.transfer import export_data, validate_import


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_bot.BotTests.asyncSetUp
    asyncTearDown = test_bot.BotTests.asyncTearDown
    send = test_bot.BotTests.send
    query = test_bot.BotTests.query
    click = test_bot.BotTests.click

    def receipt(self, payload, charge='charge1', amount=20, currency='XTR'):
        return types.SuccessfulPayment(currency=currency, total_amount=amount, invoice_payload=payload,
                                       telegram_payment_charge_id=charge, provider_payment_charge_id='')

    async def checkout(self, payload, user=99, amount=20, currency='XTR', query_id='pc1'):
        event = types.PreCheckoutQuery(id=query_id, from_user=types.User(id=user, first_name='Buyer', is_bot=False),
                                      currency=currency, total_amount=amount, invoice_payload=payload)
        await self.dp.feed_update(self.bot, types.Update(update_id=3000, pre_checkout_query=event))
        return self.bot.session.make_request.call_args.args[1]

    async def purchase(self, user, charge):
        p = PaymentStore(self.store.db)
        payload = p.order(user)
        await self.send(owner=user, successful_payment=self.receipt(payload, charge).model_dump())
        return payload

    async def test_gate_invoice_and_exact_price(self):
        await self.send('/start', owner=99)
        result = self.bot.session.make_request.call_args.args[1]
        self.assertIn('20 Stars', result.text)
        inline = await self.query(owner=99)
        self.assertEqual(inline.results, [])
        self.assertEqual(inline.button.start_parameter, 'buy')
        await self.click('buy:terms', owner=99)
        self.assertIn('shartlari', self.bot.session.make_request.call_args.args[1].text)
        await self.click('buy:accept', owner=99)
        result = self.bot.session.make_request.call_args.args[1]
        self.assertIsInstance(result, SendInvoice)
        self.assertEqual(result.currency, 'XTR')
        self.assertEqual([p.amount for p in result.prices], [20])
        self.assertEqual(result.start_parameter, 'buy')
        self.assertEqual(result.provider_token, '')
        self.assertFalse(PaymentStore(self.store.db).paid(99))
        await self.click('buy:accept', owner=42)
        self.assertNotIsInstance(self.bot.session.make_request.call_args.args[1], SendInvoice)

    async def test_checkout_validation_and_success_idempotency(self):
        p = PaymentStore(self.store.db)
        payload = p.order(99)
        for args in [dict(user=100), dict(amount=19), dict(currency='USD')]:
            self.assertFalse((await self.checkout(payload, **args)).ok)
        self.assertFalse((await self.checkout('forged')).ok)
        self.assertTrue((await self.checkout(payload)).ok)
        self.assertTrue((await self.checkout(payload)).ok)  # Same update retry.
        self.assertFalse((await self.checkout(payload, query_id='other')).ok)
        self.assertFalse(p.paid(99))  # Pre-checkout alone grants nothing.
        payment = self.receipt(payload)
        await self.send(owner=99, successful_payment=payment.model_dump())
        self.assertTrue(p.paid(99))
        await self.send(owner=99, successful_payment=payment.model_dump())
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM star_payments').fetchone()[0], 1)
        self.assertFalse((await self.checkout(payload, query_id='later')).ok)
        self.assertEqual(p.success(100, payment), 'invalid')
        self.assertFalse(p.paid(100))
        reopened = Store(self.path, owner_id=42)
        try:
            self.assertTrue(PaymentStore(reopened.db).paid(99))
        finally:
            reopened.close()

    async def test_isolation_for_paid_users_and_export(self):
        owner_item = self.store.add('Owner secret', dict(kind='text', text='private'))
        await self.purchase(99, 'paid99')
        await self.purchase(100, 'paid100')
        await self.send('User 99 content', owner=99)
        await self.send('User 100 content', owner=100)
        await self.send('User 99 title', owner=99)
        await self.send('User 100 title', owner=100)
        a, b = self.store.for_user(99), self.store.for_user(100)
        self.assertEqual(a.stats()['total'], 1)
        self.assertEqual(b.stats()['total'], 1)
        item_a = a.search()[0]
        self.assertEqual(item_a['payload']['text'], 'User 99 content')
        self.assertIsNone(a.get(owner_item))
        self.assertFalse(a.update(owner_item, title='attack'))
        a.delete(owner_item)
        self.assertIsNotNone(self.store.get(owner_item))
        with self.assertRaises(ValueError):
            a.set_reminder(owner_item, time.time()+3600)
        await self.click(f'confirm:{owner_item}', owner=99)
        self.assertIsNotNone(self.store.get(owner_item))
        self.assertEqual((await self.query(owner=100, text=f"#id:{item_a['id']}")).results, [])
        self.assertEqual(len((await self.query(owner=99)).results), 1)
        exported = json.loads(export_data(a, self.bot.id))
        self.assertEqual([row['title'] for row in exported['items']], ['User 99 title'])
        entries = validate_import(export_data(a, self.bot.id), self.bot.id)
        self.assertEqual(b.import_items(entries), 1)  # Explicit file import creates B's own copy.
        self.assertIsNone(b.get(item_a['id']))
        await self.send('/cancel', owner=99)
        self.assertEqual(self.store.stats()['total'], 1)

    async def test_duplicate_invalid_refund_and_revocation(self):
        p = PaymentStore(self.store.db)
        payload = await self.purchase(99, 'paid')
        self.assertEqual(p.success(99, self.receipt(payload, 'duplicate')), 'refund_pending')
        self.assertEqual(p.success(100, self.receipt('wrong', 'invalid')), 'refund_pending')
        self.assertFalse(p.paid(100))
        bot = AsyncMock()
        await process_refunds(bot, p)
        self.assertEqual(bot.refund_star_payment.await_count, 2)
        self.assertTrue(p.paid(99))
        self.assertEqual(p.success(99, self.receipt(payload, 'duplicate')), 'refunded')
        refund = types.RefundedPayment(currency='XTR', total_amount=20, invoice_payload=payload,
                                       telegram_payment_charge_id='paid')
        await self.send(owner=99, refunded_payment=refund.model_dump())
        self.assertFalse(p.paid(99))
        self.assertEqual((await self.query(owner=99)).results, [])
        p.refunded(100, types.RefundedPayment(currency='XTR', total_amount=20, invoice_payload='late', telegram_payment_charge_id='late'))
        self.assertEqual(p.success(100, self.receipt('late', 'late')), 'refunded')
        self.assertFalse(p.paid(100))

    async def test_support_and_admin_refund_authorization(self):
        await self.send('/paysupport Menga yordam kerak', owner=99)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM support_tickets').fetchone()[0], 1)
        await self.send('/tickets', owner=42)
        self.assertIn('Menga yordam kerak', self.bot.session.make_request.call_args.args[1].text)
        await self.purchase(99, 'payment')
        payment_id = self.store.db.execute("SELECT id FROM star_payments WHERE charge_id='payment'").fetchone()[0]
        await self.click(f'refund:{payment_id}', owner=99)
        self.assertTrue(PaymentStore(self.store.db).paid(99))
        await self.send(f'/refund {payment_id}', owner=42)
        await self.click(f'refund:{payment_id}', owner=42)
        self.assertFalse(PaymentStore(self.store.db).paid(99))
        self.assertEqual(self.store.db.execute('SELECT status FROM star_payments WHERE id=?', (payment_id,)).fetchone()[0], 'refund_pending')

    async def test_reminders_go_to_their_paid_owner_only(self):
        await self.purchase(99, 'p99')
        due = int(time.time())-30
        for user in [42, 99, 100]:
            item = self.store.for_user(user).add(str(user), dict(kind='text', text='body'))
            self.store.db.execute('INSERT INTO reminders(item_id,due_at,next_attempt) VALUES(?,?,?)', (item,due,due))
        self.store.db.commit()
        bot = AsyncMock()
        await deliver_due(bot, self.store, 42)
        self.assertEqual({call.args[0] for call in bot.send_message.await_args_list}, {42,99})
        self.assertEqual(len(self.store.for_user(100).reminders()), 1)
