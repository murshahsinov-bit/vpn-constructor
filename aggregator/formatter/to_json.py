import json
import logging

logger = logging.getLogger(__name__)

PROFILE_XHTTP = "xhttp"
PROFILE_TCP = "tcp"
PROFILE_ORDER = (PROFILE_XHTTP, PROFILE_TCP)
SUPPORTED_PROFILES = set(PROFILE_ORDER)

VISION_FLOW = "xtls-rprx-vision"
DEFAULT_FINGERPRINT = "firefox"

# Фрагментация TLS ClientHello только для TCP. Для XHTTP она не нужна:
# XHTTP и так передаёт данные отдельными HTTP-запросами/потоками.
TCP_FRAGMENT = {
    "packets": "tlshello",
    "length": "100-200",
    "interval": "10-20",
}

# Приватные сети задаём явными CIDR, а не geoip:private:
# так конфиг не зависит от наличия geoip.dat в мобильном клиенте.
PRIVATE_CIDRS = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

# В whitelist-режиме весь трафик должен идти в туннель.
# Эти маркеры не должны встречаться в routing вообще.
FORBIDDEN_ROUTING_MARKERS = ("geoip:ru", "geosite:category-ru")

# Всё, что не должно переноситься из шаблона/источников.
JUNK_TOP_LEVEL_KEYS = (
    "burstObservatory", "observatory", "stats", "meta", "dns",
    "mux", "fragment", "sockopt", "balancers",
)


def _stream(outbound: dict) -> dict:
    return outbound.get("streamSettings") or {}


def _vnext(outbound: dict) -> dict:
    vnext = (outbound.get("settings") or {}).get("vnext") or []
    return vnext[0] if vnext else {}


def _user(outbound: dict) -> dict:
    users = _vnext(outbound).get("users") or []
    return users[0] if users else {}


def _normalize_network(value) -> str:
    network = str(value or "tcp").strip().lower()
    # type=raw — новый alias для tcp; в JSON пишем tcp для совместимости.
    return "tcp" if network == "raw" else network


def _infer_profile(outbound: dict) -> str | None:
    explicit = str(outbound.get("_profile") or "").strip().lower()
    if explicit in SUPPORTED_PROFILES:
        return explicit
    network = _normalize_network(_stream(outbound).get("network"))
    if network == PROFILE_XHTTP:
        return PROFILE_XHTTP
    if network == PROFILE_TCP:
        return PROFILE_TCP
    return None


