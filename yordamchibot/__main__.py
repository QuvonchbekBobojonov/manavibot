import asyncio
import logging
import os
from contextlib import suppress

from aiogram import Bot, Dispatcher, types

from .handlers import COMMANDS, OwnerOnly, create_router
from .reminders import reminder_loop
from .storage import Store


async def main():
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
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
    worker = None
    try:
        await bot.set_my_commands([types.BotCommand(command=c, description=d) for c, d in COMMANDS])
        worker = asyncio.create_task(reminder_loop(bot, store, owner))
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        store.close()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        logging.error('Startup failure: %s', type(exc).__name__)
        raise SystemExit(1)
