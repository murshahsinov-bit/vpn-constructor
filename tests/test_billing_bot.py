# -*- coding: utf-8 -*-
import json

import pytest

from billing_bot import core
from billing_bot.handler import BillingBot
from billing_bot.worker_client import WorkerError

PLANS = [
    {"id": "m1", "days": 30, "price_rub": 149, "title": "1 месяц", "price_stars": 111},
    {"id": "m3", "days": 90, "price_rub": 349, "title": "3 месяца", "price_stars": 259},
    {"id": "m12", "days": 365, "price_rub": 990, "title": "12 месяцев", "price_stars": 734},
]

TOKEN = "SVS1.eyJleHAiOjF9.c2ln"


def test_start_text_lists_every_plan_and_trial():
    text = core.start_text(PLANS, 3)

    assert "ShieldVPN" in text
    assert "3 дня" in text
    for plan in PLANS:
        assert plan["title"] in text
        assert f"{plan['price_rub']} ₽" in text


def test_keyboards_route_by_device_and_plan():
    devices = core.device_keyboard("trial")["inline_keyboard"][0]

    assert devices[0]["callback_data"] == "trial:android"
    assert devices[1]["callback_data"] == "trial:ios"

    plans = core.plans_keyboard("ios", PLANS)["inline_keyboard"]
    assert plans[0][0]["callback_data"] == "plan:m1:ios"
    assert "111 ⭐" in plans[0][0]["text"]
    assert plans[-1][0]["callback_data"] == "buy:pick"


def test_callback_parsing_rejects_garbage():
    assert core.parse_callback("trial:android") == ("trial", "android")
    assert core.parse_callback("plan:m1:ios") is None
    assert core.parse_callback("trial") is None
    assert core.parse_plan_callback("plan:m1:ios") == ("m1", "ios")
    assert core.parse_plan_callback("plan:m1:windows") is None
    assert core.parse_callback("unknown:value") is None


def test_payment_payload_roundtrip_and_validation():
    payload = core.payment_payload("m3", "ios", 42)

    assert payload == "v1|m3|ios|42"
    assert core.parse_payment_payload(payload) == ("m3", "ios", 42)
    assert core.parse_payment_payload("v2|m3|ios|42") is None
    assert core.parse_payment_payload("v1|m3|windows|42") is None
    assert core.parse_payment_payload("v1|m3|ios|abc") is None
    assert core.parse_payment_payload("") is None


def test_license_text_differs_for_android_and_ios():
    android = core.license_text(
        "android", TOKEN, "https://example.test", "2026-12-01", 30, "apk", "happ", "incy"
    )
    ios = core.license_text(
        "ios", TOKEN, "https://example.test", "2026-12-01", 30, "apk", "happ", "incy"
    )

    assert "/activate/" in android
    assert "/sub/auto_happ.txt?token=" in android
    assert "/sub/incy.txt?token=" in ios
    assert "Happ" in ios


# --------------------------------------------------------------------- handler


class FakeWorker:
    def __init__(self) -> None:
        self.trial_calls: list[tuple[str, str]] = []
        self.issue_calls: list[tuple[str, str]] = []
        self.license_calls: list[str] = []
        self.trial_error: WorkerError | None = None

    def plans(self):
        return {"currency": "RUB", "trial_days": 3, "plans": PLANS}

    def trial(self, device, device_id):
        self.trial_calls.append((device, device_id))
        if self.trial_error:
            raise self.trial_error
        return _activation("trial", device)

    def issue(self, plan_id, device):
        self.issue_calls.append((plan_id, device))
        return _activation(plan_id, device)

    def license_info(self, token):
        self.license_calls.append(token)
        return _activation("m1", "android")


def _activation(plan: str, device: str) -> dict:
    return {
        "valid": True,
        "plan": plan,
        "device": device,
        "expires_on": "2026-12-19",
        "days_left": 30,
        "subscription_url": f"https://example.test/sub/auto_happ.txt?token={TOKEN}",
        "ios_url": f"https://example.test/sub/incy.txt?token={TOKEN}",
    }


