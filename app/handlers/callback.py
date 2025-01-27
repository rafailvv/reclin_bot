from aiogram import Router, types
from aiogram.fsm.context import FSMContext

callback_router = Router()

@callback_router.callback_query(lambda callback : callback.data.startswith('cancel') )
async def cancel_keyword_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие успешно отменено")
    await callback.answer()
