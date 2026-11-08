import logging
from urllib.parse import parse_qs, unquote, urlparse

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

    Для JSON-подписки auto допускается только:
      - protocol=vless
      - network=tcp (новые ядра пишут type=raw)
      - security=reality с непустым pbk
      - flow=xtls-rprx-vision

    Для whitelist-режима можно включить allow_tls_vision: источники
    igareck публикуют white-list конфиги как VLESS + TCP + TLS + Vision
    (SNI разрешённого домена), и такие серверы тоже годны для обхода
    белых списков. Reality остаётся приоритетным.

    fragment, mux, sockopt, wsSettings, grpcSettings и прочие расширения
    не генерируются вовсе: мобильные ядра их либо не понимают, либо
    ведут себя непредсказуемо.
    """

    def __init__(self, allow_tls_vision: bool = False):
        self.allow_tls_vision = bool(allow_tls_vision)

    def _allowed_security(self) -> set[str]:
        allowed = {REQUIRED_SECURITY}
        if self.allow_tls_vision:
            allowed.add("tls")
        return allowed

    def parse_vless(self, link: str) -> dict | None:
        try:
            parsed = urlparse(link)
            uuid = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            if not uuid or not host:
                return None

            # Заглушки из некоторых источников (0.0.0.0, localhost) и
            # нулевые UUID — не серверы, их нельзя отдавать клиентам.
            if host.strip().lower() in {"0.0.0.0", "::", "[::]", "127.0.0.1", "localhost"}:
                return None
            if not str(uuid).replace("0", "").replace("-", ""):
                return None

            params = parse_qs(parsed.query)

            security_type = (params.get("security", [""])[0] or "").strip().lower()
            network = (params.get("type", ["tcp"])[0] or "tcp").strip().lower()
            # Новые ядра пишут type=raw вместо tcp; старые raw не понимают.
            if network == "raw":
                network = "tcp"
            flow = (params.get("flow", [""])[0] or "").strip()
            encryption_type = (params.get("encryption", ["none"])[0] or "none").strip().lower()

            # --- Жёсткий фильтр: только TCP + Vision + Reality (или TLS) ---
            if security_type not in self._allowed_security():
                return None
            if network != REQUIRED_NETWORK:
                return None
            if flow != REQUIRED_FLOW:
                return None
            if encryption_type not in ("", "none"):
                return None

            public_key = (params.get("pbk", params.get("publicKey", [""]))[0] or "").strip()
            if security_type == REQUIRED_SECURITY and not public_key:
                # Reality без publicKey нерабочий.
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

            stream_settings = {
                "network": REQUIRED_NETWORK,
                "security": security_type,
            }

            if security_type == REQUIRED_SECURITY:
                stream_settings["realitySettings"] = {
                    "serverName": sni,
                    "publicKey": public_key,
                    "shortId": short_id,
                    "fingerprint": fingerprint,
                }
            else:
                # igareck WHITE-*: обычный TLS на SNI из белого списка.
                alpn_raw = (params.get("alpn", [""])[0] or "").strip()
                alpn = []
                if alpn_raw:
                    # Источники иногда кодируют alpn дважды: h2%252Chttp%252F1.1.
                    for _ in range(2):
                        decoded = unquote(alpn_raw)
                        if decoded == alpn_raw:
                            break
                        alpn_raw = decoded
                    alpn = [item.strip() for item in alpn_raw.split(",") if item.strip()]
                tls_settings = {
                    "serverName": sni,
                    "fingerprint": fingerprint,
                    "allowInsecure": False,
                }
                if alpn:
                    tls_settings["alpn"] = alpn
                stream_settings["tlsSettings"] = tls_settings

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
                "streamSettings": stream_settings,
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
