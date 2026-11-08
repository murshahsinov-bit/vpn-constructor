import json
import logging

logger = logging.getLogger(__name__)

# В JSON-подписку попадает только одна связка:
#     VLESS + TCP + Reality + Vision (flow=xtls-rprx-vision)
# Это то, что стабильно работает в Happ и INCY на Android и iOS.
SUPPORTED_PROTOCOLS = {"vless"}
REQUIRED_NETWORK = "tcp"
REQUIRED_SECURITY = "reality"
REQUIRED_FLOW = "xtls-rprx-vision"

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


def _get_vnext(outbound: dict) -> dict:
    vnext = (outbound.get("settings") or {}).get("vnext") or []
    return vnext[0] if vnext else {}


def _get_user(outbound: dict) -> dict:
    users = _get_vnext(outbound).get("users") or []
    return users[0] if users else {}


def _normalize_network(value) -> str:
    network = str(value or "tcp").strip().lower()
    # type=raw — новый alias для tcp; в JSON пишем tcp для совместимости.
    return "tcp" if network == "raw" else network


def is_compatible(outbound: dict, allow_tls: bool = False) -> bool:
    """
    Проверяет, что outbound соответствует TCP + Vision.

    security по умолчанию строго reality. В whitelist-режиме можно
    разрешить ещё и tls: white-list конфиги igareck используют TLS
    с SNI разрешённого домена, и это штатный способ обхода.
    """
    if outbound.get("protocol") not in SUPPORTED_PROTOCOLS:
        return False

    stream = outbound.get("streamSettings") or {}
    security = str(stream.get("security", "")).strip().lower()
    network = _normalize_network(stream.get("network"))

    allowed_security = {REQUIRED_SECURITY}
    if allow_tls:
        allowed_security.add("tls")

    if security not in allowed_security:
        return False
    if network != REQUIRED_NETWORK:
        return False

    vnext = _get_vnext(outbound)
    user = _get_user(outbound)
    if not vnext.get("address") or not vnext.get("port") or not user.get("id"):
        return False

    # Без flow=xtls-rprx-vision это уже не Vision, а обычный VLESS.
    if str(user.get("flow", "")).strip() != REQUIRED_FLOW:
        return False

    if security == REQUIRED_SECURITY:
        # Reality без publicKey нерабочий.
        reality = stream.get("realitySettings") or {}
        if not str(reality.get("publicKey", "")).strip():
            return False
    else:
        tls = stream.get("tlsSettings") or {}
        if not str(tls.get("serverName", "")).strip():
            return False

    return True


def _compact_outbound(outbound: dict, allow_tls: bool = False) -> dict | None:
    """
    Собирает outbound заново, оставляя только обязательные поля.

    Здесь принудительно выставляются network=tcp, security из источника
    (reality, либо tls в whitelist-режиме) и flow=xtls-rprx-vision.
    Никакие fragment, mux, sockopt, wsSettings, grpcSettings,
    xhttpSettings не переносятся.
    """
    stream = outbound.get("streamSettings") or {}
    vnext = _get_vnext(outbound)
    user_in = _get_user(outbound)

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
    if security not in ({REQUIRED_SECURITY, "tls"} if allow_tls else {REQUIRED_SECURITY}):
        return None

    stream_settings = {
        "network": REQUIRED_NETWORK,
        "security": security,
    }

    if security == REQUIRED_SECURITY:
        reality = stream.get("realitySettings") or {}
        public_key = str(reality.get("publicKey", "")).strip()
        if not public_key:
            return None
        server_name = str(reality.get("serverName", "")).strip() or address
        short_id = str(reality.get("shortId", "")).strip()
        stream_settings["realitySettings"] = {
            "serverName": server_name,
            "publicKey": public_key,
            "shortId": short_id,
            "fingerprint": "chrome",
        }
    else:
        tls = stream.get("tlsSettings") or {}
        server_name = str(tls.get("serverName", "")).strip()
        if not server_name:
            return None
        fingerprint = str(tls.get("fingerprint", "")).strip().lower() or "chrome"
        tls_settings = {
            "serverName": server_name,
            "fingerprint": fingerprint,
            "allowInsecure": False,
        }
        alpn = tls.get("alpn")
        if isinstance(alpn, list) and alpn:
            tls_settings["alpn"] = [str(item) for item in alpn if str(item).strip()]
        stream_settings["tlsSettings"] = tls_settings

    return {
        "tag": outbound.get("tag", "proxy"),
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": port,
                "users": [{
                    "id": user_id,
                    "encryption": "none",
                    "flow": REQUIRED_FLOW,
                }],
            }]
        },
        "streamSettings": stream_settings,
    }


