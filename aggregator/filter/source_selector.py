class SourceSelector:
    """
    Выбирает списки URL для скачивания в зависимости от запрошенного режима.
    """

    # Словарь источников: ключ - режим, значение - список URL
    SOURCES_MAP = {
        "auto": [
            # Проверенные и стабильные источники
            "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
            "https://raw.githubusercontent.com/Hidashimora/free-vpn-anti-rkn/main/configs/1.1.txt",
            "https://raw.githubusercontent.com/tiagorrg/vless-checker/main/keys.json"
        ],
        "whitelist": [
            # Специфичные источники для обхода белых списков
            "https://raw.githubusercontent.com/zieng2/wl/main/subs/all.txt",
            "https://raw.githubusercontent.com/rom5n/whitelist-download/main/whitelist.txt",
            # Можно добавить WHITE-CIDR-RU-checked из igareck
        ]
    }

    @classmethod
    def get_sources(cls, mode: str) -> list[str]:
        """
        Возвращает список URL для заданного режима.
        Если режим неизвестен, возвращает пустой список.
        """
        mode = mode.lower().strip()
        
        if mode in cls.SOURCES_MAP:
            return cls.SOURCES_MAP[mode]
        
        print(f"⚠️ Неизвестный режим: {mode}. Доступные: {list(cls.SOURCES_MAP.keys())}")
        return []

    @classmethod
    def add_custom_source(cls, mode: str, url: str):
        """Позволяет динамически добавить новый источник в режим."""
        if mode not in cls.SOURCES_MAP:
            cls.SOURCES_MAP[mode] = []
        if url not in cls.SOURCES_MAP[mode]:
            cls.SOURCES_MAP[mode].append(url)