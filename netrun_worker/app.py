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
