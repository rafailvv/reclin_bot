import logging
from datetime import datetime, timedelta, time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

from app.config import config
from app.db.db import AsyncSessionLocal
from app.db.models import User, Mailing, MailingStatus, MailingSchedule, Material, MaterialView
from app.utils.helpers import get_day_of_week_names

broadcast_router = Router()

# -----------------------------
# Шаги FSM
# -----------------------------
class BroadcastStates(StatesGroup):
    CHOOSING_NEW_OR_EXISTING = State()

    # Новая рассылка
    CHOOSING_STATUSES = State()
    WAITING_FOR_KEYWORD = State()  # новое состояние для ввода ключевого слова
    ENTERING_TITLE = State()
    WAITING_FOR_BROADCAST_MESSAGE = State()
    CHOOSING_SCHEDULE_TYPE = State()
    ENTERING_DAILY_TIME = State()
    ENTERING_WEEKLY_DAYS = State()
    ENTERING_WEEKLY_TIME = State()
    ENTERING_MONTHLY_DAYS = State()
    ENTERING_MONTHLY_TIME = State()
    ENTERING_ONCE_TIME = State()

    # Существующая рассылка
    CHOOSING_EXISTING_MAILING = State()
    EXISTING_MAILING_MANAGE = State()
    EDITING_EXISTING_MESSAGE = State()
    EDITING_EXISTING_SCHEDULE_TYPE = State()
    # (далее те же состояния для правок расписания)

# -----------------------------
#  Команда /broadcast
# -----------------------------
@broadcast_router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    """
    /broadcast - предлагает выбор (Новая / Существующая)
    """
    if message.chat.id not in config.ADMIN_IDS:
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Новая рассылка", callback_data="new_mailing")],
        [InlineKeyboardButton(text="Существующая рассылка", callback_data="existing_mailing")]
    ])
    sent = await message.answer("Выберите действие:", reply_markup=keyboard)
    # Сохраним у себя id этого «основного сообщения», чтобы редактировать
    await state.update_data(main_message_id=sent.message_id)
    await state.set_state(BroadcastStates.CHOOSING_NEW_OR_EXISTING)

# -----------------------------
#  Обработка «Новая рассылка»
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.CHOOSING_NEW_OR_EXISTING, F.data == "new_mailing")
async def process_new_mailing(callback: types.CallbackQuery, state: FSMContext):
    """
    «Новая рассылка» – показываем все статусы пользователей (чекбоксы), включая "админы".
    Также добавляется опция «По ключевому слову».
    """
    await callback.answer()

    async with AsyncSessionLocal() as session:
        result = await session.scalars(select(User.status).distinct().order_by(User.status))
        all_statuses = sorted({s.lower() for s in result.all() if s})
    # Добавляем "админы" как виртуальный статус
    all_statuses.append("админы")

    await state.update_data(
        all_statuses=all_statuses,
        selected_statuses={status: False for status in all_statuses},
        target_type="statuses"  # по умолчанию – по статусам
    )

    await edit_statuses_message(callback, state)
    await state.set_state(BroadcastStates.CHOOSING_STATUSES)

