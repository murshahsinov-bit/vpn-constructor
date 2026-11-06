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
            if not uuid or not host:
                return None

            params = parse_qs(parsed.query)
            
            # Приводим security к нижнему регистру
            security_type = params.get("security", ["none"])[0].lower()
            
            # ЖЕСТКИЙ ФИЛЬТР: Если это не TLS и не Reality — выкидываем сразу
            if security_type not in ["tls", "reality"]:
                return None

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
                    "security": security_type,
                    "sockopt": {
                        "tcpFastOpen": True,
                        "tcpMss": 1440,
                        "tcpcongestion": "bbr"
                    }
                },
                "mux": {"enabled": True, "concurrency": 16}
            }

            sni = params.get("sni", params.get("host", [host]))[0]

            if security_type == "tls":
                outbound["streamSettings"]["tlsSettings"] = {
                    "serverName": sni,
                    "fingerprint": params.get("fp", ["chrome"])[0]
                }
            elif security_type == "reality":
                pbk = params.get("pbk", params.get("publicKey", [""]))[0]
                if not pbk: return None
                
                outbound["streamSettings"]["realitySettings"] = {
                    "serverName": sni,
                    "publicKey": pbk,
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
            elif network == "grpc":
                outbound["streamSettings"]["grpcSettings"] = {"serviceName": params.get("serviceName", [""])[0]}

            return outbound
        except Exception:
            return None

    @staticmethod
    def parse_hysteria2(link: str) -> dict:
        try:
            parsed = urlparse(link)
            password = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            if not password or not host: return None
            
            params = parse_qs(parsed.query)
            sni = params.get("sni", params.get("host", [host]))[0]
            
            return {
                "tag": "proxy-hy2",
                "protocol": "hysteria",
                "settings": {"address": host, "port": port, "version": 2, "auth": password},
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "hysteriaSettings": {"version": 2, "auth": password},
                    "tlsSettings": {"serverName": sni, "alpn": ["h3"]},
                    "sockopt": {"tcpFastOpen": True}
                },
                "mux": {"enabled": True, "concurrency": 16}
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