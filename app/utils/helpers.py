import secrets
import csv
from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy import select, func
import pandas as pd
from sqlalchemy import select
from app.db.models import User, MaterialView, Material, MailingStatus
from datetime import datetime


from app.config import config
from app.db.models import User, KeywordLink, Material, MaterialView


async def get_or_create_user(session, tg_user):
    db_user = await session.scalar(
        select(func.count(User.id)).where(User.tg_id == str(tg_user.id))
    )
    if db_user == 0:
        new_user = User(
            tg_id=str(tg_user.id),
            username_in_tg=tg_user.username,
            first_name=tg_user.first_name or "",
            status="зарегистрирован",
            last_interaction=datetime.utcnow()
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        return new_user
    else:
        return await session.scalar(
            select(User).where(User.tg_id == str(tg_user.id))
        )


async def generate_link_for_material(
        session,
        material: Material,
        keyword,
        expire_in_days: int = None,
        max_clicks: int = None
) -> KeywordLink:
    link_str = f"{config.BOT_LINK}?start=keyword_{keyword}"  # Сгенерировать уникальный "хвост" ссылки
    expiration_date = datetime.utcnow() + timedelta(days=expire_in_days)
    new_link = KeywordLink(
        link=link_str,
        material_id=material.id,
        expiration_date=expiration_date,
        max_clicks=max_clicks
    )
    session.add(new_link)
    await session.commit()
    await session.refresh(new_link)
    return new_link


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

        data.append({
            "TG ID": user.tg_id,
            "WP ID": user.wp_id or "—",
            "Username": f"@{user.username_in_tg}" if user.username_in_tg else "—",
            "Имя": user.first_name or "—",
            "Статус": user.status or "—",
            "Дата регистрации": user.created_at.strftime('%d.%m.%Y %H:%M'),
            "Последняя активность": user.last_interaction.strftime('%d.%m.%Y %H:%M') if user.last_interaction else "—",
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
        user_stmt = select(User).where(User.tg_id == int(query))
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

