class Deduplicator:
    """
    Удаляет дубликаты серверов из списка outbound-объектов.
    Сравнивает по уникальной комбинации адреса, порта и идентификатора пользователя.
    """

    @staticmethod
    def _get_identity(outbound: dict) -> str:
        """Извлекает уникальный ключ из outbound-объекта."""
        protocol = outbound.get("protocol", "")
        
        if protocol == "vless":
            vnext = outbound.get("settings", {}).get("vnext", [{}])[0]
            address = vnext.get("address", "")
            port = vnext.get("port", "")
            # UUID пользователя
            user_id = vnext.get("users", [{}])[0].get("id", "")
            return f"vless:{address}:{port}:{user_id}"
            
        elif protocol == "hysteria":
            settings = outbound.get("settings", {})
            address = settings.get("address", "")
            port = settings.get("port", "")
            # Пароль авторизации
            auth = settings.get("auth", "")
            return f"hy2:{address}:{port}:{auth}"
            
        # Для остальных протоколов (если добавятся) используем хэш всего объекта
        return str(hash(str(outbound)))

    @classmethod
    def deduplicate(cls, outbounds: list[dict]) -> list[dict]:
        """
        Принимает список outbound-объектов, возвращает список без дубликатов.
        """
        seen = set()
        unique_outbounds = []
        
        for ob in outbounds:
            identity = cls._get_identity(ob)
            
            if identity not in seen:
                seen.add(identity)
                unique_outbounds.append(ob)
                
        return unique_outbounds