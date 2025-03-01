import logging
import re
import json
import asyncio
from datetime import datetime
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from sqlalchemy import select

from app.config import config
from app.db.db import AsyncSessionLocal
from app.db.models import Material, KeywordLink
from app.utils.helpers import generate_link_for_material, bot

keyword_router = Router()


# Определяем состояния диалога
class KeywordStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_datetime = State()
    waiting_for_maxclicks = State()


async def process_media_group(media_group_id: str, state: FSMContext, trigger_message: types.Message):
    """
    Ожидает 1 секунду для накопления всех сообщений из media‑группы,
    агрегирует вложения и сохраняет данные, включая caption и caption_entities.
    """
    await bot.send_chat_action(trigger_message.chat.id, "typing")
    await asyncio.sleep(1)  # Ждём, чтобы собрать все сообщения группы
    data = await state.get_data()
    media_group = data.get("media_group", [])
    if media_group:
        file_list = []
        # Извлекаем caption из первого сообщения (если он есть)
        caption = ""
        caption_entities = None
        for mg in media_group:
            if mg.caption or mg.text:
                caption = mg.caption or mg.text
                if mg.caption_entities:
                    caption_entities = [entity.dict() for entity in mg.caption_entities]
                break
        for msg in media_group:
            if msg.photo:
                file_list.append({"type": "photo", "file_id": msg.photo[-1].file_id})
            elif msg.document:
                file_list.append({"type": "document", "file_id": msg.document.file_id})
            elif msg.video:
                file_list.append({"type": "video", "file_id": msg.video.file_id})
        chat_id = media_group[0].chat.id
        message_ids = [msg.message_id for msg in media_group]
        await state.update_data(
            chat_id=chat_id,
            source_message_ids=message_ids,
            file_ids=json.dumps(file_list),
            caption=caption,
            caption_entities=json.dumps(caption_entities) if caption_entities else None
        )
        # Очищаем временные данные по группе
        await state.update_data(media_group=[])
        await trigger_message.answer("Введите количество дней числом либо '-' если не нужно устанавливать срок:")
        await state.set_state(KeywordStates.waiting_for_datetime)


@keyword_router.message(Command("keyword"))
async def cmd_keyword(message: types.Message, state: FSMContext):
    """
    Шаг 1: /keyword <слово>.
    Проверяем, свободно ли ключевое слово, и просим переслать сообщение.
    """
    await bot.send_chat_action(message.chat.id, "typing")
    if message.chat.id not in config.ADMIN_IDS:
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /keyword &lt;слово>")
        return

    keyword = parts[1]

    # Проверка: слово должно состоять только из английских букв и цифр
    if not re.fullmatch(r"[A-Za-z0-9]+", keyword):
        await message.answer("Ошибка: ключевое слово должно содержать только английские буквы и цифры.")
        return

    async with AsyncSessionLocal() as session:
        stmt = select(Material).where(Material.keyword == keyword)
        existing_material = await session.scalar(stmt)

    cancel_button = InlineKeyboardButton(text="Отмена", callback_data="cancel")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[cancel_button]])

    if existing_material:
        text_for_user = (
            f"Внимание! Ключевое слово '{keyword}' <b>уже занято</b>.\n\n"
            "Отправьте новое сообщение (перешлите или просто отправьте), "
            "чтобы обновить материал для этого ключевого слова.\n"
            "Или нажмите «Отмена»."
        )
    else:
        text_for_user = (
            f"Ключевое слово '{keyword}' <b>свободно</b>.\n"
            "Перешлите сообщение (или просто отправьте), "
            "которое хотите сохранить.\n"
            "Или нажмите «Отмена»."
        )

    await message.answer(text_for_user, reply_markup=keyboard)
    await state.update_data(keyword=keyword)
    await state.set_state(KeywordStates.waiting_for_message)


