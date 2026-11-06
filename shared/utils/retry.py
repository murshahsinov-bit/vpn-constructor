import asyncio
import logging
import functools
from typing import Callable, Any, Type

logger = logging.getLogger(__name__)

def async_retry(
    max_retries: int = 3, 
    initial_delay: float = 1.0, 
    backoff_factor: float = 2.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,)
) -> Callable:
    """
    Декоратор для асинхронных функций.
    Повторяет вызов при возникновении исключений.
    
    :param max_retries: Максимальное количество попыток (включая первую).
    :param initial_delay: Начальная задержка перед повтором (в секундах).
    :param backoff_factor: Множитель задержки (1 сек -> 2 сек -> 4 сек).
    :param exceptions: Кортеж исключений, при которых нужно повторять вызов.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        logger.error(f"❌ [{func.__name__}] Превышено число попыток ({max_retries}). Ошибка: {e}")
                        raise
                    
                    logger.warning(
                        f"⚠️ [{func.__name__}] Ошибка: {e}. "
                        f"Попытка {attempt}/{max_retries}. Повтор через {delay:.1f} сек..."
                    )
                    await asyncio.sleep(delay)
                    delay *= backoff_factor
                    
        return wrapper
    return decorator