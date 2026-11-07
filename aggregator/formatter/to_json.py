import json
import logging

logger = logging.getLogger(__name__)

# Максимально совместимый набор: мобильные Xray-ядра стабильно понимают
# только VLESS + TLS/Reality на tcp/ws/grpc. Всё остальное отсекается.
SUPPORTED_PROTOCOLS = {"vless"}
SUPPORTED_SECURITY = {"tls", "reality"}
SUPPORTED_NETWORKS = {"tcp", "ws", "grpc"}

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


def _is_compatible(outbound: dict) -> bool:
    """Проверяет, что outbound безопасно отдавать мобильным клиентам."""
    if outbound.get("protocol") not in SUPPORTED_PROTOCOLS:
        return False

    stream = outbound.get("streamSettings") or {}
    security = str(stream.get("security", "")).lower()
    network = str(stream.get("network", "tcp")).lower()
    if network == "raw":
        network = "tcp"

    if security not in SUPPORTED_SECURITY:
        return False
    if network not in SUPPORTED_NETWORKS:
        return False

    vnext = _get_vnext(outbound)
    users = vnext.get("users") or []
    if not vnext.get("address") or not vnext.get("port") or not users:
        return False
    if not users[0].get("id"):
        return False

    return True


def _compact_outbound(outbound: dict) -> dict | None:
    """
    Оставляет только поля, обязательные для подключения.

    Убираются fragment, mux, sockopt, xhttpSettings и прочие расширения,
    которые поддерживаются не всеми версиями Xray.
    """
    stream = outbound.get("streamSettings") or {}
    network = str(stream.get("network", "tcp")).lower()
    if network == "raw":
        network = "tcp"
    security = str(stream.get("security", "")).lower()

    vnext = _get_vnext(outbound)
    user_in = (vnext.get("users") or [{}])[0]

    user = {
        "id": str(user_in.get("id", "")).strip(),
        "encryption": "none",
    }
    if not user["id"]:
        return None

    # flow допустим только для TCP, иначе ядро падает на валидации.
    flow = str(user_in.get("flow", "")).strip()
    if flow and network == "tcp":
        user["flow"] = flow

    compact = {
        "tag": outbound.get("tag", "proxy"),
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": str(vnext.get("address", "")).strip(),
                "port": int(vnext.get("port", 443)),
                "users": [user],
            }]
        },
        "streamSettings": {
            "network": network,
            "security": security,
        },
    }

    host = compact["settings"]["vnext"][0]["address"]

    if security == "tls":
        tls = stream.get("tlsSettings") or {}
        compact["streamSettings"]["tlsSettings"] = {
            "serverName": tls.get("serverName") or host,
            "fingerprint": tls.get("fingerprint") or "chrome",
        }
    else:  # reality
        reality = stream.get("realitySettings") or {}
        public_key = str(reality.get("publicKey", "")).strip()
        if not public_key:
            return None
        compact["streamSettings"]["realitySettings"] = {
            "serverName": reality.get("serverName") or host,
            "publicKey": public_key,
            "shortId": str(reality.get("shortId", "")),
            "fingerprint": reality.get("fingerprint") or "chrome",
        }

    if network == "ws":
        ws = stream.get("wsSettings") or {}
        ws_settings = {"path": ws.get("path") or "/"}
        headers = ws.get("headers") or {}
        host_header = headers.get("Host") or headers.get("host")
        if host_header:
            ws_settings["headers"] = {"Host": host_header}
        compact["streamSettings"]["wsSettings"] = ws_settings

    elif network == "grpc":
        grpc = stream.get("grpcSettings") or {}
        compact["streamSettings"]["grpcSettings"] = {
            "serviceName": grpc.get("serviceName", ""),
        }

    return compact


def _deduplicate(outbounds: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for outbound in outbounds:
        vnext = _get_vnext(outbound)
        identity = (
            str(vnext.get("address", "")),
            str(vnext.get("port", "")),
            str((vnext.get("users") or [{}])[0].get("id", "")),
            str(outbound.get("streamSettings", {}).get("network", "")),
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(outbound)
    return result


def build_subscription(outbounds: list, template_path: str, max_outbounds: int = 1) -> dict:
    """
    Собирает упрощённый Xray-конфиг.

    В JSON попадает не более max_outbounds серверов и только VLESS/TLS/Reality.
    Никаких балансировщиков, burstObservatory, fragment, mux и geo-правил.
    Полный список ссылок остаётся в auto_all.txt / whitelist_all.txt.
    """
    limit = max(1, int(max_outbounds))
    safe_outbounds: list[dict] = []

    for outbound in outbounds:
        if not _is_compatible(outbound):
            logger.debug("Пропущен несовместимый outbound: %s", outbound.get("tag"))
            continue
        compact = _compact_outbound(outbound)
        if compact is not None:
            safe_outbounds.append(compact)

    safe_outbounds = _deduplicate(safe_outbounds)[:limit]

    if not safe_outbounds:
        raise ValueError("Нет совместимых VLESS TLS/Reality-серверов для JSON-подписки")

    prefix = "wl-proxy-" if "whitelist" in template_path else "proxy-"
    for index, outbound in enumerate(safe_outbounds):
        outbound["tag"] = f"{prefix}{index + 1}"

    with open(template_path, "r", encoding="utf-8") as file:
        config = json.load(file)

    # Убираем всё, что ломает старые мобильные ядра.
    for key in ("burstObservatory", "stats", "meta", "dns"):
        config.pop(key, None)

    config["outbounds"] = safe_outbounds + [
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"},
    ]

    # Простое детерминированное правило: локальные сети — напрямую,
    # всё остальное — через первый outbound (он же default в Xray).
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
