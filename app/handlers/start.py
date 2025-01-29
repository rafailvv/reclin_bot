# start.py

import logging
from datetime import datetime
from aiogram import Router, types, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.db.db import AsyncSessionLocal
from app.db.models import User, KeywordLink, Material, MaterialView
from app.utils.helpers import get_or_create_user

start_router = Router()

@start_router.message(CommandStart())
async def cmd_start(message: types.Message, bot: Bot,  state: FSMContext):
    """
    /start handler: проверяем наличие параметра ?start=keyword_<unique_link>
    """
    params = message.text.split(maxsplit=1)
    await state.clear()
    if len(params) > 1:
        start_param = params[1]
        if start_param.startswith("keyword_"):
            link_str = start_param.replace("keyword_", "", 1)

            async with AsyncSessionLocal() as session:
                # Ищем KeywordLink
                stmt = (
                    select(KeywordLink)
                    .join(KeywordLink.material)  # Соединяем таблицы
                    .where(Material.keyword == link_str)  # Фильтруем по keyword в таблице Material
                    .options(joinedload(KeywordLink.material))  # Загружаем связанный объект Material
                )
                link_obj = await session.scalar(stmt)
                if not link_obj:
                    await message.answer("Ссылка не найдена или недействительна.")
                    return

                # Проверяем срок и клики
                now = datetime.utcnow()
                if (link_obj.expiration_date and now > link_obj.expiration_date) \
                   or (link_obj.max_clicks is not None and link_obj.click_count >= link_obj.max_clicks):
                    await message.answer("Срок действия ссылки истёк или превышено число кликов.")
                    return

                # Увеличиваем счётчик кликов через SQL-запрос
                update_stmt = (
                    KeywordLink.__table__.update()
                    .where(KeywordLink.id == link_obj.id)
                    .values(click_count=KeywordLink.click_count + 1)
                )
                await session.execute(update_stmt)

                # Получаем Material
                material = link_obj.material
                if not material or not material.chat_id or not material.message_id:
                    await message.answer("Материал не найден или некорректен.")
                    return

                # Получаем или создаём пользователя
                user = await get_or_create_user(session, message.from_user)

                # Сохраняем запись в MaterialView
                material_view = MaterialView(
                    user_id=user.id,
                    material_id=material.id,
                    viewed_at=datetime.utcnow()
                )
                session.add(material_view)

                # Коммитим все изменения (увеличение счётчика и запись MaterialView)
                await session.commit()

                # Делаем пересылку
                try:
                    await bot.copy_message(
                        chat_id=message.chat.id,
                        from_chat_id=material.chat_id,   # откуда пересылаем
                        message_id=material.message_id   # какое сообщение пересылаем
                    )
                except Exception as e:
                    logging.error(f"Не удалось переслать сообщение: {e}")
                    await message.answer("Ошибка, обратитесь к администратору")
                return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user)
        logging.info(f"User {message.from_user.id} started the bot.")
        await message.answer(
            f"Привет, {user.first_name or 'друг'}!\n"
            f"Твой статус: {user.status}"
        )
