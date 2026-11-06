from urllib.parse import urlparse, parse_qs, unquote

def parse_hysteria2_uri(uri: str) -> dict | None:
    """Парсит Hysteria2 URI и возвращает словарь с параметрами."""
    if not (uri.startswith("hysteria2://") or uri.startswith("hy2://")):
        return None
    
    try:
        parsed = urlparse(uri)
        params = parse_qs(parsed.query)
        
        return {
            "protocol": "hysteria2",
            "password": parsed.username or params.get("auth", [""])[0],
            "address": parsed.hostname,
            "port": parsed.port or 443,
            "name": unquote(parsed.fragment) if parsed.fragment else "",
            "sni": params.get("sni", [""])[0],
            "insecure": params.get("insecure", ["0"])[0] == "1",
            "obfs": params.get("obfs", [""])[0],
            "obfs_password": params.get("obfs-password", [""])[0],
            "pinSHA256": params.get("pinSHA256", [""])[0],
        }
    except Exception:
        return None