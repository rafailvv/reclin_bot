import logging
from aiogram import Router, types
from aiogram.filters import Command
from app.db import AsyncSessionLocal
from app.db.models import User

broadcast_router = Router()

@broadcast_router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    """
    /broadcast <category> <текст>
    """
    parts = message.text.strip().split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /broadcast <category> <text>")
        return
    category = parts[1]
    text_to_send = parts[2]

    async with AsyncSessionLocal() as session:
        users = await session.scalars(
            User.select().where(User.category == category)
        )
        user_list = users.all()

        count = 0
        for u in user_list:
            try:
                await message.bot.send_message(u.tg_id, text_to_send)
                count += 1
            except Exception as e:
                logging.warning(f"Не удалось отправить пользователю {u.tg_id}: {e}")

        await message.answer(f"Отправлено {count} пользователям в категории '{category}'.")