class RecordingBot(BillingBot):
    def __init__(self, worker: FakeWorker, tmp_path) -> None:
        super().__init__(
            token="123:abc",
            worker=worker,  # type: ignore[arg-type]
            public_base_url="https://example.test",
            apk_url="https://example.test/app.apk",
            happ_url="https://happ.su",
            incy_url="https://incy.app",
            processed_path=tmp_path / "payments.json",
        )
        self.sent: list[tuple[int, str, dict | None]] = []
        self.other: list[tuple[str, dict]] = []

    def api(self, method, payload):
        if method == "sendMessage":
            self.sent.append((payload["chat_id"], payload["text"], payload.get("reply_markup")))
            return {"message_id": 1}
        if method == "editMessageText":
            self.sent.append((payload["chat_id"], payload["text"], payload.get("reply_markup")))
            return True
        self.other.append((method, payload))
        return True

    def texts(self) -> str:
        return "\n".join(text for _chat, text, _kb in self.sent)


def message_update(text: str, chat_id: int = 7, user_id: int = 42) -> dict:
    return {
        "message": {
            "message_id": 10,
            "chat": {"id": chat_id},
            "from": {"id": user_id},
            "text": text,
        }
    }


def callback_update(data: str, chat_id: int = 7, user_id: int = 42) -> dict:
    return {
        "callback_query": {
            "id": "cb-1",
            "from": {"id": user_id},
            "data": data,
            "message": {"message_id": 10, "chat": {"id": chat_id}},
        }
    }


def test_start_shows_menu_without_network(tmp_path):
    bot = RecordingBot(FakeWorker(), tmp_path)

    bot.handle_update(message_update("/start"))

    assert "тарифы" in bot.texts().lower() or "Тарифы" in bot.texts()
    assert bot.sent[0][2] is not None


def test_trial_issues_license_once_per_telegram_account(tmp_path):
    worker = FakeWorker()
    bot = RecordingBot(worker, tmp_path)

    bot.handle_update(callback_update("trial:android"))

    assert worker.trial_calls == [("android", "tg-42-android")]
    assert "/activate/" in bot.texts()

    worker.trial_error = WorkerError("trial_already_used", status=409)
    bot.handle_update(callback_update("trial:android"))
    assert "уже использован" in bot.texts()


def test_buy_plan_sends_stars_invoice(tmp_path):
    bot = RecordingBot(FakeWorker(), tmp_path)

    bot.handle_update(callback_update("plan:m3:ios"))

    invoice = next(payload for method, payload in bot.other if method == "sendInvoice")
    assert invoice["currency"] == "XTR"
    assert invoice["prices"] == [{"label": "3 месяца", "amount": 259}]
    assert invoice["payload"] == "v1|m3|ios|7"


def test_pre_checkout_accepts_known_plan_only(tmp_path):
    bot = RecordingBot(FakeWorker(), tmp_path)

    bot.handle_update(
        {"pre_checkout_query": {"id": "q1", "invoice_payload": "v1|m1:android|android|7"}}
    )
    bot.handle_update(
        {"pre_checkout_query": {"id": "q2", "invoice_payload": "v1|m1|android|7"}}
    )

    answers = [payload for method, payload in bot.other if method == "answerPreCheckoutQuery"]
    assert answers[0]["ok"] is False
    assert answers[1]["ok"] is True


def test_successful_payment_issues_license_idempotently(tmp_path):
    worker = FakeWorker()
    bot = RecordingBot(worker, tmp_path)
    update = {
        "message": {
            "chat": {"id": 7},
            "successful_payment": {
                "telegram_payment_charge_id": "charge-1",
                "invoice_payload": "v1|m12|android|7",
                "total_amount": 734,
                "currency": "XTR",
            },
        }
    }

    bot.handle_update(update)
    bot.handle_update(update)

    assert worker.issue_calls == [("m12", "android")]
    assert "/activate/" in bot.texts()
    saved = json.loads((tmp_path / "payments.json").read_text(encoding="utf-8"))
    assert saved == ["charge-1"]


def test_license_message_lookup(tmp_path):
    worker = FakeWorker()
    bot = RecordingBot(worker, tmp_path)

    bot.handle_update(message_update(f"Вот моя ссылка https://example.test/activate/{TOKEN}"))

    assert worker.license_calls == [TOKEN]
    assert "Подписка активна" in bot.texts()


def test_help_and_unknown_commands(tmp_path):
    bot = RecordingBot(FakeWorker(), tmp_path)

    bot.handle_update(callback_update("help:ios"))
    assert "Happ" in bot.texts()

    bot.handle_update(message_update("привет"))
    assert "/buy" in bot.texts()
