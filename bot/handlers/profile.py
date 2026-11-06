from aiogram import Router, F
from aiogram.types import CallbackQuery
from bot.database.crud import get_user_subscription

router = Router()

@router.callback_query(F.data == "profile_menu")
async def show_profile(callback: CallbackQuery, session):
    sub = await get_user_subscription(session, callback.from_user.id)
    
    if sub:
        status_text = (
            f"👤 Твой профиль\n\n"
            f"📦 Режим: {sub.mode}\n"
            f"📅 Действует до: {sub.expires_at.strftime('%d.%m.%Y')}\n"
            f"🔗 Ссылка: `{sub.subscription_url}`\n"
        )
    else:
        status_text = (
            "👤 Твой профиль\n\n"
            "❌ У тебя пока нет активной подписки.\n"
            "Нажми «Купить», чтобы получить доступ."
        )
        
    await callback.message.edit_text(status_text, parse_mode="Markdown")
    await callback.answer()