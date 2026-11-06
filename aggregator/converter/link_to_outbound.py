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
                    "sockopt": {"tcpFastOpen": True, "tcpMaxSeg": 1440, "tcpNoDelay": True}
                },
                "mux": {"enabled": True, "concurrency": 32, "xudpConcurrency": 16, "xudpProxyUDP443": "reject"}
            }
            
            security = outbound["streamSettings"]["security"]
            if security == "tls":
                sni = params.get("sni", [""])[0]
                if not sni:
                    outbound["streamSettings"]["tlsSettings"] = {"fingerprint": params.get("fp", ["chrome"])[0]}
                else:
                    outbound["streamSettings"]["tlsSettings"] = {
                        "serverName": sni,
                        "fingerprint": params.get("fp", ["chrome"])[0],
                        "alpn": params.get("alpn", [""])[0].split(",") if "alpn" in params and params["alpn"][0] else []
                    }
            elif security == "reality":
                # Поддерживаем оба варианта именования ключа: pbk и publicKey
                pbk = params.get("pbk", params.get("publicKey", [""]))[0]
                sni = params.get("sni", [""])[0]
                
                # Если ключа нет — сервер нерабочий
                if not pbk or not sni:
                    return None

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
                service_name = params.get("serviceName", [""])[0]
                if not service_name:
                    return None
                outbound["streamSettings"]["grpcSettings"] = {"serviceName": service_name}

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
            
            if not password or not host:
                return None

            params = parse_qs(parsed.query)
            sni = params.get("sni", [""])[0]
            if not sni:
                return None
            
            outbound = {
                "tag": "proxy-hy2",
                "protocol": "hysteria",
                "settings": {"address": host, "port": port, "version": 2, "auth": password},
                "streamSettings": {
                    "network": "hysteria",
                    "security": "tls",
                    "hysteriaSettings": {"version": 2, "auth": password},
                    "tlsSettings": {"serverName": sni, "fingerprint": params.get("fp", ["chrome"])[0], "alpn": ["h3"]},
                    "sockopt": {"tcpFastOpen": True}
                },
                "mux": {"enabled": True, "concurrency": 32}
            }
            
            if "obfs" in params and params["obfs"][0]:
                outbound["streamSettings"]["finalmask"] = {
                    "udp": [{"type": params.get("obfs", ["salamander"])[0], "settings": {"password": params.get("obfs-password", [""])[0]}}]
                }
            return outbound
        except Exception:
            return None

    def convert(self, link: str, tag: str = "proxy") -> dict:
        link = link.strip()
        if link.startswith("vless://"):
            outbound = self.parse_vless(link)
        elif link.startswith("hysteria2://") or link.startswith("hy2://"):
            outbound = self.parse_hysteria2(link)
        else:
            return None
            
        if outbound:
            outbound["tag"] = tag
        return outbound