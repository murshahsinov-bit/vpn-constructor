from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    # Telegram Bot
    bot_token: SecretStr
    
    # База данных (SQLite для простоты, можно заменить на PostgreSQL)
    database_url: str = "sqlite+aiosqlite:///vpn_bot.db"
    
    # Секретный ключ для генерации ссылок подписки
    sub_secret_key: SecretStr
    base_sub_url: str = "https://your-domain.com/sub"

    # Админы
    admin_ids: list[int] = []

    # Настройки обязательной подписки (опционально)
    # channels: list[str] = ["@your_channel"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

# Глобальный экземпляр настроек
settings = Settings()