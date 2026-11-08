from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class RankedNode:
    """Сервер, прошедший проверку задержки."""
    outbound: dict
    link: str
    delay_ms: int
    status: str = "passed"


def outbound_identity(outbound: dict) -> tuple[str, int, str]:
    """Уникальный ключ сервера: address + port + UUID."""
    vnext = (outbound.get("settings") or {}).get("vnext") or [{}]
    node = vnext[0] if vnext else {}
    users = node.get("users") or [{}]
    user = users[0] if users else {}
    try:
        port = int(node.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    return (
        str(node.get("address", "")).strip().lower(),
        port,
        str(user.get("id", "")).strip(),
    )


def _identity_from_link(link: str) -> tuple[str, int, str]:
    try:
        parsed = urlparse(link.strip())
        return (
            (parsed.hostname or "").strip().lower(),
            int(parsed.port or 443),
            str(parsed.username or "").strip(),
        )
    except (TypeError, ValueError):
        return ("", 0, "")


class XrayKnifeChecker:
    """
    Обёртка над xray-knife (https://github.com/lilendian0x00/xray-knife).

    Запускает реальный Xray-core для каждого конфига и измеряет задержку
    HTTP-запроса через прокси. На выходе — только рабочие серверы,
    отсортированные по возрастанию задержки.
    """

    def __init__(
        self,
        binary: str | None = None,
        threads: int = 50,
        timeout_ms: int = 10000,
        max_delay_ms: int = 8000,
        subprocess_timeout: int = 2400,
    ):
        self.binary = (
            binary
            or os.getenv("XRAY_KNIFE_BIN", "").strip()
            or shutil.which("xray-knife")
        )
        self.threads = max(1, min(50, int(threads)))  # не больше 50 потоков
        self.timeout_ms = max(1000, int(timeout_ms))
        self.max_delay_ms = max(self.timeout_ms, int(max_delay_ms))
        self.subprocess_timeout = max(60, int(subprocess_timeout))
        # True, только если чекер реально отработал и результаты разобраны.
        # Нужно, чтобы отличить «0 живых» от «инструмент не запустился».
        self.last_run_ok = False

    @property
    def available(self) -> bool:
        return bool(self.binary)

    def rank(self, candidates: list[tuple[dict, str]]) -> list[RankedNode]:
        self.last_run_ok = False
        if not candidates:
            return []
        if not self.binary:
            return []

        by_identity = {outbound_identity(ob): (ob, link) for ob, link in candidates}

        with tempfile.TemporaryDirectory(prefix="xray-knife-") as tmp:
            links_path = Path(tmp) / "links.txt"
            results_path = Path(tmp) / "results.json"
            links_path.write_text(
                "\n".join(link for _ob, link in candidates) + "\n",
                encoding="utf-8",
            )

            cmd = [
                self.binary,
                "http",
                "-f", str(links_path),
                "-t", str(self.threads),
                "-o", str(results_path),
                "-x", "json",
                "--sort",
                "--timeout", str(self.timeout_ms),
                "--mdelay", str(self.max_delay_ms),
                "--prescan",
                "--prescan-timeout", "3000",
                "--prescan-workers", "200",
                "--diagnose=false",
            ]

            logger.info(
                "xray-knife: проверяю %d серверов, потоков=%d, timeout=%d ms",
                len(candidates), self.threads, self.timeout_ms,
            )
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.subprocess_timeout,
                    check=False,
                )
            except FileNotFoundError:
                logger.warning("xray-knife не найден: %s", self.binary)
                return []
            except subprocess.TimeoutExpired:
                logger.warning(
                    "xray-knife не уложился в %d секунд, переключаюсь на TCP-fallback",
                    self.subprocess_timeout,
                )
                return []

            # xray-knife возвращает 3 или 4, когда ни один конфиг не прошёл
            # (в разных версиях по-разному). Это не ошибка запуска: файл
            # результатов всё равно создаётся и его нужно разобрать.
            if proc.returncode not in (0, 3, 4):
                logger.warning(
                    "xray-knife завершился с кодом %s: %s",
                    proc.returncode,
                    (proc.stderr or "")[-500:],
                )

            if not results_path.exists():
                logger.warning("xray-knife не создал файл результатов")
                return []

            try:
                raw = json.loads(results_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Не удалось разобрать результаты xray-knife: %s", exc)
                return []

        # С этого момента считаем, что чекер отработал: даже пустой список
        # результатов означает «живых нет», а не «инструмент сломан».
        self.last_run_ok = True

        if isinstance(raw, dict):
            raw = raw.get("results", [])

        ranked: dict[tuple[str, int, str], RankedNode] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "")).strip().lower()
            if status not in ("passed", "semi-passed"):
                continue
            try:
                delay = int(item.get("delay") or 0)
            except (TypeError, ValueError):
                continue
            if delay <= 0:
                continue

            link = str(item.get("link") or item.get("configLink") or "")
            identity = _identity_from_link(link)
            match = by_identity.get(identity)
            if match is None:
                continue

            node = RankedNode(outbound=match[0], link=match[1], delay_ms=delay, status=status)
            previous = ranked.get(identity)
            if previous is None or node.delay_ms < previous.delay_ms:
                ranked[identity] = node

        result = sorted(ranked.values(), key=lambda node: node.delay_ms)
        logger.info("xray-knife: рабочих серверов %d", len(result))
        return result


