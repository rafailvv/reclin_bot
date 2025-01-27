import logging

from aiogram import Router, types, Bot
from aiogram.filters import Command
from app.db.db import AsyncSessionLocal
from app.utils.helpers import get_user_statistics, export_statistics_to_csv, get_keyword_info, get_user_info

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

@stats_router.message(Command("keyword_info"))
async def cmd_keyword_info(message: types.Message, bot: Bot):
    """
    Получить информацию по ключевому слову.
    """
    keyword = message.text.split(" ", 1)[-1]  # Ключевое слово передаётся после команды
    async with AsyncSessionLocal() as session:
        info = await get_keyword_info(session, keyword)
        if not info:
            await message.answer("Ключевое слово не найдено.")
            return

        try:
            # Пересылаем сообщение, связанное с ключевым словом
            await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=info['chat_id'],  # откуда пересылаем
                message_id=info['message_id']  # какое сообщение пересылаем
            )
        except Exception as e:
            logging.error(f"Не удалось переслать сообщение: {e}")
            await message.answer("Ошибка, обратитесь к администратору")

        # Формируем текст ответа
        reply_text = (
            f"Ключевое слово: {info['keyword']}\n"
            f"Количество просмотров: {info['view_count']}\n"
            "Связанные ссылки:\n"
        )
        if info["links"]:
            for link in info["links"]:
                reply_text += f"  - {link}\n"
        else:
            reply_text += "  Нет связанных ссылок.\n"

        await message.answer(reply_text)

@stats_router.message(Command("user_info"))
async def cmd_user_info(message: types.Message):
    """
    Получить информацию по пользователю.
    """
    tg_id = message.text.split(" ", 1)[-1]  # Telegram ID пользователя передаётся после команды
    async with AsyncSessionLocal() as session:
        info = await get_user_info(session, tg_id)
        if not info:
            await message.answer("Пользователь не найден.")
            return

        user_info = info["user"]
        reply_text = (
            f"Пользователь:\n"
            f"  Telegram ID: {user_info['tg_id']}\n"
            f"  Имя: {user_info['first_name']}\n"
            f"  Статус: {user_info['status']}\n"
            f"  Категория: {user_info['category']}\n"
            f"  Дата создания: {user_info['created_at'].strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Просмотренные материалы:\n"
        )
        for material in info["viewed_materials"]:
            reply_text += (
                f"  - Ключевое слово: {material['keyword']}\n"
                f"  - Дата просмотра: {material['viewed_at'].strftime('%d.%m.%Y %H:%M')}\n"
            )

        await message.answer(reply_text)
