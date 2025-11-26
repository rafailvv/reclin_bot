import asyncio
import logging
import json
import subprocess
import os
from datetime import datetime, timedelta
from calendar import monthrange

import aiohttp
from aiohttp import BasicAuth
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

from app.db.db import AsyncSessionLocal
from app.db.models import User, Mailing, MailingStatus, MailingSchedule, Material, MaterialView
from app.config import config
from app.utils.helpers import get_users_by_ids_batched
from aiogram.types import MessageEntity, InputMediaPhoto, InputMediaDocument, InputMediaVideo
from aiogram import Bot


async def create_database_backup():
    """
    Создает бэкап базы данных PostgreSQL
    """
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        backup_filename = f"backup_{timestamp}.sql"
        backup_path = f"/tmp/{backup_filename}"
        
        # Команда для создания бэкапа
        cmd = [
            "pg_dump",
            "-h", config.DB_HOST,
            "-p", config.DB_PORT,
            "-U", config.DB_USER,
            "-d", config.DB_NAME,
            "-f", backup_path
        ]
        
        # Устанавливаем переменную окружения для пароля
        env = os.environ.copy()
        env["PGPASSWORD"] = config.DB_PASSWORD
        
        # Выполняем команду
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        if result.returncode == 0:
            logging.info(f"✅ Бэкап создан успешно: {backup_filename}")
            return backup_path
        else:
            logging.error(f"❌ Ошибка создания бэкапа: {result.stderr}")
            return None
            
    except Exception as e:
        logging.error(f"❌ Ошибка при создании бэкапа: {e}")
        return None


async def backup_scheduler(bot: Bot):
    """
    Планировщик бэкапов - создает и отправляет бэкап базы данных каждую ночь в 01:00
    """
    logging.info("🔄 Планировщик бэкапов запущен")
    
    while True:
        now = datetime.now()
        
        # Проверяем, наступило ли время для бэкапа (01:00)
        if now.hour == 1 and now.minute == 0:
            logging.info("🕐 Время создания бэкапа!")
            
            try:
                # Создаем бэкап
                backup_path = await create_database_backup()
                
                if backup_path and os.path.exists(backup_path):
                    # Отправляем бэкап в Telegram
                    with open(backup_path, 'rb') as backup_file:
                        await bot.send_document(
                            chat_id=429272623,
                            document=backup_file,
                            caption=f"📦 Бэкап базы данных\n📅 Дата: {now.strftime('%d.%m.%Y %H:%M')}\n💾 Размер: {os.path.getsize(backup_path) / 1024:.1f} KB"
                        )
                    
                    # Удаляем временный файл
                    os.remove(backup_path)
                    logging.info("✅ Бэкап отправлен и файл удален")
                else:
                    await bot.send_message(
                        chat_id=429272623,
                        text=f"❌ Ошибка создания бэкапа\n📅 Дата: {now.strftime('%d.%m.%Y %H:%M')}"
                    )
                    logging.error("❌ Не удалось создать бэкап")
                    
            except Exception as e:
                logging.error(f"❌ Ошибка в планировщике бэкапов: {e}")
                try:
                    await bot.send_message(
                        chat_id=429272623,
                        text=f"❌ Ошибка в планировщике бэкапов\n📅 Дата: {now.strftime('%d.%m.%Y %H:%M')}\n🔍 Ошибка: {str(e)}"
                    )
                except:
                    pass
        
        # Ждем 1 минуту перед следующей проверкой
        await asyncio.sleep(60)


