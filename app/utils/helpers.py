import secrets
import csv
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from sqlalchemy import func, select
from sqlalchemy import select, func
import pandas as pd
from sqlalchemy import select
from app.db.models import User, MaterialView, Material, MailingStatus
from datetime import datetime


from app.config import config
from app.db.models import User, KeywordLink, Material, MaterialView


async def get_or_create_user(session, tg_user, wp_id: str = "не зарегистрирован"):
    """
    Получает или создает пользователя в БД.
    """
    user = await session.execute(select(User).where(User.tg_id == str(tg_user.id)))
    user = user.scalar_one_or_none()

    if not user:
        user = User(
            tg_id=str(tg_user.id),
            wp_id=wp_id,
            username_in_tg=tg_user.username,
            tg_fullname=tg_user.full_name,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            created_at=datetime.utcnow()
        )
        session.add(user)
        await session.commit()  # Фиксируем изменения в БД
        await session.refresh(user)  # Загружаем user с обновленным ID

    elif wp_id and not user.wp_id:
        user.wp_id = wp_id
        await session.commit()  # Сохраняем изменения, если обновили wp_id

    return user


async def generate_link_for_material(session, material, keyword, expire_in_days, max_clicks):
    link_str = f"{config.BOT_LINK}?start=keyword_{keyword}"
    expiration_date = datetime.utcnow() + timedelta(days=expire_in_days) if expire_in_days else None

    # Проверяем, существует ли уже объект с таким URL
    stmt = select(KeywordLink).where(KeywordLink.link == link_str)
    existing_link = await session.scalar(stmt)

    if existing_link:
        # Обновляем поля существующего объекта
        existing_link.material_id = material.id
        existing_link.expiration_date = expiration_date
        existing_link.max_clicks = max_clicks
        # Если нужно сбросить счетчик кликов при обновлении, можно установить его в 0
        existing_link.click_count = 0
        link_obj = existing_link
    else:
        # Создаем новый объект, если такого URL ещё нет
        link_obj = KeywordLink(
            link=link_str,
            material_id=material.id,
            expiration_date=expiration_date,
            max_clicks=max_clicks,
            click_count=0,
        )
        session.add(link_obj)

    await session.commit()
    await session.refresh(link_obj)
    return link_obj



async def get_user_statistics(session):
    total_users = await session.scalar(select(func.count(User.id)))
    active_users = await session.scalar(
        select(func.count(User.id)).where(User.status != "неактивен")
    )
    # Группировка по категориям
    cat_stmt = select(User.status, func.count(User.id)).group_by(User.status)
    result = await session.execute(cat_stmt)
    category_data = result.all()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "category_data": category_data
    }


async def export_statistics_to_excel(session, file_path: str = "stats.xlsx"):
    """
    Экспорт статистики пользователей в Excel с дополнительными данными.
    """
    # Получаем пользователей
    users = await session.scalars(select(User))
    user_list = users.all()

    data = []

    for user in user_list:
        # Получаем просмотренные материалы
        views_stmt = (
            select(Material.keyword, MaterialView.viewed_at)
            .join(Material, Material.id == MaterialView.material_id)
            .where(MaterialView.user_id == user.id)
            .order_by(MaterialView.viewed_at.desc())  # Последние в начале
        )
        views_result = await session.execute(views_stmt)
        views = views_result.all()

        viewed_keywords = [v.keyword for v in views] if views else ["—"]
        last_viewed_at = views[0].viewed_at if views else None

        # Получаем рассылки, в которых участвует пользователь (по его статусу)
        mailing_stmt = (
            select(MailingStatus.mailing_id)
            .where(MailingStatus.user_status == user.status)
        )
        mailing_result = await session.execute(mailing_stmt)
        mailings = [str(m.mailing_id) for m in mailing_result.all()] if mailing_result else ["—"]

        # Получаем дату последнего посещения
        last_visit_stmt = (
            select(MaterialView.viewed_at)
            .where(MaterialView.user_id == user.id)
            .order_by(MaterialView.viewed_at.desc())
            .limit(1)
        )
        last_visit_result = await session.execute(last_visit_stmt)
        last_visit = last_visit_result.scalar_one_or_none()

        data.append({
            "TG ID": user.tg_id,
            "WP ID": user.wp_id or "—",
            "Username": f"@{user.username_in_tg}" if user.username_in_tg else "—",
            "Имя": user.first_name or "—",
            "Статус": (user.status or "—").lower(),
            "Дата регистрации": user.created_at.strftime('%d.%m.%Y %H:%M') if user.created_at else "—",
            "Последняя активность": user.last_interaction.strftime('%d.%m.%Y %H:%M') if user.last_interaction else "—",
            "Дата последнего посещения": last_visit.strftime('%d.%m.%Y %H:%M') if last_visit else "—",
            "Просмотренные ключевые слова": ", ".join(viewed_keywords),
            "Последний просмотр": last_viewed_at.strftime('%d.%m.%Y %H:%M') if last_viewed_at else "—",
            "Подписан на рассылки (по статусу)": ", ".join(mailings),
        })

    # Создаем DataFrame и записываем в Excel
    df = pd.DataFrame(data)
    df.to_excel(file_path, index=False, sheet_name="Статистика пользователей")

    return file_path



