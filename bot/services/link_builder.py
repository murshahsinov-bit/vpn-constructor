import hmac
import hashlib
import secrets
from urllib.parse import urlencode

class LinkBuilder:
    def __init__(self, secret_key: str, base_url: str = "https://your-domain.com/sub"):
        self.secret_key = secret_key.encode()
        self.base_url = base_url.rstrip("/")

    def _sign(self, user_id: int, mode: str, token: str) -> str:
        """Создает HMAC-подпись для защиты параметров ссылки."""
        payload = f"{user_id}:{mode}:{token}".encode()
        return hmac.new(self.secret_key, payload, hashlib.sha256).hexdigest()[:16]

    def generate_url(self, user_id: int, mode: str) -> str:
        """Генерирует уникальную ссылку подписки с токеном и подписью."""
        token = secrets.token_hex(16)  # Непредсказуемый токен (32 символа)
        signature = self._sign(user_id, mode, token)
        
        params = {
            "user": user_id,
            "mode": mode,
            "token": token,
            "sig": signature
        }
        return f"{self.base_url}/{mode}.json?{urlencode(params)}"

def verify_subscription_token(secret_key: str, user_id: int, mode: str, token: str, sig: str) -> bool:
    """Проверяет подлинность подписи при запросе подписки (используется на веб-сервере)."""
    payload = f"{user_id}:{mode}:{token}".encode()
    expected_sig = hmac.new(secret_key.encode(), payload, hashlib.sha256).hexdigest()[:16]
    return hmac.compare_digest(signature := expected_sig, sig)