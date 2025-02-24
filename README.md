# Reclin Bot

**Reclin Bot** — это проект, разработанный для автоматизации задач, связанных с рекомендационными системами. 

## Установка

1. **Клонирование репозитория:**

   ```bash
   git clone https://github.com/rafailvv/reclin_bot.git
   cd reclin_bot
   ```

2. **Установка зависимостей:**

   Рекомендуется использовать виртуальное окружение для изоляции зависимостей.

   ```bash
   python3 -m venv env
   source env/bin/activate  # Для Windows используйте `env\Scripts\activate`
   pip install -r requirements.txt
   ```

3. **Запуск бота:**

   Перед запуском убедитесь, что все необходимые настройки выполнены.

   ```bash
   python main.py
   ```

## Использование Docker

Для удобства деплоя проект включает поддержку Docker.

1. **Сборка Docker-образа:**

   ```bash
   docker build -t reclin_bot .
   ```

2. **Запуск контейнера:**

   ```bash
   docker run -d --name reclin_bot_container reclin_bot
   ```

   Альтернативно, вы можете использовать `docker-compose`:

   ```bash
   docker-compose up -d
   ```

## Поддержка

Если у вас возникли вопросы или предложения, пожалуйста, создайте issue в этом репозитории или свяжитесь с автором напрямую.

## Лицензия

Этот проект распространяется под лицензией MIT. 
