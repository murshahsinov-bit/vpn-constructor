from urllib.parse import urlparse, parse_qs, unquote

def parse_vless_uri(uri: str) -> dict | None:
    """Парсит VLESS URI и возвращает словарь с параметрами."""
    if not uri.startswith("vless://"):
        return None
    
    try:
        parsed = urlparse(uri)
        # Без UUID и адреса ссылка бесполезна: такие строки приходят
        # из битых источников и не должны попадать в пайплайн.
        if not parsed.username or not parsed.hostname:
            return None
        params = parse_qs(parsed.query)
        
        return {
            "protocol": "vless",
            "uuid": parsed.username,
            "address": parsed.hostname,
            "port": parsed.port or 443,
            "name": unquote(parsed.fragment) if parsed.fragment else "",
            "encryption": params.get("encryption", ["none"])[0],
            "flow": params.get("flow", [""])[0],
            "security": params.get("security", ["none"])[0],
            "sni": params.get("sni", [""])[0],
            "fp": params.get("fp", ["chrome"])[0],
            "pbk": params.get("pbk", [""])[0],
            "sid": params.get("sid", [""])[0],
            "network": params.get("type", ["tcp"])[0],
            "path": unquote(params.get("path", ["/"])[0]),
            "host": params.get("host", [""])[0],
        }
    except Exception:
        return None