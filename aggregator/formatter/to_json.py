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


def is_compatible(outbound: dict) -> bool:
    """Проверяет, что outbound соответствует Reality + TCP + Vision."""
    if outbound.get("protocol") not in SUPPORTED_PROTOCOLS:
        return False

    stream = outbound.get("streamSettings") or {}
    security = str(stream.get("security", "")).strip().lower()
    network = _normalize_network(stream.get("network"))

    if security != REQUIRED_SECURITY:
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

    # Reality без publicKey нерабочий.
    reality = stream.get("realitySettings") or {}
    if not str(reality.get("publicKey", "")).strip():
        return False

    return True


def _compact_outbound(outbound: dict) -> dict | None:
    """
    Собирает outbound заново, оставляя только обязательные поля.

    Здесь принудительно выставляются network=tcp, security=reality,
    fingerprint=chrome и flow=xtls-rprx-vision. Никакие fragment, mux,
    sockopt, wsSettings, grpcSettings, xhttpSettings не переносятся.
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

    reality = stream.get("realitySettings") or {}
    public_key = str(reality.get("publicKey", "")).strip()
    if not public_key:
        return None

    server_name = str(reality.get("serverName", "")).strip() or address
    short_id = str(reality.get("shortId", "")).strip()

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
        "streamSettings": {
            "network": REQUIRED_NETWORK,
            "security": REQUIRED_SECURITY,
            "realitySettings": {
                "serverName": server_name,
                "publicKey": public_key,
                "shortId": short_id,
                "fingerprint": "chrome",
            },
        },
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


def build_subscription(outbounds: list, template_path: str, max_outbounds: int = 1) -> dict:
    """
    Собирает полный Xray-конфиг (inbounds + outbounds + routing).

    В JSON попадает не более max_outbounds серверов, и каждый из них —
    строго VLESS + TCP + Reality + Vision. Никаких балансировщиков,
    burstObservatory, fragment, mux, sockopt, hysteria и geo-правил.
    Полный список ссылок остаётся в auto_all.txt / whitelist_all.txt.
    """
    limit = max(1, int(max_outbounds))
    safe_outbounds: list[dict] = []

    for outbound in outbounds:
        if not is_compatible(outbound):
            logger.debug("Пропущен несовместимый outbound: %s", outbound.get("tag"))
            continue
        compact = _compact_outbound(outbound)
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

    return config


def save_config(config: dict, filepath: str):
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(config, file, indent=2, ensure_ascii=False)
