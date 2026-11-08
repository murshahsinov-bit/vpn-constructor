# Полные коды изменённых файлов

Сгенерировано из рабочего дерева. Не является патчем.

## `netrun_worker/app.py` — Воркер Netrun: маршруты, заголовки, WebRTC

````python
# -*- coding: utf-8 -*-
"""
Netrun worker: выдаёт подписку только клиентам с действительным токеном.

Маршруты:
    GET /sub/auto.json?token=<token>          — Xray JSON для Happ/INCY
    GET /sub/whitelist.json?token=<token>     — Xray JSON с RU relay-цепочкой
    GET /sub/auto.txt?token=<token>           — share-ссылки для INCY
    GET /sub/auto_happ.txt?token=<token>      — share-ссылки для Happ
    GET /sub/whitelist.txt?token=<token>      — whitelist-ссылки для INCY
    GET /sub/whitelist_happ.txt?token=<token> — whitelist-ссылки для Happ
    GET /sub/webrtc.txt?token=<token>         — ручная инструкция WebRTC

Источники данных:
    clients.json              — база клиентов (файл или CLIENTS_JSON)
    auto.json                 — собранная JSON-подписка
    whitelist.json            — подписка с цепочкой RU relay
    auto_all.txt              — share-ссылки INCY
    auto_all_happ.txt         — share-ссылки Happ
    whitelist_all.txt         — whitelist-ссылки INCY
    whitelist_all_happ.txt    — whitelist-ссылки Happ

Сервис не является VPN/прокси-сервером: он только отдаёт подписку.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from flask import Flask, Response, jsonify, request

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

PORT = int(os.getenv("PORT", "8080"))
CACHE_TTL = max(0, int(os.getenv("CACHE_TTL", "60")))
REQUEST_TIMEOUT = max(1, int(os.getenv("REQUEST_TIMEOUT", "8")))
MAX_CONFIG_BYTES = max(1024, int(os.getenv("MAX_CONFIG_BYTES", str(10 * 1024 * 1024))))

CLIENTS_FILE = Path(os.getenv("CLIENTS_FILE", str(BASE_DIR / "clients.json")))

CLIENTS_JSON = os.getenv("CLIENTS_JSON", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip() or "main"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

CONFIG_PATH = os.getenv("CONFIG_PATH", "web/subscriptions/auto.json").strip() or "web/subscriptions/auto.json"
_default_subscriptions_dir = str(Path(CONFIG_PATH).parent).replace("\\", "/")
SUBSCRIPTIONS_DIR = os.getenv("SUBSCRIPTIONS_DIR", "").strip() or _default_subscriptions_dir
if SUBSCRIPTIONS_DIR in ("", "."):
    SUBSCRIPTIONS_DIR = "web/subscriptions"
SUBSCRIPTIONS_DIR = SUBSCRIPTIONS_DIR.strip("/")

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
HTTP_USER_AGENT = "vpn-constructor-netrun-worker/2.0"

# Заголовки подписки. Значения можно переопределить в кабинете Netrun.
PROFILE_TITLE_DEFAULT = "VPN Constructor"
PROFILE_TITLE_MAX_LENGTH = 25
PROFILE_UPDATE_INTERVAL_DEFAULT = 1
SUBSCRIPTION_TOTAL_DEFAULT = 107374182400  # 100 GiB
SUB_EXPIRE_DAYS_DEFAULT = 3
SUB_EXPIRE_MESSAGE_DEFAULT = "Подписка истекает {date}. Продлите вовремя."


@dataclass(frozen=True)
class Asset:
    """Один файл подписки: локальный fallback + путь в GitHub."""

    name: str
    kind: str  # "json" | "text"
    local_path: Path
    remote_path: str
    direct_url: str = ""


def _env_or(key: str, default: str) -> str:
    value = os.getenv(key, "").strip()
    return value or default


def _remote_path(env_key: str, default_name: str) -> str:
    value = os.getenv(env_key, "").strip()
    if value:
        return value.strip("/")
    return f"{SUBSCRIPTIONS_DIR}/{default_name}"


def _local_path(env_key: str, default_name: str) -> Path:
    configured = os.getenv(env_key, "").strip()
    if configured:
        return Path(configured)
    # Локально удобнее читать web/subscriptions, а в ZIP-архиве Netrun
    # остаётся резервная копия рядом с app.py.
    repo_copy = BASE_DIR.parent / "web" / "subscriptions" / default_name
    if repo_copy.exists():
        return repo_copy
    return BASE_DIR / default_name


ASSETS: dict[str, Asset] = {
    "auto.json": Asset(
        name="auto.json",
        kind="json",
        local_path=_local_path("AUTO_FILE", "auto.json"),
        remote_path=_remote_path("CONFIG_PATH", "auto.json"),
        direct_url=_env_or("CONFIG_URL", ""),
    ),
    "whitelist.json": Asset(
        name="whitelist.json",
        kind="json",
        local_path=_local_path("WHITELIST_FILE", "whitelist.json"),
        remote_path=_remote_path("WHITELIST_JSON_PATH", "whitelist.json"),
        direct_url=_env_or("WHITELIST_JSON_URL", ""),
    ),
    "auto_all.txt": Asset(
        name="auto_all.txt",
        kind="text",
        local_path=_local_path("AUTO_TXT_FILE", "auto_all.txt"),
        remote_path=_remote_path("AUTO_TXT_PATH", "auto_all.txt"),
        direct_url=_env_or("AUTO_TXT_URL", ""),
    ),
    "auto_all_happ.txt": Asset(
        name="auto_all_happ.txt",
        kind="text",
        local_path=_local_path("AUTO_HAPP_TXT_FILE", "auto_all_happ.txt"),
        remote_path=_remote_path("AUTO_HAPP_TXT_PATH", "auto_all_happ.txt"),
        direct_url=_env_or("AUTO_HAPP_TXT_URL", ""),
    ),
    "whitelist_all.txt": Asset(
        name="whitelist_all.txt",
        kind="text",
        local_path=_local_path("WHITELIST_TXT_FILE", "whitelist_all.txt"),
        remote_path=_remote_path("WHITELIST_TXT_PATH", "whitelist_all.txt"),
        direct_url=_env_or("WHITELIST_TXT_URL", ""),
    ),
    "whitelist_all_happ.txt": Asset(
        name="whitelist_all_happ.txt",
        kind="text",
        local_path=_local_path("WHITELIST_HAPP_TXT_FILE", "whitelist_all_happ.txt"),
        remote_path=_remote_path("WHITELIST_HAPP_TXT_PATH", "whitelist_all_happ.txt"),
        direct_url=_env_or("WHITELIST_HAPP_TXT_URL", ""),
    ),
}

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("netrun-worker")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# ---------------------------------------------------------------------------
# Загрузка clients.json
# ---------------------------------------------------------------------------

_clients_lock = threading.Lock()
_clients_cache: dict[str, Any] = {
    "key": None,
    "clients": [],
}
_env_clients_cache: list[dict[str, Any]] | None = None


def _extract_clients(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw_clients = raw.get("clients", [])
    elif isinstance(raw, list):
        raw_clients = raw
    else:
        raise ValueError("clients.json: ожидался объект или массив")

    if not isinstance(raw_clients, list):
        raise ValueError("clients.json: поле 'clients' должно быть массивом")

    result: list[dict[str, Any]] = []
    for item in raw_clients:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        token = str(item.get("token", "")).strip()
        expires_at = str(item.get("expires_at", "")).strip()
        if not token or not expires_at:
            continue
        result.append(
            {
                "name": name,
                "token": token,
                "expires_at": expires_at,
            }
        )
    return result


def _parse_env_clients() -> list[dict[str, Any]]:
    """CLIENTS_JSON может содержать JSON или base64(JSON)."""
    global _env_clients_cache
    if _env_clients_cache is not None:
        return _env_clients_cache

    if not CLIENTS_JSON:
        _env_clients_cache = []
        return _env_clients_cache

    raw_text = CLIENTS_JSON
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        try:
            decoded = base64.b64decode(raw_text, validate=True).decode("utf-8")
            raw = json.loads(decoded)
        except Exception as exc:
            logger.error("CLIENTS_JSON не является JSON или base64(JSON): %s", exc)
            _env_clients_cache = []
            return _env_clients_cache

    try:
        _env_clients_cache = _extract_clients(raw)
        logger.info("Загружено %d клиентов из CLIENTS_JSON", len(_env_clients_cache))
    except ValueError as exc:
        logger.error("%s", exc)
        _env_clients_cache = []
    return _env_clients_cache


def load_clients(force: bool = False) -> list[dict[str, Any]]:
    """Читает клиентов из CLIENTS_JSON или локального clients.json."""
    if CLIENTS_JSON:
        return _parse_env_clients()

    try:
        stat = CLIENTS_FILE.stat()
        cache_key = (str(CLIENTS_FILE), stat.st_mtime_ns, stat.st_size)
    except OSError:
        cache_key = None

    with _clients_lock:
        if not force and cache_key is not None and _clients_cache["key"] == cache_key:
            return _clients_cache["clients"]

        if cache_key is None:
            _clients_cache["key"] = None
            _clients_cache["clients"] = []
            logger.warning("Файл клиентов не найден: %s", CLIENTS_FILE)
            return []

        try:
            raw = json.loads(CLIENTS_FILE.read_text(encoding="utf-8"))
            clients = _extract_clients(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Не удалось прочитать %s: %s", CLIENTS_FILE, exc)
            clients = []

        _clients_cache["key"] = cache_key
        _clients_cache["clients"] = clients
        logger.info("Загружено %d клиентов из %s", len(clients), CLIENTS_FILE)
        return clients


def _not_expired(expires_at: str) -> bool:
    try:
        return date.fromisoformat(expires_at) >= date.today()
    except (TypeError, ValueError):
        return False


def authorize_token(token: str) -> dict[str, Any] | None:
    """Возвращает клиента, если токен существует и не истёк. Иначе None."""
    if not token or not TOKEN_RE.fullmatch(token):
        return None

    matched_active: dict[str, Any] | None = None
    # Сравниваем все токены, чтобы не давать подсказок по времени ответа.
    for client in load_clients():
        candidate = client.get("token", "")
        if candidate and secrets.compare_digest(token, candidate):
            if _not_expired(str(client.get("expires_at", ""))):
                matched_active = client

    return matched_active


# ---------------------------------------------------------------------------
# Загрузка файлов подписки (JSON и TXT)
# ---------------------------------------------------------------------------

_asset_locks: dict[str, threading.Lock] = {
    name: threading.Lock() for name in ASSETS
}
_asset_caches: dict[str, dict[str, Any]] = {
    name: {"data": None, "timestamp": 0.0, "source": None}
    for name in ASSETS
}


def _github_api_url(remote_path: str) -> str | None:
    if not GITHUB_REPO:
        return None
    path = quote(remote_path, safe="/")
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}?ref={quote(GITHUB_BRANCH, safe='')}"


def _github_raw_url(remote_path: str) -> str | None:
    if not GITHUB_REPO:
        return None
    return (
        f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
        f"{quote(GITHUB_BRANCH, safe='')}/{quote(remote_path, safe='/')}"
    )


def _jsdelivr_url(remote_path: str) -> str | None:
    if not GITHUB_REPO:
        return None
    return (
        f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@"
        f"{quote(GITHUB_BRANCH, safe='')}/{quote(remote_path, safe='/')}"
    )


def _mirror_for_raw_url(url: str) -> str | None:
    """Для raw.githubusercontent.com возвращает зеркало jsDelivr."""
    parsed = urlsplit(url)
    if parsed.netloc != "raw.githubusercontent.com":
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 4:
        return None
    user, repo, branch = parts[0], parts[1], parts[2]
    file_path = "/".join(parts[3:])
    return f"https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{file_path}"


def _remote_candidates(asset: Asset) -> list[tuple[str, dict[str, str]]]:
    """URL-кандидаты и заголовки. GitHub API идёт первым для приватных репозиториев."""
    candidates: list[tuple[str, dict[str, str]]] = []
    seen: set[str] = set()

    def add(url: str | None, headers: dict[str, str] | None = None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        candidates.append((url, headers or {}))

    api_url = _github_api_url(asset.remote_path)
    if api_url:
        headers = {
            "Accept": "application/vnd.github.raw",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": HTTP_USER_AGENT,
        }
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        add(api_url, headers)

    if asset.direct_url:
        add(asset.direct_url, {"User-Agent": HTTP_USER_AGENT})
        add(_mirror_for_raw_url(asset.direct_url), {"User-Agent": HTTP_USER_AGENT})

    add(_github_raw_url(asset.remote_path), {"User-Agent": HTTP_USER_AGENT})
    add(_jsdelivr_url(asset.remote_path), {"User-Agent": HTTP_USER_AGENT})

    return candidates


def _validate_payload(asset: Asset, data: bytes) -> None:
    """Проверяет, что JSON — это JSON, а TXT — не HTML и не пустота."""
    if not data:
        raise ValueError("пустой ответ")
    if len(data) > MAX_CONFIG_BYTES:
        raise ValueError(f"ответ больше {MAX_CONFIG_BYTES} байт")

    if asset.kind == "json":
        try:
            json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("ответ не является JSON") from exc
        return

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("TXT не является UTF-8") from exc
    stripped = text.lstrip()
    if not stripped:
        raise ValueError("пустой TXT")
    if stripped.startswith("<"):
        raise ValueError("ответ похож на HTML")


def _download_asset(asset: Asset, url: str, headers: dict[str, str]) -> bytes:
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.content
    _validate_payload(asset, data)
    return data


def _read_local_asset(asset: Asset) -> bytes | None:
    try:
        data = asset.local_path.read_bytes()
    except OSError:
        return None
    try:
        _validate_payload(asset, data)
    except ValueError as exc:
        logger.error("Локальный %s не прошёл проверку: %s", asset.local_path, exc)
        return None
    return data


def get_asset(name: str) -> tuple[bytes, str, bool]:
    """
    Возвращает (data, source, stale) для файла подписки.

    Порядок: свежий кэш -> удалённый источник -> локальный файл -> устаревший кэш.
    """
    asset = ASSETS.get(name)
    if asset is None:
        raise KeyError(f"Неизвестный файл подписки: {name}")

    cache = _asset_caches[name]
    lock = _asset_locks[name]
    now = time.monotonic()

    with lock:
        cached = cache["data"]
        cached_at = float(cache["timestamp"] or 0.0)
        cached_source = cache["source"]
        if cached and CACHE_TTL > 0 and now - cached_at < CACHE_TTL:
            return cached, str(cached_source or "cache"), False

    errors: list[str] = []
    for url, headers in _remote_candidates(asset):
        try:
            data = _download_asset(asset, url, headers)
            with lock:
                cache.update(data=data, timestamp=now, source=url)
            logger.info("%s обновлён из %s (%d байт)", name, url, len(data))
            return data, url, False
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")
            logger.warning("Не удалось получить %s из %s: %s", name, url, exc)

    local = _read_local_asset(asset)
    if local is not None:
        with lock:
            cache.update(data=local, timestamp=now, source=str(asset.local_path))
        logger.info("Используется локальный %s (%d байт)", asset.local_path, len(local))
        return local, str(asset.local_path), False

    with lock:
        stale = cache["data"]
        stale_source = cache["source"]
    if stale:
        logger.warning("Все источники %s недоступны, отдаю устаревший кэш", name)
        return stale, str(stale_source or "stale-cache"), True

    raise RuntimeError("; ".join(errors) or f"нет доступного источника {name}")


def get_auto_json() -> tuple[bytes, str, bool]:
    """Совместимость со старым кодом/тестами."""
    return get_asset("auto.json")


# ---------------------------------------------------------------------------
# HTTP-заголовки подписки (Happ + INCY)
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, "").strip() or default))
    except (TypeError, ValueError):
        return default


def _header_value(value: Any) -> str:
    """Убирает переводы строк, чтобы исключить header injection."""
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).strip()


def _title_header(value: str) -> str:
    """
    profile-title: не длиннее 25 символов.

    Happ/INCY понимают base64-вариант, поэтому кириллицу не отправляем
    сырыми байтами в HTTP-заголовке (там допустим только latin-1).
    """
    title = _header_value(value)[:PROFILE_TITLE_MAX_LENGTH]
    try:
        title.encode("latin-1")
        return title
    except UnicodeEncodeError:
        encoded = base64.b64encode(title.encode("utf-8")).decode("ascii")
        return f"base64:{encoded}"


def _expire_unix(expires_at: str) -> int | None:
    """Конец дня expires_at по UTC в Unix timestamp."""
    try:
        expires = date.fromisoformat(str(expires_at).strip())
    except (TypeError, ValueError):
        return None
    return int(
        datetime.combine(expires, dt_time.max, tzinfo=timezone.utc).timestamp()
    )


def _days_left(expires_at: str) -> int | None:
    try:
        expires = date.fromisoformat(str(expires_at).strip())
    except (TypeError, ValueError):
        return None
    return (expires - date.today()).days


def build_subscription_headers(client: dict[str, Any]) -> dict[str, str]:
    """
    Заголовки, которые Happ и INCY читают при обновлении подписки.

    profile-title              — имя подписки (<=25 символов);
    profile-update-interval    — автообновление в часах;
    subscription-userinfo      — трафик и срок действия;
    hide-url                   — скрыть URL в «Поделиться» (Happ);
    subscription-always-hwid-enable — HWID нельзя отключить (Happ);
    no-limit-xhttp-enabled     — снять лимит RAM для XHTTP (Happ iOS);
    sub-expire                 — включить баннер окончания (Happ);
    sub-expire-button-link     — кнопка «Продлить»;
    announce                   — текст сообщения в base64 (Happ + INCY).
    """
    expires_at = str(client.get("expires_at", "")).strip()
    expire_unix = _expire_unix(expires_at)
    days_left = _days_left(expires_at)

    headers: dict[str, str] = {
        "profile-title": _title_header(
            _env_or("PROFILE_TITLE", PROFILE_TITLE_DEFAULT)
        ),
        "profile-update-interval": str(
            _env_int(
                "PROFILE_UPDATE_INTERVAL",
                PROFILE_UPDATE_INTERVAL_DEFAULT,
                minimum=1,
            )
        ),
    }

    total = _env_int("SUBSCRIPTION_TOTAL_BYTES", SUBSCRIPTION_TOTAL_DEFAULT)
    upload = _env_int("SUBSCRIPTION_UPLOAD_BYTES", 0)
    download = _env_int("SUBSCRIPTION_DOWNLOAD_BYTES", 0)
    userinfo = [
        f"upload={upload}",
        f"download={download}",
        f"total={total}",
    ]
    if expire_unix is not None:
        userinfo.append(f"expire={expire_unix}")
    headers["subscription-userinfo"] = "; ".join(userinfo)

    # Необязательные ссылки: отправляем только если заданы.
    for header, env_name in (
        ("profile-web-page-url", "PROFILE_WEB_PAGE_URL"),
        ("support-url", "SUPPORT_URL"),
    ):
        value = _header_value(os.getenv(env_name, ""))
        if value:
            headers[header] = value

    # Happ-специфичные переключатели. По умолчанию включены.
    if _env_bool("HIDE_URL", True):
        headers["hide-url"] = "1"
    if _env_bool("SUBSCRIPTION_ALWAYS_HWID_ENABLE", True):
        headers["subscription-always-hwid-enable"] = "1"
    if _env_bool("NO_LIMIT_XHTTP_ENABLED", True):
        headers["no-limit-xhttp-enabled"] = "1"

    # Баннер окончания подписки. В документации Happ sub-expire — это
    # boolean-включатель, а не текст. Текст передаём через announce
    # (base64), который понимают и Happ, и INCY.
    expire_days = _env_int("SUB_EXPIRE_DAYS", SUB_EXPIRE_DAYS_DEFAULT)
    if (
        _env_bool("SUB_EXPIRE_ENABLED", True)
        and days_left is not None
        and 0 <= days_left <= expire_days
    ):
        headers["sub-expire"] = "1"
        button_link = _header_value(os.getenv("SUB_EXPIRE_BUTTON_LINK", ""))
        if button_link:
            headers["sub-expire-button-link"] = button_link

        template = _env_or("SUB_EXPIRE_TEXT", SUB_EXPIRE_MESSAGE_DEFAULT)
        try:
            message = template.format(date=expires_at, days=days_left)
        except (KeyError, ValueError):
            message = template
        message = _header_value(message)[:200]
        if message and _env_bool("SUB_EXPIRE_ANNOUNCE", True):
            encoded = base64.b64encode(message.encode("utf-8")).decode("ascii")
            headers["announce"] = f"base64:{encoded}"

    return headers


def _apply_subscription_headers(
    response: Response,
    client: dict[str, Any],
    title: str | None = None,
) -> Response:
    headers = build_subscription_headers(client)
    if title is not None:
        headers["profile-title"] = _title_header(title)
    for key, value in headers.items():
        response.headers[key] = value
    return response


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:10] if token else "-"


@app.after_request
def add_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    return response


def _authorize_request() -> tuple[str, dict[str, Any] | None]:
    token = (request.args.get("token") or "").strip()
    return token, authorize_token(token)


def _forbidden(token: str) -> tuple[Response, int]:
    logger.warning(
        "403: недействительный или истёкший токен fp=%s",
        _token_fingerprint(token),
    )
    return jsonify({"error": "forbidden"}), 403


def _serve_asset(asset_name: str, client: dict[str, Any], token: str) -> Response:
    asset = ASSETS[asset_name]
    try:
        data, source, stale = get_asset(asset_name)
    except RuntimeError as exc:
        logger.error("503: %s недоступен: %s", asset_name, exc)
        return jsonify({"error": "subscription source unavailable"}), 503

    mimetype = "application/json" if asset.kind == "json" else "text/plain"
    response = Response(data, mimetype=mimetype)
    if asset.kind == "json":
        response.headers["Content-Type"] = "application/json"
    else:
        response.headers["Content-Type"] = "text/plain; charset=utf-8"

    _apply_subscription_headers(response, client)
    if stale:
        response.headers["X-Config-Stale"] = "1"

    logger.info(
        "200: %s выдан fp=%s source=%s",
        asset_name,
        _token_fingerprint(token),
        source,
    )
    return response


@app.get("/")
def index() -> Response:
    return jsonify(
        {
            "service": "vpn-subscription-gateway",
            "status": "ok",
            "endpoints": [
                "/sub/auto.json?token=<token>",
                "/sub/whitelist.json?token=<token>",
                "/sub/auto.txt?token=<token>",
                "/sub/auto_happ.txt?token=<token>",
                "/sub/whitelist.txt?token=<token>",
                "/sub/whitelist_happ.txt?token=<token>",
                "/sub/webrtc.txt?token=<token>",
            ],
        }
    )


@app.get("/healthz")
def healthz() -> Response:
    return jsonify({"status": "ok"})


@app.get("/sub/auto.json")
def subscription_auto_json() -> Response:
    token, client = _authorize_request()
    if client is None:
        return _forbidden(token)
    return _serve_asset("auto.json", client, token)


@app.get("/sub/whitelist.json")
def subscription_whitelist_json() -> Response:
    token, client = _authorize_request()
    if client is None:
        return _forbidden(token)
    return _serve_asset("whitelist.json", client, token)


@app.get("/sub/auto.txt")
def subscription_auto_txt() -> Response:
    token, client = _authorize_request()
    if client is None:
        return _forbidden(token)
    return _serve_asset("auto_all.txt", client, token)


@app.get("/sub/auto_happ.txt")
@app.get("/sub/auto-happ.txt")
def subscription_auto_happ_txt() -> Response:
    token, client = _authorize_request()
    if client is None:
        return _forbidden(token)
    return _serve_asset("auto_all_happ.txt", client, token)


@app.get("/sub/whitelist.txt")
def subscription_whitelist_txt() -> Response:
    token, client = _authorize_request()
    if client is None:
        return _forbidden(token)
    return _serve_asset("whitelist_all.txt", client, token)


@app.get("/sub/whitelist_happ.txt")
@app.get("/sub/whitelist-happ.txt")
def subscription_whitelist_happ_txt() -> Response:
    token, client = _authorize_request()
    if client is None:
        return _forbidden(token)
    return _serve_asset("whitelist_all_happ.txt", client, token)


def _webrtc_text() -> str:
    socks = _header_value(os.getenv("WEBRTC_SOCKS5", ""))
    lines = [
        "# VPN Constructor — WebRTC-туннель (экспериментально)",
        "#",
        "# Это не автоматическая подписка, а инструкция для ручной настройки.",
        "# Схема: телефон → WebRTC DataChannel (Телемост/VK Calls) → зарубежный бридж.",
        "#",
        "# 1. Поднимите WebRTC-бридж на зарубежном VPS (TURN/STUN + DataChannel).",
        "# 2. Запустите WebRTC-клиент, который отдаёт локальный SOCKS5-прокси.",
        "# 3. Создайте комнату в разрешённом медиа-сервисе и подключите клиент и бридж.",
        "# 4. В Happ/INCY добавьте SOCKS5-профиль вручную (не через подписку).",
        "# 5. Проверьте выход: curl https://ipinfo.io/ip должен показать зарубежный IP.",
        "# 6. Не используйте как постоянный VPN: нет health-check и автопереключения.",
        "#",
    ]
    if socks:
        lines.append("# SOCKS5-адрес для ручного профиля:")
        lines.append(socks)
    else:
        lines.append(
            "# SOCKS5-адрес не задан. Владелец сервиса должен указать WEBRTC_SOCKS5."
        )
    return "\n".join(lines) + "\n"


@app.get("/sub/webrtc.txt")
def subscription_webrtc_txt() -> Response:
    token, client = _authorize_request()
    if client is None:
        return _forbidden(token)

    response = Response(_webrtc_text(), mimetype="text/plain")
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    _apply_subscription_headers(
        response,
        client,
        title="VPN Constructor WebRTC",
    )
    logger.info("200: webrtc.txt выдан fp=%s", _token_fingerprint(token))
    return response


@app.errorhandler(404)
def not_found(_error: Exception) -> tuple[Response, int]:
    return jsonify({"error": "not found"}), 404


@app.errorhandler(405)
def method_not_allowed(_error: Exception) -> tuple[Response, int]:
    return jsonify({"error": "method not allowed"}), 405


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

````

## `aggregator/formatter/to_txt.py` — TXT-подписки INCY и Happ

````python
"""Генерация TXT-подписок (share-ссылок) для INCY и Happ.

