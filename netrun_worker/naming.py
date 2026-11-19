"""Человеческие имена серверов для подписок.

Публичные подписки, из которых собирается `auto_all*.txt`, приходят с
рекламными названиями вида

    🇩🇪 Бесплатный VPN tg:VLESSFORU 🇩🇪 t.me/rjsxrd
    🌐 🔥Join+Telegram:@Farah_VPN🟣 12

В приложении и в Happ такие строки обрезаются до «Join+Telegram:@Farah_V…» и
выглядят как мусор. Поэтому воркер переписывает fragment каждой ссылки перед
выдачей: страна из флага, протокол и порядковый номер для одинаковых имён.

Модуль сознательно не трогает параметры подключения — только имя профиля.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

# Флаг -> страна. Покрывает всё, что встречается в текущих подписках, плюс
# популярные направления, чтобы новые источники не выглядели «Сервер · host».
COUNTRY_BY_FLAG = {
    "AE": "ОАЭ",
    "AM": "Армения",
    "AT": "Австрия",
    "AU": "Австралия",
    "BG": "Болгария",
    "BR": "Бразилия",
    "CA": "Канада",
    "CH": "Швейцария",
    "CN": "Китай",
    "CZ": "Чехия",
    "DE": "Германия",
    "DK": "Дания",
    "EE": "Эстония",
    "ES": "Испания",
    "FI": "Финляндия",
    "FR": "Франция",
    "GB": "Великобритания",
    "GE": "Грузия",
    "HK": "Гонконг",
    "HU": "Венгрия",
    "IE": "Ирландия",
    "IL": "Израиль",
    "IN": "Индия",
    "IS": "Исландия",
    "IT": "Италия",
    "JP": "Япония",
    "KZ": "Казахстан",
    "KR": "Южная Корея",
    "LT": "Литва",
    "LV": "Латвия",
    "MD": "Молдова",
    "NL": "Нидерланды",
    "NO": "Норвегия",
    "PL": "Польша",
    "RO": "Румыния",
    "RS": "Сербия",
    "RU": "Россия",
    "SE": "Швеция",
    "SG": "Сингапур",
    "TR": "Турция",
    "TW": "Тайвань",
    "UA": "Украина",
    "US": "США",
}

PROTOCOL_BY_NETWORK = {
    "tcp": "TCP",
    "raw": "TCP",
    "xhttp": "XHTTP",
    "ws": "WS",
    "grpc": "gRPC",
    "h2": "HTTP/2",
    "http": "HTTP/2",
    "quic": "QUIC",
    "kcp": "mKCP",
}

_FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")
_LINK_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://\S+$")
# Реклама, ссылки на каналы и служебные пометки в названиях.
_NOISE_RE = re.compile(
    r"(?:t\.me/\S+|@[A-Za-z0-9_]+|join\+?telegram|telegram|tg:|"
    r"бесплатн\w*\s*vpn|free\s*vpn|vpn|\[[^\]]*\]|cidr)",
    re.IGNORECASE,
)
# Оставляем буквы, цифры, пробелы и минимальную пунктуацию.
_KEEP_RE = re.compile(r"[^\w\s,.\-]")
_SPACES_RE = re.compile(r"\s+")

MAX_NAME = 26


def flag_code(text: str) -> str | None:
    """Двухбуквенный код страны из первого флага-эмодзи в строке."""
    match = _FLAG_RE.search(text or "")
    if not match:
        return None
    return "".join(chr(ord(char) - 0x1F1E6 + ord("A")) for char in match.group(0))


def _query_value(pairs: list[str], key: str) -> str:
    for item in pairs:
        name, _, value = item.partition("=")
        if name.strip().lower() == key:
            return unquote(value)
    return ""


def _protocol(pairs: list[str]) -> str:
    network = (_query_value(pairs, "type") or _query_value(pairs, "network")).strip().lower()
    if not network:
        network = "tcp"
    label = PROTOCOL_BY_NETWORK.get(network)
    if label:
        return label
    return network.upper()


def _clean(text: str) -> str:
    without_noise = _NOISE_RE.sub(" ", text or "")
    letters = _KEEP_RE.sub(" ", without_noise)
    collapsed = _SPACES_RE.sub(" ", letters).strip(" .,-")
    if not re.search(r"[^\W\d_]", collapsed):
        # Остались только цифры и знаки («🟣 12» из рекламного названия).
        return ""
    if len(collapsed) > MAX_NAME:
        cut = collapsed[:MAX_NAME]
        if " " in cut:
            cut = cut[: cut.rfind(" ")]
        collapsed = cut.strip(" .,-")
    return collapsed


def _host_label(netloc: str) -> str:
    host = netloc.rsplit("@", 1)[-1].split(":", 1)[0].strip().lower()
    if not host:
        return ""
    if re.fullmatch(r"[\d.]+", host) or ":" in host:
        return host  # IP-адрес: показываем как есть, он короче домена
    labels = [part for part in host.split(".") if part]
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return host


def pretty_name(link: str) -> str | None:
    """Возвращает читаемое имя для ссылки или None, если это не share-ссылка."""
    parsed = urlsplit(link.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    pairs = [item for item in parsed.query.split("&") if item]
    remark = unquote(parsed.fragment or "")
    code = flag_code(remark)

    if code and code in COUNTRY_BY_FLAG:
        base = f"{_FLAG_RE.search(remark).group(0)} {COUNTRY_BY_FLAG[code]}"
    else:
        base = _clean(_FLAG_RE.sub(" ", remark)) or _clean(remark)
        if not base:
            base = f"Сервер · {_host_label(parsed.netloc)}" if _host_label(parsed.netloc) else "Сервер"

    return f"{base} · {_protocol(pairs)}"


def prettify_subscription(text: bytes | str) -> str:
    """Переписывает имена всех share-ссылок в подписке, сохраняя порядок."""
    raw = text.decode("utf-8", errors="replace") if isinstance(text, bytes) else text
    used: dict[str, int] = {}
    output: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or not _LINK_RE.match(stripped):
            output.append(line)
            continue
        name = pretty_name(stripped) or stripped
        count = used.get(name, 0) + 1
        used[name] = count
        unique = name if count == 1 else f"{name} {count}"
        parsed = urlsplit(stripped)
        rebuilt = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, quote(unique, safe=""))
        )
        output.append(rebuilt)

    return "\n".join(output) + ("\n" if output else "")