def _deduplicate(outbounds: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for outbound in outbounds:
        vnext = _get_vnext(outbound)
        identity = (
            str(vnext.get("address", "")),
            str(vnext.get("port", "")),
            str(_get_user(outbound).get("id", "")),
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(outbound)
    return result


def build_subscription(
    outbounds: list,
    template_path: str,
    max_outbounds: int = 30,
    allow_tls: bool | None = None,
) -> dict:
    """
    Собирает полный Xray-конфиг (inbounds + outbounds + routing).

    В JSON попадает не более max_outbounds серверов (по умолчанию 30).
    Для auto каждый сервер — строго VLESS + TCP + Reality + Vision.
    Для whitelist разрешён ещё и TLS + Vision (white-list конфиги igareck),
    если allow_tls не выставлен в False явно.
    Никаких балансировщиков, burstObservatory, fragment, mux, sockopt,
    hysteria и geo-правил. Полный список ссылок остаётся в TXT.
    """
    if allow_tls is None:
        allow_tls = "whitelist" in template_path

    limit = max(1, int(max_outbounds))
    safe_outbounds: list[dict] = []

    for outbound in outbounds:
        if not is_compatible(outbound, allow_tls=allow_tls):
            logger.debug("Пропущен несовместимый outbound: %s", outbound.get("tag"))
            continue
        compact = _compact_outbound(outbound, allow_tls=allow_tls)
        if compact is not None:
            safe_outbounds.append(compact)

    safe_outbounds = _deduplicate(safe_outbounds)[:limit]

    if not safe_outbounds:
        raise ValueError(
            "Нет серверов VLESS + TCP + Reality + Vision (flow=xtls-rprx-vision)"
        )

    prefix = "wl-proxy-" if "whitelist" in template_path else "proxy-"
    for index, outbound in enumerate(safe_outbounds):
        outbound["tag"] = f"{prefix}{index + 1}"

    with open(template_path, "r", encoding="utf-8") as file:
        config = json.load(file)

    # Убираем всё, что ломает мобильные ядра или требует geo-баз.
    for key in ("burstObservatory", "stats", "meta", "dns"):
        config.pop(key, None)

    config["outbounds"] = safe_outbounds + [
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"},
    ]

    # Локальные сети — напрямую, всё остальное — через первый outbound
    # (в Xray он же default). Никаких geoip/geosite и балансировщиков.
    config["routing"] = {
        "domainStrategy": "AsIs",
        "rules": [
            {
                "type": "field",
                "ip": PRIVATE_CIDRS,
                "outboundTag": "direct",
            }
        ],
    }

    # Страховка для whitelist-режима: весь трафик должен идти в туннель.
    # Если шаблон когда-нибудь вернёт geoip:ru/geosite:category-ru —
    # такие правила вырезаются, а не тихо ломают обход белых списков.
    if "whitelist" in template_path:
        clean_rules = []
        for rule in config["routing"]["rules"]:
            serialized = json.dumps(rule, ensure_ascii=False).lower()
            if any(marker in serialized for marker in FORBIDDEN_ROUTING_MARKERS):
                logger.warning("Whitelist: удалено правило с обходом РФ: %s", rule)
                continue
            clean_rules.append(rule)
        config["routing"]["rules"] = clean_rules

    return config


def save_config(config: dict, filepath: str):
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2, ensure_ascii=False)
