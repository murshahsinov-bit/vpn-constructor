# -*- coding: utf-8 -*-
"""HTTP-клиент к воркеру подписок.

Бот не подписывает лицензии сам: единственный владелец `LICENSE_SECRET` — воркер.
Бот лишь просит у него тарифы, триал и платные лицензии, поэтому секрет не нужно
копировать в ещё один сервис, а сроки и лимиты всегда совпадают с тем, что видит
приложение.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class WorkerError(RuntimeError):
    def __init__(self, message: str, status: int = 0, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class WorkerClient:
    def __init__(self, base_url: str, admin_token: str, timeout: float = 12.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "User-Agent": "shieldvpn-billing-bot/1.0",
                **({"Content-Type": "application/json"} if data else {}),
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw or "{}")
            except ValueError:
                payload = {"error": raw.strip()[:200]}
            raise WorkerError(
                str(payload.get("error") or payload.get("message") or f"HTTP {exc.code}"),
                status=exc.code,
                payload=payload,
            ) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise WorkerError(f"worker is unreachable: {exc}") from exc

    def plans(self) -> dict[str, Any]:
        return self._request("GET", "/api/plans")

    def trial(self, device: str, device_id: str) -> dict[str, Any]:
        return self._request("POST", "/api/trial", {"device": device, "device_id": device_id})

    def issue(self, plan_id: str, device: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/admin/issue",
            {"plan": plan_id, "device": device},
            {"X-Admin-Token": self.admin_token},
        )

    def license_info(self, token: str) -> dict[str, Any]:
        return self._request("GET", f"/api/license?token={token}")
