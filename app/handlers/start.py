# start.py

import json
import logging
from datetime import datetime
from aiogram import Router, types, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaDocument, InputMediaVideo, MessageEntity
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import config
from app.db.db import AsyncSessionLocal
from app.db.models import User, KeywordLink, Material, MaterialView
from app.utils.cryptography import decrypt_wp_id
from app.utils.helpers import get_or_create_user, bot

start_router = Router()


@start_router.message(CommandStart())
async def cmd_start(message: types.Message, bot: Bot, state: FSMContext):
    """
    Обработчик /start: проверяет параметры auth_ и keyword_.
    """
    await bot.send_chat_action(message.chat.id, "typing")
    params = message.text.split(maxsplit=1)
    await state.clear()

    if len(params) > 1:
        start_param = params[1]

        # Обработка параметра auth_
        if start_param.startswith("auth_"):
            encrypted_wp_id = start_param.replace("auth_", "", 1)
            try:
                decrypted_wp_id = decrypt_wp_id(encrypted_wp_id)
            except Exception as e:
                logging.error(f"Ошибка расшифровки wp_id: {e}")
                return

            async with AsyncSessionLocal() as session:
                user = await get_or_create_user(session, message.from_user, decrypted_wp_id)
                await session.commit()

        # Обработка параметра keyword_
        if start_param.startswith("keyword_"):
            link_str = start_param.replace("keyword_", "", 1)

            async with AsyncSessionLocal() as session:
                stmt = (
                    select(KeywordLink)
                    .join(KeywordLink.material)
                    .where(Material.keyword == link_str)
                    .options(joinedload(KeywordLink.material))
                )
                link_obj = await session.scalar(stmt)
                if not link_obj:
                    await message.answer("Ссылка не найдена или недействительна.")
                    return

                now = datetime.utcnow()
                if (link_obj.expiration_date and now > link_obj.expiration_date) or \
                   (link_obj.max_clicks is not None and link_obj.click_count >= link_obj.max_clicks):
                    await message.answer("Срок действия ссылки истёк или превышено число кликов.")
                    return

                update_stmt = (
                    KeywordLink.__table__.update()
                    .where(KeywordLink.id == link_obj.id)
                    .values(click_count=KeywordLink.click_count + 1)
                )
                await session.execute(update_stmt)

                material = link_obj.material
                if not material or not material.chat_id or not material.message_id:
                    await message.answer("Материал не найден или некорректен.")
                    return

                user = await get_or_create_user(session, message.from_user)
                material_view = MaterialView(
                    user_id=user.id,
                    material_id=material.id,
                    viewed_at=datetime.utcnow()
                )
                session.add(material_view)
                await session.commit()

                if json.loads(material.file_ids):
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
                                caption=material.caption if i == 0 and material.caption else None,
                                parse_mode=None,
                                caption_entities=entities if i == 0 and material.caption else None
                            )
                        elif item["type"] == "document":
                            media_obj = InputMediaDocument(
                                media=item["file_id"],
                                caption=material.caption if i == 0 and material.caption else None,
                                parse_mode=None,
                                caption_entities=entities if i == 0 and material.caption else None
                            )
                        elif item["type"] == "video":
                            media_obj = InputMediaVideo(
                                media=item["file_id"],
                                caption=material.caption if i == 0 and material.caption else None,
                                parse_mode=None,
                                caption_entities=entities if i == 0 and material.caption else None
                            )

                        input_media.append(media_obj)

                    await bot.send_media_group(
                        chat_id=message.chat.id,
                        media=input_media
                    )

                else:
                    # Если материал без медиа‑группы, отправляем одиночное сообщение с учётом caption_entities
                    entities = (
                        [MessageEntity(**entity) for entity in json.loads(material.caption_entities)]
                        if material.caption_entities else None
                    )

                    logging.info(entities)
                    await bot.send_message(
                        chat_id=message.chat.id,
                        text=material.caption,
                        parse_mode=None,
                        entities=entities
                    )
                return

    await bot.send_photo(
        chat_id=message.chat.id,
        photo=FSInputFile("app/images/start.jpg"),
        caption=(
            "Привет! Рады видеть вас в нашем чат-боте.\n\n"
            "Здесь мы рассказываем об обновлениях, рекомендациях и материалах, "
            "а также даем приятные бонусы от партнеров.\n\n"
            "Вы можете задавать вопросы по техническим проблемам, "
            "делиться замечаниями и идеями."
        )
    )


