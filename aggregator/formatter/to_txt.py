import urllib.parse

def generate_txt(links: list) -> str:
    """
    Берет список сырых ссылок (vless://...), переименовывает их 
    с добавлением флагов и сохраняет как единый TXT-список.
    """
    country_flags = {
        "germany": "🇩🇪", "германия": "🇩🇪", "de": "🇩🇪",
        "netherlands": "🇳🇱", "нидерланды": "🇳🇱", "nl": "🇳🇱",
        "usa": "🇺🇸", "сша": "🇺🇸", "us": "🇺🇸",
        "russia": "🇷🇺", "россия": "🇷🇺", "ru": "🇷🇺",
        "finland": "🇫🇮", "финляндия": "🇫🇮", "fi": "🇫🇮",
        "poland": "🇵🇱", "польша": "🇵🇱", "pl": "🇵🇱",
        "estonia": "🇪🇪", "эстония": "🇪🇪", "ee": "🇪🇪",
        "sweden": "🇸🇪", "швеция": "🇸🇪", "se": "🇸🇪",
        "france": "🇫🇷", "франция": "🇫🇷", "fr": "🇫🇷",
    }
    
    formatted_links = []
    counter = {}
    
    for link in links:
        # Пытаемся вытащить название из хвоста ссылки (#Name)
        parsed = urllib.parse.urlparse(link)
        name = urllib.parse.unquote(parsed.fragment) if parsed.fragment else "Server"
        
        # Ищем флаг по ключевым словам
        flag = "🌐"
        name_lower = name.lower()
        for key, emoji in country_flags.items():
            if key in name_lower:
                flag = emoji
                # Очищаем имя от мусора
                name = name.replace(key, "").replace(key.capitalize(), "").strip()
                if not name:
                    name = key.capitalize()
                break
        
        # Делаем имена уникальными (Германия 1, Германия 2)
        if name in counter:
            counter[name] += 1
            name = f"{name} {counter[name]}"
        else:
            counter[name] = 1
            
        # Собираем ссылку обратно с новым именем
        new_fragment = urllib.parse.quote(f"{flag} {name}")
        new_link = urllib.parse.urlunparse(parsed._replace(fragment=new_fragment))
        formatted_links.append(new_link)
        
    return "\n".join(formatted_links)