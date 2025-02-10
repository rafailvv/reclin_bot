from datetime import datetime
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint

Base = declarative_base()

class User(Base):
    """
    Таблица пользователей.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(String, unique=True, index=True, nullable=False)
    wp_id = Column(String, nullable=True)
    status = Column(String, nullable=True)  # пример: "подписка на 6 месяцев", "зарегистрирован" и т.д.
    username_in_tg = Column(String, nullable=True)
    tg_fullname = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)

    last_interaction = Column(DateTime, nullable=True)  # Дата последнего взаимодействия
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)

class Material(Base):
    """
    Таблица материалов, привязанных к ключевому слову.
    Храним chat_id + message_id, чтобы потом делать forward.
    """
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True)
    keyword = Column(String, unique=True, nullable=False)
    chat_id = Column(String, nullable=True)  # В каком чате лежит сообщение
    message_id = Column(Integer, nullable=True)  # ID сообщения для forward

    views = relationship("MaterialView", back_populates="material", lazy="selectin")
    links = relationship("KeywordLink", back_populates="material", lazy="selectin")

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

    material = relationship("Material", back_populates="links", lazy="selectin")

class MaterialView(Base):
    """
    Таблица учёта: какой user смотрел какой keyword (Material).
    """
    __tablename__ = "material_views"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False)
    viewed_at = Column(DateTime, default=datetime.utcnow)

    material = relationship("Material", back_populates="views", lazy="selectin")

class Mailing(Base):
    """
    Таблица для хранения информации о рассылках (уведомлениях).
    """
    __tablename__ = "mailings"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    saved_chat_id = Column(String, nullable=True)
    saved_message_id = Column(String, nullable=True)
    active = Column(Integer, default=1)  # 1 = активна, 0 = нет
    created_at = Column(DateTime, default=datetime.utcnow)

    statuses = relationship("MailingStatus", back_populates="mailing", cascade="all, delete-orphan", lazy="selectin")
    schedules = relationship("MailingSchedule", back_populates="mailing", cascade="all, delete-orphan", lazy="selectin")

class MailingStatus(Base):
    """
    Связь "Рассылка - Статусы пользователей".
    """
    __tablename__ = "mailing_statuses"

    id = Column(Integer, primary_key=True)
    mailing_id = Column(Integer, ForeignKey("mailings.id", ondelete="CASCADE"))
    user_status = Column(String, nullable=False)

    mailing = relationship("Mailing", back_populates="statuses", lazy="selectin")

    __table_args__ = (
        UniqueConstraint('mailing_id', 'user_status', name='uq_mailing_status'),
    )

class MailingSchedule(Base):
    """
    Таблица расписаний рассылки.
    """
    __tablename__ = "mailing_schedules"

    id = Column(Integer, primary_key=True)
    mailing_id = Column(Integer, ForeignKey("mailings.id", ondelete="CASCADE"))
    schedule_type = Column(String, default="once")  # daily, weekly, monthly, once
    day_of_week = Column(String, nullable=True)  # "1,3,5" и т.п.
    day_of_month = Column(String, nullable=True)  # "1,15,28" и т.п.
    time_of_day = Column(String, nullable=True)  # "HH:MM"
    next_run = Column(DateTime, nullable=True)
    active = Column(Integer, default=1)

    mailing = relationship("Mailing", back_populates="schedules", lazy="selectin")

    def __repr__(self):
        return (f"<MailingSchedule(id={self.id}, mailing={self.mailing_id}, type={self.schedule_type}, "
                f"next={self.next_run}, active={self.active})>")


