import secrets
import csv
from datetime import datetime, timedelta
from sqlalchemy import func, select

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


async def export_statistics_to_csv(session, file_path: str = "stats.csv"):
    """
    Экспорт в CSV
    """
    users = await session.scalars(select(User))
    user_list = users.all()

    with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile, delimiter=";")
        writer.writerow(["TG ID", "WP ID", "Статус", "Username", "Имя"])
        for u in user_list:
            writer.writerow([u.tg_id, u.wp_id, u.status, u.username_in_tg, u.first_name])

    return file_path

from sqlalchemy import select, func

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
        select(KeywordLink.link)
        .join(Material, KeywordLink.material_id == Material.id)
        .where(Material.keyword == keyword)
    )
    link_result = await session.execute(link_stmt)
    links = [row.link for row in link_result]

    return {
        "keyword": material_data.keyword,
        "chat_id": material_data.chat_id,
        "message_id": material_data.message_id,
        "view_count": material_data.view_count,
        "links": links,
    }


async def get_user_info(session, tg_id):
    """
    Получить информацию по пользователю и ключевым словам, которые он просматривал.
    """
    # Запрос информации о пользователе
    user_stmt = select(User).where(User.tg_id == tg_id)
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

