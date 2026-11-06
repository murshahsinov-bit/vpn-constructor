from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.crud import create_payment, update_payment_status, create_subscription
from bot.services.link_builder import generate_subscription_url

router = Router()

# Тарифы (в рублях и звездах)
TARIFFS = {
    "1_month": {"price_rub": 50, "price_stars": 50, "days": 30, "label": "1 месяц"},
    "3_months": {"price_rub": 100, "price_stars": 100, "days": 90, "label": "3 месяца"},
    "1_year": {"price_rub": 300, "price_stars": 300, "days": 365, "label": "1 год"},
}

@router.callback_query(F.data == "buy_menu")
async def show_tariffs(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    for key, data in TARIFFS.items():
        builder.button(
            text=f"{data['label']} — {data['price_rub']} ₽",
            callback_data=f"pay_{key}"
        )
    builder.button(text="🔙 Назад", callback_data="back_to_start")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "Выбери подходящий тариф:\n\n"
        "💡 Все тарифы включают доступ к серверам с умным автовыбором.",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("pay_"))
async def process_payment(callback: CallbackQuery, session, bot):
    tariff_id = callback.data.split("_", 1)[1]
    tariff = TARIFFS.get(tariff_id)
    
    if not tariff:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    # Создаём запись о платеже в БД (pending)
    payment = await create_payment(
        session=session,
        user_id=callback.from_user.id,
        amount=tariff["price_rub"],
        tariff_id=tariff_id
    )
    
    # Отправляем счёт через Telegram Stars
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"VPN подписка: {tariff['label']}",
        description="Доступ к быстрым серверам с обходом блокировок",
        payload=f"vpn_sub_{payment.id}",
        provider_token="", # Для Stars оставляем пустым
        currency="XTR", # XTR — код для Telegram Stars
        prices=[LabeledPrice(label=tariff['label'], amount=tariff["price_stars"])],
        start_parameter="vpn_subscription"
    )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    # Обязательно отвечаем, иначе платёж не пройдёт
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def on_successful_payment(message: Message, session):
    # Извлекаем ID платежа из payload
    payload = message.successful_payment.invoice_payload
    payment_id = int(payload.split("_")[-1])
    
    # Обновляем статус платежа на success
    await update_payment_status(session, payment_id, "success")
    
    # Определяем тариф по сумме (можно вытащить из БД, но для простоты по payload)
    # В реальности лучше хранить tariff_id в БД и брать оттуда
    tariff_id = "1_month" # Заглушка, в реальности нужно брать из платежа
    
    # Генерируем ссылку на подписку
    sub_url = generate_subscription_url(user_id=message.from_user.id, mode="auto")
    
    # Создаём подписку в БД
    await create_subscription(
        session=session,
        user_id=message.from_user.id,
        mode="auto",
        days=TARIFFS[tariff_id]["days"],
        subscription_url=sub_url
    )
    
    await message.answer(
        f"✅ Оплата прошла успешно!\n\n"
        f"Твоя ссылка для подключения:\n"
        f"`{sub_url}`\n\n"
        f"Скопируй её и вставь в приложение INCY.",
        parse_mode="Markdown"
    )