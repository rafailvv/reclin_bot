import json
import logging
import os
from datetime import datetime

from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.types import MessageEntity, InputMediaPhoto, InputMediaDocument, InputMediaVideo, FSInputFile
from sqlalchemy import select, delete
from sqlalchemy.orm import joinedload

from app.config import config
from app.db.db import AsyncSessionLocal
from app.db.models import KeywordLink, Material, MaterialView
from app.utils.helpers import get_user_statistics, get_keyword_info, get_user_info, export_statistics_to_excel

stats_router = Router()

@stats_router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """
    Показать статистику
    """
    if message.chat.id not in config.ADMIN_IDS:
        return
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
    if message.chat.id not in config.ADMIN_IDS:
        return
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

async def send_keyword_info(chat_id: int, keyword: str, bot: Bot):
    """
    Получает материал и информацию по ключевому слову, отправляет медиа (если есть) и текст с данными.
    Добавляет кнопку для удаления ключевого слова.
    """
    async with AsyncSessionLocal() as session:
        info = await get_keyword_info(session, keyword)
        stmt = (
            select(KeywordLink)
            .join(KeywordLink.material)
            .where(Material.keyword == keyword)
            .options(joinedload(KeywordLink.material))
        )
        link_obj = await session.scalar(stmt)
    if not link_obj:
        await bot.send_message(chat_id, f"Ключевое слово '{keyword}' не найдено.")
        return

    material = link_obj.material
    if not material or not material.chat_id or not material.message_id:
        await bot.send_message(chat_id, "Материал не найден или некорректен.")
        return

    # Отправляем материал (если есть медиа — отправляем media_group, иначе текстовое сообщение)
    if material.file_ids and json.loads(material.file_ids):
        file_list = json.loads(material.file_ids)
        input_media = []
        for i, item in enumerate(file_list):
            entities = (
                [MessageEntity(**entity) for entity in json.loads(material.caption_entities)]
                if material.caption_entities else None
            )
            if item["type"] == "photo":
                media_obj = InputMediaPhoto(
                    media=item["file_id"],
                    caption=material.caption if (i == 0 and material.caption) else None,
                    caption_entities=entities if (i == 0 and material.caption) else None
                )
            elif item["type"] == "document":
                media_obj = InputMediaDocument(
                    media=item["file_id"],
                    caption=material.caption if (i == 0 and material.caption) else None,
                    caption_entities=entities if (i == 0 and material.caption) else None
                )
            elif item["type"] == "video":
                media_obj = InputMediaVideo(
                    media=item["file_id"],
                    caption=material.caption if (i == 0 and material.caption) else None,
                    caption_entities=entities if (i == 0 and material.caption) else None
                )
            input_media.append(media_obj)
        await bot.send_media_group(chat_id=chat_id, media=input_media)
    else:
        entities = (
            [MessageEntity(**entity) for entity in json.loads(material.caption_entities)]
            if material.caption_entities else None
        )
        await bot.send_message(chat_id=chat_id, text=material.caption, entities=entities)

    # Формируем текст с информацией по ключевому слову
    reply_text = (
        f"Ключевое слово: <b>{info['keyword']}</b>\n"
        f"Количество просмотров: <b>{info['view_count']}</b>\n\n"
        "Связанные ссылки:\n"
    )
    if info["links"]:
        for link_data in info["links"]:
            link_text = f"{link_data['link']}\n"
            if link_data["expiration_date"]:
                link_text += f"Действует до: <b>{link_data['expiration_date'].strftime('%d.%m.%Y %H:%M')}</b>\n"
            else:
                link_text += "Действует <b>без срока действия</b>.\n"
            link_text += f"Максимальное кол-во кликов: <b>{link_data['max_clicks'] if link_data['max_clicks'] is not None else 'без ограничений'}</b>\n"
            reply_text += link_text
    else:
        reply_text += "Нет связанных ссылок.\n"

    # Кнопка удаления
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Удалить ключевое слово", callback_data=f"delete_keyword_{keyword}")]
    ])
    await bot.send_message(chat_id=chat_id, text=reply_text, reply_markup=keyboard, parse_mode="HTML")


@stats_router.message(Command("keyword_info"))
async def cmd_keyword_info(message: types.Message, bot: Bot):
    """
    Если команда вызывается с аргументом (например, /keyword_info MARCH8),
    сразу показывает информацию по этому ключевому слову.
    Если аргумент не передан, выводит список всех ключевых слов.
    """
    if message.chat.id not in config.ADMIN_IDS:
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) == 2:
        keyword = parts[1]
        await send_keyword_info(message.chat.id, keyword, bot)
    else:
        async with AsyncSessionLocal() as session:
            materials = (await session.scalars(select(Material))).all()
        if not materials:
            await message.answer("Нет сохранённых ключевых слов.")
            return
        buttons = [
            [types.InlineKeyboardButton(text=m.keyword, callback_data=f"info_keyword_{m.keyword}")]
            for m in materials
        ]
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите ключевое слово для просмотра информации:", reply_markup=keyboard)