async def mailing_scheduler(bot):
    """
    Периодически проверяет расписания и отправляет рассылку, если настало время.
    Теперь поддерживается выбор пользователей для рассылки как по статусу, так и по ключевым словам (в том числе по нескольким ключевым словам).
    При отправке используются поля file_ids, caption и caption_entities для формирования сообщения.
    """
    while True:
        await asyncio.sleep(60)  # Проверяем раз в 60 секунд
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
                        if any(ms.user_status.startswith("keyword:") for ms in mailing_statuses):
                            keyword_statuses = [ms.user_status for ms in mailing_statuses if ms.user_status.startswith("keyword:")]
                            keywords = [s.split(":", 1)[1].strip() for s in keyword_statuses]
                            if not keywords:
                                logging.error(f"Ключевые слова не заданы для рассылки '{mailing.title}'. Пропускаем данную рассылку.")
                                continue

                            materials_result = await session.scalars(select(Material).where(Material.keyword.in_(keywords)))
                            materials_list = materials_result.all()
                            if not materials_list:
                                logging.error(f"Неверные ключевые слова {keywords} для рассылки '{mailing.title}'. Пропускаем данную рассылку.")
                                continue

                            material_ids = [material.id for material in materials_list]
                            mviews = await session.scalars(select(MaterialView).where(MaterialView.material_id.in_(material_ids)))
                            mviews_list = mviews.all()
                            user_ids = [mv.user_id for mv in mviews_list]
                            if user_ids:
                                users_list = await get_users_by_ids_batched(session, user_ids)
                            else:
                                users_list = []
                        else:
                            # Таргетинг по статусам
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
                        unique_users = set({u.tg_id: u for u in users_list if u.tg_id}.values())

                        # Рассылка сообщений с учетом вложений, caption и caption_entities
                        success_count = 0
                        error_count = 0
                        for u in unique_users:
                            try:
                                attachments = json.loads(mailing.file_ids)
                                entities = None
                                if mailing.caption_entities:
                                    try:
                                        entities = [MessageEntity(**entity) for entity in json.loads(mailing.caption_entities)]
                                    except Exception as e:
                                        logging.error(f"Ошибка парсинга caption_entities: {e}")
                                        entities = None
                                if attachments and len(attachments) > 1:
                                    input_media = []
                                    for idx, att in enumerate(attachments):
                                        if att["type"] == "photo":
                                            media_obj = InputMediaPhoto(
                                                media=att["file_id"],
                                                caption=mailing.caption if (idx == 0 and mailing.caption) else None,
                                                caption_entities=entities if (idx == 0 and mailing.caption) else None,
                                                parse_mode=None,
                                            )
                                        elif att["type"] == "document":
                                            media_obj = InputMediaDocument(
                                                media=att["file_id"],
                                                caption=mailing.caption if (idx == 0 and mailing.caption) else None,
                                                caption_entities=entities if (idx == 0 and mailing.caption) else None,
                                                parse_mode=None,
                                            )
                                        elif att["type"] == "video":
                                            media_obj = InputMediaVideo(
                                                media=att["file_id"],
                                                caption=mailing.caption if (idx == 0 and mailing.caption) else None,
                                                caption_entities=entities if (idx == 0 and mailing.caption) else None,
                                                parse_mode=None,
                                            )
                                        input_media.append(media_obj)
                                    await bot.send_media_group(chat_id=u.tg_id, media=input_media)
                                elif attachments and len(attachments) == 1:
                                    att = attachments[0]
                                    if att["type"] == "photo":
                                        await bot.send_photo(
                                            chat_id=u.tg_id,
                                            photo=att["file_id"],
                                            caption=mailing.caption,
                                            caption_entities=entities,
                                            parse_mode=None,
                                        )
                                    elif att["type"] == "document":
                                        await bot.send_document(
                                            chat_id=u.tg_id,
                                            document=att["file_id"],
                                            caption=mailing.caption,
                                            caption_entities=entities,
                                            parse_mode=None,
                                        )
                                    elif att["type"] == "video":
                                        await bot.send_video(
                                            chat_id=u.tg_id,
                                            video=att["file_id"],
                                            caption=mailing.caption,
                                            caption_entities=entities,
                                            parse_mode=None,
                                        )
                                else:
                                    await bot.send_message(
                                        chat_id=u.tg_id,
                                        text=mailing.caption,
                                        entities=entities,
                                        parse_mode=None,
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
                            # Пересчитываем next_run для следующего запуска
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
                    if status == "Подписка активна":
                        status = user_data.get("last_Tarif_name")
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
