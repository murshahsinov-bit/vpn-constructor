import uuid
import secrets
import json

class ConfigGenerator:
    """
    Генерирует конфигурацию и секреты для BPB Panel.
    """
    @staticmethod
    def generate_secrets() -> dict:
        """Создает уникальные UUID, пароль для Trojan и путь подписки."""
        return {
            "UUID": str(uuid.uuid4()),
            "TROJAN_PASS": secrets.token_urlsafe(16),
            "SUB_PATH": f"/sub/{secrets.token_hex(8)}",
            "PANEL_PASSWORD": secrets.token_urlsafe(12)
        }

    @staticmethod
    def build_config(secrets: dict, custom_domain: str = None) -> dict:
        """
        Формирует объект конфигурации для дальнейшего использования.
        """
        config = {
            "secrets": secrets,
            "domain": custom_domain or "worker.example.workers.dev",
            "protocols": ["VLESS", "Trojan", "WireGuard"]
        }
        return config

    @staticmethod
    def export_to_json(config: dict, filepath: str):
        """Сохраняет конфигурацию в JSON-файл."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)