def _identity(outbound: dict) -> tuple[str, int, str]:
    vnext = _vnext(outbound)
    user = _user(outbound)
    try:
        port = int(vnext.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    return (
        str(vnext.get("address", "")).strip().lower(),
        port,
        str(user.get("id", "")).strip(),
    )


def _allowed_security(profile: str, allow_tls: bool, allow_xhttp_tls: bool) -> set[str]:
    allowed = {"reality"}
    if allow_tls:
        allowed.add("tls")
    if profile == PROFILE_XHTTP and allow_xhttp_tls:
        allowed.add("tls")
    return allowed


def is_compatible(
    outbound: dict,
    allow_tls: bool = False,
    allow_xhttp_tls: bool = True,
    profile: str | None = None,
) -> bool:
    """
    Проверяет, что outbound можно отдать клиенту.

    security=reality разрешён всегда. TLS разрешён:
      * для XHTTP — Cloudflare/CDN (allow_xhttp_tls);
      * для TCP — только whitelist-режим (allow_tls).

    TCP обязан иметь flow=xtls-rprx-vision. XHTTP flow не использует.
    """
    if outbound.get("protocol") not in {"vless"}:
        return False

    profile = profile or _infer_profile(outbound)
    if profile not in SUPPORTED_PROFILES:
        return False

    stream = _stream(outbound)
    security = str(stream.get("security", "")).strip().lower()
    network = _normalize_network(stream.get("network"))
    if network != profile:
        return False

    if security not in _allowed_security(profile, allow_tls, allow_xhttp_tls):
        return False

    vnext = _vnext(outbound)
    user = _user(outbound)
    if not vnext.get("address") or not vnext.get("port") or not user.get("id"):
        return False

    if profile == PROFILE_TCP:
        # Без flow=xtls-rprx-vision это уже не Vision, а обычный VLESS.
        if str(user.get("flow", "")).strip() != VISION_FLOW:
            return False
    else:
        # XHTTP несовместим с Vision; flow должен быть пустым.
        if str(user.get("flow", "")).strip() not in ("", "none"):
            return False

    if security == "reality":
        reality = stream.get("realitySettings") or {}
        if not str(reality.get("publicKey", "")).strip():
            return False
    else:
        tls = stream.get("tlsSettings") or {}
        if not str(tls.get("serverName", "")).strip():
            return False

    return True


def _compact_outbound(
    outbound: dict,
    profile: str,
    allow_tls: bool,
    allow_xhttp_tls: bool,
) -> dict | None:
    """
    Собирает outbound заново, оставляя только обязательные поля.

    Здесь принудительно выставляются:
      * network = xhttp/tcp;
      * security из источника;
      * fingerprint = firefox;
      * flow = xtls-rprx-vision только для TCP;
      * fragment только для TCP.

    Никакие mux, sockopt, wsSettings, grpcSettings, balancers не
    переносятся. sockopt для whitelist-цепочки добавляется позже.
    """
    stream = _stream(outbound)
    vnext = _vnext(outbound)
    user_in = _user(outbound)

    user_id = str(user_in.get("id", "")).strip()
    if not user_id:
        return None

    address = str(vnext.get("address", "")).strip()
    if not address:
        return None
    try:
        port = int(vnext.get("port", 443))
    except (TypeError, ValueError):
        return None

    security = str(stream.get("security", "")).strip().lower()
    if security not in _allowed_security(profile, allow_tls, allow_xhttp_tls):
        return None

    stream_settings: dict = {
        "network": profile,
        "security": security,
    }

    if security == "reality":
        reality = stream.get("realitySettings") or {}
        public_key = str(reality.get("publicKey", "")).strip()
        if not public_key:
            return None
        server_name = str(reality.get("serverName", "")).strip() or address
        reality_settings = {
            "serverName": server_name,
            "publicKey": public_key,
            "shortId": str(reality.get("shortId", "")).strip(),
            "fingerprint": DEFAULT_FINGERPRINT,
        }
        spider_x = str(reality.get("spiderX", "")).strip()
        if spider_x:
            reality_settings["spiderX"] = spider_x
        stream_settings["realitySettings"] = reality_settings
    else:
        tls = stream.get("tlsSettings") or {}
        server_name = str(tls.get("serverName", "")).strip()
        if not server_name:
            return None
        tls_settings = {
            "serverName": server_name,
            "fingerprint": DEFAULT_FINGERPRINT,
            "allowInsecure": bool(tls.get("allowInsecure", False)),
        }
        alpn = tls.get("alpn")
        if isinstance(alpn, list) and alpn:
            tls_settings["alpn"] = [str(item) for item in alpn if str(item).strip()]
        stream_settings["tlsSettings"] = tls_settings

    if profile == PROFILE_XHTTP:
        source_xhttp = stream.get("xhttpSettings") or {}
        xhttp_settings = {
            # Единый режим для Android/desktop: один долгоживущий поток.
            "mode": "stream-one",
            "path": str(source_xhttp.get("path") or "/"),
        }
        host = str(source_xhttp.get("host", "")).strip()
        if not host and security == "tls":
            # У XHTTP за CDN Host обычно совпадает с SNI. Если источник
            # не передал host, подставляем serverName, чтобы запрос попал
            # на нужный виртуальный хост Cloudflare/Fastly.
            host = str((stream.get("tlsSettings") or {}).get("serverName", "")).strip()
        if host:
            xhttp_settings["host"] = host
        extra = source_xhttp.get("extra")
        if isinstance(extra, dict) and extra:
            clean_extra = {k: v for k, v in extra.items() if k != "mode"}
            if clean_extra:
                xhttp_settings["extra"] = clean_extra
        stream_settings["xhttpSettings"] = xhttp_settings
        user_flow = ""
    else:
        user_flow = VISION_FLOW

    result = {
        "tag": outbound.get("tag", "proxy"),
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": port,
                "users": [{
                    "id": user_id,
                    "encryption": "none",
                    "flow": user_flow,
                }],
            }]
        },
        "streamSettings": stream_settings,
    }
    if profile == PROFILE_TCP:
        result["fragment"] = dict(TCP_FRAGMENT)
    return result


