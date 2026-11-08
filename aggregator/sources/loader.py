import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SourceLoader:
    """Загружает список источников из JSON и фильтрует их по режиму."""

    def __init__(self, json_path: str = "aggregator/sources/sources.json"):
        self.json_path = json_path
        self.registry = self._load_registry()

    def _load_registry(self) -> Dict[str, List[Dict[str, Any]]]:
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Файл реестра не найден: {self.json_path}")
            return {"auto": [], "whitelist": []}
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON в {self.json_path}: {e}")
            return {"auto": [], "whitelist": []}

    def get_sources(self, mode: str) -> List[Dict[str, Any]]:
        """
        Возвращает источники для режима вместе с метаданными:
        name, url, format. Именно name используется для проверки
        происхождения серверов в whitelist-режиме.
        """
        mode = mode.lower().strip()
        sources = self.registry.get(mode, [])

        result = []
        for source in sources:
            if not source.get("enabled", True):
                continue
            url = source.get("url")
            if not url:
                continue
            result.append({
                "name": source.get("name") or url,
                "url": url,
                "format": (source.get("format") or "text").lower(),
            })

        logger.info(f"Режим '{mode}': загружено {len(result)} источников.")
        return result

    def get_urls(self, mode: str) -> List[str]:
        """Совместимость: только URL для заданного режима."""
        return [source["url"] for source in self.get_sources(mode)]