@stats_router.callback_query(lambda c: c.data and c.data.startswith("info_keyword_"))
async def show_keyword_info(callback: types.CallbackQuery, bot: Bot):
    keyword = callback.data[len("info_keyword_"):]
    await send_keyword_info(callback.message.chat.id, keyword, bot)
    await callback.answer()


@stats_router.callback_query(lambda c: c.data and c.data.startswith("delete_keyword_"))
async def prompt_delete_keyword(callback: types.CallbackQuery, bot: Bot):
    keyword = callback.data[len("delete_keyword_"):]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Да ✅", callback_data=f"confirm_delete_keyword_{keyword}"),
        types.InlineKeyboardButton(text="Нет ❌", callback_data=f"cancel_delete_keyword_{keyword}")]
    ])
    await callback.message.edit_text(
        f"Вы действительно хотите удалить ключевое слово '{keyword}' и всю связанную с ним информацию?",
        reply_markup=keyboard
    )
    await callback.answer()


@stats_router.callback_query(lambda c: c.data and c.data.startswith("confirm_delete_keyword_"))
async def confirm_delete_keyword(callback: types.CallbackQuery, bot: Bot):
    keyword = callback.data[len("confirm_delete_keyword_"):]
    async with AsyncSessionLocal() as session:
        material = await session.scalar(select(Material).where(Material.keyword == keyword))
        if not material:
            await callback.message.edit_text(f"Ключевое слово '{keyword}' не найдено.")
            return
        # Удаляем все связанные записи из KeywordLink и MaterialView
        await session.execute(delete(KeywordLink).where(KeywordLink.material_id == material.id))
        await session.execute(delete(MaterialView).where(MaterialView.material_id == material.id))
        # Удаляем сам материал
        await session.delete(material)
        await session.commit()
    await callback.message.edit_text(f"Ключевое слово '{keyword}' и вся связанная с ним информация удалены.")
    await callback.answer()

@stats_router.callback_query(lambda c: c.data and c.data.startswith("cancel_delete_keyword_"))
async def cancel_delete_keyword(callback: types.CallbackQuery, bot: Bot):
    keyword = callback.data[len("cancel_delete_keyword_"):]
    await callback.message.edit_text(f"Удаление ключевого слова '{keyword}' отменено.")
    await callback.answer()


@stats_router.message(Command("user_info"))
async def cmd_user_info(message: types.Message):
    """
    Получить информацию по пользователю (по ID, username или имени).
    """
    if message.chat.id not in config.ADMIN_IDS:
        return
    query = message.text.split(" ", 1)[-1].strip()
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
        if user_info.get("created_at"):
            reply_text += f"Дата регистрации: <b>{user_info['created_at'].strftime('%d.%m.%Y %H:%M')}</b>\n"
        reply_text += (
            f"Имя: <b><a href='tg://user?id={user_info['tg_id']}'>{user_info['first_name']}</a></b>\n"
            f"Статус: <b>{user_info['status']}</b>\n"
            f"Просмотренные материалы:\n"
        )
        for material in info["viewed_materials"]:
            reply_text += (
                f"- Ключевое слово: <b>{material['keyword']}</b>\n"
                f"- Дата просмотра: <b>{material['viewed_at'].strftime('%d.%m.%Y %H:%M')}</b>\n"
            )
        await message.answer(reply_text, parse_mode="HTML")


@stats_router.message(Command("info"))
async def cmd_info(message: types.Message):
    """
    Отображает список всех доступных команд и их описание.
    """
    if message.chat.id not in config.ADMIN_IDS:
        return
    info_text = (
        "🤖 *Доступные команды:*\n\n"
        "📢 */broadcast* — управление рассылками (создание, редактирование, удаление)\n"
        "🔗 */keyword <ключевое слово>* – генерация ссылки по ключевому слову\n"
        "📊 */stats* — статистика пользователей и активности\n"
        "📂 */export_stats* — экспорт статистики пользователей в Excel\n"
        "🔑 */keyword_info <ключевое слово>* — информация по ключевому слову\n"
        "👤 */user_info <ID | @username | имя>* — информация о пользователе\n"
        "ℹ️ */info* — показать список доступных команд\n\n"
        "⚡ Используйте команды для управления ботом!"
    )
    await message.answer(info_text, parse_mode="Markdown")
