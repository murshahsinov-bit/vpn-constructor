from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, field_validator
import json

class Settings(BaseSettings):
    # Telegram Bot
    bot_token: SecretStr
    
    # База данных (SQLite по умолчанию)
    database_url: str = "sqlite+aiosqlite:///./vpn_bot.db"
    
    # Секретный ключ для генерации ссылок подписки
    sub_secret_key: SecretStr
    base_sub_url: str = "https://your-domain.com/sub"

    # Админы
    admin_ids: list[int] = []

    # Прокси для Telegram (если в РФ)
    proxy_url: str | None = None

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        """Позволяет писать в .env как [123, 456], так и просто 123 или 123,456"""
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            return [int(x.strip()) for x in v.split(",") if x.strip().isdigit()]
        return v

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

# Глобальный экземпляр настроек
settings = Settings()