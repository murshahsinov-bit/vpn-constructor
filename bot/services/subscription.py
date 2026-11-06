from datetime import datetime, timedelta
from typing import Optional

def calculate_expiry_date(days: int) -> datetime:
    """Вычисляет дату окончания подписки, прибавляя дни к текущему моменту."""
    return datetime.utcnow() + timedelta(days=days)

def is_subscription_active(expires_at: Optional[datetime]) -> bool:
    """Проверяет, активна ли подписка (не истекла ли дата)."""
    if not expires_at:
        return False
    return datetime.utcnow() < expires_at

def extend_subscription(current_expires_at: Optional[datetime], added_days: int) -> datetime:
    """Продлевает подписку: если активна — прибавляет дни к текущей дате, если нет — от сегодня."""
    base_date = current_expires_at if is_subscription_active(current_expires_at) else datetime.utcnow()
    return base_date + timedelta(days=added_days)