def build_statuses_keyboard(all_statuses, selected_dict):
    """
    Создаём клавиатуру чекбоксов для всех статусов.
    Добавлена дополнительная кнопка "По ключевому слову".
    """
    buttons = []
    for st in all_statuses:
        checked = "✅" if selected_dict.get(st, False) else ""
        btn_text = f"{checked}{st}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"toggle_status_{st}")])
    # Кнопка «Далее»
    buttons.append([InlineKeyboardButton(text="Далее", callback_data="statuses_done")])
    # Новая кнопка «По ключевому слову»
    buttons.append([InlineKeyboardButton(text="По ключевому слову", callback_data="by_keyword")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def edit_statuses_message(callback: types.CallbackQuery, state: FSMContext):
    """
    Редактирует «основное» сообщение, показывая список статусов (чекбоксы).
    """
    data = await state.get_data()
    all_statuses = data["all_statuses"]
    selected = data["selected_statuses"]

    text = (
        "Выберите статусы пользователей для рассылки.\n"
        "Нажимайте для (де)активации. Затем нажмите 'Далее' или выберите 'По ключевому слову'."
    )
    kb = build_statuses_keyboard(all_statuses, selected)
    main_msg_id = data["main_message_id"]
    await callback.message.edit_text(text, reply_markup=kb)

# -----------------------------
#  «Существующая рассылка»
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.CHOOSING_NEW_OR_EXISTING, F.data == "existing_mailing")
async def process_existing_mailing(callback: types.CallbackQuery, state: FSMContext):
    """
    «Существующая рассылка» – показываем список активных рассылок
    """
    await callback.answer()

    async with AsyncSessionLocal() as session:
        mailings = (await session.scalars(
            select(Mailing).where(Mailing.active == 1)
        )).all()

    if not mailings:
        await callback.message.edit_text("Активных рассылок нет.")
        await state.clear()
        return

    kb_rows = []
    for m in mailings:
        kb_rows.append(
            [InlineKeyboardButton(text=m.title, callback_data=f"mailing_{m.id}")]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.edit_text("Выберите рассылку:", reply_markup=kb)
    await state.set_state(BroadcastStates.CHOOSING_EXISTING_MAILING)

# -----------------------------
#  Клик по чекбоксам статусов / кнопке «Далее» / «По ключевому слову»
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.CHOOSING_STATUSES)
async def handle_statuses_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if callback.data.startswith("toggle_status_"):
        # Переключаем чекбокс
        st = callback.data.replace("toggle_status_", "")
        selected = data["selected_statuses"]
        selected[st] = not selected[st]
        await state.update_data(selected_statuses=selected)
        await edit_statuses_message(callback, state)
        await callback.answer()

    elif callback.data == "statuses_done":
        selected = data["selected_statuses"]
        chosen = [st for st, val in selected.items() if val]
        if not chosen:
            await callback.answer("Выберите хотя бы один статус!", show_alert=True)
            return
        await callback.answer()
        await state.set_state(BroadcastStates.ENTERING_TITLE)
        await callback.message.edit_text("Введите название рассылки:")

    elif callback.data == "by_keyword":
        # Выбрана рассылка по ключевому слову
        await state.update_data(target_type="keyword")
        await callback.message.edit_text("Введите ключевое слово:")
        await state.set_state(BroadcastStates.WAITING_FOR_KEYWORD)
        await callback.answer()

    else:
        await callback.answer("Неизвестная команда")

# -----------------------------
#  Обработка ввода ключевого слова (для рассылки по ключевому слову)
# -----------------------------
@broadcast_router.message(BroadcastStates.WAITING_FOR_KEYWORD)
async def process_keyword_input(message: types.Message, state: FSMContext):
    keyword = message.text.strip()
    async with AsyncSessionLocal() as session:
        material = await session.scalar(select(Material).where(Material.keyword == keyword))
    if not material:
        await message.answer("Неверное ключевое слово. Попробуйте ещё раз.")
        return
    await state.update_data(keyword=keyword)
    await message.answer(f"Ключевое слово '{keyword}' <b>принято</b>.\nВведите название рассылки:")
    await state.set_state(BroadcastStates.ENTERING_TITLE)

# -----------------------------
#  Ввод названия рассылки
# -----------------------------
@broadcast_router.message(BroadcastStates.ENTERING_TITLE)
async def enter_mailing_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(mailing_title=title)
    await message.answer("Теперь пришлите (или перешлите) сообщение, которое будет рассылаться.")
    await state.set_state(BroadcastStates.WAITING_FOR_BROADCAST_MESSAGE)

# -----------------------------
#  Сохранение сообщения-образца рассылки
# -----------------------------
@broadcast_router.message(BroadcastStates.WAITING_FOR_BROADCAST_MESSAGE)
async def receive_broadcast_message(message: types.Message, state: FSMContext):
    """
    Сохраняем saved_chat_id и saved_message_id из пересланного/присланного сообщения.
    """
    saved_chat_id = str(message.chat.id)
    saved_message_id = str(message.message_id)

    await state.update_data(
        saved_chat_id=saved_chat_id,
        saved_message_id=saved_message_id
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ежедневно", callback_data="schedule_daily")],
        [InlineKeyboardButton(text="Еженедельно", callback_data="schedule_weekly")],
        [InlineKeyboardButton(text="Ежемесячно", callback_data="schedule_monthly")],
        [InlineKeyboardButton(text="Единоразово", callback_data="schedule_once")],
    ])
    await message.answer(
        "Сообщение для рассылки сохранено.\nВыберите периодичность:",
        reply_markup=kb
    )
    await state.update_data(is_edit=False)
    await state.set_state(BroadcastStates.CHOOSING_SCHEDULE_TYPE)

