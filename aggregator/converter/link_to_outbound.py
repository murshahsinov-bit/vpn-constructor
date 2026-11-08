import json
import logging
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

# Профили, которые попадают в JSON-подписку.
#   xhttp — XHTTP + Reality/TLS, основной профиль для Android и десктопа.
#   tcp   — TCP + Reality/TLS + Vision, резервный профиль для iOS и старых ядер.
PROFILE_XHTTP = "xhttp"
PROFILE_TCP = "tcp"
SUPPORTED_PROFILES = {PROFILE_XHTTP, PROFILE_TCP}

VISION_FLOW = "xtls-rprx-vision"
DEFAULT_FINGERPRINT = "firefox"

# Фрагментация TLS ClientHello. Только для TCP-профилей: XHTTP уже
# разбивает поток на HTTP-запросы, и лишняя фрагментация ему не нужна.
TCP_FRAGMENT = {
    "packets": "tlshello",
    "length": "100-200",
    "interval": "10-20",
}

# XHTTP-режимы, которые понимает Xray-core. Клиентский mode не обязан
# совпадать с серверным: сервер XHTTP принимает все режимы.
XHTTP_MODES = {"auto", "packet-up", "stream-up", "stream-one"}
SUPPORTED_FINGERPRINTS = {
    "chrome", "firefox", "safari", "ios", "android", "edge",
    "random", "randomized",
}


def _first(params: dict, *names: str, default: str = "") -> str:
    """Возвращает первый непустой параметр из списка альтернативных имён."""
    for name in names:
        values = params.get(name)
        if values:
            value = str(values[0] or "").strip()
            if value:
                return value
    return default


def _decode_repeatedly(value: str, rounds: int = 3) -> str:
    """Источники иногда кодируют path/host/alpn дважды."""
    decoded = value
    for _ in range(rounds):
        new_value = unquote(decoded)
        if new_value == decoded:
            break
        decoded = new_value
    return decoded


