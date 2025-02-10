import os
from dotenv import load_dotenv

load_dotenv()  # Загрузим .env

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    BOT_LINK: str = os.getenv("BOT_LINK", "")
    DB_HOST: str = os.getenv("DATABASE_HOST", "localhost")
    DB_USER: str = os.getenv("DATABASE_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "postgres")
    DB_NAME: str = os.getenv("DATABASE_NAME", "postgres")
    DB_PORT: str = os.getenv("DATABASE_PORT", "5432")

    ADMIN_IDS: list[int] = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

    API_URL : str = os.getenv("API_URL", "https://reclin.ru/wp-json/api/")
    USERNAME : str = os.getenv("API_USERNAME")
    PASSWORD : str = os.getenv("API_PASSWORD")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

config = Config()
