import logging
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# Единственная комбинация, которая в 2026 стабильно проходит ТСПУ
# и одинаково работает в Happ и INCY (Xray-core, Android/iOS):
#     VLESS + TCP + Reality + Vision (flow=xtls-rprx-vision)
#
# WS + TLS, gRPC, XHTTP, Hysteria и прочее отбрасываются ещё на этапе
# парсинга, поэтому в JSON-подписку они физически не попадают.
REQUIRED_NETWORK = "tcp"
REQUIRED_SECURITY = "reality"
REQUIRED_FLOW = "xtls-rprx-vision"

# fingerprint в Reality должен быть реалистичным TLS-отпечатком.
# Пустое значение заменяем на chrome.
SUPPORTED_FINGERPRINTS = {"chrome", "firefox", "safari", "ios", "android", "edge"}


class LinkToOutboundConverter:
    """
    Преобразует share-ссылки в outbound-объекты Xray.

    Для JSON-подписки допускается только:
      - protocol=vless
      - network=tcp (новые ядра пишут type=raw)
      - security=reality с непустым pbk
      - flow=xtls-rprx-vision

    fragment, mux, sockopt, wsSettings, grpcSettings и прочие расширения
    не генерируются вовсе: мобильные ядра их либо не понимают, либо
    ведут себя непредсказуемо.
    """

    @staticmethod
    def parse_vless(link: str) -> dict | None:
        try:
            parsed = urlparse(link)
            uuid = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            if not uuid or not host:
                return None

            params = parse_qs(parsed.query)

            security_type = (params.get("security", [""])[0] or "").strip().lower()
            network = (params.get("type", ["tcp"])[0] or "tcp").strip().lower()
            # Новые ядра пишут type=raw вместо tcp; старые raw не понимают.
            if network == "raw":
                network = "tcp"
            flow = (params.get("flow", [""])[0] or "").strip()
            encryption_type = (params.get("encryption", ["none"])[0] or "none").strip().lower()

            # --- Жёсткий фильтр: только Reality + TCP + Vision ---
            if security_type != REQUIRED_SECURITY:
                return None
            if network != REQUIRED_NETWORK:
                return None
            if flow != REQUIRED_FLOW:
                return None
            if encryption_type not in ("", "none"):
                return None

            public_key = (params.get("pbk", params.get("publicKey", [""]))[0] or "").strip()
            if not public_key:
                return None

            sni = (
                (params.get("sni", [""])[0] or "").strip()
                or (params.get("host", [""])[0] or "").strip()
                or host
            )
            short_id = (params.get("sid", [""])[0] or "").strip()  # пустой shortId допустим

            fingerprint = (params.get("fp", ["chrome"])[0] or "chrome").strip().lower()
            if fingerprint not in SUPPORTED_FINGERPRINTS:
                fingerprint = "chrome"

            # Vision включается только через flow у пользователя.
            user = {
                "id": uuid,
                "encryption": "none",
                "flow": REQUIRED_FLOW,
            }

            return {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": host,
                        "port": port,
                        "users": [user],
                    }]
                },
                "streamSettings": {
                    "network": REQUIRED_NETWORK,
                    "security": REQUIRED_SECURITY,
                    "realitySettings": {
                        "serverName": sni,
                        "publicKey": public_key,
                        "shortId": short_id,
                        "fingerprint": fingerprint,
                    },
                },
            }
        except Exception as exc:
            logger.debug("Не удалось разобрать VLESS-ссылку: %s", exc)
            return None

    @staticmethod
    def parse_hysteria2(link: str) -> dict | None:
        """
        Hysteria2 остаётся только для TXT-подписки и health-check.

        Xray-core (Happ, INCY) этот outbound не поддерживает, поэтому
        build_subscription() отбрасывает всё, где protocol != vless.
        """
        try:
            parsed = urlparse(link)
            password = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            if not password or not host:
                return None
            params = parse_qs(parsed.query)
            return {
                "tag": "proxy-hy2",
                "protocol": "hysteria",
                "settings": {"address": host, "port": port, "version": 2, "auth": password},
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "hysteriaSettings": {"version": 2, "auth": password},
                    "tlsSettings": {"serverName": (params.get("sni", [host])[0] or host)},
                },
            }
        except Exception:
            return None

    def convert(self, link: str, tag: str = "proxy") -> dict | None:
        link = link.strip()
        if link.startswith("vless://"):
            outbound = self.parse_vless(link)
        elif link.startswith(("hysteria2://", "hy2://")):
            outbound = self.parse_hysteria2(link)
        else:
            return None
        if outbound:
            outbound["tag"] = tag
        return outbound