def _parse_bool(value: str, default: bool = False) -> bool:
    value = str(value or "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


class LinkToOutboundConverter:
    """
    Преобразует share-ссылки в outbound-объекты Xray.

    Поддерживаются VLESS с транспортами tcp/xhttp и security reality/tls.
    WS/gRPC/hysteria в JSON не попадают: для них нет безопасного профиля,
    который одинаково работает в Happ/INCY и проходит ТСПУ.

    Правила:
      * XHTTP + Reality       -> профиль ``xhttp``, flow пустой;
      * XHTTP + TLS           -> профиль ``xhttp`` (Cloudflare/CDN);
      * TCP + Reality + Vision-> профиль ``tcp``, flow=xtls-rprx-vision;
      * TCP + TLS + Vision    -> только whitelist (allow_tls_vision);
      * fingerprint всегда firefox;
      * fragment добавляется только TCP-профилю.

    Никакие mux/sockopt/wsSettings/grpcSettings не генерируются.
    """

    def __init__(
        self,
        allow_tls_vision: bool = False,
        allow_xhttp_tls: bool = True,
    ):
        self.allow_tls_vision = bool(allow_tls_vision)
        # XHTTP поверх TLS — это штатный режим Cloudflare CDN.
        self.allow_xhttp_tls = bool(allow_xhttp_tls)

    def _allowed_security(self, profile: str) -> set[str]:
        allowed = {"reality"}
        if profile == PROFILE_XHTTP and self.allow_xhttp_tls:
            allowed.add("tls")
        if self.allow_tls_vision:
            allowed.add("tls")
        return allowed

    def parse_vless(self, link: str) -> dict | None:
        try:
            # Некоторые источники отдают HTML-экранированные &amp; в query.
            link = link.strip().replace("&amp;", "&")
            parsed = urlparse(link)
            uuid = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            if not uuid or not host:
                return None

            # Заглушки из некоторых источников (0.0.0.0, localhost) и
            # нулевые UUID — не серверы, их нельзя отдавать клиентам.
            if host.strip().lower() in {
                "0.0.0.0", "::", "[::]", "127.0.0.1", "localhost",
            }:
                return None
            if not str(uuid).replace("0", "").replace("-", ""):
                return None

            params = parse_qs(parsed.query, keep_blank_values=True)

            security_type = _first(params, "security").lower()
            network = _first(params, "type", "network", default="tcp").lower()
            # Новые ядра пишут type=raw вместо tcp.
            if network == "raw":
                network = "tcp"
            flow = _first(params, "flow")
            encryption_type = _first(params, "encryption", default="none").lower()

            if encryption_type not in ("", "none"):
                return None

            # WS/gRPC и прочие транспорты осознанно не поддерживаются.
            if network == "ws":
                logger.debug("WS-конфиг пропущен: ТСПУ детектирует WebSocket")
                return None
            if network not in SUPPORTED_PROFILES:
                return None

            profile = PROFILE_XHTTP if network == PROFILE_XHTTP else PROFILE_TCP

            if security_type not in self._allowed_security(profile):
                return None

            # Для TCP без Vision это обычный VLESS; для XHTTP flow не нужен.
            if profile == PROFILE_TCP and flow != VISION_FLOW:
                return None
            if profile == PROFILE_XHTTP:
                flow = ""

            public_key = _first(params, "pbk", "publicKey")
            if security_type == "reality" and not public_key:
                # Reality без publicKey нерабочий.
                return None

            sni = (
                _first(params, "sni", "peer")
                or _first(params, "host")
                or host
            )
            short_id = _first(params, "sid", "shortId")
            spider_x = _first(params, "spx", "spiderX")

            # Требование проекта: везде firefox. Параметр fp из источника
            # игнорируется, чтобы не отдавать chrome/safari, которые ТСПУ
            # уже научился выделять по JA3/JA4.
            fingerprint = DEFAULT_FINGERPRINT
            source_fp = _first(params, "fp").lower()
            if source_fp and source_fp not in SUPPORTED_FINGERPRINTS:
                logger.debug("Неизвестный fingerprint %r, использую firefox", source_fp)

            stream_settings: dict = {
                "network": profile,
                "security": security_type,
            }

            if security_type == "reality":
                reality_settings = {
                    "serverName": sni,
                    "publicKey": public_key,
                    "shortId": short_id,
                    "fingerprint": fingerprint,
                }
                if spider_x:
                    reality_settings["spiderX"] = spider_x
                stream_settings["realitySettings"] = reality_settings
            else:
                alpn_raw = _decode_repeatedly(_first(params, "alpn")).strip()
                alpn = [
                    item.strip()
                    for item in alpn_raw.split(",")
                    if item.strip()
                ]
                tls_settings = {
                    "serverName": sni,
                    "fingerprint": fingerprint,
                    "allowInsecure": _parse_bool(_first(params, "allowInsecure", "insecure")),
                }
                if alpn:
                    tls_settings["alpn"] = alpn
                stream_settings["tlsSettings"] = tls_settings

            if profile == PROFILE_XHTTP:
                path = _decode_repeatedly(_first(params, "path")) or "/"
                xhttp_host = _decode_repeatedly(_first(params, "host"))
                mode = _first(params, "mode", default="stream-one").lower()
                if mode not in XHTTP_MODES:
                    mode = "stream-one"
                # Требование проекта — stream-one. Сервер XHTTP принимает
                # этот режим независимо от значения mode в share-ссылке.
                mode = "stream-one"

                xhttp_settings: dict = {"mode": mode, "path": path}
                if xhttp_host:
                    xhttp_settings["host"] = xhttp_host

                extra_raw = _first(params, "extra")
                if extra_raw:
                    try:
                        extra = json.loads(_decode_repeatedly(extra_raw))
                        if isinstance(extra, dict):
                            # mode задаём отдельно; остальные поля (например,
                            # xPaddingBytes) сохраняем.
                            extra.pop("mode", None)
                            if extra:
                                xhttp_settings["extra"] = extra
                    except (TypeError, ValueError, json.JSONDecodeError):
                        logger.debug("Не удалось разобрать xhttp extra=%r", extra_raw)

                stream_settings["xhttpSettings"] = xhttp_settings

            user = {
                "id": uuid,
                "encryption": "none",
                "flow": flow,
            }

            outbound = {
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
                # Служебные поля нужны пайплайну, в JSON они не попадут.
                "_profile": profile,
                "_network": profile,
                "_security": security_type,
                "_flow": flow,
            }

            if profile == PROFILE_TCP:
                # Фрагментация только для TCP: режем TLS ClientHello так,
                # чтобы SNI не попадал в первый пакет.
                outbound["fragment"] = dict(TCP_FRAGMENT)

            return outbound
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