# -----------------------------
# Выбор типа расписания (новая рассылка)
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.CHOOSING_SCHEDULE_TYPE)
async def choose_schedule_type_new(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    await callback.answer()

    if data == "schedule_daily":
        await callback.message.edit_text("Введите время в формате HH:MM (например 09:00):")
        await state.set_state(BroadcastStates.ENTERING_DAILY_TIME)

    elif data == "schedule_weekly":
        await state.update_data(selected_weekdays=[])
        text = "Выберите дни недели. Нажимайте, чтобы выделить.\nЗатем нажмите 'Далее'."
        await callback.message.edit_text(text, reply_markup=build_weekdays_keyboard([]))
        await state.set_state(BroadcastStates.ENTERING_WEEKLY_DAYS)

    elif data == "schedule_monthly":
        await state.update_data(selected_monthdays=[])
        text = "Выберите даты месяца. Нажимайте, чтобы выделить.\nЗатем 'Далее'."
        await callback.message.edit_text(text, reply_markup=build_monthdays_keyboard([]))
        await state.set_state(BroadcastStates.ENTERING_MONTHLY_DAYS)

    elif data == "schedule_once":
        text = (
            "Единоразовая рассылка.\n\n"
            "Введите дату и время в формате <b>YYYY-MM-DD HH:MM</b>, "
            "чтобы запланировать отправку.\n\n"
            "Или нажмите кнопку «Отправить сейчас» чтобы отправить сразу.\n"
            "Нажмите «Отмена», чтобы выйти."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отправить сейчас", callback_data="send_once_now")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await state.set_state(BroadcastStates.ENTERING_ONCE_TIME)

    else:
        await callback.message.edit_text("Неизвестная команда.")
        await state.clear()

# -----------------------------
#  Обработка единоразовой рассылки (отправка сразу)
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.ENTERING_ONCE_TIME)
async def once_time_choice_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "send_once_now":
        data = await state.get_data()
        is_edit = data.get("is_edit", False)
        if not is_edit:
            await send_once_broadcast(state, callback)
            await state.clear()
        else:
            await send_once_broadcast_existing(state, callback)
            await state.clear()

    elif callback.data == "cancel":
        await callback.message.edit_text("Действие отменено.")
        await state.clear()
    else:
        await callback.answer("Неизвестная команда", show_alert=True)

@broadcast_router.message(BroadcastStates.ENTERING_ONCE_TIME)
async def once_time_entered(message: types.Message, state: FSMContext):
    text = message.text.strip()
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        now = datetime.utcnow()
        if dt <= now:
            await message.answer("Указанное время уже прошло. Введите будущее время или нажмите «Отправить сейчас».")
            return
        data = await state.get_data()
        is_edit = data.get("is_edit", False)

        if not is_edit:
            await create_mailing_in_db(
                state,
                schedule_type="once",
                next_run=dt
            )
            await message.answer(f"Единоразовая рассылка запланирована на {dt} (UTC).")
        else:
            mailing_id = data["existing_mailing_id"]
            await add_schedule_for_existing_mailing(
                mailing_id,
                schedule_type="once",
                next_run=dt
            )
            await message.answer(f"Для существующей рассылки назначен единоразовый запуск на {dt} (UTC).")
        await state.clear()

    except ValueError:
        await message.answer(
            "Неверный формат даты/времени. "
            "Используйте формат <b>YYYY-MM-DD HH:MM</b>, "
            "либо нажмите «Отправить сейчас».",
            parse_mode="HTML"
        )

# -----------------------------
#  Отправка единоразовой рассылки (без записи в БД)
# -----------------------------
async def send_once_broadcast(state: FSMContext, callback_or_message: types.Message | types.CallbackQuery):
    data = await state.get_data()
    if data.get("target_type") == "keyword":
        keyword = data.get("keyword")
        async with AsyncSessionLocal() as session:
            material = await session.scalar(select(Material).where(Material.keyword == keyword))
            if not material:
                if isinstance(callback_or_message, types.CallbackQuery):
                    await callback_or_message.message.edit_text("Неверное ключевое слово, попробуйте ещё раз.")
                else:
                    await callback_or_message.answer("Неверное ключевое слово, попробуйте ещё раз.")
                return
            mviews = await session.scalars(select(MaterialView).where(MaterialView.material_id == material.id))
            mviews_list = mviews.all()
            user_ids = [mv.user_id for mv in mviews_list]
            if user_ids:
                users = await session.scalars(select(User).where(User.id.in_(user_ids)))
                users_list = users.all()
            else:
                users_list = []
    else:
        selected_statuses = data["selected_statuses"]
        chosen_statuses = [st for st, val in selected_statuses.items() if val]
        users_list = []
        async with AsyncSessionLocal() as session:
            if "админы" in chosen_statuses:
                admin_users = await session.scalars(
                    select(User).where(User.tg_id.in_(map(str, config.ADMIN_IDS)))
                )
                users_list.extend(admin_users.all())
            non_admin_statuses = [st.lower() for st in chosen_statuses if st.lower() != "админы"]
            if non_admin_statuses:
                users_by_status = await session.scalars(
                    select(User).where(func.lower(User.status).in_(non_admin_statuses))
                )
                users_list.extend(users_by_status.all())
    bot = callback_or_message.bot if isinstance(callback_or_message, types.CallbackQuery) else callback_or_message.bot
    success_count = 0
    error_count = 0
    for user in users_list:
        if not user.tg_id:
            continue
        try:
            await bot.copy_message(
                chat_id=user.tg_id,
                from_chat_id=data["saved_chat_id"],
                message_id=int(data["saved_message_id"])
            )
            success_count += 1
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение пользователю {user.tg_id}: {e}")
            error_count += 1
    final_text = f"Единоразовая рассылка завершена.\nУспешно: {success_count}, Ошибок: {error_count}"
    if isinstance(callback_or_message, types.CallbackQuery):
        await callback_or_message.message.edit_text(final_text)
    else:
        await callback_or_message.answer(final_text)

# -----------------------------
#  Создание новой рассылки и её расписания
# -----------------------------
async def create_mailing_in_db(
    state: FSMContext,
    schedule_type: str,
    day_of_week: str = None,
    day_of_month: str = None,
    time_of_day: str = None,
    next_run: datetime = None
):
    data = await state.get_data()
    title = data["mailing_title"]
    saved_chat_id = data["saved_chat_id"]
    saved_message_id = data["saved_message_id"]

    async with AsyncSessionLocal() as session:
        new_mailing = Mailing(
            title=title,
            saved_chat_id=saved_chat_id,
            saved_message_id=saved_message_id,
            active=1,
            created_at=datetime.utcnow()
        )
        session.add(new_mailing)
        await session.flush()  # получим ID

        # Если рассылка по ключевому слову – сохраняем статус с префиксом "keyword:"
        if data.get("target_type") == "keyword":
            keyword_val = data.get("keyword")
            ms = MailingStatus(mailing_id=new_mailing.id, user_status=f"keyword:{keyword_val}")
            session.add(ms)
        else:
            statuses = data["selected_statuses"]
            chosen_statuses = [st for st, val in statuses.items() if val]
            for st in chosen_statuses:
                ms = MailingStatus(mailing_id=new_mailing.id, user_status=st)
                session.add(ms)

        sch = MailingSchedule(
            mailing_id=new_mailing.id,
            schedule_type=schedule_type,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            time_of_day=time_of_day,
            next_run=next_run or datetime.utcnow(),
            active=1
        )
        session.add(sch)
        await session.commit()

# -----------------------------
#  Обработчик «существующая рассылка» (после выбора)
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.CHOOSING_EXISTING_MAILING)
async def existing_mailing_selected(callback: types.CallbackQuery, state: FSMContext):
    if not callback.data.startswith("mailing_"):
        await callback.answer("Неизвестная команда")
        return

    mailing_id = int(callback.data.split("_", 1)[1])
    async with AsyncSessionLocal() as session:
        mailing = await session.get(Mailing, mailing_id)
        if not mailing or mailing.active == 0:
            await callback.message.edit_text("Рассылка не найдена или деактивирована.")
            await state.clear()
            return

        await state.update_data(
            mailing_title=mailing.title,
            existing_mailing_id=mailing_id
        )

        schedules = (
            await session.scalars(
                select(MailingSchedule)
                .where(MailingSchedule.mailing_id == mailing_id,
                       MailingSchedule.active == 1)
            )
        ).all()

        mailing_statuses = (
            await session.scalars(
                select(MailingStatus.user_status)
                .where(MailingStatus.mailing_id == mailing_id)
            )
        ).all()

    info_lines = [f"Название рассылки: <b>{mailing.title}</b>\n"]
    if schedules:
        info_lines.append("Текущее расписание:")
        for sch in schedules:
            if sch.schedule_type == "daily":
                info_lines.append(f"- Тип: <b>ежедневно</b>")
                info_lines.append(f"- Время (UTC): <b>{sch.time_of_day}</b>")
            elif sch.schedule_type == "weekly":
                info_lines.append(f"- Тип: <b>еженедельно</b>")
                wdays = sch.day_of_week.split(',') if sch.day_of_week else []
                day_names = []
                for wd in wdays:
                    try:
                        day_int = int(wd)
                        day_names.append(await get_day_of_week_names(day_int))
                    except:
                        pass
                info_lines.append(f"- Дни недели: <b>{', '.join(day_names)}</b>")
                info_lines.append(f"- Время (UTC): <b>{sch.time_of_day}</b>")
            elif sch.schedule_type == "monthly":
                info_lines.append(f"- Тип: <b>ежемесячно</b>")
                info_lines.append(f"- Дни месяца: <b>{sch.day_of_month.replace(',', ', ')}</b>")
                info_lines.append(f"- Время (UTC): <b>{sch.time_of_day}</b>")
            elif sch.schedule_type == "once":
                info_lines.append("- Тип: <b>единоразово</b>")
            info_lines.append(f"- Следующий запуск (UTC): <b>{sch.next_run}</b>\n")
    else:
        info_lines.append("Нет активных расписаний.\n")

    if mailing_statuses:
        info_lines.append("Статусы пользователей для рассылки:")
        info_lines.append(", ".join([f"<b>{status}</b>" for status in mailing_statuses]))
    else:
        info_lines.append("Статусы для рассылки не заданы.")

    final_text = "\n".join(info_lines)
    await callback.message.answer(final_text, parse_mode="HTML")

    try:
        await callback.bot.copy_message(
            chat_id=callback.message.chat.id,
            from_chat_id=mailing.saved_chat_id,
            message_id=mailing.saved_message_id
        )
    except Exception as e:
        logging.warning(f"Не удалось скопировать сообщение: {e}")
        await callback.message.answer("Не удалось скопировать исходное сообщение.")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить сообщение", callback_data="edit_mailing_message")],
        [InlineKeyboardButton(text="Изменить расписание", callback_data="edit_mailing_schedule")],
        [InlineKeyboardButton(text="Удалить рассылку", callback_data="delete_mailing")]
    ])
    await callback.message.answer("Управление рассылкой:", reply_markup=kb)
    await state.set_state(BroadcastStates.EXISTING_MAILING_MANAGE)

