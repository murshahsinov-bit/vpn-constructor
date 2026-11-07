import logging
from urllib.parse import urlparse, parse_qs, unquote

logger = logging.getLogger(__name__)

# Транспорты, которые стабильно понимают мобильные Xray-ядра (v2rayNG, OneXray, INCY и т.п.).
# xhttp / httpupgrade / h2 / quic / kcp сознательно исключены: их поддержка зависит от версии ядра.
SUPPORTED_NETWORKS = {"tcp", "ws", "grpc"}
SUPPORTED_SECURITY = {"tls", "reality"}
SUPPORTED_FINGERPRINTS = {"chrome", "firefox", "safari", "ios", "android", "edge"}


class LinkToOutboundConverter:
    """
    Преобразует share-ссылки в outbound-объекты Xray.

    Для JSON-подписки генерируется только минимальный набор полей:
    protocol/settings/streamSettings. Всё, что зависит от версии ядра
    (fragment, mux, sockopt, xhttp, hysteria), в JSON не попадает.
    """

    @staticmethod
    def parse_vless(link: str) -> dict:
        try:
            parsed = urlparse(link)
            uuid = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            if not uuid or not host:
                return None

            params = parse_qs(parsed.query)
            security_type = params.get("security", ["none"])[0].lower()
            network = params.get("type", ["tcp"])[0].lower()
            # Новые ядра пишут type=raw вместо tcp; старые raw не понимают.
            if network == "raw":
                network = "tcp"
            encryption_type = params.get("encryption", ["none"])[0].lower()

            # Только TLS/Reality: без них конфиг бессмысленен и небезопасен.
            if security_type not in SUPPORTED_SECURITY:
                return None
            if encryption_type not in ("", "none"):
                return None
            if network not in SUPPORTED_NETWORKS:
                return None

            sni = (params.get("sni", [""])[0] or params.get("host", [""])[0] or host).strip()
            fingerprint = (params.get("fp", ["chrome"])[0] or "chrome").lower()
            if fingerprint not in SUPPORTED_FINGERPRINTS:
                fingerprint = "chrome"

            user = {
                "id": uuid,
                "encryption": "none",
            }

            # flow (xtls-rprx-vision) допустим только для TCP.
            # С ws/grpc Xray падает с ошибкой конфигурации.
            flow = params.get("flow", [""])[0].strip()
            if flow and network == "tcp":
                user["flow"] = flow

            stream_settings = {
                "network": network,
                "security": security_type,
            }

            if security_type == "tls":
                stream_settings["tlsSettings"] = {
                    "serverName": sni,
                    "fingerprint": fingerprint,
                }
            else:  # reality
                public_key = params.get("pbk", params.get("publicKey", [""]))[0]
                short_id = params.get("sid", [""])[0]  # пустой shortId допустим
                if not public_key:
                    return None
                stream_settings["realitySettings"] = {
                    "serverName": sni,
                    "publicKey": public_key,
                    "shortId": short_id,
                    "fingerprint": fingerprint,
                }

            if network == "ws":
                path = unquote(params.get("path", ["/"])[0]) or "/"
                ws_settings = {"path": path}
                host_header = params.get("host", [""])[0]
                if host_header:
                    ws_settings["headers"] = {"Host": host_header}
                stream_settings["wsSettings"] = ws_settings
            elif network == "grpc":
                stream_settings["grpcSettings"] = {
                    "serviceName": params.get("serviceName", [""])[0],
                }
            # Для tcp дополнительных настроек не требуется.

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
                "streamSettings": stream_settings,
            }
        except Exception as exc:
            logger.debug("Не удалось разобрать VLESS-ссылку: %s", exc)
            return None

    @staticmethod
    def parse_hysteria2(link: str) -> dict:
        """
        Hysteria2 остаётся для TXT-подписки и health-check.

        В JSON Xray-core этот outbound не поддерживает, поэтому
        build_subscription() отфильтровывает protocol != vless.
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
                    "tlsSettings": {"serverName": params.get("sni", [host])[0]},
                },
            }
        except Exception:
            return None

    def convert(self, link: str, tag: str = "proxy") -> dict:
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
