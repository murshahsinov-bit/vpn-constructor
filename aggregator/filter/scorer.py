class ConfigScorer:
    """
    Оценивает конфигурацию сервера по шкале от 0 до 100.
    Чем выше балл, тем более предпочтителен сервер для премиум-подписки.
    """

    @staticmethod
    def calculate_score(outbound: dict) -> int:
        score = 50  # Базовый балл (нейтральный)
        
        protocol = outbound.get("protocol", "")
        stream = outbound.get("streamSettings", {})
        security = stream.get("security", "none")
        network = stream.get("network", "tcp")
        
        # 1. Оценка протокола
        if protocol == "hysteria":
            score += 20  # Hysteria2 отлично обходит блокировки и дает скорость
        elif protocol == "vless":
            score += 10  # Современный протокол
        elif protocol in ["vmess", "shadowsocks"]:
            score -= 10  # Старенькие, но рабочие
            
        # 2. Оценка безопасности (Security)
        if security == "reality":
            score += 30  # Топчик, лучшая маскировка
        elif security == "tls":
            score += 15  # Хорошо, но трафик виден как TLS
        elif security == "none":
            score -= 30  # Опасно, трафик открыт
            
        # 3. Оценка транспорта
        if network == "xhttp":
            score += 10  # Современный xhttp (новый xray)
        elif network in ["ws", "grpc"]:
            score += 5
        elif network == "tcp":
            if security != "reality":
                score -= 5  # Голый TCP без Reality сейчас легко палится
                
        # Ограничиваем диапазон от 0 до 100
        return max(0, min(100, score))

    @classmethod
    def sort_by_score(cls, outbounds: list[dict]) -> list[dict]:
        """Сортирует список серверов от лучших к худшим."""
        # Добавляем временное поле _score для сортировки
        for ob in outbounds:
            ob["_score"] = cls.calculate_score(ob)
            
        sorted_list = sorted(outbounds, key=lambda x: x["_score"], reverse=True)
        
        # Убираем временное поле, чтобы не тащить его в финальный JSON
        for ob in sorted_list:
            del ob["_score"]
            
        return sorted_list