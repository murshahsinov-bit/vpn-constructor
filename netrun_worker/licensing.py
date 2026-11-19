# -*- coding: utf-8 -*-
"""
Подписанные лицензии ShieldVPN.

Формат: ``SVS1.<base64url(payload)>.<base64url(hmac_sha256)>``.

Лицензия самодостаточна: воркеру не нужна база данных, чтобы понять, кому и до
какого срока отдавать подписку. Секрет знают только воркер и бот продаж, поэтому
клиент не может продлить себе срок или сменить тариф.

Payload:
    v    — версия схемы (1);
    sub  — идентификатор подписки (короткий, не PII);
    plan — trial | m1 | m3 | m12;
    dev  — android | ios | any;
    iat  — выдача, Unix time;
    exp  — окончание, Unix time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

PREFIX = "SVS1"
MAX_TOKEN_LENGTH = 1024

PLAN_TRIAL = "trial"


class LicenseError(ValueError):
    """Лицензия отсутствует, повреждена, подделана или истекла."""


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _signature(secret: str, body: str) -> bytes:
    return hmac.new(
        secret.encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).digest()


def sign_license(secret: str, payload: dict[str, Any]) -> str:
    """Подписывает payload и возвращает компактный токен лицензии."""
    if not secret:
        raise LicenseError("license secret is not configured")
    body = b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{PREFIX}.{body}.{b64url_encode(_signature(secret, body))}"


def issue_license(
    secret: str,
    *,
    sub: str,
    plan: str,
    device: str = "any",
    days: int,
    now: int | None = None,
) -> str:
    """Выдаёт лицензию на `days` дней от текущего момента."""
    issued = int(time.time() if now is None else now)
    return sign_license(
        secret,
        {
            "v": 1,
            "sub": sub,
            "plan": plan,
            "dev": device,
            "iat": issued,
            "exp": issued + max(1, int(days)) * 86_400,
        },
    )


def verify_license(secret: str, token: str, now: int | None = None) -> dict[str, Any]:
    """
    Проверяет подпись и срок. Бросает `LicenseError`, если лицензия не годится.
    Возвращает payload.
    """
    if not secret:
        raise LicenseError("license secret is not configured")
    value = (token or "").strip()
    if not value or len(value) > MAX_TOKEN_LENGTH:
        raise LicenseError("empty or oversized license")

    parts = value.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("unsupported license format")

    body = parts[1]
    expected = _signature(secret, body)
    try:
        given = b64url_decode(parts[2])
    except (ValueError, TypeError) as exc:
        raise LicenseError("broken signature encoding") from exc
    if not hmac.compare_digest(expected, given):
        raise LicenseError("bad signature")

    try:
        payload = json.loads(b64url_decode(body))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise LicenseError("broken payload") from exc
    if not isinstance(payload, dict):
        raise LicenseError("payload is not an object")

    expires = payload.get("exp")
    issued = payload.get("iat")
    if not isinstance(expires, int) or not isinstance(issued, int):
        raise LicenseError("payload has no validity window")
    if expires <= int(time.time() if now is None else now):
        raise LicenseError("license expired")
    if payload.get("v") != 1:
        raise LicenseError("unsupported license version")
    return payload


def lookalike(token: str) -> bool:
    """Быстрая проверка, что строка похожа на лицензию (без секрета)."""
    value = (token or "").strip()
    return len(value) <= MAX_TOKEN_LENGTH and value.startswith(PREFIX + ".") and value.count(".") == 2
