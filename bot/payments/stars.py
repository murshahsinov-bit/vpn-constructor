import logging
from aiogram import Bot
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message

logger = logging.getLogger(__name__)

class StarsPayment:
    """
    Сервис для работы с платежами через Telegram Stars.
    """

    @staticmethod
    async def send_invoice(
        bot: Bot, 
        chat_id: int, 
        title: str, 
        description: str, 
        payload: str, 
        amount_stars: int
    ) -> Message:
        """
        Отправляет счет на оплату пользователю.
        """
        try:
            invoice_msg = await bot.send_invoice(
                chat_id=chat_id,
                title=title,
                description=description,
                payload=payload,
                provider_token="",  # Для Stars всегда пустая строка
                currency="XTR",     # Код валюты Telegram Stars
                prices=[LabeledPrice(label=title, amount=amount_stars)],
                start_parameter="vpn_subscription"
            )
            return invoice_msg
        except Exception as e:
            logger.error(f"Ошибка при отправке счета Stars: {e}")
            raise

    @staticmethod
    async def approve_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot) -> bool:
        """
        Подтверждает готовность к оплате. 
        Telegram требует обязательного ответа, иначе платеж зависнет.
        """
        try:
            # Здесь можно добавить проверку: не истек ли тариф, не забанен ли юзер
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
            return True
        except Exception as e:
            logger.error(f"Ошибка при подтверждении pre_checkout: {e}")
            await bot.answer_pre_checkout_query(
                pre_checkout_query.id, 
                ok=False, 
                error_message="Платеж не может быть обработан. Попробуйте позже."
            )
            return False

    @staticmethod
    def parse_payload(payload: str) -> dict | None:
        """
        Извлекает данные из payload (например, 'vpn_sub_1_month_123').
        Возвращает словарь с параметрами или None при ошибке.
        """
        try:
            # Пример payload: "vpn_sub_1_month_12345"
            parts = payload.split("_")
            if len(parts) >= 4 and parts[0] == "vpn" and parts[1] == "sub":
                return {
                    "tariff_id": parts[2],
                    "payment_id": int(parts[3])
                }
            return None
        except (ValueError, IndexError):
            return None