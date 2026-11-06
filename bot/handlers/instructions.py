from aiogram import Router, F
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query(F.data == "instructions_menu")
async def show_instructions(callback: CallbackQuery):
    text = (
        "📖 *Инструкция по подключению*\n\n"
        "1. Скопируй ссылку на подписку из профиля.\n"
        "2. Открой приложение *INCY*.\n"
        "3. Нажми «+» или «Добавить провайдера».\n"
        "4. Вставь ссылку в поле для URL.\n"
        "5. Нажми «Умный автовыбор» и пользуйся!\n\n"
        "Если что-то не работает — пиши в поддержку."
    )
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()