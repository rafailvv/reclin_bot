import asyncio
import logging
from datetime import datetime, timedelta, date, time
from sqlalchemy import select
from app.db.db import AsyncSessionLocal
from app.db.models import (
    Mailing,
    MailingSchedule,
    MailingStatus,
    User
)


async def mailing_scheduler(bot):
    """
    Периодически проверяем расписания и отправляем рассылку, если настало время.
    """
    while True:
        logging.info("Проверка расписаний рассылок...")
        now = datetime.utcnow()

        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    # Ищем все активные расписания, у которых next_run <= now
                    stmt = select(MailingSchedule).where(
                        MailingSchedule.active == 1,
                        MailingSchedule.next_run <= now
                    )
                    schedules_to_run = (await session.scalars(stmt)).all()

                    for schedule in schedules_to_run:
                        mailing = schedule.mailing
                        if mailing.active != 1:
                            # Рассылка не активна, пропускаем
                            continue

                        # Собираем все статусы, привязанные к этой рассылке
                        statuses_stmt = select(MailingStatus).where(
                            MailingStatus.mailing_id == mailing.id
                        )
                        mailing_statuses = (await session.scalars(statuses_stmt)).all()
                        statuses_list = [ms.user_status for ms in mailing_statuses]

                        # Выбираем всех пользователей, у которых status в списке
                        users_stmt = select(User).where(
                            User.status.in_(statuses_list)
                        )
                        users = (await session.scalars(users_stmt)).all()

                        # Отправляем copy_message
                        for u in users:
                            try:
                                await bot.copy_message(
                                    chat_id=u.tg_id,
                                    from_chat_id=mailing.saved_chat_id,
                                    message_id=mailing.saved_message_id
                                )
                            except Exception as e:
                                logging.warning(f"Не удалось отправить пользователю {u.tg_id}: {e}")

                        # Обновляем next_run
                        schedule.next_run = compute_next_run(schedule)
                        await session.commit()
            await asyncio.sleep(60)  # раз в минуту

        except Exception as e:
            logging.error(f"Ошибка в планировщике рассылок: {e}")


def compute_next_run(schedule: MailingSchedule) -> datetime:
    """
    Упрощённая логика расчёта следующего запуска.
    """
    now = datetime.utcnow()

    if schedule.schedule_type == "daily":
        # просто +1 день
        return schedule.next_run + timedelta(days=1)

    elif schedule.schedule_type == "weekly":
        # day_of_week может хранить несколько дней, но для упрощения берём первый
        if schedule.day_of_week:
            # Если там "2,5" и т.д.
            # здесь условно обрабатываем только первый
            days = [int(d.strip()) for d in schedule.day_of_week.split(",")]
            if not days:
                return now + timedelta(weeks=1)

            # Предположим, уже назначено на нужный день,
            # просто +7 дней
            return schedule.next_run + timedelta(weeks=1)

        else:
            # fallback
            return now + timedelta(weeks=1)

    elif schedule.schedule_type == "monthly":
        # day_of_month может быть "1,15,28" и т.д.
        # мы берём первую дату
        if schedule.day_of_month:
            days = [int(d.strip()) for d in schedule.day_of_month.split(",")]
            if not days:
                return now + timedelta(days=30)
            # прибавим 1 месяц к текущей дате (schedule.next_run)
            dt = schedule.next_run
            year = dt.year
            month = dt.month + 1
            if month > 12:
                month = 1
                year += 1
            day = days[0]  # берём первый из списка

            # Пытаемся создать дату
            from calendar import monthrange
            max_day = monthrange(year, month)[1]
            if day > max_day:
                day = max_day

            return datetime(year, month, day, dt.hour, dt.minute)
        else:
            return now + timedelta(days=30)

    else:
        # once — отправили один раз и отключаем
        schedule.active = 0
        return now
