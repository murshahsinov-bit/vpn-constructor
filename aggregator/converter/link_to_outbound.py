import json
from urllib.parse import urlparse, parse_qs, unquote

class LinkToOutboundConverter:
    @staticmethod
    def parse_vless(link: str) -> dict:
        try:
            parsed = urlparse(link)
            uuid = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            params = parse_qs(parsed.query)
            
            outbound = {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": host,
                        "port": port,
                        "users": [{
                            "id": uuid,
                            "encryption": params.get("encryption", ["none"])[0],
                            "flow": params.get("flow", [""])[0]
                        }]
                    }]
                },
                "streamSettings": {
                    "network": params.get("type", ["tcp"])[0],
                    "security": params.get("security", ["none"])[0],
                    "sockopt": {
                        "tcpFastOpen": True,
                        "tcpMaxSeg": 1440,
                        "tcpNoDelay": True
                    }
                },
                # Включаем Mux для ускорения открытия сайтов
                "mux": {
                    "enabled": True,
                    "concurrency": 32,
                    "xudpConcurrency": 16,
                    "xudpProxyUDP443": "reject"
                }
            }
            
            security = outbound["streamSettings"]["security"]
            if security == "tls":
                outbound["streamSettings"]["tlsSettings"] = {
                    "serverName": params.get("sni", [""])[0],
                    "fingerprint": params.get("fp", ["chrome"])[0],
                    "alpn": params.get("alpn", [""])[0].split(",") if "alpn" in params else []
                }
            elif security == "reality":
                outbound["streamSettings"]["realitySettings"] = {
                    "serverName": params.get("sni", [""])[0],
                    "publicKey": params.get("pbk", [""])[0],
                    "shortId": params.get("sid", [""])[0],
                    "fingerprint": params.get("fp", ["chrome"])[0]
                }
            
            network = outbound["streamSettings"]["network"]
            if network == "xhttp":
                outbound["streamSettings"]["xhttpSettings"] = {
                    "path": unquote(params.get("path", ["/"])[0]),
                    "host": params.get("host", [""])[0],
                    "mode": params.get("mode", ["auto"])[0]
                }
            elif network == "ws":
                outbound["streamSettings"]["wsSettings"] = {
                    "path": unquote(params.get("path", ["/"])[0]),
                    "headers": {"Host": params.get("host", [""])[0]}
                }

            return outbound

        except Exception as e:
            print(f"Ошибка парсинга VLESS: {e}")
            return None

    @staticmethod
    def parse_hysteria2(link: str) -> dict:
        try:
            parsed = urlparse(link)
            password = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            params = parse_qs(parsed.query)
            
            outbound = {
                "tag": "proxy-hy2",
                "protocol": "hysteria",
                "settings": {
                    "address": host,
                    "port": port,
                    "version": 2,
                    "auth": password
                },
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "hysteriaSettings": {"version": 2, "auth": password},
                    "tlsSettings": {
                        "serverName": params.get("sni", [""])[0],
                        "fingerprint": params.get("fp", ["chrome"])[0],
                        "alpn": ["h3"]
                    },
                    "sockopt": {"tcpFastOpen": True}
                },
                "mux": {"enabled": True, "concurrency": 32}
            }
            return outbound
        except Exception as e:
            print(f"Ошибка парсинга Hysteria2: {e}")
            return None

    def convert(self, link: str, tag: str = "proxy") -> dict:
        link = link.strip()
        if link.startswith("vless://"):
            outbound = self.parse_vless(link)
        elif link.startswith("hysteria2://"):
            outbound = self.parse_hysteria2(link)
        else:
            return None
            
        if outbound:
            outbound["tag"] = tag
            return outbound
        return None