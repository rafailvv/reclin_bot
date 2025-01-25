import secrets
import csv
from datetime import datetime, timedelta
from sqlalchemy import func, select
from app.db import User, KeywordLink, Material

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
            category="common",
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

async def generate_unique_link() -> str:
    """
    Упрощённая генерация ссылки (token_urlsafe).
    """
    return secrets.token_urlsafe(10)

async def generate_link_for_material(
    session,
    material: Material,
    expire_in_days: int = 7,
    max_clicks: int = 5
) -> KeywordLink:
    link_str = await generate_unique_link()
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
    cat_stmt = select(User.category, func.count(User.id)).group_by(User.category)
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
