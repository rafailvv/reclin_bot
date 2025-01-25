import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import config
from app.db import init_db
from app.db import Base
from app.handlers.start import start_router
from app.handlers.broadcast import broadcast_router
from app.handlers.keyword import keyword_router
from app.handlers.stats import stats_router
from app.tasks import mailing_scheduler

logging.basicConfig(level=logging.INFO)

async def main():
    # Инициализируем БД (создаём таблицы)
    await init_db(Base)

    bot = Bot(token=config.BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем роутеры
    dp.include_router(start_router)
    dp.include_router(broadcast_router)
    dp.include_router(keyword_router)
    dp.include_router(stats_router)

    # Запускаем фоновые задачи
    # Способ 1: через встроенный механизм startup
    dp.startup.register(lambda _: asyncio.create_task(mailing_scheduler(bot)))

    logging.info("Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