Один и тот же набор серверов отдаётся в двух вариантах:

* ``incy`` — фрагментация query-параметрами INCY:
  ``fragmentPackets=tlshello&fragmentLength=100-200&fragmentInterval=10-20``;
* ``happ`` — фрагментация одним параметром Happ:
  ``fragment=100-200,10-20,tlshello``.

Фрагментация добавляется только TCP-ссылкам. XHTTP-ссылки не трогаем:
XHTTP и так передаёт данные отдельными HTTP-запросами, а лишние
параметры могут сломать импорт в некоторых клиентах.
"""

from __future__ import annotations

import re
import urllib.parse

COUNTRY_FLAGS = {
    "germany": "🇩🇪", "германия": "🇩🇪", "de": "🇩🇪",
    "netherlands": "🇳🇱", "нидерланды": "🇳🇱", "nl": "🇳🇱",
    "usa": "🇺🇸", "сша": "🇺🇸", "us": "🇺🇸",
    "russia": "🇷🇺", "россия": "🇷🇺", "ru": "🇷🇺",
    "finland": "🇫🇮", "финляндия": "🇫🇮", "fi": "🇫🇮",
    "poland": "🇵🇱", "польша": "🇵🇱", "pl": "🇵🇱",
    "estonia": "🇪🇪", "эстония": "🇪🇪", "ee": "🇪🇪",
    "sweden": "🇸🇪", "швеция": "🇸🇪", "se": "🇸🇪",
    "france": "🇫🇷", "франция": "🇫🇷", "fr": "🇫🇷",
}

# INCY читает фрагментацию из отдельных query-параметров.
INCY_FRAGMENT_PARAMS = (
    ("fragmentPackets", "tlshello"),
    ("fragmentLength", "100-200"),
    ("fragmentInterval", "10-20"),
)

# Happ читает один параметр: length,interval,packets[,maxSplit].
HAPP_FRAGMENT_PARAMS = (
    ("fragment", "100-200,10-20,tlshello"),
)

# Если источник уже прислал фрагментацию, заменяем её своим форматом,
# а не дублируем параметры.
FRAGMENT_KEYS = {
    "fragment",
    "fragmentpackets",
    "fragmentlength",
    "fragmentinterval",
    "fragmentmaxsplit",
}

SUPPORTED_CLIENTS = {"incy", "happ"}


def _query_pairs(query: str) -> list[str]:
    """Возвращает query как список исходных пар, не перекодируя значения."""
    return [item for item in (query or "").split("&") if item]


def _query_value(pairs: list[str], key: str) -> str:
    key = key.lower()
    for item in pairs:
        name, _, value = item.partition("=")
        if name.lower() == key:
            return urllib.parse.unquote(value)
    return ""


def _is_tcp_link(pairs: list[str]) -> bool:
    """TCP/raw — да; xhttp/ws/grpc/h2 и прочее — нет."""
    network = (_query_value(pairs, "type") or _query_value(pairs, "network") or "tcp")
    network = network.strip().lower()
    if network == "raw":
        network = "tcp"
    return network == "tcp"


def _with_fragment(link: str, client: str) -> str:
    """Добавляет к TCP-ссылке параметры фрагментации нужного клиента."""
    parsed = urllib.parse.urlsplit(link)

    # Фрагментацию описываем только для VLESS: у VMess/Trojan/Hysteria
    # query-семантика другая, и такие ссылки в пайплайне и так не собираются.
    if parsed.scheme.lower() != "vless":
        return link

    pairs = _query_pairs(parsed.query)
    if not _is_tcp_link(pairs):
        return link

    fragment_params = (
        HAPP_FRAGMENT_PARAMS if client == "happ" else INCY_FRAGMENT_PARAMS
    )
    kept = [
        item for item in pairs
        if item.partition("=")[0].strip().lower() not in FRAGMENT_KEYS
    ]
    kept.extend(f"{key}={value}" for key, value in fragment_params)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "&".join(kept), parsed.fragment)
    )


def _decorate_name(link: str, counter: dict[str, int]) -> str:
    """Добавляет флаг страны и уникализирует имя в fragment ссылки."""
    parsed = urllib.parse.urlsplit(link)
    if not parsed.fragment:
        return link

    # Happ разрешает `#title?serverDescription=...`. Сохраняем хвост
    # после `?`, чтобы не сломать расширенные метаданные.
    title_raw, separator, meta_raw = parsed.fragment.partition("?")
    name = urllib.parse.unquote(title_raw).strip() or "Server"

    # Функция может применяться к уже украшенному имени (например, при
    # повторной генерации из готового TXT). Сохраняем флаг, но не дублируем.
    existing_flag = ""
    match = re.match(r"^([\U0001F1E6-\U0001F1FF]{2}|\U0001F310)\s+", name)
    if match:
        existing_flag = match.group(1)
        name = name[match.end():].strip() or "Server"

    flag = existing_flag or "🌐"
    name_lower = name.lower()
    for key, emoji in COUNTRY_FLAGS.items():
        if key in name_lower:
            flag = emoji
            name = name.replace(key, "").replace(key.capitalize(), "").strip()
            if not name:
                name = key.capitalize()
            break

    if name in counter:
        counter[name] += 1
        name = f"{name} {counter[name]}"
    else:
        counter[name] = 1

    new_fragment = urllib.parse.quote(f"{flag} {name}")
    if separator:
        new_fragment = f"{new_fragment}?{meta_raw}"
    return urllib.parse.urlunsplit(parsed._replace(fragment=new_fragment))


def generate_txt(links: list[str], client: str = "incy") -> str:
    """
    Собирает TXT-подписку.

    ``client="incy"`` — параметры INCY (по умолчанию, совместимо со старым
    вызовом ``generate_txt(links)``); ``client="happ"`` — параметр Happ.
    """
    client = (client or "incy").strip().lower()
    if client not in SUPPORTED_CLIENTS:
        raise ValueError(f"Неизвестный клиент TXT-подписки: {client}")

    formatted_links: list[str] = []
    counter: dict[str, int] = {}

    for raw_link in links:
        link = (raw_link or "").strip()
        if not link:
            continue
        link = _with_fragment(link, client)
        formatted_links.append(_decorate_name(link, counter))

    return "\n".join(formatted_links)

````

## `aggregator/run.py` — Агрегатор: две TXT, relay, YCF

````python
import asyncio
import base64
import copy
import ipaddress
import logging
import os
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlencode, urlparse

import yaml

from aggregator.sources.loader import SourceLoader
from aggregator.fetcher.downloader import ConfigDownloader
from aggregator.converter.link_to_outbound import (
    TCP_FRAGMENT,
    VISION_FLOW,
    LinkToOutboundConverter,
)
from aggregator.formatter.to_json import build_subscription, save_config
from aggregator.formatter.to_txt import generate_txt
from aggregator.health.latency import outbound_identity, rank_by_latency

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


PROFILE_ORDER = ("xhttp", "tcp")
_LINK_PREFIXES = (
    "vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://",
)


@dataclass
class ServerRecord:
    """Один сервер и все его живые/поддерживаемые профили."""
    identity: tuple[str, int, str]
    variants: dict[str, dict] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    sources: set[str] = field(default_factory=set)
    delays: dict[str, int] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)

    @property
    def alive_profiles(self) -> list[str]:
        return [p for p in PROFILE_ORDER if p in self.delays and p in self.variants]

    @property
    def delay_ms(self) -> int:
        return min(self.delays.values()) if self.delays else 10 ** 9


def _try_base64(text: str) -> str | None:
    """Пытается декодировать base64-подписку, игнорируя переводы строк."""
    cleaned = "".join(text.split())
    if not cleaned:
        return None
    padded = cleaned + "=" * (-len(cleaned) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except Exception:
        return None
    if decoded.lstrip().startswith(_LINK_PREFIXES) or "vless://" in decoded:
        return decoded
    return None


def _decode_source(text: str, source_format: str = "text") -> str:
    """Декодирует base64-подписку, если источник отдаёт её в таком виде."""
    if source_format == "base64":
        decoded = _try_base64(text)
        if decoded is None:
            logger.debug("Источник помечен как base64, но декодировать не удалось")
            return text
        return decoded

    # Часть источников меняет формат без предупреждения, пробуем аккуратно.
    return _try_base64(text) or text


def _security(outbound: dict) -> str:
    return str((outbound.get("streamSettings") or {}).get("security", "")).strip().lower()


def _server_name(outbound: dict) -> str:
    stream = outbound.get("streamSettings") or {}
    reality = stream.get("realitySettings") or {}
    tls = stream.get("tlsSettings") or {}
    return str(reality.get("serverName") or tls.get("serverName") or "").strip().lower()


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _alternate_variant(source: dict, target_profile: str) -> dict | None:
    """
    Строит второй профиль из той же пары address/port/uuid/pbk/sni.

    Такой профиль — гипотеза: сервер мог поднять только один транспорт.
    Поэтому он проходит реальную проверку xray-knife и попадает в JSON
    только если действительно работает. Если сервер поддерживает оба
    транспорта, клиент получает proxy-xhttp-N и proxy-tcp-N.
    """
    if _security(source) != "reality":
        return None
    if target_profile not in PROFILE_ORDER:
        return None

    variant = copy.deepcopy(source)
    stream = variant.setdefault("streamSettings", {})
    reality = stream.get("realitySettings") or {}
    reality["fingerprint"] = "firefox"
    stream["realitySettings"] = reality
    server_name = str(reality.get("serverName", "")).strip()
    users = (variant.get("settings") or {}).get("vnext", [{}])[0].get("users", [{}])
    if not users:
        return None
    user = users[0]

    if target_profile == "tcp":
        stream.pop("xhttpSettings", None)
        stream["network"] = "tcp"
        user["flow"] = VISION_FLOW
        variant["fragment"] = dict(TCP_FRAGMENT)
        variant["_flow"] = VISION_FLOW
    else:
        stream["network"] = "xhttp"
        user["flow"] = ""
        xhttp_settings = {"mode": "stream-one", "path": "/"}
        if server_name and not _is_ip(server_name):
            xhttp_settings["host"] = server_name
        stream["xhttpSettings"] = xhttp_settings
        variant.pop("fragment", None)
        variant["_flow"] = ""

    variant["_profile"] = target_profile
    variant["_network"] = target_profile
    variant["_synthetic"] = True
    return variant


def _outbound_to_link(outbound: dict) -> str | None:
    """Собирает share-ссылку для проверки синтетического профиля."""
    vnext = (outbound.get("settings") or {}).get("vnext") or [{}]
    node = vnext[0]
    users = node.get("users") or [{}]
    user = users[0]
    address = str(node.get("address", "")).strip()
    port = int(node.get("port") or 0)
    user_id = str(user.get("id", "")).strip()
    if not address or not port or not user_id:
        return None

    stream = outbound.get("streamSettings") or {}
    profile = str(outbound.get("_profile") or stream.get("network") or "tcp").lower()
    security = str(stream.get("security", "")).lower()
    reality = stream.get("realitySettings") or {}
    tls = stream.get("tlsSettings") or {}

    params = {
        "type": profile,
        "security": security,
        "encryption": "none",
        "fp": "firefox",
    }
    if security == "reality":
        params["pbk"] = str(reality.get("publicKey", "")).strip()
        params["sid"] = str(reality.get("shortId", "")).strip()
        params["sni"] = str(reality.get("serverName", "")).strip()
    else:
        params["sni"] = str(tls.get("serverName", "")).strip()
        alpn = tls.get("alpn")
        if isinstance(alpn, list) and alpn:
            params["alpn"] = ",".join(str(item) for item in alpn)

    if profile == "tcp":
        params["flow"] = VISION_FLOW
    else:
        xhttp = stream.get("xhttpSettings") or {}
        params["path"] = str(xhttp.get("path") or "/")
        params["mode"] = "stream-one"
        host = str(xhttp.get("host", "")).strip()
        if host:
            params["host"] = host

    host_part = f"[{address}]" if ":" in address else address
    query = urlencode(params, quote_via=quote, safe="")
    return f"vless://{user_id}@{host_part}:{port}?{query}#synthetic-{profile}"


def _parse_sources(
    mode: str,
    raw_texts: dict[str, str],
    source_by_url: dict[str, dict],
    allow_tls_vision: bool = False,
) -> list[ServerRecord]:
    """
    Парсит ссылки и собирает серверы вместе с профилями.

    Один и тот же сервер может публиковаться двумя ссылками: XHTTP и TCP.
    Обе сохраняются в ``variants``, чтобы formatter отдал клиенту два
    outbound с одинаковым номером.
    """
    converter = LinkToOutboundConverter(
        allow_tls_vision=allow_tls_vision,
        allow_xhttp_tls=True,
    )
    records: dict[tuple[str, int, str], ServerRecord] = {}

    for url, text in raw_texts.items():
        source = source_by_url.get(url, {})
        source_name = str(source.get("name") or url)
        text = _decode_source(text, str(source.get("format") or "text"))

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("vless://"):
                # Пайплайн собирает только VLESS. WS/gRPC и Hysteria
                # отбрасываются ещё до проверки задержки.
                continue

            outbound = converter.convert(line)
            if not outbound:
                continue

            profile = str(outbound.get("_profile") or "").strip().lower()
            if profile not in PROFILE_ORDER:
                continue

            identity = outbound_identity(outbound)
            record = records.get(identity)
            if record is None:
                record = ServerRecord(identity=identity)
                records[identity] = record

            existing = record.variants.get(profile)
            replace = existing is None
            if existing is not None and _security(existing) != "reality" and _security(outbound) == "reality":
                # Reality предпочтительнее TLS при одном и том же профиле.
                replace = True
            if replace:
                record.variants[profile] = outbound
                record.links[profile] = line
            else:
                record.links.setdefault(profile, line)

            record.sources.add(source_name)

    logger.info(
        "Режим %s: серверов %d (xhttp=%d, tcp=%d, оба=%d)",
        mode,
        len(records),
        sum(1 for r in records.values() if "xhttp" in r.variants),
        sum(1 for r in records.values() if "tcp" in r.variants),
        sum(1 for r in records.values() if len(r.variants) > 1),
    )
    return list(records.values())


def _candidates(records: list[ServerRecord]) -> list[tuple[dict, str]]:
    candidates: list[tuple[dict, str]] = []
    for record in records:
        for profile, outbound in record.variants.items():
            link = record.links.get(profile)
            if link:
                candidates.append((outbound, link))
    return candidates


async def _rank_records_async(
    records: list[ServerRecord],
    latency_config: dict,
) -> list[ServerRecord]:
    candidates = _candidates(records)
    if not candidates:
        return []

    ranked = await rank_by_latency(candidates, latency_config)

    by_identity = {record.identity: record for record in records}
    for node in ranked:
        record = by_identity.get(outbound_identity(node.outbound))
        if record is None:
            continue
        profile = str(node.outbound.get("_profile") or "").strip().lower()
        if profile not in PROFILE_ORDER:
            continue
        previous = record.delays.get(profile)
        if previous is None or node.delay_ms < previous:
            record.delays[profile] = node.delay_ms
            record.statuses[profile] = node.status

    alive = [record for record in records if record.delays]
    # Сортировка по лучшей задержке; при равенстве — больше профилей.
    alive.sort(key=lambda record: (record.delay_ms, -len(record.alive_profiles)))
    return alive


async def _synthesize_and_rank(
    records: list[ServerRecord],
    latency_config: dict,
    candidate_limit: int = 60,
) -> list[ServerRecord]:
    """
    Пробует второй транспорт для лучших серверов.

    Проверяются только гипотезы: если сервер не поднял XHTTP/TCP на том же
    порту, xray-knife отбросит профиль. В JSON попадут только рабочие.
    """
    synthetic: list[tuple[ServerRecord, str, dict, str]] = []
    for record in records[:max(1, candidate_limit)]:
        if len(record.variants) >= 2:
            continue
        source_profile = next(iter(record.variants), None)
        if source_profile is None:
            continue
        source = record.variants[source_profile]
        for target_profile in PROFILE_ORDER:
            if target_profile == source_profile or target_profile in record.variants:
                continue
            variant = _alternate_variant(source, target_profile)
            if variant is None:
                continue
            link = _outbound_to_link(variant)
            if link:
                synthetic.append((record, target_profile, variant, link))

    if not synthetic:
        return records

    logger.info("Проверяю второй профиль для %d серверов (XHTTP/TCP)", len(synthetic))
    ranked = await rank_by_latency(
        [(variant, link) for _record, _profile, variant, link in synthetic],
        latency_config,
    )

    by_link = {
        link: (record, profile, variant)
        for record, profile, variant, link in synthetic
    }
    added = 0
    for node in ranked:
        # Второй профиль — гипотеза. TCP-fallback и SKIP_LATENCY её не
        # подтверждают, поэтому принимаем только реальный HTTP-тест.
        if node.status not in ("passed", "semi-passed"):
            continue
        match = by_link.get(node.link.strip())
        if match is None:
            continue
        record, profile, variant = match
        if profile in record.variants:
            continue
        record.variants[profile] = variant
        record.links[profile] = node.link
        record.delays[profile] = node.delay_ms
        record.statuses[profile] = node.status
        added += 1

    records.sort(key=lambda record: (record.delay_ms, -len(record.alive_profiles)))
    logger.info("Второй профиль подтверждён у %d серверов", added)
    return records


def _builder_entries(records: list[ServerRecord], limit: int) -> list[dict]:
    """
    Преобразует записи в формат formatter: один entry = один сервер,
    внутри ``_variants`` лежат XHTTP/TCP outbound-ы.
    """
    entries: list[dict] = []
    for record in records[:max(1, int(limit))]:
        profiles = record.alive_profiles
        if not profiles:
            continue

        variants: dict[str, dict] = {}
        for profile in profiles:
            outbound = copy.deepcopy(record.variants[profile])
            outbound["tag"] = f"proxy-{profile}"
            outbound["_profile"] = profile
            outbound["_source"] = ", ".join(sorted(record.sources))
            outbound["_sources"] = sorted(record.sources)
            variants[profile] = outbound

        base = copy.deepcopy(variants[profiles[0]])
        base["_variants"] = variants
        base["_profiles"] = profiles
        base["_links"] = {p: record.links[p] for p in profiles if p in record.links}
        base["_delay_ms"] = record.delay_ms
        base["_sources"] = sorted(record.sources)
        entries.append(base)
    return entries


def _txt_links(records: list[ServerRecord], limit: int) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for record in records[:max(1, int(limit))]:
        for profile in record.alive_profiles:
            link = record.links.get(profile)
            if link and link not in seen:
                seen.add(link)
                links.append(link)
    return links


def _has_source_prefix(record: ServerRecord, prefixes: tuple[str, ...]) -> bool:
    return any(name.startswith(prefixes) for name in record.sources)


def _socks_outbound(raw: str, tag: str = "proxy-ycf-1") -> dict | None:
    """
    Дополнительный SOCKS5-профиль (например, релей внутри Yandex Cloud
    Functions). Задаётся переменной YANDEX_FUNCTIONS_SOCKS:

        socks5://user:pass@host:1080
    """
    raw = str(raw or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "socks5://" + raw
    try:
        parsed = urlparse(raw)
        host = parsed.hostname
        port = parsed.port or 1080
        if not host:
            return None
        users = []
        if parsed.username:
            users.append({
                "user": unquote(parsed.username),
                "pass": unquote(parsed.password or ""),
            })
        return {
            "tag": tag,
            "protocol": "socks",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": int(port),
                    "users": users,
                }]
            },
        }
    except (TypeError, ValueError):
        logger.warning("Не удалось разобрать YANDEX_FUNCTIONS_SOCKS")
        return None


def _ycf_outbound() -> dict | None:
    return _socks_outbound(os.getenv("YANDEX_FUNCTIONS_SOCKS", ""))


def _relay_from_link(link: str) -> dict | None:
    converter = LinkToOutboundConverter(allow_tls_vision=True, allow_xhttp_tls=True)
    outbound = converter.convert(link, tag="wl-relay")
    if outbound is None:
        logger.error("RU_RELAY_LINK не удалось разобрать как VLESS-релей")
        return None
    outbound["_profile"] = outbound.get("_profile") or "tcp"
    return outbound


def _relay_from_records(
    records: list[ServerRecord],
    relay_config: dict,
) -> tuple[dict | None, tuple[str, int, str] | None, str | None]:
    """
    Выбирает RU relay из whitelist-источников.

    igareck публикует white-list конфиги, которые и есть входные RU VPS.
    Предпочитаем SNI gosuslugi.ru и источники igareck_, исключаем Yandex
    Cloud (его AS блокируется).
    """
    prefixes = tuple(relay_config.get("require_source_prefixes") or ["igareck_"])
    preferred_sni = [
        str(item).strip().lower()
        for item in (relay_config.get("preferred_sni") or ["gosuslugi.ru"])
        if str(item).strip()
    ]
    # Для входа в whitelist-цепочку SNI должен быть из белого списка
    # оператора. Если preferred_sni задан, остальные узлы не подходят:
    # это не «красивый бонус», а условие прохождения первого прыжка.
    require_preferred = bool(relay_config.get("require_preferred_sni", True))
    excluded_sni = [
        str(item).strip().lower()
        for item in (relay_config.get("exclude_sni_suffixes") or [
            "yandex", "yandexcloud.net", "cloud.yandex",
        ])
        if str(item).strip()
    ]

    # TCP-fallback проверяет только открытый порт. Такой узел нельзя
    # ставить входным relay: он может быть мёртвым прокси.
    allow_tcp_fallback = bool(relay_config.get("allow_tcp_fallback", False))
    real_statuses = ("passed", "semi-passed")

    best: tuple[tuple[int, int, int, int], ServerRecord, str] | None = None
    for record in records:
        if not record.delays:
            continue
        if prefixes and not _has_source_prefix(record, prefixes):
            continue

        # TCP+Vision совместимее с iOS и старыми ядрами, поэтому он
        # приоритетнее XHTTP при выборе входного RU relay.
        for profile in ("tcp", "xhttp"):
            if profile not in record.delays or profile not in record.variants:
                continue
            status = record.statuses.get(profile, "")
            if not allow_tcp_fallback and status not in real_statuses:
                continue
            outbound = record.variants[profile]
            sni = _server_name(outbound)
            host = outbound_identity(outbound)[0].lower()
            if any(marker in sni or marker in host for marker in excluded_sni):
                continue
            matches_preferred = any(
                marker in sni or marker in host for marker in preferred_sni
            )
            if require_preferred and preferred_sni and not matches_preferred:
                continue
            preferred = 0 if matches_preferred else 1
            security_rank = 0 if _security(outbound) == "reality" else 1
            source_rank = 0 if _has_source_prefix(record, prefixes) else 1
            score = (preferred, security_rank, source_rank, record.delays[profile])
            if best is None or score < best[0]:
                best = (score, record, profile)

    if best is None:
        return None, None, None

    _score, record, profile = best
    outbound = copy.deepcopy(record.variants[profile])
    outbound["tag"] = "wl-relay"
    outbound["_profile"] = profile
    outbound["_source"] = ", ".join(sorted(record.sources))
    logger.info(
        "Whitelist: выбран RU relay %s:%s (%s, SNI=%s, %d ms)",
        outbound_identity(outbound)[0],
        outbound_identity(outbound)[1],
        profile,
        _server_name(outbound) or "-",
        record.delays[profile],
    )
    return outbound, record.identity, record.links.get(profile)


def _write_txt(mode: str, links: list[str], config: dict) -> None:
    """
    Пишет два TXT-варианта одного режима.

    INCY и Happ используют разный синтаксис фрагментации в share-ссылке,
    поэтому ``auto_all.txt``/``whitelist_all.txt`` — для INCY, а
    ``*_all_happ.txt`` — для Happ.
    """
    output_dir = config['paths']['output_dir']
    os.makedirs(output_dir, exist_ok=True)

    for client, suffix in (("incy", ""), ("happ", "_happ")):
        txt_content = generate_txt(links, client=client)
        output_txt = os.path.join(output_dir, f"{mode}_all{suffix}.txt")
        with open(output_txt, "w", encoding="utf-8") as file:
            file.write(txt_content)
        logger.info(
            "💾 %s: %d ссылок (%s)", output_txt, len(links), client
        )


async def _collect(mode: str, config: dict, allow_tls_vision: bool = False) -> list[ServerRecord]:
    logger.info(f"=== СБОР ДЛЯ РЕЖИМА: {mode} ===")

    loader = SourceLoader()
    sources = loader.get_sources(mode)
    if not sources:
        logger.error(f"Для режима {mode} нет источников")
        return []

    urls = [source["url"] for source in sources]
    source_by_url = {source["url"]: source for source in sources}

    async with ConfigDownloader() as downloader:
        raw_texts = await downloader.fetch_many(urls)

    records = _parse_sources(
        mode,
        raw_texts,
        source_by_url,
        allow_tls_vision=allow_tls_vision,
    )
    if not records:
        logger.error(f"❌ Для режима {mode} не найдено ни одного подходящего сервера")
        return []

    aggregator_cfg = config.get("aggregator", {}) or {}
    latency_config = dict(
        aggregator_cfg.get("latency_check")
        or config.get("latency_check")
        or {}
    )
    env_binary = os.getenv("XRAY_KNIFE_BIN", "").strip()
    if env_binary:
        # Переменная окружения важнее config.yaml: так локальная сборка
        # может указать полный путь к бинарнику.
        latency_config["binary"] = env_binary
    env_fragment = os.getenv("XRAY_KNIFE_FRAGMENT", "").strip()
    if env_fragment:
        # В workflow можно переопределить фрагментацию без правки config.yaml.
        latency_config["fragment"] = env_fragment
    if not latency_config.get("fragment"):
        latency_config["fragment"] = "tlshello,100-200,10-20"

    records = await _rank_records_async(records, latency_config)
    if not records:
        logger.error(
            f"❌ Для режима {mode} проверка задержки не дала живых серверов. "
            "TXT будет собран из непроверенных ссылок."
        )
        return []

    skip_latency = str(os.getenv("SKIP_LATENCY", "")).lower() in ("1", "true", "yes", "on")
    real_checked = any(
        status in ("passed", "semi-passed")
        for record in records
        for status in record.statuses.values()
    )
    if (
        bool(aggregator_cfg.get("synthesize_alternate_profiles", True))
        and not skip_latency
        and real_checked
    ):
        records = await _synthesize_and_rank(
            records,
            latency_config,
            int(aggregator_cfg.get("synthesis_candidates", 60)),
        )
    elif not real_checked:
        logger.warning(
            "Синтез второго профиля пропущен: нет реальной проверки "
            "(SKIP_LATENCY или TCP-fallback)"
        )

    logger.info(f"🏆 Живых серверов: {len(records)}")
    for record in records[:10]:
        host, port, _uuid = record.identity
        sources_text = ",".join(sorted(record.sources))
        profiles = "+".join(record.alive_profiles)
        logger.info(
            "    %5d ms  %s:%s  [%s] (%s)",
            record.delay_ms, host, port, profiles, sources_text,
        )
    return records


async def _process_auto(config: dict) -> list[ServerRecord]:
    records = await _collect("auto", config, allow_tls_vision=False)
    if not records:
        return []

    max_json = max(1, int(config['aggregator'].get('json_max_outbounds', 30)))
    max_servers = max(1, int(config['aggregator'].get('max_servers_per_subscription', 30)))

    entries = _builder_entries(records, max_json)
    template_path = os.path.join(config['paths']['templates_dir'], "auto_template.json")

    try:
        final_config = build_subscription(
            entries,
            template_path,
            max_outbounds=max_json,
            allow_tls=False,
            allow_xhttp_tls=True,
            extra_outbounds=[ob for ob in [_ycf_outbound()] if ob],
        )
    except ValueError as exc:
        logger.error(f"❌ JSON для режима auto не собран: {exc}")
        logger.error("Старый auto.json оставлен без изменений.")
    else:
        output_json = os.path.join(config['paths']['output_dir'], "auto.json")
        os.makedirs(os.path.dirname(output_json), exist_ok=True)
        save_config(final_config, output_json)
        profile_count = sum(
            1 for ob in final_config["outbounds"] if ob.get("protocol") == "vless"
        )
        logger.info(
            "💾 %s: %d серверов, %d outbound-профилей, %d байт",
            output_json,
            len(entries),
            profile_count,
            os.path.getsize(output_json),
        )

    _write_txt("auto", _txt_links(records, max_servers), config)
    return records


async def _process_whitelist(
    config: dict,
    auto_records: list[ServerRecord],
) -> None:
    aggregator_cfg = config.get("aggregator", {}) or {}
    whitelist_cfg = (
        aggregator_cfg.get("whitelist")
        or config.get("whitelist")
        or {}
    )
    relay_cfg = whitelist_cfg.get("relay", {}) or {}
    max_json = max(1, int(whitelist_cfg.get("json_max_servers", 10)))
    max_servers = max(1, int(config['aggregator'].get('max_servers_per_subscription', 30)))

    allow_tls_vision = bool(whitelist_cfg.get("allow_tls_vision", True))
    whitelist_records = await _collect(
        "whitelist",
        config,
        allow_tls_vision=allow_tls_vision,
    )

    explicit_link = (
        os.getenv("RU_RELAY_LINK", "").strip()
        or str(relay_cfg.get("link", "")).strip()
    )

    relay_outbound: dict | None = None
    relay_identity: tuple[str, int, str] | None = None
    relay_link: str | None = None

    if explicit_link:
        relay_outbound = _relay_from_link(explicit_link)
        if relay_outbound is not None:
            relay_identity = outbound_identity(relay_outbound)
            relay_link = explicit_link
            logger.info(
                "Whitelist: используется явный RU relay %s:%s (SNI=%s)",
                relay_identity[0],
                relay_identity[1],
                _server_name(relay_outbound) or "-",
            )
        else:
            logger.warning("Явный RU relay не разобран, пробую igareck-узел")

    if relay_outbound is None:
        relay_outbound, relay_identity, relay_link = _relay_from_records(
            whitelist_records,
            relay_cfg,
        )

    # Цели: лучшие зарубежные серверы из auto, а не сами RU relay-узлы.
    if bool(whitelist_cfg.get("targets_from_auto", True)) and auto_records:
        targets = [r for r in auto_records if r.identity != relay_identity]
    else:
        targets = [r for r in whitelist_records if r.identity != relay_identity]
    targets = targets[:max_json]

    # Цепочка имеет смысл только на реально проверенных серверах:
    # TCP-fallback/SKIP_LATENCY проверяют лишь порт.
    real_statuses = ("passed", "semi-passed")
    targets = [
        record for record in targets
        if any(status in real_statuses for status in record.statuses.values())
    ]
    if not targets:
        logger.error(
            "Whitelist: нет реально проверенных целевых серверов. "
            "whitelist.json оставлен прежним."
        )
        return

    if relay_outbound is None and not bool(whitelist_cfg.get("allow_without_relay", False)):
        logger.error(
            "Whitelist: RU relay не найден. Задайте RU_RELAY_LINK (VLESS Reality "
            "SNI=gosuslugi.ru на Timeweb/VDSina/Selectel) или живой igareck-узел. "
            "whitelist.json и whitelist_all*.txt оставлены прежними, чтобы не "
            "отдавать клиентам конфиг без обхода белых списков."
        )
        return

    target_links = _txt_links(targets, max_json)
    if relay_link:
        _write_txt("whitelist", [relay_link] + target_links, config)
    elif whitelist_records:
        _write_txt("whitelist", _txt_links(whitelist_records, max_servers), config)
    else:
        logger.warning(
            "Whitelist: проверенных ссылок нет, whitelist_all*.txt оставлены прежними"
        )

    entries = _builder_entries(targets, max_json)
    template_path = os.path.join(config['paths']['templates_dir'], "whitelist_template.json")

    try:
        final_config = build_subscription(
            entries,
            template_path,
            max_outbounds=max_json,
            allow_tls=True,
            allow_xhttp_tls=True,
            relay=relay_outbound,
            extra_outbounds=[],
        )
    except ValueError as exc:
        logger.error(f"❌ JSON для режима whitelist не собран: {exc}")
        logger.error("Старый whitelist.json оставлен без изменений.")
        return

    output_json = os.path.join(config['paths']['output_dir'], "whitelist.json")
    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    save_config(final_config, output_json)

    relay_tag = "wl-relay" if relay_outbound else "none"
    chained = sum(
        1 for ob in final_config["outbounds"]
        if ((ob.get("streamSettings") or {}).get("sockopt") or {}).get("dialerProxy") == relay_tag
    )
    logger.info(
        "💾 %s: %d серверов, %d цепочек %s → зарубежный VPS, %d байт",
        output_json,
        len(entries),
        chained,
        relay_tag,
        os.path.getsize(output_json),
    )


async def main():
    config_path = os.getenv("AGGREGATOR_CONFIG", "aggregator/config.yaml")
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    modes = list(config['aggregator'].get('modes') or [])
    auto_records: list[ServerRecord] = []

    if "auto" in modes:
        auto_records = await _process_auto(config)

    if "whitelist" in modes:
        await _process_whitelist(config, auto_records)


if __name__ == "__main__":
    asyncio.run(main())

````

## `HAPP_INCY.md` — Документация Happ/INCY

````markdown
# Happ, INCY и v2RayTun: подписка, заголовки и импорт

Воркер отдаёт один и тот же набор серверов в нескольких форматах:

| Маршрут | Формат | Кому |
|---|---|---|
| `/sub/auto.json` | полный Xray JSON | Happ, INCY, v2RayTun |
| `/sub/whitelist.json` | Xray JSON с цепочкой RU relay | Happ, INCY, v2RayTun |
| `/sub/auto.txt` | share-ссылки с фрагментацией INCY | INCY |
| `/sub/auto_happ.txt` | share-ссылки с фрагментацией Happ | Happ |
| `/sub/whitelist.txt` | whitelist-ссылки INCY | INCY |
| `/sub/whitelist_happ.txt` | whitelist-ссылки Happ | Happ |
| `/sub/webrtc.txt` | инструкция + SOCKS5 | ручной WebRTC-профиль |

Любой маршрут требует персональный `?token=<TOKEN>`. Без токена или после
срока действия возвращается `403 forbidden`.

---

## 1. HTTP-заголовки подписки

Воркер добавляет заголовки к JSON и TXT-ответам. Клиент читает их при
каждом обновлении подписки.

| Заголовок | Happ | INCY | Что делает |
|---|---|---|---|
| `profile-title` | да | да | имя подписки, максимум 25 символов |
| `profile-update-interval` | да | да | автообновление в часах (`1`) |
| `subscription-userinfo` | да | да | трафик и дата окончания |
| `profile-web-page-url` | да | да | кнопка «сайт» / тариф |
| `support-url` | да | да | кнопка поддержки в Telegram |
| `hide-url` | да | — | скрывает URL в «Поделиться» (Happ) |
| `subscription-always-hwid-enable` | да | — | HWID нельзя отключить в настройках |
| `no-limit-xhttp-enabled` | да | — | снимает лимит RAM для XHTTP (Happ iOS) |
| `sub-expire` | да | — | включает баннер окончания подписки |
| `sub-expire-button-link` | да | — | ссылка кнопки «Продлить» |
| `announce` | да | да | текст объявления, можно в base64 |

Пример реального ответа:

```http
HTTP/2 200
content-type: application/json
profile-title: VPN Constructor
profile-update-interval: 1
subscription-userinfo: upload=0; download=0; total=107374182400; expire=1796687999
hide-url: 1
subscription-always-hwid-enable: 1
no-limit-xhttp-enabled: 1
```

### Важное про `sub-expire`

В актуальной документации Happ `sub-expire` — это **boolean-включатель**,
а не текст:

```http
sub-expire: 1
sub-expire-button-link: https://t.me/your_bot
```

Happ сам показывает локализованное сообщение «Ваша подписка заканчивается
через N д.» за 3 дня до окончания. Поэтому воркер отправляет `sub-expire: 1`
только когда до окончания осталось не больше `SUB_EXPIRE_DAYS` дней.

Текст вида «Подписка истекает 2026-12-07. Продлите вовремя.» передаётся
отдельным заголовком `announce` в base64 — его понимают и Happ, и INCY.
Так кириллица не ломает HTTP-заголовки (в них допустим только latin-1).

### `subscription-userinfo`

```text
upload=0; download=0; total=107374182400; expire=<unix_timestamp>
```

- `total` — 100 GiB по умолчанию (`SUBSCRIPTION_TOTAL_BYTES`);
- `expire` — конец дня `expires_at` из `clients.json` в Unix-секундах;
- если дата в `clients.json` некорректна, поле `expire` не отправляется.

### `profile-title`

Ограничение — 25 символов. Если задать кириллическое имя, воркер
автоматически кодирует его как `base64:<UTF-8>`, потому что Happ и INCY
поддерживают такой формат.

---

## 2. Два профиля на один сервер

Для каждого живого сервера в `auto.json` может быть два outbound:

| Профиль | Транспорт | Для кого |
|---|---|---|
| `proxy-xhttp-N` | XHTTP + Reality или XHTTP + TLS (Cloudflare) | **Android**, десктоп |
| `proxy-tcp-N` | TCP + Reality/TLS + Vision + фрагментация | **iOS**, старые ядра |

Номер `N` общий: `proxy-xhttp-7` и `proxy-tcp-7` — один и тот же сервер.
Если один профиль не подключается, переключитесь на второй с тем же номером.

| Клиент | Приоритет | Если не работает |
|---|---|---|
| Happ Android | `proxy-xhttp-*` | `proxy-tcp-*` |
| **Happ iOS** | **`proxy-tcp-*`** | `proxy-xhttp-*`, если ядро свежее |
| INCY Android | `proxy-xhttp-*` | `proxy-tcp-*` |
| **INCY iOS** | **`proxy-tcp-*`** | `proxy-xhttp-*` |
| v2RayTun Android | `proxy-xhttp-*` | `proxy-tcp-*` |
| v2RayTun iOS | `proxy-tcp-*` | `proxy-xhttp-*` |

Причины:

- XHTTP+Reality маскирует трафик под обычный HTTP/2 и лучше проходит ТСПУ;
- XHTTP+Reality **не поддерживается на iOS** в Happ — там нужен TCP+Vision;
- Vision + фрагментация ClientHello надёжнее на старых Network Extension;
- `fingerprint: firefox` стоит во всех Reality/TLS-профилях.

Пара `proxy-xhttp-N` + `proxy-tcp-N` появляется только тогда, когда
агрегатор реально проверил оба транспорта на одном и том же сервере.
Если источник опубликовал только TCP, второго профиля не будет: это не
ошибка формата, а отсутствие подтверждённого транспорта. Docs-таблица
выше описывает приоритеты для случая, когда пара есть.

---

## 3. Фрагментация в TXT-ссылках

У INCY и Happ разный синтаксис, поэтому файлов два.

### INCY

```text
/sub/auto.txt
/sub/whitelist.txt
```

К TCP-ссылкам добавляются query-параметры:

```text
&fragmentPackets=tlshello&fragmentLength=100-200&fragmentInterval=10-20
```

Полный пример:

```text
vless://UUID@HOST:443?security=reality&sni=example.com&type=tcp&flow=xtls-rprx-vision&pbk=...&sid=...&fragmentPackets=tlshello&fragmentLength=100-200&fragmentInterval=10-20#🇩🇪 Berlin
```

### Happ

```text
/sub/auto_happ.txt
/sub/whitelist_happ.txt
```

К TCP-ссылкам добавляется один параметр:

```text
&fragment=100-200,10-20,tlshello
```

Формат Happ: `fragment=length,interval,packets[,maxSplit]`.

### Что важно

- фрагментация добавляется **только TCP/raw-ссылкам**;
- XHTTP-ссылки не меняются: у них уже есть свои `path`, `host`, `mode`;
- если источник уже прислал `fragment`, `fragmentPackets`,
  `fragmentLength`, `fragmentInterval` или `fragmentMaxSplit`, они
  заменяются, а не дублируются;
- имена серверов и флаги стран сохраняются в обоих файлах.

---

## 4. Импорт в Happ

### Android

1. Установите Happ из Google Play или с официального сайта.
2. На главном экране нажмите **«+»**.
3. Выберите **«Добавить подписку»**.
4. Вставьте:
   ```text
   https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>
   ```
   Это предпочтительный вариант: Happ получает полный Xray-конфиг
   с двумя профилями на сервер.
5. Дождитесь загрузки и выберите `proxy-xhttp-1`.
6. Если не подключается — `proxy-tcp-1`.

Если Happ не понимает JSON-подписку в вашей версии, используйте
`/sub/auto_happ.txt?token=<TOKEN>` — там те же серверы share-ссылками
с правильной фрагментацией Happ.

### iOS

1. Установите Happ из App Store.
2. **«+»** → **«Подписка»**.
3. Вставьте `/sub/auto.json?token=<TOKEN>`.
4. Разрешите добавление VPN-конфигурации (Face ID / Touch ID).
5. Выберите **`proxy-tcp-1`** (Vision + fragment).
6. Включите подключение.

На iOS не выбирайте `proxy-xhttp-*`: XHTTP+Reality там не работает.
Если хочется share-ссылки, используйте `/sub/auto_happ.txt?token=<TOKEN>`.

---

## 5. Импорт в INCY

### Android

1. Установите INCY.
2. На главном экране нажмите **«+»**.
3. Выберите **«Добавить подписку»** / **«Импорт из ссылки»**.
4. Вставьте:
   ```text
   https://vpn-auth.de1.netrun.io/sub/auto.txt?token=<TOKEN>
   ```
   INCY отлично работает с share-ссылками и читает
   `fragmentPackets/fragmentLength/fragmentInterval` прямо из URL.
5. Сохраните и выберите `proxy-xhttp-1`.
6. Нажмите **«Подключить»**.

JSON-вариант `/sub/auto.json?token=<TOKEN>` тоже поддерживается.

### iOS

1. Установите INCY из App Store.
2. **«+»** → **«Подписка»**.
3. Вставьте `/sub/auto.txt?token=<TOKEN>`.
4. Разрешите добавление VPN-конфигурации.
5. Выберите `proxy-tcp-1`.

Если импорт по ссылке не появляется, скопируйте ссылку и используйте
**«Импорт из буфера обмена»**.

---

## 6. v2RayTun

1. **«+»** → **«Импорт подписки»**.
2. Вставьте `/sub/auto.json?token=<TOKEN>` (или TXT-вариант).
3. На Android выберите `proxy-xhttp-1`, на iOS — `proxy-tcp-1`.

---

## 7. Whitelist-подписка и RU relay

Ссылки:

```text
https://vpn-auth.de1.netrun.io/sub/whitelist.json?token=<TOKEN>
https://vpn-auth.de1.netrun.io/sub/whitelist.txt?token=<TOKEN>
https://vpn-auth.de1.netrun.io/sub/whitelist_happ.txt?token=<TOKEN>
```

Схема:

```text
телефон → RU VPS (разрешённый IP/SNI) → зарубежный VPS → интернет
```

В `whitelist.json`:

- первый outbound — **целевой** зарубежный сервер, а не relay;
- у каждого `wl-proxy-*` есть
  `streamSettings.sockopt.dialerProxy = "wl-relay"`;
- `wl-relay` идёт последним среди proxy-outbound и напрямую, без `sockopt`;
- `geoip:ru` и `geosite:category-ru` отсутствуют полностью.

Порядок outbound важен: первый outbound становится default. Если бы
первым был `wl-relay`, клиент пустил бы весь трафик в RU VPS без второго
плеча. Поэтому цепочка задаётся через `dialerProxy`, а не порядком.

> **Важно.** В TXT-варианте (`/sub/whitelist.txt` и
> `/sub/whitelist_happ.txt`) цепочку `dialerProxy` выразить нельзя: это
> просто список share-ссылок, где первой идёт RU relay, а затем целевые
> серверы. Для настоящей цепочки «клиент → RU relay → зарубежный VPS»
> используйте **`whitelist.json`**.

### Требования к RU relay

- Timeweb, VDSina или Selectel (не Yandex Cloud: его AS блокируется);
- VLESS + Reality + Vision;
- SNI `gosuslugi.ru` или другой домен из белого списка оператора;
- порт 443.

### Как включить

1. Поднимите Xray на RU VPS.
2. Соберите ссылку:
   ```text
   vless://<UUID>@<RU_IP>:443?security=reality&sni=gosuslugi.ru&pbk=<PUBLIC_KEY>&sid=<SHORT_ID>&type=tcp&flow=xtls-rprx-vision#RU-Relay
   ```
3. В GitHub → **Settings → Secrets and variables → Actions** создайте
   секрет `RU_RELAY_LINK`.
4. Запустите workflow. В логе будет:
   ```text
   Whitelist: используется явный RU relay <IP>:443 (SNI=gosuslugi.ru)
   💾 web/subscriptions/whitelist.json: 10 серверов, 10 цепочек wl-relay → зарубежный VPS
   ```

### Автоматический fallback

Если `RU_RELAY_LINK` не задан, агрегатор ищет в `whitelist_records` узел:

- из источника `igareck_*`;
- с SNI из `preferred_sni` (`gosuslugi.ru`);
- прошедший реальную проверку `passed`/`semi-passed`;
- не из Yandex Cloud.

Для этого в `aggregator/config.yaml`:

```yaml
relay:
  preferred_sni:
    - "gosuslugi.ru"
  require_preferred_sni: true
  allow_tcp_fallback: false
```

`require_preferred_sni: true` означает: узел с другим SNI не будет выбран
входом цепочки. Если подходящего relay нет, `whitelist.json` и
`whitelist_all*.txt` **не перезаписываются** — лучше старый рабочий
конфиг, чем цепочка без входа.

---

## 8. Cloudflare CDN и XHTTP

Для сервера за Cloudflare используется `proxy-xhttp-*` с
`security: "tls"`. В JSON сохраняются:

- `xhttpSettings.host` — домен CDN (например, `web-tomcat.pages.dev`);
- `xhttpSettings.path` — путь из share-ссылки;
- `xhttpSettings.mode: "stream-one"`;
- `tlsSettings.serverName` — SNI CDN;
- `tlsSettings.fingerprint: "firefox"`.

Клиент видит только edge-IP Cloudflare, а не адрес VPS. Такой профиль
работает в Happ Android и INCY. На Happ iOS используйте парный
`proxy-tcp-*`.

---

## 9. Yandex Cloud Functions (`proxy-ycf-1`)

`functions.yandexcloud.net` часто в белых списках операторов. Если у вас
есть SOCKS5-релей внутри Yandex Cloud Functions, задайте секрет:

```text
YANDEX_FUNCTIONS_SOCKS=socks5://user:password@host:1080
```

Агрегатор добавит в `auto.json` **дополнительный** outbound
`proxy-ycf-1`. Reality-профили при этом не заменяются. YCF не даёт
гарантии скорости и не подходит для видео — это резерв, когда основные
профили недоступны.

---

## 10. WebRTC-туннель (`/sub/webrtc.txt`)

Экспериментальный ручной fallback. Автоматической подписки нет.

```text
https://vpn-auth.de1.netrun.io/sub/webrtc.txt?token=<TOKEN>
```

Маршрут отдаёт инструкцию и SOCKS5-адрес из `WEBRTC_SOCKS5`:

```text
WEBRTC_SOCKS5=socks5://user:pass@host:1080
```

Схема:

1. На зарубежном VPS поднимите WebRTC-бридж (TURN/STUN + DataChannel).
2. Запустите WebRTC-клиент, который отдаёт локальный SOCKS5.
3. Создайте комнату в Телемост/VK Calls и подключите клиент и бридж.
4. В Happ/INCY добавьте SOCKS5-профиль вручную.
5. Проверьте: `curl https://ipinfo.io/ip` показывает зарубежный IP.

Ограничения: скорость зависит от медиа-сервиса и NAT, нет health-check и
автопереключения. Только аварийный вариант.

---

## 11. Проверка заголовков

### PowerShell

```powershell
$url = "https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>"
$r = Invoke-WebRequest $url -UseBasicParsing

$r.StatusCode
$r.Headers['Content-Type']
$r.Headers['profile-title']
$r.Headers['profile-update-interval']
$r.Headers['subscription-userinfo']
$r.Headers['hide-url']
$r.Headers['subscription-always-hwid-enable']
$r.Headers['no-limit-xhttp-enabled']
```

Ожидаемо:

```text
200
application/json
VPN Constructor
1
upload=0; download=0; total=107374182400; expire=1796687999
1
1
1
```

### curl

```bash
curl -sS -D - -o /dev/null \
  "https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>"
```

Проверка TXT:

```bash
curl -sS "https://vpn-auth.de1.netrun.io/sub/auto.txt?token=<TOKEN>" | head -n 2
curl -sS "https://vpn-auth.de1.netrun.io/sub/auto_happ.txt?token=<TOKEN>" | head -n 2
```

В INCY-файле должны быть `fragmentPackets=tlshello`,
`fragmentLength=100-200`, `fragmentInterval=10-20`.
В Happ-файле — `fragment=100-200,10-20,tlshello`.

Проверка whitelist-цепочки:

```powershell
$wl = (Invoke-WebRequest "https://vpn-auth.de1.netrun.io/sub/whitelist.json?token=<TOKEN>" -UseBasicParsing).Content | ConvertFrom-Json

$wl.outbounds | Select-Object -First 3 tag, protocol
$wl.outbounds | Where-Object tag -eq 'wl-relay' |
    Select-Object tag, @{n='sni';e={$_.streamSettings.realitySettings.serverName}}
$wl.outbounds | Where-Object { $_.streamSettings.sockopt.dialerProxy -eq 'wl-relay' } |
    Select-Object tag, @{n='dialerProxy';e={$_.streamSettings.sockopt.dialerProxy}}
```

Ожидаемо:

- первый outbound — `wl-proxy-*`;
- `wl-relay` присутствует и имеет SNI `gosuslugi.ru`;
- все `wl-proxy-*` имеют `dialerProxy = wl-relay`;
- в JSON нет `geoip:ru` и `geosite:category-ru`.

Проверка профилей:

```powershell
$cfg = (Invoke-WebRequest "https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>" -UseBasicParsing).Content | ConvertFrom-Json
$cfg.outbounds | Where-Object protocol -eq 'vless' |
    Select-Object tag,
                  @{n='network';e={$_.streamSettings.network}},
                  @{n='security';e={$_.streamSettings.security}},
                  @{n='flow';e={$_.settings.vnext[0].users[0].flow}},
                  @{n='fragment';e={$_.fragment.packets}},
                  @{n='fp';e={$_.streamSettings.realitySettings.fingerprint}}
```

Ожидаемо: `proxy-xhttp-N` и `proxy-tcp-N` с одинаковым `N`, у TCP
`flow=xtls-rprx-vision` и `fragment=tlshello`, у всех `fp=firefox`.

---

## 12. Если не подключается

1. **Проверьте срок токена.** Истёкший токен даёт `403 forbidden`.
2. **Попробуйте парный профиль** с тем же номером.
3. **iOS:** только `proxy-tcp-*`, XHTTP+Reality там не работает.
4. **Удалите старый профиль** и импортируйте заново: клиенты кэшируют
   подписку.
5. **Отключите другие VPN/Always-on VPN.**
6. **Смените сеть:** некоторые операторы режут нестандартные порты.
7. **Обновите Happ/INCY:** XHTTP и Vision требуют свежего Xray-core.
8. **Проверьте время на устройстве:** ошибка >2 минут ломает TLS/Reality.
9. **Whitelist:** убедитесь, что в `whitelist.json` есть `wl-relay`,
   а у целей — `dialerProxy: "wl-relay"`.
10. **Заголовки не видны:** проверьте, что запрос идёт на воркер, а не на
    GitHub Pages. GitHub Pages не отдаёт динамические заголовки и не
    проверяет токены.

````
