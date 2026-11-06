from typing import Any, Awaitable, Callable, Dict
from time import monotonic
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

class ThrottlingMiddleware(BaseMiddleware):
    """
    Анти-флуд мидлварь.
    Блокирует частые сообщения от одного пользователя.
    """
    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit
        # Словарь для хранения времени последнего сообщения: {user_id: timestamp}
        self.users_time: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Работаем только с Message и CallbackQuery
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        user_id = user.id
        now = monotonic()
        last_time = self.users_time.get(user_id, 0.0)

        # Если с последнего действия прошло меньше лимита — игнорируем событие
        if now - last_time < self.rate_limit:
            # Для Message можно ответить предупреждением, для Callback — просто проигнорировать
            if isinstance(event, Message):
                await event.answer("⏳ Слишком часто! Подожди немного.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⏳ Не так быстро!", show_alert=False)
            
            # Не вызываем handler(event, data), чтобы остановить обработку
            return None

        # Обновляем время последнего действия
        self.users_time[user_id] = now
        return await handler(event, data)