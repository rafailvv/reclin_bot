# start.py

import logging
from datetime import datetime
from aiogram import Router, types, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import FSInputFile
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import config
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

    await bot.send_photo(
        chat_id=message.chat.id,
        photo=FSInputFile("app/images/start.jpg"),
        caption=(
            "Привет! Рады приветствовать вас в нашем чат-боте.\n\n"
            "Здесь мы будем рассказывать о наших обновлениях, новых рекомендациях и материалах сайта, "
            "а также дарить вам приятные бонусы от наших партнеров.\n\n"
            "Через специальное меню вы можете задавать вопросы по техническим проблемам на сайте, "
            "писать свои замечания и идеи."
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
        await bot.send_message(config.ADMIN_IDS[0], f"Пользователь <a href='tg://user?id={message.from_user.url}'>{message.from_user.full_name}</a> (@{message.from_user.username}) отправил рекомендацию:\n\n{message.text}")
    else:
        await bot.send_message(config.ADMIN_IDS[0], f"Пользователь <a href='tg://user?id={message.from_user.url}'>{message.from_user.full_name}</a> отправил рекомендацию:\n\n{message.text}")

    await message.answer("Спасибо за Ваше обращение!")
    await state.clear()

@start_router.message(Command("ideas"))
async def cmd_ideas(message: types.Message, state: FSMContext):
    await message.answer("Поделитесь своими идеями по улучшению сайта. Если вы нашли ошибку на сайте, то укажите здесь о ней <b>одним сообщением</b>.")
    await state.set_state(UserState.waiting_for_idea)

@start_router.message(UserState.waiting_for_idea)
async def receive_idea(message: types.Message, bot: Bot, state: FSMContext):
    if message.from_user.username is not None:
        await bot.send_message(config.ADMIN_IDS[0], f"Пользователь <a href='tg://user?id={message.from_user.url}'>{message.from_user.full_name}</a> (@{message.from_user.username}) отправил идею/ошибку:\n\n{message.text}")
    else:
        await bot.send_message(config.ADMIN_IDS[0], f"Пользователь <a href='tg://user?id={message.from_user.url}'>{message.from_user.full_name}</a> отправил идею/ошибку:\n\n{message.text}")
    await message.answer("Спасибо за Ваше обращение!")
    await state.clear()