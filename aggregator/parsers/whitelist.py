def parse_whitelist_content(content: str) -> list[str]:
    """
    Извлекает VLESS URI из текстового содержимого whitelist-файла.
    Игнорирует пустые строки и строки-комментарии, начинающиеся с '#'.
    """
    valid_uris = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("vless://"):
            valid_uris.append(line)
    return valid_uris