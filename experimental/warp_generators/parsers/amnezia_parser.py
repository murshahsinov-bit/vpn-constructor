import logging
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class AmneziaParser:
    """
    Парсер конфигурационных файлов AmneziaWG (.conf).
    Извлекает параметры интерфейса, пира и уникальные настройки обфускации.
    """

    def __init__(self):
        # Базовые поля WireGuard
        self.wg_fields = {
            "interface": ["PrivateKey", "Address", "DNS", "MTU", "ListenPort"],
            "peer": ["PublicKey", "PresharedKey", "Endpoint", "AllowedIPs", "PersistentKeepalive"]
        }
        # Поля обфускации AmneziaWG
        self.awg_fields = ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4", "I1", "I2", "I3", "I4", "I5"]

    def _parse_section(self, content: str, section: str) -> Dict[str, str]:
        """Извлекает пары ключ=значение из указанной секции."""
        result = {}
        # Ищем секцию, например [Interface] ... до следующей [ или конца файла
        pattern = rf"\[{section}\](.*?)(?=\n\[|\Z)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        
        if not match:
            return result

        section_text = match.group(1)
        for line in section_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
        
        return result

    def parse_conf(self, conf_content: str) -> Optional[Dict[str, Any]]:
        """
        Парсит полный текст .conf файла.
        Возвращает словарь с секциями 'interface', 'peer' и 'amnezia'.
        """
        try:
            interface_data = self._parse_section(conf_content, "Interface")
            peer_data = self._parse_section(conf_content, "Peer")

            if not interface_data or not peer_data:
                logger.error("Не найдены обязательные секции [Interface] или [Peer]")
                return None

            # Формируем результат
            parsed = {
                "interface": {k: v for k, v in interface_data.items() if k in self.wg_fields["interface"]},
                "peer": {k: v for k, v in peer_data.items() if k in self.wg_fields["peer"]},
                "amnezia": {}
            }

            # Извлекаем параметры AmneziaWG (могут быть как в Interface, так и в Peer)
            all_fields = {**interface_data, **peer_data}
            for field in self.awg_fields:
                if field in all_fields:
                    value = all_fields[field]
                    # Пытаемся привести числа к int, если это возможно
                    try:
                        parsed["amnezia"][field] = int(value) if value.isdigit() else value
                    except ValueError:
                        parsed["amnezia"][field] = value

            return parsed

        except Exception as e:
            logger.error(f"Ошибка парсинга .conf: {e}")
            return None

    def to_json(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """
        Преобразует результат parse_conf в формат, пригодный для сохранения в JSON.
        """
        if not parsed:
            return {}

        # Собираем плоскую структуру для удобства
        json_data = {
            "type": "amneziawg",
            "name": "WARP Amnezia",
            "interface": {
                "private_key": parsed["interface"].get("PrivateKey"),
                "address": parsed["interface"].get("Address"),
                "dns": parsed["interface"].get("DNS"),
                "mtu": parsed["interface"].get("MTU"),
                "listen_port": parsed["interface"].get("ListenPort")
            },
            "peer": {
                "public_key": parsed["peer"].get("PublicKey"),
                "preshared_key": parsed["peer"].get("PresharedKey"),
                "endpoint": parsed["peer"].get("Endpoint"),
                "allowed_ips": parsed["peer"].get("AllowedIPs"),
                "persistent_keepalive": parsed["peer"].get("PersistentKeepalive")
            },
            "amnezia_settings": parsed.get("amnezia", {})
        }

        # Убираем None значения для чистоты JSON
        for section in ["interface", "peer"]:
            json_data[section] = {k: v for k, v in json_data[section].items() if v is not None}

        return json_data