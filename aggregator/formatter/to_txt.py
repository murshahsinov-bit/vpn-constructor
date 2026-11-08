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
