#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manager.py — автономное управление клиентами VPN-Конструктора.

Скрипт использует только стандартную библиотеку Python (без pip install).
Данные клиентов хранятся в clients.json рядом с этим файлом.

Примеры:
    python manager.py add --name "Иван" --days 30
    python manager.py renew --name "Иван" --days 30
    python manager.py stats
    python manager.py sync
    python manager.py check --status active
    python manager.py check --status expired

Ссылки клиентов ведут на Netrun:
    https://<сервис>.netrun.io/sub/auto.json?token=...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Пути и настройки
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CLIENTS_FILE = BASE_DIR / "clients.json"
STATS_FILE = BASE_DIR / "stats.txt"
ENV_FILE = BASE_DIR / ".env"

NETRUN_DIR = BASE_DIR / "netrun_worker"
NETRUN_CLIENTS_FILE = NETRUN_DIR / "clients.json"
NETRUN_AUTO_FILE = NETRUN_DIR / "auto.json"
UPSTREAM_AUTO_FILE = BASE_DIR / "web" / "subscriptions" / "auto.json"

DATE_FORMAT = "%Y-%m-%d"
TOKEN_LENGTH = 32


# ---------------------------------------------------------------------------
# Цветной вывод
# ---------------------------------------------------------------------------

class C:
    """ANSI-коды для цветного вывода в терминале."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"
    WHITE = "\033[97m"


def _enable_windows_ansi() -> None:
    """Включает поддержку ANSI-кодов в консоли Windows 10+."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # STD_OUTPUT_HANDLE = -11, ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def _init_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    _enable_windows_ansi()


_init_console()

USE_COLOR = (
    sys.stdout.isatty() or os.getenv("FORCE_COLOR", "").lower() in ("1", "true", "yes")
) and not os.getenv("NO_COLOR")


def paint(text: str, *styles: str, enabled: bool | None = None) -> str:
    """Оборачивает текст ANSI-кодами, если цвет включён."""
    use = USE_COLOR if enabled is None else enabled
    if not use or not styles:
        return text
    return "".join(styles) + text + C.RESET


def text_width(text: str) -> int:
    """Ширина строки с учётом широких (CJK/emoji) символов."""
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - text_width(text))


def render_table(
    headers: list[str],
    rows: list[list[str]],
    styles: list[list[str | None]] | None = None,
    use_color: bool = True,
) -> str:
    """Рисует аккуратную ASCII-таблицу с необязательной раскраской ячеек."""
    enabled = USE_COLOR and use_color
    columns = len(headers)
    widths = [text_width(header) for header in headers]

    for row in rows:
        for index in range(columns):
            widths[index] = max(widths[index], text_width(row[index]))

    separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def make_line(cells: list[str], row_styles: list[str | None] | None = None) -> str:
        parts = []
        for index, cell in enumerate(cells):
            padded = " " + _pad(cell, widths[index]) + " "
            style = row_styles[index] if row_styles else None
            parts.append(paint(padded, style, enabled=enabled) if style else padded)
        return "|" + "|".join(parts) + "|"

    header_styles: list[str | None] = [C.BOLD] * columns
    lines = [
        paint(separator, C.GRAY, enabled=enabled),
        make_line(headers, header_styles),
        paint(separator, C.GRAY, enabled=enabled),
    ]

    for index, row in enumerate(rows):
        lines.append(make_line(row, styles[index] if styles else None))

    lines.append(paint(separator, C.GRAY, enabled=enabled))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Конфигурация из .env (без python-dotenv)
# ---------------------------------------------------------------------------

def load_env(path: Path) -> dict[str, str]:
    """Простой парсер .env: KEY=VALUE, поддержка export и кавычек."""
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


ENV = load_env(ENV_FILE)


