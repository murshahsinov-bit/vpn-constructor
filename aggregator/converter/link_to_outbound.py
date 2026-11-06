import json
from urllib.parse import urlparse, parse_qs, unquote

class LinkToOutboundConverter:
    """
    Преобразует строки протоколов (vless, hysteria2) в JSON-объекты outbound для Xray.
    """

    @staticmethod
    def parse_vless(link: str) -> dict:
        """
        Парсит VLESS-ссылку и возвращает outbound-объект.
        Пример: vless://uuid@host:443?security=reality&sni=...&pbk=...&sid=...&type=tcp&flow=xtls-rprx-vision#Name
        """
        try:
            parsed = urlparse(link)
            # Извлекаем UUID и хост
            uuid = parsed.username
            host = parsed.hostname
            port = parsed.port or 443
            
            # Парсим параметры (query string)
            params = parse_qs(parsed.query)
            
            # Собираем базовый outbound
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
                    "security": params.get("security", ["none"])[0]
                }
            }
            
            # Настройки безопасности (TLS / Reality)
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
            
            # Настройки транспорта (xhttp / ws / grpc)
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
                outbound["streamSettings"]["grpcSettings"] = {
                    "serviceName": params.get("serviceName", [""])[0]
                }

            return outbound

        except Exception as e:
            print(f"Ошибка парсинга VLESS: {e}")
            return None

    @staticmethod
    def parse_hysteria2(link: str) -> dict:
        """
        Парсит Hysteria2-ссылку и возвращает outbound-объект.
        Пример: hysteria2://password@host:port?sni=...&insecure=1#Name
        """
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
                    "hysteriaSettings": {
                        "version": 2,
                        "auth": password
                    },
                    "tlsSettings": {
                        "serverName": params.get("sni", [""])[0],
                        "fingerprint": params.get("fp", ["chrome"])[0],
                        "alpn": ["h3"]
                    }
                }
            }
            
            # Если есть параметр obfs (маскировка)
            if "obfs" in params:
                outbound["streamSettings"]["finalmask"] = {
                    "udp": [{"type": params.get("obfs", ["salamander"])[0], 
                             "settings": {"password": params.get("obfs-password", [""])[0]}}]
                }

            return outbound

        except Exception as e:
            print(f"Ошибка парсинга Hysteria2: {e}")
            return None

    def convert(self, link: str, tag: str = "proxy") -> dict:
        """
        Главный метод. Определяет протокол и вызывает нужный парсер.
        """
        link = link.strip()
        if link.startswith("vless://"):
            outbound = self.parse_vless(link)
        elif link.startswith("hysteria2://"):
            outbound = self.parse_hysteria2(link)
        else:
            print(f"Неизвестный протокол: {link[:20]}...")
            return None
            
        if outbound:
            # Присваиваем уникальный тег, чтобы Xray мог их различать
            outbound["tag"] = tag
            return outbound
        return None

# --- Пример использования ---
if __name__ == "__main__":
    converter = LinkToOutboundConverter()
    
    # Пример VLESS Reality ссылки
    vless_link = "vless://e0c8c4a3-4d56-49c1-b403-40cbd757473b@example.com:443?security=reality&sni=www.microsoft.com&pbk=abc123&sid=def456&type=tcp&flow=xtls-rprx-vision#Test"
    outbound_json = converter.convert(vless_link, tag="proxy-vless-1")
    
    if outbound_json:
        print(json.dumps(outbound_json, indent=2, ensure_ascii=False))