@start_router.message(Command("site"))
async def cmd_site(message: types.Message):
    await message.answer(
        "<b>Наш сайт с сокращенными клиническими рекомендациями</b>\n\n"
        "Друзья, в этом посте вы узнаете все про наш сайт с сокращенными клиническими рекомендациями Reclin.ru\n\n"
        "Как вы уже поняли, на сайте представлены сокращенные клинические рекомендации, утвержденные МЗ РФ. "
        "Однако, мы стремимся добавлять и другие полезные материалы. Всю информацию мы берем с официального "
        "сайта Рубрикатор клинических рекомендаций - https://cr.minzdrav.gov.ru/schema/3_1. "
        "Занимаются сокращением клинических рекомендаций команда врачей, каждый по своей специальности👩‍⚕️👨‍⚕️\n\n"
        "<b>Разберем основные фишки нашего сайта:</b>\n\n"
        "✅ Вся информация четко структурирована, что позволяет быстро ориентироваться в клинической рекомендации\n\n"
        "✅ Всплывающее окно с краткими пояснениями - информация, которая дополняет основной текст\n\n"
        "✅ Все клинические рекомендации дополнены картинками, схемами и алгоритмами\n\n"
        "✅ Препараты, которые есть в клинических рекомендациях, представлены в виде таблиц с указанием дозировок, "
        "торговых названий и способов применения\n\n"
        "Кроме того, вы найдете массу других полезных и удобных вещей на нашем сайте. Переходите скорее - Reclin.ru"
    )


@start_router.message(Command("contacts"))
async def cmd_contacts(message: types.Message):
    await message.answer(
        "Контакты:\n\n"
        "📧 Email - reclin2022@gmail.com\n"
        "🔗 Группа ВК - https://vk.com/reclin\n"
        "📢 Telegram - https://t.me/reclinlive"
    )


@start_router.message(Command("tech"))
async def cmd_tech(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Перейти в поддержку", url="http://t.me/reclin2022")]
        ]
    )
    await message.answer("Опишите вашу проблему и мы обязательно во всем разберемся", reply_markup=keyboard)


class UserState(StatesGroup):
    waiting_for_recommendation = State()
    waiting_for_idea = State()


@start_router.message(Command("recommendations"))
async def cmd_recommendations(message: types.Message, state: FSMContext):
    await message.answer("Напишите <b>одним сообщением</b>, какую клиническую рекомендацию вы хотите видеть на сайте. Мы обязательно поработаем над этим")
    await state.set_state(UserState.waiting_for_recommendation)


@start_router.message(UserState.waiting_for_recommendation)
async def receive_recommendation(message: types.Message, bot: Bot, state: FSMContext):
    if message.from_user.username is not None:
        await bot.send_message(config.ADMIN_IDS[0],
            f"Пользователь <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a> (@{message.from_user.username}) отправил рекомендацию:\n\n{message.text}"
        )
    else:
        await bot.send_message(config.ADMIN_IDS[0],
            f"Пользователь <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a> отправил рекомендацию:\n\n{message.text}"
        )
    await message.answer("Спасибо за Ваше обращение!")
    await state.clear()


@start_router.message(Command("ideas"))
async def cmd_ideas(message: types.Message, state: FSMContext):
    await message.answer("Поделитесь своими идеями по улучшению сайта. Если вы нашли ошибку на сайте, то укажите здесь о ней <b>одним сообщением</b>.")
    await state.set_state(UserState.waiting_for_idea)


@start_router.message(UserState.waiting_for_idea)
async def receive_idea(message: types.Message, bot: Bot, state: FSMContext):
    for admin_id in config.ADMIN_IDS:
        if message.from_user.username is not None:
            await bot.send_message(admin_id,
                f"Пользователь <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a> (@{message.from_user.username}) отправил сообщение:\n\n{message.text}"
            )
        else:
            await bot.send_message(admin_id,
                f"Пользователь <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a> отправил сообщение:\n\n{message.text}"
            )
    await message.answer("Спасибо за Ваше обращение!")
    await state.clear()
