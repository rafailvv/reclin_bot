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
    Удаляет существующие таблицы и создаёт их заново при запуске.
    """
    async with engine.begin() as conn:
        # Удаляем все таблицы
        await conn.run_sync(Base.metadata.drop_all)
        logging.info("Все таблицы удалены.")

        # Создаём все таблицы заново
        await conn.run_sync(Base.metadata.create_all)
        logging.info("Таблицы в БД созданы/обновлены.")
