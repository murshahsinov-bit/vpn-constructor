from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select, func
from bot.database.models import User, Subscription

router = Router()

# Замени на свой Telegram ID
ADMIN_ID = 123456789 

@router.message(Command("admin"))
async def admin_panel(message: Message, session):
    if message.from_user.id != ADMIN_ID:
        return
    
    # Считаем пользователей
    result = await session.execute(select(func.count()).select_from(User))
    user_count = result.scalar()
    
    # Считаем активные подписки
    result = await session.execute(
        select(func.count()).select_from(Subscription).where(Subscription.is_active == True)
    )
    active_subs = result.scalar()
    
    await message.answer(
        f"👑 *Админ-панель*\n\n"
        f"👥 Пользователей: {user_count}\n"
        f"💳 Активных подписок: {active_subs}\n\n"
        f"Для выдачи подписки вручную: `/grant <user_id> <days>`",
        parse_mode="Markdown"
    )