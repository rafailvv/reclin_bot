import asyncio
import logging
from datetime import datetime, timedelta
from app.db.db import AsyncSessionLocal
from app.db.models import Mailing, User
from sqlalchemy import select

async def get_active_mailings(session):
    result = await session.scalars(
        select(Mailing).where(Mailing.active == 1)
    )
    return result.all()

async def mailing_scheduler(bot):
    """
    Периодически проверяем активные рассылки и отправляем, если настало время.
    """
    while True:
        await asyncio.sleep(60)
        logging.info("Проверка рассылок...")
        try:
            async with AsyncSessionLocal() as session:
                mailings = await get_active_mailings(session)
                now = datetime.utcnow()

                for mailing in mailings:
                    if mailing.send_datetime and mailing.send_datetime <= now:
                        # Отправить рассылку
                        logging.info(f"Отправляем рассылку: {mailing.title}")

                        users = await session.scalars(
                            select(User).where(User.category == mailing.category_filter)
                        )
                        user_list = users.all()

                        for u in user_list:
                            try:
                                await bot.send_message(u.tg_id, mailing.text)
                            except Exception as e:
                                logging.warning(
                                    f"Не удалось отправить пользователю {u.tg_id}: {e}"
                                )

                        # Обновляем дату следующей рассылки или деактивируем
                        if mailing.periodicity == "daily":
                            mailing.send_datetime += timedelta(days=1)
                        elif mailing.periodicity == "weekly":
                            mailing.send_datetime += timedelta(weeks=1)
                        elif mailing.periodicity == "monthly":
                            mailing.send_datetime += timedelta(days=30)
                        else:
                            # once или custom — деактивируем
                            mailing.active = 0

                        await session.commit()
        except Exception as e:
            logging.error(f"Ошибка в планировщике рассылок: {e}")
