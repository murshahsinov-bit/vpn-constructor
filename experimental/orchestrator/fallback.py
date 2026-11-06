import os
import shutil
import logging

logger = logging.getLogger(__name__)

class FallbackManager:
    """
    Управляет откатом на стабильные конфиги, если эксперимент провалился.
    """
    def __init__(self, subscriptions_dir: str = "web/subscriptions"):
        self.dir = subscriptions_dir
        self.stable_file = os.path.join(self.dir, "auto.json")
        self.experimental_file = os.path.join(self.dir, "experimental.json")

    def is_experimental_alive(self) -> bool:
        """
        Проверяет, есть ли в experimental.json живые серверы.
        Если файла нет или в нем 0 outbound-ов (кроме direct/block) — возвращает False.
        """
        if not os.path.exists(self.experimental_file):
            return False
            
        import json
        try:
            with open(self.experimental_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Проверяем, что в outbounds есть хоть что-то, кроме прямого соединения и блокировки
                active_proxies = [ob for ob in data.get("outbounds", []) if ob.get("protocol") not in ["freedom", "blackhole"]]
                return len(active_proxies) > 0
        except Exception as e:
            logger.error(f"Ошибка чтения experimental.json: {e}")
            return False

    def apply_fallback(self) -> str:
        """
        Если эксперимент мертв, возвращает путь к стабильному auto.json.
        Если эксперимент жив, возвращает experimental.json.
        """
        if self.is_experimental_alive():
            logger.info("🟢 Экспериментальные ноды живы. Отдаем experimental.json")
            return self.experimental_file
        
        logger.error("🔴 Экспериментальные ноды мертвы. Включаем fallback на auto.json")
        
        # Можем физически скопировать стабильный конфиг поверх экспериментального,
        # чтобы ссылка клиента (которая ведет на experimental.json) не менялась, 
        # но контент стал безопасным.
        if os.path.exists(self.stable_file):
            shutil.copyfile(self.stable_file, self.experimental_file)
            return self.experimental_file
        
        return self.experimental_file