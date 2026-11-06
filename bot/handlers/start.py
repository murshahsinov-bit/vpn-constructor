from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.crud import get_or_create_user

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, session):
    # Создаём или получаем пользователя из БД
    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Купить подписку", callback_data="buy_menu")
    builder.button(text="👤 Мой профиль", callback_data="profile_menu")
    builder.button(text="📖 Инструкция", callback_data="instructions_menu")
    builder.adjust(1) # Кнопки в столбик

    await message.answer(
        f"Привет, {message.from_user.first_name}!\n\n"
        "Здесь ты можешь купить быстрый и стабильный VPN для обхода блокировок.\n"
        "Выбирай действие:",
        reply_markup=builder.as_markup()
    )