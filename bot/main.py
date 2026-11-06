import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from bot.config import settings
from bot.database.models import Base
from bot.handlers import routers
from bot.middlewares import ThrottlingMiddleware, CheckSubscriptionMiddleware

# Настройка логирования
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Мидлварь для внедрения сессии БД в хендлеры
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Any, Awaitable, Callable, Dict

class DataBaseSession(BaseMiddleware):
    """Прокидывает AsyncSession в хендлеры через data['session']."""
    def __init__(self, session_pool: async_sessionmaker):
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with self.session_pool() as session:
            data["session"] = session
            return await handler(event, data)

async def main():
    # 1. Инициализация БД
    engine = create_async_engine(settings.database_url, echo=False)
    session_pool = async_sessionmaker(engine, expire_on_commit=False)

    # Создаем таблицы (если их нет)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Инициализация бота и диспетчера
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # 3. Подключение мидлварей (порядок важен)
    # Мидлварь БД должна быть первой, чтобы сессия была доступна остальным
    dp.update.middleware(DataBaseSession(session_pool=session_pool))
    
    # Анти-флуд
    dp.message.middleware(ThrottlingMiddleware(rate_limit=0.5))
    dp.callback_query.middleware(ThrottlingMiddleware(rate_limit=0.5))

    # Проверка подписки (раскомментируй, если используешь)
    # dp.message.middleware(CheckSubscriptionMiddleware(channels=["@your_channel"]))
    # dp.callback_query.middleware(CheckSubscriptionMiddleware(channels=["@your_channel"]))

    # 4. Регистрация роутеров
    for router in routers:
        dp.include_router(router)

    # 5. Запуск
    logger.info("🚀 Бот запущен")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
    finally:
        await bot.session.close()
        await engine.dispose()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен")