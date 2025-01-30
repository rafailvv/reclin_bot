import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from app.db.db import AsyncSessionLocal
from app.db.models import User, Mailing, MailingStatus, MailingSchedule
from app.config import config

from datetime import datetime, timedelta
from calendar import monthrange


async def mailing_scheduler(bot):
    """
    Периодически проверяем расписания и отправляем рассылку, если настало время.
    """
    while True:
        await asyncio.sleep(60)  # Проверяем раз в минуту
        logging.info("🔄 Проверка расписаний рассылок...")
        now = datetime.utcnow()

        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    # Ищем все активные рассылки, у которых next_run <= now
                    stmt = select(MailingSchedule).where(
                        MailingSchedule.active == 1,
                        MailingSchedule.next_run <= now
                    )
                    schedules_to_run = (await session.scalars(stmt)).all()

                    if not schedules_to_run:
                        logging.info("✅ Нет запланированных рассылок для отправки.")
                    else:
                        logging.info(f"📬 Найдено {len(schedules_to_run)} рассылок для отправки.")

                    for schedule in schedules_to_run:
                        mailing = schedule.mailing
                        if not mailing or mailing.active != 1:
                            continue  # Пропускаем, если рассылка неактивна

                        # Получаем статусы пользователей для рассылки
                        statuses_stmt = select(MailingStatus).where(
                            MailingStatus.mailing_id == mailing.id
                        )
                        mailing_statuses = (await session.scalars(statuses_stmt)).all()
                        statuses_list = [ms.user_status for ms in mailing_statuses]

                        # Получаем список пользователей с нужными статусами
                        users_stmt = select(User).where(User.status.in_(statuses_list))
                        users = (await session.scalars(users_stmt)).all()

                        # Если среди статусов есть "админы", добавляем админов в рассылку
                        if "админы" in statuses_list:
                            admin_users_stmt = select(User).where(User.tg_id.in_(map(str, config.ADMIN_IDS)))
                            admin_users = (await session.scalars(admin_users_stmt)).all()
                            users.extend(admin_users)

                        # Убираем дубликаты пользователей (если вдруг один человек попал по разным статусам)
                        unique_users = {u.tg_id: u for u in users}.values()

                        # Рассылка сообщений
                        success_count = 0
                        error_count = 0
                        for u in unique_users:
                            if not u.tg_id:
                                continue
                            try:
                                await bot.copy_message(
                                    chat_id=u.tg_id,
                                    from_chat_id=mailing.saved_chat_id,
                                    message_id=mailing.saved_message_id
                                )
                                success_count += 1
                            except Exception as e:
                                logging.warning(f"❌ Ошибка отправки пользователю {u.tg_id}: {e}")
                                error_count += 1

                        logging.info(
                            f"📢 Рассылка '{mailing.title}' завершена: Успешно: {success_count}, Ошибок: {error_count}")

                        # Если рассылка единоразовая, деактивируем ее
                        if schedule.schedule_type == "once":
                            schedule.active = 0
                            logging.info(f"🛑 Единоразовая рассылка '{mailing.title}' завершена и деактивирована.")
                        else:
                            # Пересчитываем `next_run` для следующего запуска
                            schedule.next_run = compute_next_run(schedule)

                        await session.commit()

        except Exception as e:
            logging.error(f"⚠ Ошибка в планировщике рассылок: {e}")
            await asyncio.sleep(60)  # Если произошла ошибка, ждем минуту перед повтором



def compute_next_run(schedule: MailingSchedule) -> datetime:
    """
    Расчёт следующего времени запуска в зависимости от типа расписания.
    """
    now = datetime.utcnow()

    if schedule.schedule_type == "daily":
        return schedule.next_run + timedelta(days=1)

    elif schedule.schedule_type == "weekly":
        if schedule.day_of_week:
            days = sorted(int(d.strip()) for d in schedule.day_of_week.split(","))

            for day in days:
                offset = (day - 1) - schedule.next_run.weekday()
                if offset <= 0:
                    offset += 7
                candidate = schedule.next_run + timedelta(days=offset)
                if candidate > now:
                    return candidate

            return schedule.next_run + timedelta(days=7)

    elif schedule.schedule_type == "monthly":
        if schedule.day_of_month:
            days = sorted(int(d.strip()) for d in schedule.day_of_month.split(","))

            for day in days:
                month, year = schedule.next_run.month, schedule.next_run.year
                found_valid_date = False

                while not found_valid_date:
                    try:
                        # Пробуем создать дату с указанным днем
                        candidate = schedule.next_run.replace(day=day, month=month, year=year)
                        if candidate > now:
                            return candidate
                    except ValueError:
                        # Если день не существует в этом месяце, пробуем следующий месяц
                        pass

                    # Переход на следующий месяц
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1

                    # Проверяем, существует ли такой день в новом месяце
                    last_day_of_month = monthrange(year, month)[1]
                    if day <= last_day_of_month:
                        found_valid_date = True
                        return datetime(year, month, day, schedule.next_run.hour, schedule.next_run.minute)

    # Если тип "once", рассылка больше не должна запускаться
    schedule.active = 0
    return now