@keyword_router.message(KeywordStates.waiting_for_message)
async def keyword_save_message(message: types.Message, state: FSMContext):
    """
    Шаг 2: Получаем сообщение от пользователя.
    Обрабатываем как одиночное сообщение, так и сообщение из media‑группы.
    """
    await bot.send_chat_action(message.chat.id, "typing")
    if message.media_group_id:
        data = await state.get_data()
        media_group = data.get("media_group", [])
        media_group.append(message)
        await state.update_data(media_group=media_group)
        if len(media_group) == 1:
            # Запускаем задачу для обработки всей группы
            asyncio.create_task(process_media_group(message.media_group_id, state, message))
        return
    else:
        file_list = []
        caption = message.caption or message.text or ""
        logging.info("no media " + caption)
        if message.caption_entities:
            caption_entities = [entity.dict() for entity in message.caption_entities]
        elif message.entities:
            caption_entities = [entity.dict() for entity in message.entities]
        else:
            caption_entities = None
        if message.photo:
            file_list.append({"type": "photo", "file_id": message.photo[-1].file_id})
        elif message.document:
            file_list.append({"type": "document", "file_id": message.document.file_id})
        elif message.video:
            file_list.append({"type": "video", "file_id": message.video.file_id})
        await state.update_data(
            chat_id=message.chat.id,
            source_message_ids=[message.message_id],
            file_ids=json.dumps(file_list),
            caption=caption,
            caption_entities=json.dumps(caption_entities) if caption_entities else None
        )
        await message.answer("Введите количество дней числом либо '-' если не нужно устанавливать срок:")
        await state.set_state(KeywordStates.waiting_for_datetime)


@keyword_router.message(KeywordStates.waiting_for_datetime)
async def keyword_set_datetime(message: types.Message, state: FSMContext):
    """
    Шаг 3: Пользователь вводит число дней (или '-') для определения срока действия.
    """
    await bot.send_chat_action(message.chat.id, "typing")
    user_text = message.text.strip()
    if user_text == "-":
        await state.update_data(expire_in_days=None)
    else:
        try:
            days = int(user_text)
            if days <= 0:
                await message.answer("Ошибка: число дней должно быть > 0 или '-'.")
                return
            await state.update_data(expire_in_days=days)
        except ValueError:
            await message.answer("Ошибка: введите число или '-'. Попробуйте ещё раз.")
            return
    await message.answer("Введите максимальное количество кликов, либо '-' если без ограничения:")
    await state.set_state(KeywordStates.waiting_for_maxclicks)


@keyword_router.message(KeywordStates.waiting_for_maxclicks)
async def keyword_set_maxclicks(message: types.Message, state: FSMContext):
    """
    Шаг 4: Пользователь вводит максимальное количество кликов (или '-'),
    после чего материал сохраняется в базе. Если материал с таким URL уже существует,
    его данные будут обновлены.
    """
    await bot.send_chat_action(message.chat.id, "typing")
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

    data = await state.get_data()
    keyword = data["keyword"]
    expire_in_days = data.get("expire_in_days")
    chat_id = data["chat_id"]
    source_message_ids = data["source_message_ids"]
    file_ids = data.get("file_ids")
    caption = data.get("caption", "")
    caption_entities = data.get("caption_entities")

    logging.info("Текст: " + caption)

    async with AsyncSessionLocal() as session:
        stmt = select(Material).where(Material.keyword == keyword)
        existing_material = await session.scalar(stmt)
        if existing_material:
            existing_material.chat_id = str(chat_id)
            existing_material.message_id = ",".join(str(mid) for mid in source_message_ids)
            existing_material.file_ids = file_ids
            existing_material.caption = caption
            existing_material.caption_entities = caption_entities
            material = existing_material
        else:
            material = Material(
                keyword=keyword,
                chat_id=str(chat_id),
                message_id=",".join(str(mid) for mid in source_message_ids),
                file_ids=file_ids,
                caption=caption,
                caption_entities=caption_entities
            )
            session.add(material)
        await session.commit()
        await session.refresh(material)
        link_obj = await generate_link_for_material(
            session,
            material,
            keyword,
            expire_in_days=expire_in_days,
            max_clicks=max_clicks
        )
    await message.answer(
        f"Материал для ключевого слова <b>{keyword}</b> сохранён!\n"
        f"Ссылка: {link_obj.link}\n\n"
        f"Действительна <b>{str(expire_in_days) + ' дн.,' if expire_in_days is not None else 'бессрочно'}</b> "
        f"максимум переходов: <b>{max_clicks if max_clicks is not None else 'без ограничений'}</b>."
    )
    await state.clear()