# -----------------------------
#  Меню управления существующей рассылкой
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.EXISTING_MAILING_MANAGE)
async def manage_existing_mailing(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    mailing_id = data.get("existing_mailing_id")

    if callback.data == "edit_mailing_message":
        await callback.message.edit_text("Пришлите новое сообщение/пересланное:")
        await state.set_state(BroadcastStates.EDITING_EXISTING_MESSAGE)
        await callback.answer()

    elif callback.data == "edit_mailing_schedule":
        async with AsyncSessionLocal() as session:
            schedules = (await session.scalars(
                select(MailingSchedule).where(MailingSchedule.mailing_id == mailing_id)
            )).all()
            for s in schedules:
                s.active = 0
            await session.commit()

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Ежедневно", callback_data="schedule_daily_exists")],
            [InlineKeyboardButton(text="Еженедельно", callback_data="schedule_weekly_exists")],
            [InlineKeyboardButton(text="Ежемесячно", callback_data="schedule_monthly_exists")],
            [InlineKeyboardButton(text="Единоразово", callback_data="schedule_once_exists")],
        ])
        await state.update_data(is_edit=True)
        await callback.message.edit_text("Выберите новый тип расписания:", reply_markup=kb)
        await state.set_state(BroadcastStates.EDITING_EXISTING_SCHEDULE_TYPE)
        await callback.answer()

    elif callback.data == "delete_mailing":
        async with AsyncSessionLocal() as session:
            mailing = await session.get(Mailing, mailing_id)
            if mailing:
                mailing.active = 0
                await session.commit()
        await callback.message.edit_text("Рассылка удалена (деактивирована).")
        await state.clear()
        await callback.answer()

    else:
        await callback.answer("Неизвестная команда")

