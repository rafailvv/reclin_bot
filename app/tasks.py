import asyncio
import logging
from datetime import datetime, timedelta
from calendar import monthrange

import aiohttp
from aiohttp import BasicAuth
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

from app.db.db import AsyncSessionLocal
from app.db.models import User, Mailing, MailingStatus, MailingSchedule, Material, MaterialView
from app.config import config


async def mailing_scheduler(bot):
    """
    Периодически проверяет расписания и отправляет рассылку, если настало время.
    Теперь поддерживается выбор пользователей для рассылки как по статусу, так и по ключевому слову.
    """
    while True:
        await asyncio.sleep(10)  # Проверяем раз в минуту
        logging.info("🔄 Проверка расписаний рассылок...")
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

                    if not schedules_to_run:
                        logging.info("✅ Нет запланированных рассылок для отправки.")
                    else:
                        logging.info(f"📬 Найдено {len(schedules_to_run)} рассылок для отправки.")

                    for schedule in schedules_to_run:
                        mailing = schedule.mailing
                        if not mailing or mailing.active != 1:
                            continue  # Пропускаем, если рассылка неактивна

                        # Получаем статусы рассылки
                        mailing_statuses = (await session.scalars(
                            select(MailingStatus).where(MailingStatus.mailing_id == mailing.id)
                        )).all()

                        # Если хотя бы один статус начинается с "keyword:", выбираем пользователей по просмотрам материала
                        if any(st.user_status.startswith("keyword:") for st in mailing_statuses):
                            keyword = [st.user_status for st in mailing_statuses if st.user_status.startswith("keyword:")][0].split(":", 1)[1]
                            material = await session.scalar(select(Material).where(Material.keyword == keyword))
                            if not material:
                                logging.error(f"Неверное ключевое слово '{keyword}' для рассылки '{mailing.title}'. Пропускаем данную рассылку.")
                                continue
                            mviews = await session.scalars(select(MaterialView).where(MaterialView.material_id == material.id))
                            mviews_list = mviews.all()
                            user_ids = [mv.user_id for mv in mviews_list]
                            if user_ids:
                                users = await session.scalars(select(User).where(User.id.in_(user_ids)))
                                users_list = users.all()
                            else:
                                users_list = []
                        else:
                            all_statuses = [ms.user_status.lower() for ms in mailing_statuses]

                            non_admin_statuses = [st for st in all_statuses if st != "админы"]
                            users_list = []
                            users_by_status = await session.scalars(
                                select(User).where(func.lower(User.status).in_(non_admin_statuses))
                            )
                            users_list.extend(users_by_status.all())
                            if "админы" in all_statuses:
                                admin_users = await session.scalars(
                                    select(User).where(User.tg_id.in_(map(str, config.ADMIN_IDS)))
                                )
                                users_list.extend(admin_users.all())

                        # Убираем дубликаты пользователей по tg_id
                        unique_users = {u.tg_id: u for u in users_list if u.tg_id}.values()

                        # Рассылка сообщений
                        success_count = 0
                        error_count = 0
                        for u in unique_users:
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

                        # Если рассылка единоразовая, деактивируем её
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


async def fetch_users():
    """
    Запрашивает список пользователей из API с Basic Auth.
    """
    async with aiohttp.ClientSession() as session:
        auth = BasicAuth(config.USERNAME, config.PASSWORD)
        try:
            async with session.get(config.API_URL + "users/", auth=auth) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"Ошибка запроса: {response.status}")
                    return None
        except aiohttp.ClientError as e:
            print(f"Ошибка сети: {e}")
            return None


async def update_database(bot):
    """
    Обновляет базу данных, проверяя изменения в API.
    """
    logging.info("Начало использование обновления БД")
    while True:
        async with AsyncSessionLocal() as session:
            try:
                users = await fetch_users()
                if not users:
                    logging.info("Не удалось получить данные из API.")
                    await asyncio.sleep(60 * 5)
                    continue
                for user_data in users:
                    wp_id = user_data.get("id_user")
                    first_name = user_data.get("name_user")
                    last_name = user_data.get("surname_user")
                    status = user_data.get("last_tarif_status")
                    created_at = datetime.strptime(user_data.get("registration_date"), "%Y-%m-%d %H:%M:%S")

                    # Ищем пользователя в базе данных
                    result = await session.execute(select(User).where(User.wp_id == wp_id))
                    user = result.scalars().first()

                    if user:
                        updated = False
                        if user.status != status:
                            user.status = status
                            updated = True
                        if user.created_at is None:
                            user.created_at = created_at
                            updated = True
                        if user.first_name != first_name:
                            user.first_name = first_name
                            updated = True
                        if user.last_name != last_name:
                            user.last_name = last_name
                            updated = True

                        if updated:
                            session.add(user)

                await session.commit()
                logging.info("База данных обновлена.")

            except SQLAlchemyError as e:
                logging.info(f"Ошибка базы данных: {e}")
                await session.rollback()
            except Exception as e:
                logging.info(f"Ошибка при обновлении базы данных: {e}")

        await asyncio.sleep(60 * 5)


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
                        candidate = schedule.next_run.replace(day=day, month=month, year=year)
                        if candidate > now:
                            return candidate
                    except ValueError:
                        pass
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                    last_day_of_month = monthrange(year, month)[1]
                    if day <= last_day_of_month:
                        found_valid_date = True
                        return datetime(year, month, day, schedule.next_run.hour, schedule.next_run.minute)

    # Для единоразовой рассылки деактивируем расписание
    schedule.active = 0
    return now
