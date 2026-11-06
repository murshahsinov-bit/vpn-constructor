from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Купить подписку", callback_data="buy_menu")
    builder.button(text="👤 Мой профиль", callback_data="profile_menu")
    builder.button(text="📖 Инструкция", callback_data="instructions_menu")
    builder.adjust(1)  # Кнопки в столбик
    return builder.as_markup()

def get_tariffs_kb() -> InlineKeyboardMarkup:
    """Меню выбора тарифа."""
    builder = InlineKeyboardBuilder()
    builder.button(text="1 месяц — 50 ₽", callback_data="pay_1_month")
    builder.button(text="3 месяца — 100 ₽", callback_data="pay_3_months")
    builder.button(text="1 год — 300 ₽", callback_data="pay_1_year")
    builder.button(text="🔙 Назад", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()

def get_back_kb(target: str = "back_to_start") -> InlineKeyboardMarkup:
    """Универсальная кнопка «Назад»."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=target)
    return builder.as_markup()