async def _tcp_probe(host: str, port: int, timeout: float, sem: asyncio.Semaphore) -> int | None:
    start = time.perf_counter()
    try:
        async with sem:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            elapsed = int((time.perf_counter() - start) * 1000)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return elapsed
    except (asyncio.TimeoutError, OSError):
        return None


async def _rank_tcp(
    candidates: list[tuple[dict, str]],
    concurrency: int = 50,
    timeout: float = 5.0,
) -> list[RankedNode]:
    """Резервный режим: TCP RTT до сервера. Не проверяет сам прокси."""
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    tasks = []
    for outbound, _link in candidates:
        host, port, _uuid = outbound_identity(outbound)
        if not host or not port:
            tasks.append(asyncio.sleep(0, result=None))
        else:
            tasks.append(_tcp_probe(host, port, timeout, sem))

    delays = await asyncio.gather(*tasks)
    result = [
        RankedNode(outbound=outbound, link=link, delay_ms=delay, status="tcp")
        for (outbound, link), delay in zip(candidates, delays)
        if delay is not None
    ]
    result.sort(key=lambda node: node.delay_ms)
    logger.info("TCP-fallback: живых серверов %d", len(result))
    return result


async def rank_by_latency(
    candidates: list[tuple[dict, str]],
    config: dict | None = None,
) -> list[RankedNode]:
    """
    Проверяет задержку и возвращает серверы от меньшего пинга к большему.

    Порядок:
      1. SKIP_LATENCY=1 — пропустить проверку (ручная отладка).
      2. xray-knife — реальный HTTP-запрос через прокси.
      3. TCP-fallback — только TCP RTT, если инструмента нет.
    """
    config = config or {}
    if not candidates:
        return []

    if str(os.getenv("SKIP_LATENCY", "")).lower() in ("1", "true", "yes", "on"):
        logger.warning("SKIP_LATENCY включён: серверы не проверяются, порядок источников сохранён")
        return [
            RankedNode(outbound=outbound, link=link, delay_ms=0, status="skipped")
            for outbound, link in candidates
        ]

    if config.get("enabled", True):
        checker = XrayKnifeChecker(
            binary=config.get("binary") or os.getenv("XRAY_KNIFE_BIN") or None,
            threads=int(config.get("threads", 50)),
            timeout_ms=int(config.get("timeout_ms", 10000)),
            max_delay_ms=int(config.get("max_delay_ms", 8000)),
            subprocess_timeout=int(config.get("subprocess_timeout_seconds", 2400)),
        )
        if checker.available:
            ranked = checker.rank(candidates)
            if checker.last_run_ok:
                if not ranked:
                    logger.warning(
                        "xray-knife отработал, но живых серверов нет. "
                        "TCP-fallback отключён: открытый TCP-порт не значит рабочий прокси."
                    )
                return ranked
            logger.warning(
                "xray-knife не смог отработать (нет бинарника, таймаут или битый вывод). "
                "Переключаюсь на TCP-fallback."
            )
        else:
            logger.warning(
                "xray-knife не установлен. В GitHub Actions он ставится через go install; "
                "локально используется TCP-fallback."
            )

    if config.get("fallback_tcp", True):
        return await _rank_tcp(
            candidates,
            concurrency=int(config.get("fallback_concurrency", 50)),
            timeout=float(config.get("fallback_timeout_seconds", 5.0)),
        )

    return []