# -----------------------------
#  Редактирование сообщения существующей рассылки
# -----------------------------
@broadcast_router.message(BroadcastStates.EDITING_EXISTING_MESSAGE)
async def editing_existing_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mailing_id = data.get("existing_mailing_id")

    new_chat_id = str(message.chat.id)
    new_msg_id = str(message.message_id)

    async with AsyncSessionLocal() as session:
        mailing = await session.get(Mailing, mailing_id)
        if mailing and mailing.active == 1:
            mailing.saved_chat_id = new_chat_id
            mailing.saved_message_id = new_msg_id
            await session.commit()

    await message.answer("Сообщение для рассылки обновлено.")
    await state.clear()

# -----------------------------
#  Изменение расписания существующей рассылки: выбор типа
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.EDITING_EXISTING_SCHEDULE_TYPE)
async def editing_existing_schedule_type(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    await callback.answer()

    if data == "schedule_daily_exists":
        await callback.message.edit_text("Введите время в формате HH:MM (например 09:00):")
        await state.set_state(BroadcastStates.ENTERING_DAILY_TIME)

    elif data == "schedule_weekly_exists":
        await state.update_data(selected_weekdays=[])
        text = "Выберите дни недели. Нажимайте, чтобы выделить.\nЗатем нажмите 'Далее'."
        await callback.message.edit_text(text, reply_markup=build_weekdays_keyboard([]))
        await state.set_state(BroadcastStates.ENTERING_WEEKLY_DAYS)

    elif data == "schedule_monthly_exists":
        await state.update_data(selected_monthdays=[])
        text = "Выберите даты месяца. Нажимайте, чтобы выделить.\nЗатем 'Далее'."
        await callback.message.edit_text(text, reply_markup=build_monthdays_keyboard([]))
        await state.set_state(BroadcastStates.ENTERING_MONTHLY_DAYS)

    elif data == "schedule_once_exists":
        text = (
            "Единоразовая рассылка (редактируем существующую).\n\n"
            "Введите дату и время в формате <b>YYYY-MM-DD HH:MM</b> по UTC, "
            "чтобы запланировать.\n\n"
            "Или нажмите кнопку «Отправить сейчас» чтобы отправить сразу.\n"
            "Нажмите «Отмена», чтобы выйти."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отправить сейчас", callback_data="send_once_now")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel")]
        ])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await state.update_data(is_edit=True)
        await state.set_state(BroadcastStates.ENTERING_ONCE_TIME)

    else:
        await callback.message.edit_text("Неизвестная команда.")
        await state.clear()

