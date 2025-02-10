import logging
from openpyxl import load_workbook
from app.db.models import User

from openpyxl import load_workbook
import logging
from sqlalchemy import update # Предполагается, что модель User импортирована из модуля models

async def load_initial_data_from_excel(session, file_path: str):
    """
    Считывает Excel-файл (reclin_base.xlsx) и заполняет таблицу User,
    если она изначально пустая.

    Ожидается, что в Excel есть столбцы в порядке:
    1) TG ID
    2) WP ID
    3) Статус
    4) Username в TG
    5) Имя в TG

    Если порядок другой, корректируйте чтение колонок.
    """
    try:
        wb = load_workbook(filename=file_path)
        sheet = wb.active  # или wb["Имя_листа"], если нужно конкретно по названию

        # Предположим, что первая строка (row=1) - это заголовки,
        # и данные начинаются со второй строки (row=2).
        row_num = 2
        rows_added = 0

        while True:
            # Берём ячейку из колонки 1 (A) - TG ID
            tg_id_cell = sheet.cell(row=row_num, column=1)
            if not tg_id_cell.value:
                # Если TG ID пустой (или None), скорее всего, достигли конца данных.
                break

            tg_id = str(tg_id_cell.value).strip()
            wp_id = str(sheet.cell(row=row_num, column=2).value or "").strip()
            status = str(sheet.cell(row=row_num, column=3).value or "").strip()
            username_in_tg = str(sheet.cell(row=row_num, column=4).value or "").strip()
            first_name = str(sheet.cell(row=row_num, column=5).value or "").strip()

            # Создаём объект пользователя
            user_obj = User(
                tg_id=tg_id,
                wp_id=wp_id,
                status=status,
                username_in_tg=username_in_tg,
                tg_fullname=first_name
            )

            session.add(user_obj)
            rows_added += 1
            row_num += 1

        # Сохраняем добавленные записи в базу данных
        await session.commit()
        logging.info(f"Загрузка из Excel завершена: добавлено {rows_added} пользователь(ей).")

        # После сохранения пробегаемся по всем записям и устанавливаем created_at в None.
        # Можно использовать массовое обновление через SQL-запрос:
        await session.execute(update(User).values(created_at=None))
        await session.commit()
        logging.info("Поле created_at для всех пользователей установлено в None.")

    except FileNotFoundError:
        logging.error(f"Файл '{file_path}' не найден. Пропускаем загрузку из Excel.")
    except Exception as e:
        logging.error(f"Ошибка при загрузке Excel: {e}")
