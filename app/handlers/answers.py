from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

answer_router = Router()

# --- Состояния ---
class AnswerState(StatesGroup):
    waiting_for_answer = State()

# --- Кнопка "Отменить" ---
def cancel_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить", callback_data="cancel_reply")]
    ])

# --- Обработка нажатия на кнопку "Ответить" ---
@answer_router.callback_query(F.data.startswith("reply:"))
async def on_reply_click(callback: types.CallbackQuery, state: FSMContext):
    _, user_id, message_id = callback.data.split(":")
    await state.set_state(AnswerState.waiting_for_answer)
    await state.update_data(target_user=int(user_id))
    await callback.message.answer("Напишите ответ на сообщение или прикрепите файл 👇", reply_markup=cancel_button())
    await callback.answer()

# --- Обработка любого типа ответа (сообщение копируется) ---
@answer_router.message(AnswerState.waiting_for_answer)
async def process_answer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("target_user")

    try:
        await message.copy_to(chat_id=user_id)
        await message.answer("Ответ отправлен ✅")
    except Exception as e:
        await message.answer(f"Не удалось отправить сообщение: {e}")

    await state.clear()

# --- Отмена ответа ---
@answer_router.callback_query(F.data == "cancel_reply")
async def cancel_reply(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()
