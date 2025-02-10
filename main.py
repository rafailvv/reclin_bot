import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select, func

from app.config import config
from app.db.db import init_db, AsyncSessionLocal
from app.db.models import Base, User
from app.handlers.callback import callback_router
from app.handlers.start import start_router
from app.handlers.broadcast import broadcast_router
from app.handlers.keyword import keyword_router
from app.handlers.stats import stats_router
from app.tasks import mailing_scheduler, update_database

from app.utils.excel_loader import load_initial_data_from_excel

logging.basicConfig(level=logging.INFO)

async def main():
    # Шаг 1: создаём таблицы (если не существуют)
    await init_db(Base)

    # Шаг 2: проверяем, пуста ли таблица User
    async with AsyncSessionLocal() as session:
        count_users = await session.scalar(select(func.count(User.id)))
        if count_users == 0:
            logging.info("Таблица User пуста. Загружаем данные из reclin_base.xlsx ...")
            await load_initial_data_from_excel(session, file_path="reclin_base.xlsx")
        else:
            logging.info(f"В таблице User уже есть {count_users} запись(-ей). Пропускаем загрузку Excel.")

    # Инициализация бота и диспетчера
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
    dp = Dispatcher(storage=MemoryStorage())

    # Подключаем роутеры
    dp.include_router(start_router)
    dp.include_router(broadcast_router)
    dp.include_router(keyword_router)
    dp.include_router(stats_router)
    dp.include_router(callback_router)

    # Регистрируем запуск фоновой задачи в on_startup
    asyncio.create_task(mailing_scheduler(bot))
    asyncio.create_task(update_database(bot))

    logging.info("Starting bot polling...")
    await dp.start_polling(bot)



if __name__ == "__main__":
    import uvloop
    uvloop.install()
    asyncio.run(main())

