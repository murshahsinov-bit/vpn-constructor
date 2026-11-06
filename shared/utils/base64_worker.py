import base64
import logging

logger = logging.getLogger(__name__)

def encode_b64(text: str) -> str:
    """Кодирует строку в Base64 (UTF-8)."""
    try:
        return base64.b64encode(text.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Ошибка кодирования Base64: {e}")
        return ""

def decode_b64(encoded_str: str) -> str:
    """
    Декодирует строку из Base64.
    Автоматически добавляет padding (символы '='), если его не хватает.
    """
    try:
        # Убираем возможные пробелы и переносы строк
        encoded_str = encoded_str.strip().replace("\n", "").replace("\r", "")
        
        # Добавляем padding до кратности 4
        padding_needed = len(encoded_str) % 4
        if padding_needed:
            encoded_str += "=" * (4 - padding_needed)
            
        decoded_bytes = base64.b64decode(encoded_str)
        return decoded_bytes.decode('utf-8')
    except Exception as e:
        logger.debug(f"Ошибка декодирования Base64: {e}. Строка: {encoded_str[:20]}...")
        return ""