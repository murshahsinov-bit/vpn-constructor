import json
import logging
import os
from datetime import datetime, date
from typing import Dict, Any

logger = logging.getLogger(__name__)

class YandexQuotaTracker:
    """Отслеживание расхода бесплатной квоты Yandex Cloud Functions."""
    
    def __init__(self, state_file: str = "yc_quota_state.json"):
        self.state_file = state_file
        self.limit_invocations = 1_000_000
        self.limit_gb_hours = 10.0
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        current_month = date.today().strftime("%Y-%m")
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("month") == current_month:
                        return data
            except Exception as e:
                logger.warning(f"Ошибка чтения состояния квоты: {e}")
        return {"month": current_month, "invocations": 0, "gb_hours": 0.0}

    def _save_state(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def log_usage(self, memory_mb: int = 256, duration_ms: float = 100.0):
        gb = memory_mb / 1024.0
        hours = duration_ms / 3_600_000.0
        self.state["invocations"] += 1
        self.state["gb_hours"] += gb * hours
        self._save_state()
        logger.info(f"Вызовов: {self.state['invocations']}, ГБ×час: {self.state['gb_hours']:.4f}")

    def is_over_threshold(self) -> bool:
        return (self.state["invocations"] / self.limit_invocations > 0.85 or 
                self.state["gb_hours"] / self.limit_gb_hours > 0.85)