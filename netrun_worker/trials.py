# -*- coding: utf-8 -*-
"""Учёт выданных пробных периодов.

Файл маленький (id устройства → время выдачи; IP → отметки выдач), поэтому
JSON достаточно. Netrun может пересоздать контейнер: если файл недоступен,
учёт остаётся в памяти процесса — триал нельзя получить дважды за один запуск,
а после перезапуска защита слабее. Для продакшена см. DEPLOY_NETRUN.md.

IP ограничиваем не «один триал навсегда» (мобильные операторы сидят за CGNAT),
а несколькими выдачами в сутки: это отсекает массовый перебор, но не ломает
обычных пользователей.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("netrun-worker.trials")

MAX_ENTRIES = 20_000
PRUNE_AFTER_DAYS = 365
IP_DAILY_LIMIT_DEFAULT = 5


class TrialLedger:
    def __init__(self, path: Path | str | None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._devices: dict[str, int] = {}
        self._ips: dict[str, list[int]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None or not self._path.exists():
            return
        try:
            data: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("не удалось прочитать %s: %s", self._path, exc)
            return
        if not isinstance(data, dict):
            return
        self._devices = {
            key: value
            for key, value in (data.get("devices") or {}).items()
            if isinstance(key, str) and isinstance(value, int)
        }
        self._ips = {
            key: [stamp for stamp in value if isinstance(stamp, int)]
            for key, value in (data.get("ips") or {}).items()
            if isinstance(key, str) and isinstance(value, list)
        }

    def _prune(self, now: int) -> None:
        cutoff = now - PRUNE_AFTER_DAYS * 86_400
        self._devices = {k: v for k, v in self._devices.items() if v >= cutoff}
        self._ips = {
            k: [stamp for stamp in stamps if stamp >= cutoff]
            for k, stamps in self._ips.items()
        }
        self._ips = {k: v for k, v in self._ips.items() if v}
        if len(self._devices) > MAX_ENTRIES:
            self._devices = dict(
                sorted(self._devices.items(), key=lambda item: item[1], reverse=True)[
                    :MAX_ENTRIES
                ]
            )

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"devices": self._devices, "ips": self._ips},
                separators=(",", ":"),
                sort_keys=True,
            )
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self._path.parent),
                delete=False,
                suffix=".tmp",
            ) as handle:
                handle.write(payload)
                tmp_name = handle.name
            os.replace(tmp_name, self._path)
        except OSError as exc:
            logger.warning("не удалось сохранить %s: %s", self._path, exc)

    def claim(
        self,
        device_id: str,
        ip_key: str,
        ttl_days: int,
        ip_daily_limit: int = IP_DAILY_LIMIT_DEFAULT,
    ) -> bool:
        """
        True — триал выдан и записан. False — устройство уже получало триал
        за последние `ttl_days`, либо с этого IP сегодня выдач слишком много.
        """
        now = int(time.time())
        cutoff = now - max(1, ttl_days) * 86_400
        day_cutoff = now - 86_400
        with self._lock:
            self._load()
            self._prune(now)
            if self._devices.get(device_id, 0) > cutoff:
                return False
            if ip_key:
                recent = [stamp for stamp in self._ips.get(ip_key, []) if stamp >= day_cutoff]
                if len(recent) >= max(1, ip_daily_limit):
                    return False
                recent.append(now)
                self._ips[ip_key] = recent
            self._devices[device_id] = now
            self._save()
            return True