async def get_keyword_info(session, keyword):
    """
    Получить информацию по ключевому слову.
    """
    # Запрос информации о ключевом слове и связанных данных
    stmt = (
        select(
            Material.keyword,
            Material.chat_id,
            Material.message_id,
            func.count(MaterialView.id).label("view_count"),
        )
        .join(MaterialView, Material.id == MaterialView.material_id, isouter=True)
        .where(Material.keyword == keyword)
        .group_by(Material.id)
    )
    result = await session.execute(stmt)
    material_data = result.first()

    if not material_data:
        return None

    # Запрос ссылок для ключевого слова
    link_stmt = (
        select(
            KeywordLink.link,
            KeywordLink.expiration_date,
            KeywordLink.max_clicks,
            KeywordLink.click_count
        )
        .join(Material, KeywordLink.material_id == Material.id)
        .where(Material.keyword == keyword)
    )
    link_result = await session.execute(link_stmt)

    links = []
    for row in link_result:
        link_info = {
            "link": row.link,
            "expiration_date": row.expiration_date,
            "max_clicks": row.max_clicks
        }
        links.append(link_info)

    return {
        "keyword": material_data.keyword,
        "chat_id": material_data.chat_id,
        "message_id": material_data.message_id,
        "view_count": material_data.view_count,
        "links": links,
    }


async def get_user_info(session, query):
    """
    Получить информацию по пользователю и ключевым словам, которые он просматривал.
    Поддерживает поиск по Telegram ID, username (@username) и имени.
    """
    user_stmt = None

    if query.isdigit():  # Если введено число, ищем по Telegram ID
        user_stmt = select(User).where(User.tg_id == query)
    elif query.startswith("@"):  # Если начинается с @, ищем по username
        user_stmt = select(User).where(User.username_in_tg.ilike(query[1:]))
    else:  # Ищем по first_name (некоторые пользователи могут быть без username)
        user_stmt = select(User).where(User.first_name.ilike(f"%{query}%"))

    user_result = await session.execute(user_stmt)
    user = user_result.scalars().first()

    if not user:
        return None

    # Запрос всех материалов, которые пользователь просмотрел
    stmt = (
        select(
            Material.keyword,
            Material.chat_id,
            Material.message_id,
            MaterialView.viewed_at
        )
        .join(MaterialView, Material.id == MaterialView.material_id)
        .where(MaterialView.user_id == user.id)
    )
    result = await session.execute(stmt)
    viewed_materials = result.all()

    return {
        "user": {
            "tg_id": user.tg_id,
            "username": user.username_in_tg,  # Добавляем username, если есть
            "first_name": user.first_name,
            "status": user.status,
            "created_at": user.created_at,
            "last_interaction": user.last_interaction,
        },
        "viewed_materials": [
            {
                "keyword": material.keyword,
                "chat_id": material.chat_id,
                "message_id": material.message_id,
                "viewed_at": material.viewed_at,
            }
            for material in viewed_materials
        ],
    }


async def get_day_of_week_names(number):
    """
    Получить название дня недели по его номеру (0-6)
    """
    days_of_week = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days_of_week[number-1] if 1 <= number < 8 else None

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))

