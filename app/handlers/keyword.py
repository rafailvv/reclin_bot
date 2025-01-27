from aiogram import Router, types
from aiogram.filters import Command
from app.db.db import AsyncSessionLocal
from app.db.models import Material
from app.utils.helpers import generate_link_for_material

keyword_router = Router()

@keyword_router.message(Command("keyword"))
async def cmd_keyword(message: types.Message):
    """
    /keyword <слово>
    Находит материал, генерирует и выдаёт ссылку на материал (упрощённо).
    """
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Использование: /keyword <слово>")
        return
    keyword = parts[1]

    async with AsyncSessionLocal() as session:
        material = await session.scalar(
            Material.select().where(Material.keyword == keyword)
        )
        if not material:
            await message.answer(f"Материал для ключевого слова '{keyword}' не найден.")
            return

        link_obj = await generate_link_for_material(session, material)
        link_text = f"https://example.com/{link_obj.link}"

        await message.answer(
            f"Ссылка для <b>{keyword}</b>:\n{link_text}\n\n"
            f"Действительна до {link_obj.expiration_date}, "
            f"максимум переходов: {link_obj.max_clicks}."
        )
