from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

class CheckSubscriptionMiddleware(BaseMiddleware):
    """
    Проверяет обязательную подписку на канал(ы).
    """
    def __init__(self, channels: list[str]):
        # Список ID каналов или их @username (например, ["@my_channel", "-1001234567890"])
        self.channels = channels

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Пропускаем команду /start, чтобы пользователь мог запустить бота
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        # Получаем экземпляр бота из контекста
        bot = data["bot"]
        is_subscribed = True

        for channel in self.channels:
            try:
                member = await bot.get_chat_member(chat_id=channel, user_id=user.id)
                # Если статус 'left' или 'kicked' — не подписан
                if member.status in ["left", "kicked"]:
                    is_subscribed = False
                    break
            except TelegramBadRequest:
                # Если бот не админ в канале или канал не найден
                is_subscribed = False
                break

        if not is_subscribed:
            # Создаём клавиатуру с кнопками подписки
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Подписаться", url="https://t.me/your_channel")],
                [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub")]
            ])
            
            text = "⚠️ Для использования бота необходимо подписаться на канал!"
            
            if isinstance(event, Message):
                await event.answer(text, reply_markup=kb)
            elif isinstance(event, CallbackQuery):
                await event.message.answer(text, reply_markup=kb)
                await event.answer("Подпишись на канал!", show_alert=True)
            
            # Останавливаем обработку
            return None

        # Если подписан — пропускаем дальше
        return await handler(event, data)