def _group_servers(outbounds: list[dict]) -> list[dict[str, dict]]:
    """
    Группирует outbounds по серверу (address+port+uuid).

    Один сервер может иметь несколько профилей. run.py передаёт их через
    ``_variants`` (xhttp/tcp). Если метаданных нет — определяем профиль по
    network, чтобы функция работала и с «сырыми» outbound-объектами.
    """
    groups: dict[tuple[str, int, str], dict[str, dict]] = {}
    order: list[tuple[str, int, str]] = []

    def add(profile: str | None, outbound: dict) -> None:
        if profile not in SUPPORTED_PROFILES:
            return
        identity = _identity(outbound)
        if not identity[0] or not identity[1] or not identity[2]:
            return
        if identity not in groups:
            groups[identity] = {}
            order.append(identity)
        existing = groups[identity].get(profile)
        if existing is None:
            groups[identity][profile] = outbound
            return
        # Reality предпочтительнее TLS; иначе оставляем первый вариант.
        old_security = str(_stream(existing).get("security", "")).lower()
        new_security = str(_stream(outbound).get("security", "")).lower()
        if old_security != "reality" and new_security == "reality":
            groups[identity][profile] = outbound

    for outbound in outbounds:
        variants = outbound.get("_variants")
        if isinstance(variants, dict) and variants:
            for profile, variant in variants.items():
                if isinstance(variant, dict):
                    add(profile, variant)
        else:
            add(_infer_profile(outbound), outbound)

    return [groups[identity] for identity in order]


def _compact_relay(relay: dict, allow_tls: bool, allow_xhttp_tls: bool) -> dict | None:
    """Готовит outbound RU relay. SOCKS-релей нужен для Yandex Cloud Functions."""
    protocol = str(relay.get("protocol", "")).strip().lower()
    if protocol == "socks":
        settings = relay.get("settings") or {}
        servers = settings.get("servers") or []
        if not servers:
            return None
        server = servers[0]
        if not server.get("address") or not server.get("port"):
            return None
        return {
            "tag": "wl-relay",
            "protocol": "socks",
            "settings": {
                "servers": [{
                    "address": server["address"],
                    "port": int(server["port"]),
                    "users": server.get("users") or [],
                }]
            },
        }

    profile = _infer_profile(relay)
    if profile not in SUPPORTED_PROFILES:
        return None
    compact = _compact_outbound(relay, profile, allow_tls, allow_xhttp_tls)
    if compact is None:
        return None
    compact["tag"] = "wl-relay"
    return compact


def _compact_extra(extra: dict, allow_tls: bool, allow_xhttp_tls: bool) -> dict | None:
    """Дополнительный профиль (например, SOCKS5 внутри Yandex Cloud Functions)."""
    protocol = str(extra.get("protocol", "")).strip().lower()
    if protocol == "socks":
        settings = extra.get("settings") or {}
        servers = settings.get("servers") or []
        if not servers:
            return None
        server = servers[0]
        if not server.get("address") or not server.get("port"):
            return None
        return {
            "tag": extra.get("tag", "proxy-ycf-1"),
            "protocol": "socks",
            "settings": {
                "servers": [{
                    "address": server["address"],
                    "port": int(server["port"]),
                    "users": server.get("users") or [],
                }]
            },
        }

    profile = _infer_profile(extra)
    if profile not in SUPPORTED_PROFILES:
        return None
    compact = _compact_outbound(extra, profile, allow_tls, allow_xhttp_tls)
    if compact is None:
        return None
    compact["tag"] = extra.get("tag", "proxy-extra-1")
    return compact


