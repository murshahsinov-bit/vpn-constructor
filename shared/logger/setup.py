import logging
import logging.handlers
import os
import sys
from typing import Optional

def setup_logging(
    log_dir: str = "logs", 
    log_level: int = logging.INFO, 
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5
) -> None:
    """
    Инициализирует глобальную конфигурацию логирования.
    
    :param log_dir: Папка для сохранения файлов логов.
    :param log_level: Минимальный уровень логирования (по умолчанию INFO).
    :param max_bytes: Максимальный размер одного файла лога перед ротацией.
    :param backup_count: Количество старых файлов лога, которые нужно хранить.
    """
    # Создаем директорию для логов, если её нет
    os.makedirs(log_dir, exist_ok=True)
    
    # Формат сообщений: [Время] [Модуль] [Уровень] Сообщение
    log_format = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Получаем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Очищаем существующие хендлеры, чтобы избежать дублирования при перезапуске
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 1. Хендлер для вывода в консоль (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    # 2. Хендлер для записи в файл с ротацией
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(log_dir, "app.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    # Отдельный файл только для ошибок (ERROR и CRITICAL)
    error_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(log_dir, "errors.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(log_format)
    root_logger.addHandler(error_handler)

    # Подавляем слишком болтливые логи от сторонних библиотек
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    root_logger.info("✅ Система логирования успешно инициализирована.")


def get_logger(name: str) -> logging.Logger:
    """
    Возвращает логгер для конкретного модуля.
    Использование: logger = get_logger(__name__)
    """
    return logging.getLogger(name)