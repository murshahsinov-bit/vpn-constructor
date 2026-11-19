# -*- coding: utf-8 -*-
"""Тарифы ShieldVPN в рублях и их эквивалент в Telegram Stars."""

from __future__ import annotations

import math
import os

CURRENCY = "RUB"

#: Сколько рублей стоит один Telegram Star при отображении цены.
#: Курс меняется, поэтому вынесен в env.
STAR_RUB_RATE_DEFAULT = 1.35

#: Тарифы. Цены намеренно низкие: это массовый продукт для РФ.
PLANS: tuple[dict[str, object], ...] = (
    {"id": "m1", "days": 30, "price_rub": 149, "title": "1 месяц"},
    {"id": "m3", "days": 90, "price_rub": 349, "title": "3 месяца"},
    {"id": "m12", "days": 365, "price_rub": 990, "title": "12 месяцев"},
)

PLAN_IDS = {str(plan["id"]) for plan in PLANS}


def star_rate() -> float:
    raw = os.getenv("STAR_RUB_RATE", "").strip()
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return STAR_RUB_RATE_DEFAULT
    return rate if rate > 0 else STAR_RUB_RATE_DEFAULT


def stars_for_rub(price_rub: int) -> int:
    """Цена в Stars: округляем вверх, минимум 1 звезда."""
    return max(1, math.ceil(int(price_rub) / star_rate()))


def trial_days() -> int:
    raw = os.getenv("TRIAL_DAYS", "").strip()
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return 3
    return min(max(days, 1), 14)


def plan_by_id(plan_id: str) -> dict[str, object] | None:
    for plan in PLANS:
        if plan["id"] == plan_id:
            return plan
    return None


def plans_payload() -> dict[str, object]:
    return {
        "currency": CURRENCY,
        "trial_days": trial_days(),
        "star_rub_rate": star_rate(),
        "plans": [
            {
                **plan,
                "price_stars": stars_for_rub(int(plan["price_rub"])),
            }
            for plan in PLANS
        ],
    }