def build_subscription(
    outbounds: list,
    template_path: str,
    max_outbounds: int = 30,
    allow_tls: bool | None = None,
    allow_xhttp_tls: bool = True,
    relay: dict | None = None,
    extra_outbounds: list[dict] | None = None,
) -> dict:
    """
    Собирает полный Xray-конфиг (inbounds + outbounds + routing).

    ``max_outbounds`` — максимум СЕРВЕРОВ (не профилей). Если сервер
    поддерживает XHTTP и TCP, он даёт два outbound с одинаковым номером:
    ``proxy-xhttp-1`` и ``proxy-tcp-1``.

    ``relay`` — outbound RU VPS. Для whitelist каждый целевой outbound
    получает ``streamSettings.sockopt.dialerProxy = "wl-relay"``: клиент
    идёт на RU VPS, а тот — на зарубежный сервер.

    В auto нет ws/mux/sockopt/balancers/geoip:ru/geosite:category-ru.
    """
    if allow_tls is None:
        allow_tls = "whitelist" in template_path

    limit = max(1, int(max_outbounds))
    groups = _group_servers(outbounds)[:limit]

    safe_groups: list[dict[str, dict]] = []
    for group in groups:
        compacted: dict[str, dict] = {}
        for profile in PROFILE_ORDER:
            source = group.get(profile)
            if source is None:
                continue
            if not is_compatible(
                source,
                allow_tls=allow_tls,
                allow_xhttp_tls=allow_xhttp_tls,
                profile=profile,
            ):
                logger.debug("Пропущен несовместимый %s outbound: %s", profile, source.get("tag"))
                continue
            compact = _compact_outbound(source, profile, allow_tls, allow_xhttp_tls)
            if compact is not None:
                compacted[profile] = compact
        if compacted:
            safe_groups.append(compacted)

    if not safe_groups:
        raise ValueError(
            "Нет серверов VLESS: XHTTP+Reality/TLS или TCP+Reality/TLS+Vision"
        )

    prefix = "wl-proxy" if "whitelist" in template_path else "proxy"
    target_outbounds: list[dict] = []
    for index, group in enumerate(safe_groups, start=1):
        for profile in PROFILE_ORDER:
            outbound = group.get(profile)
            if outbound is None:
                continue
            outbound["tag"] = f"{prefix}-{profile}-{index}"
            target_outbounds.append(outbound)

    extra_compacted: list[dict] = []
    for extra in extra_outbounds or []:
        compact = _compact_extra(extra, allow_tls, allow_xhttp_tls)
        if compact is not None:
            extra_compacted.append(compact)

    relay_outbound = None
    if relay:
        relay_outbound = _compact_relay(relay, allow_tls, allow_xhttp_tls)
        if relay_outbound is None:
            raise ValueError("RU relay не удалось преобразовать в outbound")
        # Цепочка: целевой сервер -> RU relay. Сам relay идёт напрямую.
        for outbound in target_outbounds:
            stream = outbound.setdefault("streamSettings", {})
            sockopt = stream.setdefault("sockopt", {})
            sockopt["dialerProxy"] = relay_outbound["tag"]

    with open(template_path, "r", encoding="utf-8") as file:
        config = json.load(file)

    # Убираем всё, что ломает мобильные ядра или требует geo-баз.
    for key in JUNK_TOP_LEVEL_KEYS:
        config.pop(key, None)

    # relay идёт последним: первый outbound остаётся целевым и становится
    # default. Логически цепочка всё равно начинается с RU relay.
    config["outbounds"] = (
        target_outbounds
        + extra_compacted
        + ([relay_outbound] if relay_outbound else [])
        + [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ]
    )

    routing = config.setdefault("routing", {})
    routing.pop("balancers", None)
    routing.pop("observatory", None)

    rules: list[dict] = [
        {
            "type": "field",
            "ip": PRIVATE_CIDRS,
            "outboundTag": "direct",
        },
        {
            "type": "field",
            "network": "tcp,udp",
            "outboundTag": target_outbounds[0]["tag"],
        },
    ]

    # Страховка для whitelist-режима: весь трафик должен идти в туннель.
    # Если шаблон когда-нибудь вернёт geoip:ru/geosite:category-ru —
    # такие правила вырезаются, а не тихо ломают обход белых списков.
    if "whitelist" in template_path:
        clean_rules = []
        for rule in rules:
            serialized = json.dumps(rule, ensure_ascii=False).lower()
            if any(marker in serialized for marker in FORBIDDEN_ROUTING_MARKERS):
                logger.warning("Whitelist: удалено правило с обходом РФ: %s", rule)
                continue
            clean_rules.append(rule)
        rules = clean_rules

    routing["domainStrategy"] = "AsIs"
    routing["rules"] = rules

    # Последняя страховка: geo-правила не должны попасть в JSON ни из
    # шаблона, ни из будущих изменений.
    serialized_config = json.dumps(config, ensure_ascii=False).lower()
    for marker in FORBIDDEN_ROUTING_MARKERS:
        if marker in serialized_config:
            raise ValueError(f"В итоговом конфиге остался запрещённый маркер {marker}")

    return config


def save_config(config: dict, filepath: str):
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2, ensure_ascii=False)
