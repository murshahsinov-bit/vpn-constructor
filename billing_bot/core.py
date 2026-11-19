# -*- coding: utf-8 -*-
"""Чистая логика бота: клавиатуры, callback-и и тексты.

Здесь нет сети и Telegram API — всё это можно покрыть обычными unit-тестами.
Тарифы приходят снаружи (из воркера через `/api/plans`), чтобы цены в боте, на
сайте и в приложении нельзя было рассинхронизировать.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping
from urllib.parse import quote

DEVICE_ANDROID = "android"
DEVICE_IOS = "ios"
DEVICES = (DEVICE_ANDROID, DEVICE_IOS)

Plan = Mapping[str, Any]


def device_title(device: str) -> str:
    return "Android" if device == DEVICE_ANDROID else "iPhone / iPad"


def activation_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/activate/{quote(token, safe='')}"


def subscription_url(base_url: str, token: str, device: str) -> str:
    path = "incy.txt" if device == DEVICE_IOS else "auto_happ.txt"
    return f"{base_url.rstrip('/')}/sub/{path}?token={quote(token, safe='')}"


def format_price(price_rub: int) -> str:
    return f"{int(price_rub)} ₽"


def plan_button_text(plan: Plan) -> str:
    return (
        f"{plan['title']} — {format_price(int(plan['price_rub']))} "
        f"({int(plan.get('price_stars') or 0)} ⭐)"
    )


def plan_by_id(plans: Iterable[Plan], plan_id: str) -> Plan | None:
    for plan in plans:
        if str(plan.get("id")) == plan_id:
            return plan
    return None


def start_text(plans: Iterable[Plan], trial_days: int) -> str:
    prices = "\n".join(
        f"• {plan['title']} — <b>{format_price(int(plan['price_rub']))}</b>"
        for plan in plans
    )
    return (
        "🛡 <b>ShieldVPN</b> — быстрый VPN с обходом DPI для YouTube.\n\n"
        f"🎁 Пробный период: <b>{trial_days} дня</b> бесплатно, один раз на устройство.\n\n"
        f"Тарифы:\n{prices}\n\n"
        "Выберите, что нужно:"
    )


def main_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "🎁 Пробный период", "callback_data": "trial:pick"},
                {"text": "💳 Купить подписку", "callback_data": "buy:pick"},
            ],
            [
                {"text": "📱 Как подключиться", "callback_data": "help:pick"},
            ],
        ]
    }


def device_keyboard(action: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "🤖 Android", "callback_data": f"{action}:{DEVICE_ANDROID}"},
                {"text": "🍏 iPhone / iPad", "callback_data": f"{action}:{DEVICE_IOS}"},
            ],
            [{"text": "← Назад", "callback_data": "menu"}],
        ]
    }


def plans_keyboard(device: str, plans: Iterable[Plan]) -> dict[str, Any]:
    rows = [
        [{"text": plan_button_text(plan), "callback_data": f"plan:{plan['id']}:{device}"}]
        for plan in plans
    ]
    rows.append([{"text": "← Назад", "callback_data": "buy:pick"}])
    return {"inline_keyboard": rows}


def trial_used_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "💳 Купить подписку", "callback_data": "buy:pick"}],
            [{"text": "← В меню", "callback_data": "menu"}],
        ]
    }


def parse_callback(data: str) -> tuple[str, str] | None:
    """'trial:android' → ('trial', 'android'); неизвестное — None."""
    parts = (data or "").split(":")
    if len(parts) != 2:
        return None
    action, value = parts
    if action in ("trial", "buy", "help"):
        return action, value
    return None


def parse_plan_callback(data: str) -> tuple[str, str] | None:
    """'plan:m3:ios' → ('m3', 'ios')."""
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != "plan":
        return None
    _, plan_id, device = parts
    if device not in DEVICES or not plan_id:
        return None
    return plan_id, device


def payment_payload(plan_id: str, device: str, user_id: int) -> str:
    return f"v1|{plan_id}|{device}|{int(user_id)}"


def parse_payment_payload(payload: str) -> tuple[str, str, int] | None:
    parts = (payload or "").split("|")
    if len(parts) != 4 or parts[0] != "v1":
        return None
    _, plan_id, device, raw_user = parts
    if not plan_id or device not in DEVICES:
        return None
    try:
        user_id = int(raw_user)
    except ValueError:
        return None
    return plan_id, device, user_id


def license_text(
    device: str,
    token: str,
    base_url: str,
    expires_on: str,
    days_left: int,
    apk_url: str,
    happ_url: str,
    incy_url: str,
) -> str:
    activate = activation_url(base_url, token)
    sub = subscription_url(base_url, token, device)
    if device == DEVICE_ANDROID:
        app_link = (
            "1. Установите приложение ShieldVPN:\n"
            f"{apk_url}\n\n"
            "2. Откройте его и на экране активации вставьте эту ссылку:\n"
            f"<code>{activate}</code>\n\n"
            "Приложение само подтянет серверы и включит обход DPI для YouTube."
        )
        extra = (
            "\n\nЕсли хотите подключиться через Happ, добавьте подписку:\n"
            f"<code>{sub}</code>"
        )
    else:
        app_link = (
            "На iPhone подписка работает через Happ или INCY:\n\n"
            f"• Happ: <code>{sub}</code>\n"
            f"• INCY: <code>{sub}</code>\n\n"
            f"Скачать Happ: {happ_url}\n"
            f"Скачать INCY: {incy_url}"
        )
        extra = (
            "\n\nСтраница активации (если нужно скопировать ссылку ещё раз):\n"
            f"{activate}"
        )

    return (
        f"✅ Подписка активна до <b>{expires_on}</b> (осталось {days_left} дн.).\n\n"
        f"{app_link}{extra}\n\n"
        "Сохраните это сообщение: по нему можно восстановить доступ."
    )


def help_text(device: str, apk_url: str, happ_url: str, incy_url: str) -> str:
    if device == DEVICE_ANDROID:
        return (
            "🤖 <b>Android</b>\n\n"
            "1. Скачайте APK:\n"
            f"{apk_url}\n"
            "2. Разрешите установку из неизвестных источников.\n"
            "3. Откройте ShieldVPN и вставьте ссылку активации из бота.\n"
            "4. Нажмите «Подключиться» и разрешите VPN.\n\n"
            "Альтернатива — Happ:\n"
            f"{happ_url}"
        )
    return (
        "🍏 <b>iPhone / iPad</b>\n\n"
        "1. Установите Happ или INCY.\n"
        f"Happ: {happ_url}\n"
        f"INCY: {incy_url}\n"
        "2. Скопируйте ссылку подписки из бота.\n"
        "3. В приложении выберите «Добавить подписку» и вставьте ссылку.\n"
        "4. Подключитесь к ближайшему серверу."
    )
