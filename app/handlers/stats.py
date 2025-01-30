import logging
import os
from datetime import datetime

from aiogram import Router, types, Bot
from aiogram.filters import Command
from app.db.db import AsyncSessionLocal
from app.utils.helpers import get_user_statistics, get_keyword_info, get_user_info, \
    export_statistics_to_excel

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

@stats_router.message(Command("export_stats"))
async def cmd_export_stats(message: types.Message):
    """
    Экспорт статистики пользователей в Excel и отправка файла.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    file_path = f"users_stats_{timestamp}.xlsx"  # Указываем дату и время в названии файла
    message = await message.answer("Ожидайте, собираем информацию...")
    async with AsyncSessionLocal() as session:
        file_path = await export_statistics_to_excel(session, file_path)
    await message.delete()
    # Отправляем файл пользователю
    await message.answer_document(document=types.FSInputFile(file_path))

    # Удаляем файл после отправки (чтобы не засорять сервер)
    if os.path.exists(file_path):
        os.remove(file_path)

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
            f"Ключевое слово: <b>{info['keyword']}</b>\n"
            f"Количество просмотров: <b>{info['view_count']}</b>\n"
            "\nСвязанные ссылки:\n"
        )

        if info["links"]:
            for link_data in info["links"]:
                link_text = f"{link_data['link']}\n"
                if link_data["expiration_date"]:
                    link_text += f"Действует до: <b>{link_data['expiration_date'].strftime('%d.%m.%Y %H:%M')}</b>\n"
                link_text += f"Максимальное кол-во кликов: <b>{link_data['max_clicks']}</b>\n"
                reply_text += link_text
        else:
            reply_text += "Нет связанных ссылок.\n"

        await message.answer(reply_text)


@stats_router.message(Command("user_info"))
@stats_router.message(Command("user_info"))
async def cmd_user_info(message: types.Message):
    """
    Получить информацию по пользователю (по ID, username или имени).
    """
    query = message.text.split(" ", 1)[-1].strip()  # Получаем аргумент команды

    if not query:
        await message.answer("Укажите Telegram ID, username (@username) или имя пользователя.")
        return

    async with AsyncSessionLocal() as session:
        info = await get_user_info(session, query)
        if not info:
            await message.answer("Пользователь не найден.")
            return

        user_info = info["user"]
        reply_text = (
            f"Пользователь:\n"
            f"Telegram ID: <a href='tg://user?id={user_info['tg_id']}'>{user_info['tg_id']}</a>\n"
        )

        if user_info.get("username"):
            reply_text += f"Username: @{user_info['username']}\n"

        reply_text += (
            f"Имя: <b><a href='tg://user?id={user_info['tg_id']}'>{user_info['first_name']}</a></b>\n"
            f"Статус: <b>{user_info['status']}</b>\n"
            f"Дата регистрации: <b>{user_info['created_at'].strftime('%d.%m.%Y %H:%M')}</b>\n\n"
            f"Просмотренные материалы:\n"
        )

        for material in info["viewed_materials"]:
            reply_text += (
                f"- Ключевое слово: <b>{material['keyword']}</b>\n"
                f"- Дата просмотра: <b>{material['viewed_at'].strftime('%d.%m.%Y %H:%M')}</b>\n"
            )

        await message.answer(reply_text, parse_mode="HTML")
