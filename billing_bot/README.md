# ShieldVPN Billing Bot

Telegram-бот продаж: пробный период, тарифы в рублях и оплата звёздами
Telegram (XTR). Приложение, сайт и бот берут цены из одного места — воркера
подписок (`GET /api/plans`), поэтому рассинхронизировать их нельзя.

## Что умеет

| Действие | Что происходит |
| --- | --- |
| `/start` | Тарифы, кнопки «Пробный период», «Купить», «Как подключиться» |
| «Пробный период» | Выбор Android/iPhone → `POST /api/trial` → ссылка активации |
| «Купить» | Выбор устройства → тариф → счёт в Stars → лицензия |
| Ссылка/код `SVS1…` | Бот проверяет лицензию и повторно присылает ссылки |
| `/help` | Инструкция для Android (APK) и iOS (Happ/INCY) |

Бот не хранит секрет подписи: лицензии подписывает воркер, бот получает их
через `POST /api/admin/issue` с `X-Admin-Token`.

## Запуск

```bash
export BOT_TOKEN=...          # @BotFather
export ADMIN_TOKEN=...        # тот же, что ADMIN_TOKEN воркера
export PUBLIC_BASE_URL=https://vpn-auth.de1.netrun.io
python -m billing_bot.handler
```

или

```bash
docker build -f billing_bot/Dockerfile -t shieldvpn-bot .
docker run --env-file billing_bot/.env shieldvpn-bot
```

Полный список переменных — в `.env.example`.

## Оплата

Telegram Stars не требуют юрлица, эквайринга и модерации магазина: счёт
создаётся методом `sendInvoice` с `currency: "XTR"` и `provider_token` не
передаётся. После `successful_payment` бот выдаёт лицензию; номер платежа
запоминается в `PAYMENTS_FILE`, поэтому повторный апдейт не выдаст вторую
лицензию.

Чтобы принимать Stars, включите Payments в @BotFather и проверьте, что бот не
в тестовом режиме.

## Цены

Меняются в одном файле: `netrun_worker/plans.py`. Курс рубля к звезде —
переменная `STAR_RUB_RATE` воркера (по умолчанию 1.35 ₽ за звезду). После
изменения перезапустите воркер: бот подхватит новые цены в течение часа или
сразу при открытии «Купить».

## Тесты

```bash
python -m pytest tests/test_billing_bot.py -q
```
