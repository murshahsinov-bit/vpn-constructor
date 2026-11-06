import json
import os
import logging
from datetime import datetime, date
from typing import Dict, Any

logger = logging.getLogger(__name__)

class CodespacesQuotaTracker:
    """
    Отслеживает расход бесплатных core-hours GitHub Codespaces.
    Лимит: 120 core-hours/мес (60 часов на 2-ядерной VM).
    """
    def __init__(self, state_file: str = "quota_state.json", monthly_core_limit: int = 120):
        self.state_file = state_file
        self.monthly_core_limit = monthly_core_limit
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Загружает состояние из файла или создаёт новое на текущий месяц."""
        current_month = date.today().strftime("%Y-%m")
        
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("month") == current_month:
                        return data
            except Exception as e:
                logger.warning(f"Ошибка чтения состояния квоты: {e}")
        
        # Если файла нет или начался новый месяц — сбрасываем счётчик
        return {"month": current_month, "used_core_hours": 0.0}

    def _save_state(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def log_usage(self, hours: float, cores: int = 2):
        """Фиксирует использование core-hours и сохраняет состояние."""
        spent = hours * cores
        self.state["used_core_hours"] += spent
        self._save_state()
        logger.info(f"[Quota] Списано {spent} core-hours. Всего за месяц: {self.state['used_core_hours']}/{self.monthly_core_limit}")

    def has_quota_remaining(self, required_hours: float = 1.0, cores: int = 2) -> bool:
        """Проверяет, хватит ли квоты на запуск сессии."""
        needed = required_hours * cores
        remaining = self.monthly_core_limit - self.state["used_core_hours"]
        if remaining < needed:
            logger.warning(f"[Quota] Недостаточно core-hours: осталось {remaining}, нужно {needed}")
            return False
        return True