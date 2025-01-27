import logging
from aiogram import Router, types, F
from aiogram.filters import CommandStart
from app.db.db import AsyncSessionLocal
from app.utils.helpers import get_or_create_user

start_router = Router()

@start_router.message(CommandStart())
async def cmd_start(message: types.Message):
    """
    Обработчик команды /start
    """
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user)
        logging.info(f"User {message.from_user.id} started the bot.")
        await message.answer(
            f"Привет, {user.first_name or 'друг'}!\n"
            f"Твой статус: {user.status}"
        )
