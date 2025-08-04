# Используем официальный образ Python
FROM python:3.10-slim

# Устанавливаем локаль, если нужно
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Устанавливаем необходимые системные пакеты
RUN apt-get update && apt-get install -y \
    build-essential \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Копируем список зависимостей
COPY requirements.txt /app/requirements.txt

WORKDIR /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект в контейнер
COPY . /app

# Запускаем main.py
CMD ["python", "-m", "main"]
