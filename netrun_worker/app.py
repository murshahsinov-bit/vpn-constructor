# -*- coding: utf-8 -*-
"""
Netrun worker: выдаёт подписку только клиентам с действительным токеном.

Маршрут:
    GET /sub/auto.json?token=<token>

Источники данных:
    clients.json  — база клиентов (локальный файл или переменная CLIENTS_JSON)
    auto.json     — собранная подписка (локальный файл или GitHub/CONFIG_URL)

Сервис не является VPN/прокси-сервером: он только отдаёт JSON-подписку.
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
from datetime import date
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
AUTO_FILE = Path(os.getenv("AUTO_FILE", str(BASE_DIR / "auto.json")))

CLIENTS_JSON = os.getenv("CLIENTS_JSON", "").strip()
CONFIG_URL = os.getenv("CONFIG_URL", "").strip()

GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip() or "main"
CONFIG_PATH = os.getenv("CONFIG_PATH", "web/subscriptions/auto.json").strip() or "web/subscriptions/auto.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
HTTP_USER_AGENT = "vpn-constructor-netrun-worker/1.0"

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
# Получение auto.json
# ---------------------------------------------------------------------------

_config_lock = threading.Lock()
_config_cache: dict[str, Any] = {
    "data": None,
    "timestamp": 0.0,
    "source": None,
}


def _github_api_url() -> str | None:
    if not GITHUB_REPO:
        return None
    path = quote(CONFIG_PATH, safe="/")
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}?ref={quote(GITHUB_BRANCH, safe='')}"


def _github_raw_url() -> str | None:
    if not GITHUB_REPO:
        return None
    return (
        f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
        f"{quote(GITHUB_BRANCH, safe='')}/{quote(CONFIG_PATH, safe='/')}"
    )


def _jsdelivr_url() -> str | None:
    if not GITHUB_REPO:
        return None
    return (
        f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@"
        f"{quote(GITHUB_BRANCH, safe='')}/{quote(CONFIG_PATH, safe='/')}"
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


def _remote_candidates() -> list[tuple[str, dict[str, str]]]:
    """URL-кандидаты и заголовки. GitHub API идёт первым для приватных репозиториев."""
    candidates: list[tuple[str, dict[str, str]]] = []
    seen: set[str] = set()

    def add(url: str | None, headers: dict[str, str] | None = None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        candidates.append((url, headers or {}))

    api_url = _github_api_url()
    if api_url:
        headers = {
            "Accept": "application/vnd.github.raw",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": HTTP_USER_AGENT,
        }
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        add(api_url, headers)

    if CONFIG_URL:
        add(CONFIG_URL, {"User-Agent": HTTP_USER_AGENT})
        add(_mirror_for_raw_url(CONFIG_URL), {"User-Agent": HTTP_USER_AGENT})

    add(_github_raw_url(), {"User-Agent": HTTP_USER_AGENT})
    add(_jsdelivr_url(), {"User-Agent": HTTP_USER_AGENT})

    return candidates


def _valid_json(data: bytes) -> bool:
    try:
        json.loads(data)
        return True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


def _download_config(url: str, headers: dict[str, str]) -> bytes:
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.content
    if not data:
        raise ValueError("пустой ответ")
    if len(data) > MAX_CONFIG_BYTES:
        raise ValueError(f"ответ больше {MAX_CONFIG_BYTES} байт")
    if not _valid_json(data):
        raise ValueError("ответ не является JSON")
    return data


def _read_local_config() -> bytes | None:
    try:
        data = AUTO_FILE.read_bytes()
    except OSError:
        return None
    if data and len(data) <= MAX_CONFIG_BYTES and _valid_json(data):
        return data
    if data:
        logger.error("Локальный %s не является корректным JSON", AUTO_FILE)
    return None


def get_auto_json() -> tuple[bytes, str, bool]:
    """
    Возвращает (data, source, stale).

    Порядок: свежий кэш -> удалённый источник -> локальный файл -> устаревший кэш.
    """
    now = time.monotonic()

    with _config_lock:
        cached = _config_cache["data"]
        cached_at = float(_config_cache["timestamp"] or 0.0)
        cached_source = _config_cache["source"]
        if cached and CACHE_TTL > 0 and now - cached_at < CACHE_TTL:
            return cached, str(cached_source or "cache"), False

    errors: list[str] = []
    for url, headers in _remote_candidates():
        try:
            data = _download_config(url, headers)
            with _config_lock:
                _config_cache.update(data=data, timestamp=now, source=url)
            logger.info("Подписка обновлена из %s (%d байт)", url, len(data))
            return data, url, False
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {exc}")
            logger.warning("Не удалось получить подписку из %s: %s", url, exc)

    local = _read_local_config()
    if local is not None:
        with _config_lock:
            _config_cache.update(data=local, timestamp=now, source=str(AUTO_FILE))
        logger.info("Используется локальная подписка %s (%d байт)", AUTO_FILE, len(local))
        return local, str(AUTO_FILE), False

    with _config_lock:
        stale = _config_cache["data"]
        stale_source = _config_cache["source"]
    if stale:
        logger.warning("Все источники недоступны, отдаю устаревший кэш")
        return stale, str(stale_source or "stale-cache"), True

    raise RuntimeError("; ".join(errors) or "нет доступного источника auto.json")


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


@app.get("/")
def index() -> Response:
    return jsonify(
        {
            "service": "vpn-subscription-gateway",
            "status": "ok",
            "endpoint": "/sub/auto.json?token=<token>",
        }
    )


@app.get("/healthz")
def healthz() -> Response:
    return jsonify({"status": "ok"})


@app.get("/sub/auto.json")
def subscription() -> Response:
    token = (request.args.get("token") or "").strip()

    client = authorize_token(token)
    if client is None:
        logger.warning("403: недействительный или истёкший токен fp=%s", _token_fingerprint(token))
        return jsonify({"error": "forbidden"}), 403

    try:
        data, _source, stale = get_auto_json()
    except RuntimeError as exc:
        logger.error("503: подписка недоступна: %s", exc)
        return jsonify({"error": "subscription source unavailable"}), 503

    response = Response(data, mimetype="application/json")
    response.headers["Content-Type"] = "application/json"
    if stale:
        response.headers["X-Config-Stale"] = "1"

    logger.info("200: подписка выдана fp=%s", _token_fingerprint(token))
    return response


@app.errorhandler(404)
def not_found(_error: Exception) -> tuple[Response, int]:
    return jsonify({"error": "not found"}), 404


@app.errorhandler(405)
def method_not_allowed(_error: Exception) -> tuple[Response, int]:
    return jsonify({"error": "method not allowed"}), 405


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