# -----------------------------
#  Вспомогательная: единоразовая рассылка для существующей
# -----------------------------
async def send_once_broadcast_existing(state: FSMContext, callback: types.CallbackQuery):
    data = await state.get_data()
    mailing_id = data.get("existing_mailing_id")
    await callback.message.answer("Ожидайте, идет рассылка...")

    async with AsyncSessionLocal() as session:
        mailing = await session.get(Mailing, mailing_id)
        if not mailing:
            return
        mail_stats = await session.scalars(
            select(MailingStatus).where(MailingStatus.mailing_id == mailing_id)
        )

        # Если рассылка по ключевому слову, то выбираем пользователей, просмотревших материал
        if any(st.user_status.startswith("keyword:") for st in mail_stats):
            keyword = [st.user_status for st in mail_stats if st.user_status.startswith("keyword:")][0].split(":", 1)[1]
            material = await session.scalar(select(Material).where(Material.keyword == keyword))
            if not material:
                await callback.message.edit_text("Неверное ключевое слово, попробуйте ещё раз.")
                return
            mviews = await session.scalars(select(MaterialView).where(MaterialView.material_id == material.id))
            mviews_list = mviews.all()
            user_ids = [mv.user_id for mv in mviews_list]
            if user_ids:
                users = await session.scalars(select(User).where(User.id.in_(user_ids)))
                users_list = users.all()
            else:
                users_list = []
        else:
            all_statuses = [ms.user_status.lower() for ms in mail_stats.all()]

            non_admin_statuses = [st for st in all_statuses if st != "админы"]
            users_list = []
            users_by_status = await session.scalars(
                select(User).where(func.lower(User.status).in_(non_admin_statuses))
            )
            users_list.extend(users_by_status.all())
            if "админы" in all_statuses:
                admin_users = await session.scalars(
                    select(User).where(User.tg_id.in_(map(str, config.ADMIN_IDS)))
                )
                users_list.extend(admin_users.all())

    bot = callback.bot
    success_count = 0
    error_count = 0
    for user in users_list:
        if not user.tg_id:
            continue
        try:
            await bot.copy_message(
                chat_id=user.tg_id,
                from_chat_id=mailing.saved_chat_id,
                message_id=mailing.saved_message_id
            )
            success_count += 1
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение пользователю {user.tg_id}: {e}")
            error_count += 1

    logging.info(f"Единоразовая рассылка для mailing_id={mailing_id} завершена: "
                 f"успешно={success_count}, ошибок={error_count}.")
    text = f"Единоразовая рассылка завершена.\nУспешно: {success_count}, Ошибок: {error_count}"
    await callback.message.edit_text(text)

