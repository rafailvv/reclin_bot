from aiogram import Router, types
from aiogram.filters import Command
from app.db.db import AsyncSessionLocal
from app.utils.helpers import get_user_statistics, export_statistics_to_csv

stats_router = Router()

@stats_router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """
    Показать статистику
    """
    async with AsyncSessionLocal() as session:
        stats = await get_user_statistics(session)
        reply_text = (
            f"Общее количество пользователей: {stats['total_users']}\n"
            f"Активных: {stats['active_users']}\n"
            "Пользователи по категориям:\n"
        )
        for cat, cnt in stats["category_data"]:
            reply_text += f"  - {cat}: {cnt}\n"

        await message.answer(reply_text)

@stats_router.message(Command("export_csv"))
async def cmd_export_csv(message: types.Message):
    """
    Экспорт статистики в CSV
    """
    async with AsyncSessionLocal() as session:
        csv_path = await export_statistics_to_csv(session, "users_stats.csv")
    # Отправим файл
    await message.answer_document(document=types.FSInputFile(csv_path))
