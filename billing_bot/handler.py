# -*- coding: utf-8 -*-
"""Telegram-бот продаж ShieldVPN.

Работает на длинном опросе `getUpdates`: отдельный сервер, вебхук и домен не
нужны, а на Netrun/Railway хватает одного процесса. Оплата — Telegram Stars
(currency ``XTR``): в РФ это единственный платёжный путь, который не требует
юрлица, эквайринга и проверки магазина приложений.

Поток:
    /start → «Пробный период» или «Купить» → Android / iPhone → тариф →
    счёт в Stars → `successful_payment` → лицензия из воркера → сообщение со
    ссылкой активации.

Тарифы и лицензии выдаёт воркер: у бота нет ни `LICENSE_SECRET`, ни своей базы.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:  # запуск как пакет: python -m billing_bot.handler
    from .core import (
        DEVICE_ANDROID,
        DEVICE_IOS,
        device_keyboard,
        device_title,
        help_text,
        license_text,
        main_keyboard,
        parse_callback,
        parse_payment_payload,
        parse_plan_callback,
        payment_payload,
        plan_by_id,
        plans_keyboard,
        start_text,
        trial_used_keyboard,
    )
    from .worker_client import WorkerClient, WorkerError
except ImportError:  # запуск как скрипт: python billing_bot/handler.py
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from core import (  # type: ignore[no-redef]
        DEVICE_ANDROID,
        DEVICE_IOS,
        device_keyboard,
        device_title,
        help_text,
        license_text,
        main_keyboard,
        parse_callback,
        parse_payment_payload,
        parse_plan_callback,
        payment_payload,
        plan_by_id,
        plans_keyboard,
        start_text,
        trial_used_keyboard,
    )
    from worker_client import WorkerClient, WorkerError  # type: ignore[no-redef]

logger = logging.getLogger("shieldvpn.billing_bot")

TELEGRAM_API = "https://api.telegram.org"
LICENSE_RE = re.compile(r"SVS1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

#: Тарифы, если воркер ещё не ответил (сразу после старта).
FALLBACK_PLANS: tuple[dict[str, Any], ...] = (
    {"id": "m1", "days": 30, "price_rub": 149, "title": "1 месяц", "price_stars": 111},
    {"id": "m3", "days": 90, "price_rub": 349, "title": "3 месяца", "price_stars": 259},
    {"id": "m12", "days": 365, "price_rub": 990, "title": "12 месяцев", "price_stars": 734},
)


class TelegramError(RuntimeError):
    pass


class BillingBot:
    def __init__(
        self,
        token: str,
        worker: WorkerClient,
        public_base_url: str,
        apk_url: str,
        happ_url: str,
        incy_url: str,
        support_url: str = "",
        processed_path: Path | None = None,
    ) -> None:
        self.token = token
        self.worker = worker
        self.public_base_url = public_base_url.rstrip("/")
        self.apk_url = apk_url
        self.happ_url = happ_url
        self.incy_url = incy_url
        self.support_url = support_url
        self.processed_path = processed_path
        self.plans: list[dict[str, Any]] = [dict(plan) for plan in FALLBACK_PLANS]
        self.trial_days = 3
        self._plans_fetched_at = 0.0
        self._processed: set[str] = set()
        self._load_processed()

    # ------------------------------------------------------------------ API

    def api(self, method: str, payload: dict[str, Any]) -> Any:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{TELEGRAM_API}/bot{self.token}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # сеть/HTTP: Telegram вернёт ошибку в теле
            raise TelegramError(f"{method}: {exc}") from exc
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description')}")
        return body.get("result")

    # ------------------------------------------------------------------ plans

    def refresh_plans(self, force: bool = False) -> None:
        if not force and time.time() - self._plans_fetched_at < 3600:
            return
        try:
            payload = self.worker.plans()
        except WorkerError as exc:
            logger.warning("тарифы не получены, работаю на локальной копии: %s", exc)
            return
        plans = payload.get("plans")
        if isinstance(plans, list) and plans:
            self.plans = [plan for plan in plans if isinstance(plan, dict)]
            self.trial_days = int(payload.get("trial_days") or 3)
            self._plans_fetched_at = time.time()

    def plan(self, plan_id: str) -> dict[str, Any] | None:
        found = plan_by_id(self.plans, plan_id)
        return dict(found) if found else None

    # ------------------------------------------------------------- idempotency

    def _load_processed(self) -> None:
        if not self.processed_path or not self.processed_path.exists():
            return
        try:
            data = json.loads(self.processed_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, list):
            self._processed = {str(item) for item in data}

    def _mark_processed(self, charge_id: str) -> bool:
        """True — платёж ещё не обрабатывался."""
        if not charge_id or charge_id in self._processed:
            return False
        self._processed.add(charge_id)
        if self.processed_path:
            try:
                self.processed_path.parent.mkdir(parents=True, exist_ok=True)
                self.processed_path.write_text(
                    json.dumps(sorted(self._processed)), encoding="utf-8"
                )
            except OSError as exc:
                logger.warning("не удалось сохранить список платежей: %s", exc)
        return True

    # ---------------------------------------------------------------- polling

    def run(self) -> None:
        self.refresh_plans(force=True)
        offset = 0
        logger.info("бот запущен, ожидаю сообщения")
        while True:
            try:
                result = self.api(
                    "getUpdates",
                    {
                        "offset": offset,
                        "timeout": 25,
                        "allowed_updates": [
                            "message",
                            "callback_query",
                            "pre_checkout_query",
                        ],
                    },
                )
            except TelegramError as exc:
                logger.warning("getUpdates: %s", exc)
                time.sleep(3)
                continue

            updates = result if isinstance(result, list) else []
            for update in updates:
                offset = int(update.get("update_id", offset)) + 1
                try:
                    self.handle_update(update)
                except Exception:  # один битый апдейт не должен ронять бота
                    logger.exception("update %s failed", update.get("update_id"))

    # ------------------------------------------------------------------ router

    def handle_update(self, update: dict[str, Any]) -> None:
        if "pre_checkout_query" in update:
            self.on_pre_checkout(update["pre_checkout_query"])
            return
        if "callback_query" in update:
            self.on_callback(update["callback_query"])
            return
        message = update.get("message") or {}
        if not message:
            return
        if message.get("successful_payment"):
            self.on_successful_payment(message)
            return
        self.on_message(message)

    # ------------------------------------------------------------------ texts

    def _send(
        self,
        chat_id: int,
        text: str,
        keyboard: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        self.api("sendMessage", payload)

    def _menu_text(self) -> str:
        return start_text(self.plans, self.trial_days)

    # --------------------------------------------------------------- messages

    def on_message(self, message: dict[str, Any]) -> None:
        chat_id = int((message.get("chat") or {}).get("id") or 0)
        if not chat_id:
            return
        text = str(message.get("text") or "").strip()
        lowered = text.lower()

        if lowered.startswith("/start") or lowered.startswith("/menu"):
            self._send(chat_id, self._menu_text(), main_keyboard())
            return
        if lowered.startswith("/help"):
            self._send(chat_id, "Выберите устройство:", device_keyboard("help"))
            return
        if lowered.startswith("/buy") or lowered.startswith("/subscribe"):
            self._send(chat_id, "Выберите устройство:", device_keyboard("buy"))
            return
        if LICENSE_RE.search(text):
            self.on_license_text(chat_id, text)
            return

        self._send(
            chat_id,
            "Я помогу оформить подписку ShieldVPN.\n\n"
            "• /start — меню и тарифы\n"
            "• /buy — купить подписку\n"
            "• /help — как подключиться\n\n"
            "Если у вас уже есть ссылка активации, просто отправьте её сообщением.",
            main_keyboard(),
        )

    def on_license_text(self, chat_id: int, text: str) -> None:
        match = LICENSE_RE.search(text or "")
        if not match:
            self._send(chat_id, "Не нашёл код в сообщении. Пришлите ссылку целиком.")
            return
        token = match.group(0)
        try:
            info = self.worker.license_info(token)
        except WorkerError as exc:
            if exc.status == 403:
                self._send(chat_id, "Эта лицензия недействительна или истекла.")
            else:
                self._send(chat_id, "Сервис подписок недоступен, попробуйте позже.")
            logger.info("license lookup failed: %s", exc)
            return
        device = str(info.get("device") or DEVICE_ANDROID)
        if device not in (DEVICE_ANDROID, DEVICE_IOS):
            device = DEVICE_ANDROID
        self._send_license(chat_id, token, info, device)

    # -------------------------------------------------------------- callbacks

    def on_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback.get("id") or "")
        message = callback.get("message") or {}
        chat_id = int((message.get("chat") or {}).get("id") or 0)
        user_id = int((callback.get("from") or {}).get("id") or 0)
        data = str(callback.get("data") or "")

        if callback_id:
            self.api("answerCallbackQuery", {"callback_query_id": callback_id})
        if not chat_id:
            return

        if data == "menu":
            self._replace(chat_id, message, self._menu_text(), main_keyboard())
            return

        plan_pick = parse_plan_callback(data)
        if plan_pick is not None:
            self.on_plan(chat_id, *plan_pick)
            return

        parsed = parse_callback(data)
        if parsed is None:
            self._send(chat_id, "Кнопка устарела, откройте меню заново.", main_keyboard())
            return
        action, value = parsed

        if action == "trial" and value == "pick":
            self._send(
                chat_id,
                f"Пробный период на {self.trial_days} дня — бесплатно.\n"
                "Выберите устройство:",
                device_keyboard("trial"),
            )
            return
        if action == "trial" and value in (DEVICE_ANDROID, DEVICE_IOS):
            self.on_trial(chat_id, user_id, value)
            return
        if action == "buy" and value == "pick":
            self._send(chat_id, "Выберите устройство:", device_keyboard("buy"))
            return
        if action == "buy" and value in (DEVICE_ANDROID, DEVICE_IOS):
            self.refresh_plans()
            self._send(
                chat_id,
                f"<b>{device_title(value)}</b>\n\nВыберите тариф. "
                "Оплата — звёздами Telegram, карта не нужна.",
                plans_keyboard(value, self.plans),
            )
            return
        if action == "help" and value == "pick":
            self._send(chat_id, "Выберите устройство:", device_keyboard("help"))
            return
        if action == "help" and value in (DEVICE_ANDROID, DEVICE_IOS):
            self._send(
                chat_id,
                help_text(value, self.apk_url, self.happ_url, self.incy_url),
                main_keyboard(),
            )
            return

        self._send(chat_id, self._menu_text(), main_keyboard())

    def _replace(
        self,
        chat_id: int,
        message: dict[str, Any],
        text: str,
        keyboard: dict[str, Any],
    ) -> None:
        message_id = int(message.get("message_id") or 0)
        if not message_id:
            self._send(chat_id, text, keyboard)
            return
        try:
            self.api(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": keyboard,
                },
            )
        except TelegramError:
            self._send(chat_id, text, keyboard)

    # ------------------------------------------------------------------ trial

    def on_trial(self, chat_id: int, user_id: int, device: str) -> None:
        if not user_id:
            self._send(chat_id, "Не удалось определить аккаунт, попробуйте ещё раз.")
            return
        device_id = f"tg-{user_id}-{device}"
        try:
            info = self.worker.trial(device, device_id)
        except WorkerError as exc:
            if exc.status == 409:
                self._send(
                    chat_id,
                    "Пробный период уже использован на этом аккаунте.\n\n"
                    "Подписка стоит от 149 ₽ в месяц.",
                    trial_used_keyboard(),
                )
            else:
                self._send(
                    chat_id, "Не получилось выдать пробный период. Попробуйте позже."
                )
            logger.info("trial отказан: %s", exc)
            return

        token = _token_from(info)
        if not token:
            self._send(chat_id, "Сервис вернул некорректный ответ, попробуйте позже.")
            logger.error("trial без лицензии в ответе: %s", info)
            return
        self._send_license(chat_id, token, info, device)

    # ------------------------------------------------------------------- plan

    def on_plan(self, chat_id: int, plan_id: str, device: str) -> None:
        self.refresh_plans()
        plan = self.plan(plan_id)
        if plan is None:
            self._send(chat_id, "Тариф не найден, откройте меню заново.", main_keyboard())
            return
        stars = int(plan.get("price_stars") or 1)
        self.api(
            "sendInvoice",
            {
                "chat_id": chat_id,
                "title": f"ShieldVPN — {plan['title']}",
                "description": (
                    f"Доступ на {plan['days']} дней для {device_title(device)}. "
                    "Обход DPI для YouTube и автовыбор серверов."
                ),
                "payload": payment_payload(plan_id, device, chat_id),
                "currency": "XTR",
                "prices": [{"label": str(plan["title"]), "amount": stars}],
                "reply_markup": {
                    "inline_keyboard": [[{"text": "← Назад", "callback_data": "buy:pick"}]]
                },
            },
        )

    # --------------------------------------------------------------- payments

    def on_pre_checkout(self, query: dict[str, Any]) -> None:
        query_id = str(query.get("id") or "")
        payload = parse_payment_payload(str(query.get("invoice_payload") or ""))
        ok = payload is not None and self.plan(payload[0]) is not None
        body: dict[str, Any] = {"pre_checkout_query_id": query_id, "ok": ok}
        if not ok:
            body["error_message"] = "Тариф устарел, откройте меню заново."
        self.api("answerPreCheckoutQuery", body)

    def on_successful_payment(self, message: dict[str, Any]) -> None:
        chat_id = int((message.get("chat") or {}).get("id") or 0)
        payment = message.get("successful_payment") or {}
        charge_id = str(payment.get("telegram_payment_charge_id") or "")
        payload = parse_payment_payload(str(payment.get("invoice_payload") or ""))
        if not payload or not chat_id:
            logger.warning("платёж без валидного payload: %s", charge_id)
            return
        if not self._mark_processed(charge_id):
            logger.info("платёж %s уже обработан", charge_id)
            return

        plan_id, device, _user_id = payload
        try:
            info = self.worker.issue(plan_id, device)
        except WorkerError as exc:
            logger.error("не удалось выдать лицензию за платёж %s: %s", charge_id, exc)
            support = (
                f"\nПоддержка: {html.escape(self.support_url)}" if self.support_url else ""
            )
            self._send(
                chat_id,
                "Оплата получена, но выдача подвисла. Напишите в поддержку."
                f"{support}\nНомер платежа: <code>{html.escape(charge_id)}</code>",
            )
            return

        token = _token_from(info)
        if not token:
            logger.error("воркер не вернул лицензию за платёж %s", charge_id)
            self._send(
                chat_id,
                "Оплата получена, но лицензия не сформировалась. "
                f"Номер платежа: <code>{html.escape(charge_id)}</code>",
            )
            return

        self._send_license(chat_id, token, info, device)
        logger.info(
            "оплата: plan=%s device=%s stars=%s expires=%s",
            plan_id,
            device,
            str(payment.get("total_amount") or ""),
            str(info.get("expires_on") or ""),
        )

    # ----------------------------------------------------------------- output

    def _send_license(
        self,
        chat_id: int,
        token: str,
        info: dict[str, Any],
        device: str,
    ) -> None:
        text = license_text(
            device=device,
            token=token,
            base_url=self.public_base_url,
            expires_on=str(info.get("expires_on") or ""),
            days_left=int(info.get("days_left") or 0),
            apk_url=self.apk_url,
            happ_url=self.happ_url,
            incy_url=self.incy_url,
        )
        self._send(chat_id, text, main_keyboard())


def _token_from(info: dict[str, Any]) -> str:
    """Лицензия из ответа воркера: поле `token` или параметр в ссылке."""
    direct = str(info.get("token") or "").strip()
    if LICENSE_RE.fullmatch(direct):
        return direct
    for key in ("subscription_url", "ios_url"):
        value = urllib.parse.unquote(str(info.get(key) or ""))
        match = LICENSE_RE.search(value)
        if match:
            return match.group(0)
    return ""


def build_bot_from_env() -> BillingBot:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан")
    admin_token = os.getenv("ADMIN_TOKEN", "").strip()
    if not admin_token:
        raise SystemExit("ADMIN_TOKEN не задан: бот не сможет выдавать лицензии")
    base_url = os.getenv("PUBLIC_BASE_URL", "https://vpn-auth.de1.netrun.io").strip()
    return BillingBot(
        token=token,
        worker=WorkerClient(base_url, admin_token),
        public_base_url=base_url,
        apk_url=os.getenv(
            "APK_URL",
            "https://github.com/murshahsinov-bit/vpn-constructor/releases/latest",
        ),
        happ_url=os.getenv("HAPP_ANDROID_URL", "https://happ.su"),
        incy_url=os.getenv("INCY_URL", "https://happ.su"),
        support_url=os.getenv("SUPPORT_URL", ""),
        processed_path=Path(
            os.getenv(
                "PAYMENTS_FILE",
                str(Path(__file__).resolve().parent / "data" / "payments.json"),
            )
        ),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    build_bot_from_env().run()
