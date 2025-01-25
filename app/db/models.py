from datetime import datetime
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey

Base = declarative_base()

class User(Base):
    """
    Таблица пользователей.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(String, unique=True, index=True, nullable=False)
    wp_id = Column(String, nullable=True)
    status = Column(String, nullable=True)             # пример: "подписка на 6 месяцев", "зарегистрирован" и т.д.
    username_in_tg = Column(String, nullable=True)
    first_name = Column(String, nullable=True)

    category = Column(String, default="common")         # Категория пользователя
    last_interaction = Column(DateTime, nullable=True)  # Дата последнего взаимодействия
    created_at = Column(DateTime, default=datetime.utcnow)


class Material(Base):
    """
    Таблица материалов, привязанных к ключевому слову.
    """
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True)
    keyword = Column(String, unique=True, nullable=False)
    text_content = Column(Text, nullable=True)
    # Дополнительно ссылки на файлы/картинки/видео


class KeywordLink(Base):
    """
    Таблица уникальных ссылок для материалов.
    """
    __tablename__ = "keyword_links"

    id = Column(Integer, primary_key=True)
    link = Column(String, unique=True, nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    expiration_date = Column(DateTime, nullable=True)
    max_clicks = Column(Integer, nullable=True)
    click_count = Column(Integer, default=0)

    material = relationship("Material")


class Mailing(Base):
    """
    Таблица для хранения информации о рассылках (уведомлениях).
    """
    __tablename__ = "mailings"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    text = Column(Text, nullable=True)
    send_datetime = Column(DateTime, nullable=True)
    periodicity = Column(String, default="once")  # daily/weekly/monthly/custom/once
    category_filter = Column(String, default="common")
    active = Column(Integer, default=1)  # 1 = активна, 0 = нет

    created_at = Column(DateTime, default=datetime.utcnow)
