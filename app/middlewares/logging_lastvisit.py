import datetime
import logging

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Update
from sqlalchemy import update

from app.db.db import AsyncSessionLocal
from app.db.models import User

class LoggingAndLastVisitMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):

        # Определяем идентификатор пользователя из сообщения или callback
        user_id = None
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id

        # Если идентификатор найден — обновляем last_interaction в базе
        if user_id:
            # Приводим user_id к строке, если в модели поле tg_id определено как строковый тип
            user_id_str = str(user_id)
            async with AsyncSessionLocal() as session:
                stmt = (
                    update(User)
                    .where(User.tg_id == user_id_str)
                    .values(last_interaction=datetime.datetime.utcnow())
                )
                await session.execute(stmt)
                await session.commit()

        # Передаём управление дальше обработчику
        return await handler(event, data)