def get_base_url(override: str | None = None) -> str:
    """Возвращает базовый URL Netrun-сервиса без пути /sub/auto.json."""
    base = (
        override
        or os.getenv("NETRUN_BASE_URL")
        or ENV.get("NETRUN_BASE_URL")
        # Обратная совместимость со старыми .env
        or os.getenv("PUBLIC_SUB_URL")
        or ENV.get("PUBLIC_SUB_URL")
        or os.getenv("BASE_SUB_URL")
        or ENV.get("BASE_SUB_URL")
        or "https://YOUR-SERVICE.netrun.io"
    )
    base = base.strip().rstrip("/")
    for suffix in ("/sub/auto.json", "/auto.json", "/sub"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    return base


def is_placeholder_url(base_url: str) -> bool:
    lowered = base_url.lower()
    return (
        "your-service" in lowered
        or "your-domain" in lowered
        or "username.github.io" in lowered
    )


def get_secret_key() -> str:
    secret = os.getenv("SUB_SECRET_KEY") or ENV.get("SUB_SECRET_KEY")
    if not secret:
        print(
            paint(
                "⚠️  SUB_SECRET_KEY не найден в .env. Используется небезопасное значение по умолчанию.",
                C.YELLOW,
            ),
            file=sys.stderr,
        )
        return "change_me"
    return secret


# ---------------------------------------------------------------------------
# Работа с clients.json
# ---------------------------------------------------------------------------

class ManagerError(Exception):
    """Ошибка, которую нужно показать пользователю без трейсбека."""


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(str(value))


def load_clients() -> list[dict]:
    """Читает clients.json и приводит записи к единому виду."""
    if not CLIENTS_FILE.exists():
        return []

    try:
        raw = json.loads(CLIENTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManagerError(
            f"Файл {CLIENTS_FILE.name} повреждён: {exc}. Исправьте JSON или восстановите файл из резервной копии."
        ) from exc
    except OSError as exc:
        raise ManagerError(f"Не удалось прочитать {CLIENTS_FILE.name}: {exc}") from exc

    if isinstance(raw, dict):
        raw_clients = raw.get("clients", [])
    elif isinstance(raw, list):
        raw_clients = raw
    else:
        raise ManagerError(f"Неверная структура {CLIENTS_FILE.name}: ожидался объект или массив.")

    if not isinstance(raw_clients, list):
        raise ManagerError(f"Неверная структура {CLIENTS_FILE.name}: поле 'clients' должно быть массивом.")

    clients: list[dict] = []
    for index, item in enumerate(raw_clients, start=1):
        if not isinstance(item, dict):
            print(f"⚠️  Запись #{index} пропущена: это не объект.", file=sys.stderr)
            continue

        name = str(item.get("name", "")).strip()
        token = str(item.get("token", "")).strip()
        issued_at = str(item.get("issued_at", "")).strip()
        expires_at = str(item.get("expires_at", "")).strip()
        link = str(item.get("link", "")).strip()

        if not name or not expires_at:
            print(f"⚠️  Запись #{index} пропущена: нет имени или даты окончания.", file=sys.stderr)
            continue

        try:
            parse_iso_date(expires_at)
        except ValueError:
            print(
                f"⚠️  Запись «{name}» пропущена: неверная дата окончания {expires_at!r}.",
                file=sys.stderr,
            )
            continue

        try:
            parse_iso_date(issued_at)
        except ValueError:
            issued_at = date.today().isoformat()

        clients.append(
            {
                "name": name,
                "issued_at": issued_at,
                "expires_at": expires_at,
                "token": token,
                "link": link,
            }
        )

    return clients


def save_clients(clients: list[dict]) -> None:
    """Атомарно сохраняет clients.json."""
    payload = {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "clients": clients,
    }
    temporary = CLIENTS_FILE.with_name(CLIENTS_FILE.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, CLIENTS_FILE)
    except OSError as exc:
        raise ManagerError(f"Не удалось сохранить {CLIENTS_FILE.name}: {exc}") from exc


def find_client(clients: list[dict], name: str) -> dict | None:
    wanted = name.strip().casefold()
    for client in clients:
        if client["name"].casefold() == wanted:
            return client
    return None


def require_client(clients: list[dict], name: str) -> dict:
    client = find_client(clients, name)
    if client is None:
        raise ManagerError(
            f"Клиент «{name.strip()}» не найден. Посмотрите список: python manager.py check --status all"
        )
    return client


def generate_token(name: str, issued_at: str, existing_tokens: set[str]) -> str:
    """Генерирует уникальный токен на основе hashlib + secrets."""
    secret = get_secret_key()
    while True:
        nonce = secrets.token_urlsafe(32)
        material = f"{name}|{issued_at}|{nonce}|{secret}".encode("utf-8")
        token = hashlib.sha256(material).hexdigest()[:TOKEN_LENGTH]
        if token not in existing_tokens:
            return token


def build_link(name: str, token: str, base_url: str) -> str:
    """Персональная ссылка на Netrun-воркер. Имя в URL не передаётся."""
    del name  # оставлен в сигнатуре для читаемости вызовов
    return f"{base_url.rstrip('/')}/sub/auto.json?token={quote(token, safe='')}"


def refresh_client_links(clients: list[dict], base_url: str) -> None:
    """Пересобирает ссылки всех клиентов под текущий адрес Netrun."""
    for client in clients:
        token = str(client.get("token", "")).strip()
        if token:
            client["link"] = build_link(str(client.get("name", "")), token, base_url)


def sync_netrun_bundle(clients: list[dict]) -> tuple[Path, bool]:
    """
    Создаёт netrun_worker/clients.json и копии JSON/TXT-подписок для ZIP.

    Возвращает (путь к clients.json, скопирован ли auto.json).
    """
    NETRUN_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "clients": clients,
    }
    temporary = NETRUN_CLIENTS_FILE.with_name(NETRUN_CLIENTS_FILE.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, NETRUN_CLIENTS_FILE)
    except OSError as exc:
        raise ManagerError(f"Не удалось создать {NETRUN_CLIENTS_FILE}: {exc}") from exc

    copied_auto = False
    if UPSTREAM_AUTO_FILE.exists():
        try:
            shutil.copy2(UPSTREAM_AUTO_FILE, NETRUN_AUTO_FILE)
            copied_auto = True
        except OSError as exc:
            print(
                paint(f"⚠️  Не удалось скопировать auto.json в netrun_worker: {exc}", C.YELLOW),
                file=sys.stderr,
            )

    # TXT/Happ-варианты и whitelist нужны воркеру как локальный fallback,
    # если GitHub/CONFIG_URL временно недоступны.
    for bundle_name in (
        "auto_all.txt",
        "auto_all_happ.txt",
        "whitelist.json",
        "whitelist_all.txt",
        "whitelist_all_happ.txt",
    ):
        source = UPSTREAM_AUTO_FILE.parent / bundle_name
        if not source.exists():
            continue
        try:
            shutil.copy2(source, NETRUN_DIR / bundle_name)
        except OSError as exc:
            print(
                paint(
                    f"⚠️  Не удалось скопировать {bundle_name} в netrun_worker: {exc}",
                    C.YELLOW,
                ),
                file=sys.stderr,
            )

    return NETRUN_CLIENTS_FILE, copied_auto


def days_left(client: dict, today: date) -> int:
    return (parse_iso_date(client["expires_at"]) - today).days


def is_active(client: dict, today: date) -> bool:
    return parse_iso_date(client["expires_at"]) >= today


def status_label(client: dict, today: date) -> str:
    expires = parse_iso_date(client["expires_at"])
    if expires < today:
        return "Истёк"
    if expires == today:
        return "Истекает сегодня"
    return "Активен"


def status_style(client: dict, today: date) -> str:
    return C.RED if not is_active(client, today) else C.GREEN


def calculate_rows(clients: list[dict], today: date) -> tuple[list[list[str]], list[list[str | None]]]:
    """Возвращает строки таблицы и стили ячеек. Активные идут первыми."""
    ordered = sorted(
        clients,
        key=lambda client: (
            0 if is_active(client, today) else 1,
            parse_iso_date(client["expires_at"]),
            client["name"].casefold(),
        ),
    )

    rows: list[list[str]] = []
    styles: list[list[str | None]] = []

    for client in ordered:
        remaining = days_left(client, today)
        style = status_style(client, today)
        rows.append(
            [
                client["name"],
                status_label(client, today),
                str(remaining),
                client["expires_at"],
                client.get("link", ""),
            ]
        )
        styles.append(
            [
                style if remaining < 0 else None,
                style,
                style if remaining < 0 else None,
                style if remaining < 0 else None,
                C.DIM if remaining < 0 else None,
            ]
        )

    return rows, styles


HEADERS = ["Имя", "Статус", "Дней", "Окончание", "Ссылка"]


def print_summary(clients: list[dict], today: date) -> None:
    active = sum(1 for client in clients if is_active(client, today))
    expired = len(clients) - active
    print(
        paint("Всего: ", C.BOLD)
        + str(len(clients))
        + paint(" | Активных: ", C.BOLD)
        + paint(str(active), C.GREEN)
        + paint(" | Истекших: ", C.BOLD)
        + paint(str(expired), C.RED)
    )


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------

def positive_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("количество дней должно быть целым числом") from exc
    if days <= 0:
        raise argparse.ArgumentTypeError("количество дней должно быть больше нуля")
    return days


def cmd_add(args: argparse.Namespace) -> int:
    name = args.name.strip()
    if not name:
        raise ManagerError("Имя клиента не может быть пустым.")
    if len(name) > 64:
        raise ManagerError("Имя клиента слишком длинное (максимум 64 символа).")

    clients = load_clients()
    if find_client(clients, name) is not None:
        raise ManagerError(
            f"Клиент «{name}» уже существует. Для продления используйте: "
            f'python manager.py renew --name "{name}" --days {args.days}'
        )

    today = date.today()
    issued_at = today.isoformat()
    expires_at = (today + timedelta(days=args.days)).isoformat()
    base_url = get_base_url(args.base_url)
    existing_tokens = {client["token"] for client in clients if client.get("token")}
    token = generate_token(name, issued_at, existing_tokens)
    link = build_link(name, token, base_url)

    client = {
        "name": name,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "token": token,
        "link": link,
    }
    clients.append(client)
    refresh_client_links(clients, base_url)
    save_clients(clients)
    bundle_path, _ = sync_netrun_bundle(clients)

    print(paint("✅ Клиент добавлен", C.GREEN, C.BOLD))
    print(f"   {paint('Имя:', C.BOLD)} {name}")
    print(f"   {paint('Выдан:', C.BOLD)} {issued_at}")
    print(f"   {paint('Истекает:', C.BOLD)} {expires_at} ({args.days} дн.)")
    print(f"   {paint('Токен:', C.BOLD)} {token}")
    print(f"   {paint('Ссылка:', C.BOLD)} {paint(link, C.CYAN)}")
    print(f"   {paint('Netrun-бандл:', C.BOLD)} {bundle_path.relative_to(BASE_DIR)}")
    if is_placeholder_url(base_url):
        print(
            paint(
                "⚠️  NETRUN_BASE_URL ещё не настроен. Укажите реальный адрес в .env и выполните: python manager.py sync",
                C.YELLOW,
            )
        )
    return 0


def cmd_renew(args: argparse.Namespace) -> int:
    name = args.name.strip()
    clients = load_clients()
    client = require_client(clients, name)

    today = date.today()
    old_expires = parse_iso_date(client["expires_at"])
    # Продлеваем от текущей даты, если подписка уже истекла, иначе — от даты окончания.
    base_date = max(today, old_expires)
    new_expires = base_date + timedelta(days=args.days)
    base_url = get_base_url(args.base_url)

    client["expires_at"] = new_expires.isoformat()
    refresh_client_links(clients, base_url)
    save_clients(clients)
    bundle_path, _ = sync_netrun_bundle(clients)

    print(paint("✅ Подписка продлена", C.GREEN, C.BOLD))
    print(f"   {paint('Имя:', C.BOLD)} {client['name']}")
    print(f"   {paint('Было:', C.BOLD)} {old_expires.isoformat()}")
    print(f"   {paint('Стало:', C.BOLD)} {paint(new_expires.isoformat(), C.GREEN)} (+{args.days} дн.)")
    print(f"   {paint('Ссылка:', C.BOLD)} {paint(client.get('link', ''), C.CYAN)}")
    print(f"   {paint('Netrun-бандл:', C.BOLD)} {bundle_path.relative_to(BASE_DIR)}")
    if is_placeholder_url(base_url):
        print(
            paint(
                "⚠️  NETRUN_BASE_URL ещё не настроен. Укажите реальный адрес в .env и выполните: python manager.py sync",
                C.YELLOW,
            )
        )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Пересобирает ссылки и готовит netrun_worker/ к загрузке на Netrun."""
    clients = load_clients()
    base_url = get_base_url(args.base_url)

    refresh_client_links(clients, base_url)
    save_clients(clients)
    bundle_path, copied_auto = sync_netrun_bundle(clients)

    print(paint("✅ Netrun-бандл обновлён", C.GREEN, C.BOLD))
    print(f"   {paint('Сервис:', C.BOLD)} {base_url}")
    print(f"   {paint('Клиентов:', C.BOLD)} {len(clients)}")
    print(f"   {paint('clients.json:', C.BOLD)} {bundle_path.relative_to(BASE_DIR)}")
    if copied_auto:
        print(f"   {paint('auto.json:', C.BOLD)} {NETRUN_AUTO_FILE.relative_to(BASE_DIR)}")
    else:
        print(
            paint(
                "⚠️  web/subscriptions/auto.json не найден. Сервис будет брать подписку из GitHub/CONFIG_URL.",
                C.YELLOW,
            )
        )
    if is_placeholder_url(base_url):
        print(
            paint(
                "⚠️  NETRUN_BASE_URL всё ещё содержит заглушку. Укажите адрес из кабинета Netrun в .env.",
                C.YELLOW,
            )
        )
    print()
    print(paint("Теперь загрузите содержимое папки netrun_worker/ на Netrun (ZIP).", C.CYAN))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    clients = load_clients()
    today = date.today()

    print()
    print(paint("VPN-Конструктор — статистика клиентов", C.BOLD, C.CYAN))
    print(paint(f"Дата: {today.isoformat()}", C.GRAY))
    print()

    if not clients:
        print(paint("Клиентов пока нет. Добавьте первого: python manager.py add --name \"Иван\" --days 30", C.YELLOW))
        table = render_table(HEADERS, [], use_color=False)
    else:
        rows, styles = calculate_rows(clients, today)
        print(render_table(HEADERS, rows, styles))
        print()
        print_summary(clients, today)
        table = render_table(HEADERS, rows, use_color=False)

    content = "\n".join(
        [
            "VPN-Конструктор — статистика клиентов",
            f"Сформировано: {datetime.now().isoformat(timespec='seconds')}",
            "",
            table,
            "",
            f"Всего: {len(clients)}",
            f"Активных: {sum(1 for client in clients if is_active(client, today))}",
            f"Истекших: {sum(1 for client in clients if not is_active(client, today))}",
            "",
        ]
    )
    try:
        STATS_FILE.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ManagerError(f"Не удалось сохранить {STATS_FILE.name}: {exc}") from exc

    print()
    print(paint(f"💾 Таблица сохранена в {STATS_FILE.name}", C.GREEN))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    clients = load_clients()
    today = date.today()

    status = args.status or "active"
    if args.active:
        status = "active"
    if args.expired:
        status = "expired"

    if args.name:
        client = find_client(clients, args.name)
        clients = [client] if client else []
        if not clients:
            print(paint(f"Клиент «{args.name.strip()}» не найден.", C.YELLOW))
            return 0

    if status == "active":
        selected = [client for client in clients if is_active(client, today)]
        title = "Активные клиенты"
    elif status == "expired":
        selected = [client for client in clients if not is_active(client, today)]
        title = "Истекшие клиенты"
    else:
        selected = list(clients)
        title = "Все клиенты"

    print()
    print(paint(f"VPN-Конструктор — {title}", C.BOLD, C.CYAN))
    print()

    if not selected:
        print(paint("Клиентов с таким статусом нет.", C.YELLOW))
        return 0

    rows, styles = calculate_rows(selected, today)
    print(render_table(HEADERS, rows, styles))
    print()
    print_summary(selected, today)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manager.py",
        description="Автономное управление клиентами VPN-Конструктора (только стандартная библиотека Python).",
        epilog=(
            "Примеры:\n"
            '  python manager.py add --name "Иван" --days 30\n'
            '  python manager.py renew --name "Иван" --days 30\n'
            "  python manager.py stats\n"
            "  python manager.py sync\n"
            "  python manager.py check --status active\n"
            "  python manager.py check --status expired"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Переопределить NETRUN_BASE_URL из .env (адрес сервиса Netrun).",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="КОМАНДА")

    add_parser = subparsers.add_parser("add", help="Добавить нового клиента")
    add_parser.add_argument("--name", required=True, help="Имя клиента")
    add_parser.add_argument("--days", required=True, type=positive_days, help="Срок подписки в днях")
    add_parser.set_defaults(func=cmd_add)

    renew_parser = subparsers.add_parser("renew", help="Продлить подписку клиента")
    renew_parser.add_argument("--name", required=True, help="Имя клиента")
    renew_parser.add_argument("--days", required=True, type=positive_days, help="Сколько дней добавить")
    renew_parser.set_defaults(func=cmd_renew)

    stats_parser = subparsers.add_parser("stats", help="Показать статистику и сохранить stats.txt")
    stats_parser.set_defaults(func=cmd_stats)

    sync_parser = subparsers.add_parser("sync", help="Обновить ссылки и netrun_worker/clients.json")
    sync_parser.set_defaults(func=cmd_sync)

    check_parser = subparsers.add_parser("check", help="Показать активных или истекших клиентов")
    check_filter = check_parser.add_mutually_exclusive_group()
    check_filter.add_argument(
        "--status",
        choices=("active", "expired", "all"),
        default=None,
        help="active — активные (по умолчанию), expired — истекшие, all — все",
    )
    check_filter.add_argument("--active", action="store_true", help="Только активные (то же, что --status active)")
    check_filter.add_argument("--expired", action="store_true", help="Только истекшие (то же, что --status expired)")
    check_parser.add_argument("--name", default=None, help="Показать только одного клиента")
    check_parser.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except ManagerError as exc:
        print(paint(f"Ошибка: {exc}", C.RED), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(paint("\nПрервано пользователем.", C.YELLOW), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