# -----------------------------
# Универсальные функции: построение клавиатур и т.п.
# -----------------------------
def build_weekdays_keyboard(selected_days: list):
    row = []
    for d in range(1, 8):
        checked = "✅" if d in selected_days else ""
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d-1]
        btn_text = f"{checked}{day_name}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"weekday_{d}"))
    kb = []
    kb.append(row)
    kb.append([InlineKeyboardButton(text="Далее", callback_data="weekdays_done")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def build_monthdays_keyboard(selected_days: list):
    rows = []
    row = []
    for d in range(1, 32):
        checked = "✅" if d in selected_days else ""
        btn_text = f"{checked}{d}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"monthday_{d}"))
        if len(row) == 8:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Далее", callback_data="monthdays_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# -----------------------------
#  Выбор дней недели (новая/существующая)
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.ENTERING_WEEKLY_DAYS)
async def choosing_weekly_days(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_weekdays", [])

    if callback.data.startswith("weekday_"):
        day = int(callback.data.replace("weekday_", ""))
        if day in selected:
            selected.remove(day)
        else:
            selected.append(day)
        await state.update_data(selected_weekdays=selected)
        text = "Выберите дни недели. Нажимайте, чтобы выделить.\nЗатем нажмите 'Далее'."
        await callback.message.edit_text(text, reply_markup=build_weekdays_keyboard(selected))
        await callback.answer()

    elif callback.data == "weekdays_done":
        if not selected:
            await callback.answer("Выберите хотя бы один день!", show_alert=True)
            return
        await callback.message.edit_text("Введите время в формате HH:MM (например, 09:00):")
        await state.set_state(BroadcastStates.ENTERING_WEEKLY_TIME)
        await callback.answer()

    else:
        await callback.answer("Неизвестная команда")

# -----------------------------
#  Ввод времени для еженедельной рассылки
# -----------------------------
@broadcast_router.message(BroadcastStates.ENTERING_WEEKLY_TIME)
async def entering_weekly_time(message: types.Message, state: FSMContext):
    time_str = message.text.strip()
    try:
        hh, mm = time_str.split(":")
        dt_time = time(hour=int(hh), minute=int(mm))
    except:
        await message.answer("Неверный формат. Введите время HH:MM.")
        return

    data = await state.get_data()
    selected_days = data.get("selected_weekdays", [])
    is_edit = data.get("is_edit", False)

    day_of_week_str = ",".join(str(d) for d in selected_days)
    now = datetime.utcnow()
    first_run = None
    for d in selected_days:
        offset = (d - 1) - now.weekday()
        if offset < 0:
            offset += 7
        candidate = datetime(
            year=now.year,
            month=now.month,
            day=now.day,
            hour=dt_time.hour,
            minute=dt_time.minute
        ) + timedelta(days=offset)
        if not first_run or candidate < first_run:
            first_run = candidate
    if first_run <= now:
        first_run += timedelta(weeks=1)

    if not is_edit:
        await create_mailing_in_db(
            state,
            schedule_type="weekly",
            day_of_week=day_of_week_str,
            time_of_day=time_str,
            next_run=first_run
        )
        await message.answer("Еженедельная рассылка создана!")
    else:
        mailing_id = data["existing_mailing_id"]
        await add_schedule_for_existing_mailing(
            mailing_id,
            schedule_type="weekly",
            day_of_week=day_of_week_str,
            time_of_day=time_str,
            next_run=first_run
        )
        await message.answer("Расписание обновлено (еженедельно).")

    await state.clear()

# -----------------------------
#  Выбор дат месяца (новая/существующая)
# -----------------------------
@broadcast_router.callback_query(BroadcastStates.ENTERING_MONTHLY_DAYS)
async def choosing_monthly_days(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_monthdays", [])

    if callback.data.startswith("monthday_"):
        day = int(callback.data.replace("monthday_", ""))
        if day in selected:
            selected.remove(day)
        else:
            selected.append(day)
        await state.update_data(selected_monthdays=selected)
        text = "Выберите даты месяца. Нажимайте, чтобы выделить.\nЗатем 'Далее'."
        await callback.message.edit_text(text, reply_markup=build_monthdays_keyboard(selected))
        await callback.answer()

    elif callback.data == "monthdays_done":
        if not selected:
            await callback.answer("Выберите хотя бы одну дату!", show_alert=True)
            return
        await callback.message.edit_text("Введите время в формате HH:MM (например 09:00):")
        await state.set_state(BroadcastStates.ENTERING_MONTHLY_TIME)
        await callback.answer()
    else:
        await callback.answer("Неизвестная команда")

# -----------------------------
#  Ввод времени для ежемесячной рассылки
# -----------------------------
@broadcast_router.message(BroadcastStates.ENTERING_MONTHLY_TIME)
async def entering_monthly_time(message: types.Message, state: FSMContext):
    time_str = message.text.strip()
    try:
        hh, mm = time_str.split(":")
        dt_time = time(hour=int(hh), minute=int(mm))
    except:
        await message.answer("Неверный формат. Введите время в формате HH:MM (например 09:00).")
        return

    data = await state.get_data()
    selected_days = data.get("selected_monthdays", [])
    is_edit = data.get("is_edit", False)

    day_of_month_str = ",".join(str(d) for d in selected_days)
    now = datetime.utcnow()
    first_run = None
    for d in selected_days:
        candidate = datetime(now.year, now.month, d, dt_time.hour, dt_time.minute)
        if candidate <= now:
            month = now.month + 1
            year = now.year
            if month > 12:
                month = 1
                year += 1
            from calendar import monthrange
            max_d = monthrange(year, month)[1]
            if d > max_d:
                d = max_d
            candidate = datetime(year, month, d, dt_time.hour, dt_time.minute)
        if not first_run or candidate < first_run:
            first_run = candidate

    if not is_edit:
        await create_mailing_in_db(
            state,
            schedule_type="monthly",
            day_of_month=day_of_month_str,
            time_of_day=time_str,
            next_run=first_run
        )
        await message.answer("Ежемесячная рассылка создана!")
    else:
        mailing_id = data["existing_mailing_id"]
        await add_schedule_for_existing_mailing(
            mailing_id,
            schedule_type="monthly",
            day_of_month=day_of_month_str,
            time_of_day=time_str,
            next_run=first_run
        )
        await message.answer("Расписание обновлено (ежемесячно).")

    await state.clear()

# -----------------------------
#  Ввод времени для ежедневной рассылки
# -----------------------------
@broadcast_router.message(BroadcastStates.ENTERING_DAILY_TIME)
async def entering_daily_time(message: types.Message, state: FSMContext):
    time_str = message.text.strip()
    try:
        hh, mm = time_str.split(":")
        dt_time = time(hour=int(hh), minute=int(mm))
    except:
        await message.answer("Неверный формат. Введите время в формате HH:MM (например 09:00).")
        return

    data = await state.get_data()
    is_edit = data.get("is_edit", False)

    now = datetime.utcnow()
    first_run = datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        hour=dt_time.hour,
        minute=dt_time.minute
    )
    if first_run <= now:
        first_run += timedelta(days=1)

    if not is_edit:
        await create_mailing_in_db(
            state,
            schedule_type="daily",
            time_of_day=time_str,
            next_run=first_run
        )
        await message.answer("Ежедневная рассылка создана!")
    else:
        mailing_id = data["existing_mailing_id"]
        await add_schedule_for_existing_mailing(
            mailing_id,
            schedule_type="daily",
            time_of_day=time_str,
            next_run=first_run
        )
        await message.answer("Расписание обновлено (ежедневно).")

    await state.clear()

# -----------------------------
#  Функция для добавления (создания) нового расписания к существующей рассылке
# -----------------------------
async def add_schedule_for_existing_mailing(
    mailing_id: int,
    schedule_type: str,
    day_of_week: str = None,
    day_of_month: str = None,
    time_of_day: str = None,
    next_run: datetime = None
):
    async with AsyncSessionLocal() as session:
        mailing = await session.get(Mailing, mailing_id)
        if not mailing or mailing.active == 0:
            return

        sch = MailingSchedule(
            mailing_id=mailing_id,
            schedule_type=schedule_type,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            time_of_day=time_of_day,
            next_run=next_run or datetime.utcnow(),
            active=1
        )
        session.add(sch)
        await session.commit()
