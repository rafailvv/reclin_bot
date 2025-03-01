import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import config

# Создаём асинхронный движок SQLAlchemy
engine = create_async_engine(config.database_url, echo=False)

# Создаём фабрику асинхронных сессий
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db(Base):
    """
    Удаляет все таблицы, кроме User, и создаёт их заново при запуске.
    """
    async with engine.begin() as conn:
        # Получаем список таблиц для удаления, исключая User
        tables_to_drop = [table for table in Base.metadata.sorted_tables if table.name != "users"]

        # Удаляем выбранные таблицы
        for table in reversed(tables_to_drop):  # Удаляем в обратном порядке зависимостей
            await conn.run_sync(table.drop)
        logging.info("Все таблицы, кроме User, удалены.")

        # Создаём все таблицы заново
        await conn.run_sync(Base.metadata.create_all)
        logging.info("Таблицы в БД созданы/обновлены.")
