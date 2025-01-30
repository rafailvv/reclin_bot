# keyword.py

import re
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from sqlalchemy import select
from sqlalchemy.orm import NotExtension

from app.config import config
from app.db.db import AsyncSessionLocal
from app.db.models import Material
from app.utils.helpers import generate_link_for_material

keyword_router = Router()

# Машина состояний
class KeywordStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_datetime = State()
    waiting_for_maxclicks = State()


@keyword_router.message(Command("keyword"))
async def cmd_keyword(message: types.Message, state: FSMContext):
    """
    Шаг 1: /keyword <слово>
    Проверяем, занято ли слово, либо готовим к созданию/обновлению
    и просим у пользователя переслать сообщение.
    """
    if message.chat.id not in config.ADMIN_IDS:
        return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /keyword <слово>")
        return

    keyword = parts[1]

    async with AsyncSessionLocal() as session:
        stmt = select(Material).where(Material.keyword == keyword)
        existing_material = await session.scalar(stmt)

    # Кнопка «Отмена»
    cancel_button = InlineKeyboardButton(text="Отмена", callback_data="cancel ")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[cancel_button]])

    if existing_material:
        text_for_user = (
            f"Внимание! Ключевое слово '{keyword}' уже занято.\n"
            f"Отправьте новое сообщение (перешлите или просто отправьте), "
            f"чтобы обновить материал для этого ключевого слова.\n"
            f"Или нажмите «Отмена»."
        )
    else:
        text_for_user = (
            f"Ключевое слово '{keyword}' свободно.\n"
            f"Перешлите сообщение (или просто отправьте), "
            f"которое хотите сохранить.\n"
            f"Или нажмите «Отмена»."
        )

    await message.answer(text_for_user, reply_markup=keyboard)
    # Сохраняем keyword в FSM
    await state.update_data(keyword=keyword)
    # Переходим в следующее состояние
    await state.set_state(KeywordStates.waiting_for_message)


@keyword_router.message(KeywordStates.waiting_for_message)
async def keyword_save_message(message: types.Message, state: FSMContext):
    """
    Шаг 2: Получаем от пользователя сообщение,
    сохраняем его chat_id и message_id во временном состоянии.
    """
    # Если пользователь пересылает сообщение, у forwarded message будет:
    #   message.forward_from_chat / message.forward_from_message_id
    # Но если пересылка из приватного чата, бот может не иметь прав на forward.
    # Проще всего хранить текущий chat_id и message_id,
    # если мы хотим потом делать forward именно из этого же чата.
    # Однако в реальности нужны права на пересылку. Ниже - упрощённый пример.

    # Будем считать, что сообщение мы будем пересылать *из* ЛИЧНОГО чата с пользователем,
    # тогда chat_id = message.chat.id, message_id = message.message_id
    # (т.е. фактически копия самого сообщения в личном чате бота с пользователем).
    # Если нужно обрабатывать forwarding из групп/каналов - логика будет сложнее.

    data = await state.get_data()

    # Сохраним в FSM
    await state.update_data(
        chat_id=message.chat.id,
        source_message_id=message.message_id
    )

    # Теперь спрашиваем у пользователя дату/время
    await message.answer("Введите количество дней числом либо '-' если не нужно устанавливать срок:")
    await state.set_state(KeywordStates.waiting_for_datetime)


@keyword_router.message(KeywordStates.waiting_for_datetime)
async def keyword_set_datetime(message: types.Message, state: FSMContext):
    """
    Шаг 3: Пользователь вводит дату/время (или '-').
    Если дата/время указаны, позже высчитаем разницу для expire_in_days.
    """
    user_text = message.text.strip()

    if user_text == "-":
        # Отсутствует дата => используем по умолчанию 7 дней
        await state.update_data(expire_in_days=None)
    else:
        # Пытаемся распарсить дату и время
        # Формат: YYYY-MM-DD HH:MM
        try:
            days = int(user_text)
            if days <= 0:
                await message.answer("Ошибка: число дней должно быть > 0 или '-'.")
                return
            await state.update_data(expire_in_days=days)
        except ValueError:
            await message.answer("Ошибка: введите число или '-'. Попробуйте ещё раз.")
            return

    # Теперь запрашиваем максимальное количество кликов
    await message.answer("Введите максимальное количество кликов, либо '-' если без ограничения:")
    await state.set_state(KeywordStates.waiting_for_maxclicks)


@keyword_router.message(KeywordStates.waiting_for_maxclicks)
async def keyword_set_maxclicks(message: types.Message, state: FSMContext):
    """
    Шаг 4: Пользователь вводит max_clicks или '-'.
    После этого создаём/обновляем Material и генерируем ссылку.
    """
    user_text = message.text.strip()
    if user_text == "-":
        max_clicks = None
    else:
        if not user_text.isdigit():
            await message.answer("Ошибка: введите число или '-'. Попробуйте ещё раз.")
            return
        max_clicks = int(user_text)
        if max_clicks <= 0:
            await message.answer("Ошибка: число кликов должно быть > 0 или '-'.")
            return

    # Достаём все данные из FSM
    data = await state.get_data()
    keyword = data["keyword"]
    expire_in_days = data.get("expire_in_days")
    chat_id = data["chat_id"]
    source_message_id = data["source_message_id"]

    # Теперь нужно создать/обновить Material
    async with AsyncSessionLocal() as session:
        stmt = select(Material).where(Material.keyword == keyword)
        existing_material = await session.scalar(stmt)

        if existing_material:
            # Обновляем chat_id / message_id
            existing_material.chat_id = str(chat_id)
            existing_material.message_id = source_message_id
            material = existing_material
        else:
            material = Material(
                keyword=keyword,
                chat_id=str(chat_id),
                message_id=source_message_id
            )
            session.add(material)

        await session.commit()
        await session.refresh(material)

        # Генерируем ссылку
        link_obj = await generate_link_for_material(
            session,
            material,
            keyword,
            expire_in_days=expire_in_days,
            max_clicks=max_clicks
        )


    # Отправляем пользователю финальный ответ
    await message.answer(
        f"Материал для ключевого слова <b>{keyword}</b> сохранён!\n"
        f"Ссылка: {link_obj.link}\n\n"
        f"Действительна <b>{str(expire_in_days) + ' дн.,' if expire_in_days is not None else 'бессрочно'}</b>"
        f"максимум переходов: <b>{max_clicks if max_clicks is not None else 'без ограничений'}</b>."
    )

    # Сбрасываем состояние
    await state.clear()
