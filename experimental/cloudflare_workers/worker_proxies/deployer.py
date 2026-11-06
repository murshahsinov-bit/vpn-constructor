import logging
import requests
from cloudflare import Cloudflare

logger = logging.getLogger(__name__)

class WorkerProxyDeployer:
    """
    Автоматизирует развертывание простых прокси-скриптов (VLESS/Trojan) 
    в Cloudflare Workers через официальный Python SDK.
    """
    def __init__(self, api_token: str, account_id: str):
        # Инициализация клиента Cloudflare SDK
        self.client = Cloudflare(api_token=api_token)
        self.account_id = account_id

    def download_proxy_script(self, save_path: str = "vless_worker.js") -> str:
        """
        Скачивает готовый скрипт прокси (например, из популярного репозитория edgetunnel).
        """
        # Используем проверенный скрипт с поддержкой WebSocket
        url = "https://raw.githubusercontent.com/3Kmfi6HP/EDtunnel/main/_worker.js"
        logger.info(f"Скачивание скрипта прокси из {url}...")
        
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        logger.info(f"Скрипт сохранен в {save_path}")
        return save_path

    def deploy_simple_proxy(self, worker_name: str, script_path: str, uuid: str) -> bool:
        """
        Развертывает прокси-скрипт и настраивает переменные окружения.
        """
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()

            # В новом SDK (>= 4.3.1) деплой скрипта и настройка переменных 
            # объединены в одном удобном вызове
            logger.info(f"Развертывание воркера {worker_name}...")
            self.client.workers.scripts.update(
                account_id=self.account_id,
                script_name=worker_name,
                content=script_content,
                metadata={
                    "main_module": script_path.split("/")[-1],
                    "compatibility_date": "2026-11-01",
                    "bindings": [
                        {
                            "type": "plain_text",
                            "name": "UUID",
                            "text": uuid
                        },
                        {
                            "type": "plain_text",
                            "name": "PROXYIP",
                            "text": "proxyip.fxxk.workers.dev" # Запасной прокси-IP
                        }
                    ]
                }
            )
            logger.info(f"✅ Воркер {worker_name} успешно развернут с UUID: {uuid}")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка развертывания воркера: {e}")
            return False

    def deploy_with_durable_objects(self, worker_name: str, script_path: str) -> bool:
        """
        Для сложных сценариев (например, если прокси-скрипт использует Durable Objects 
        для управления тысячами WebSocket-соединений) требуется указать миграции.
        """
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()

            logger.info(f"Развертывание воркера {worker_name} с Durable Objects...")
            self.client.workers.scripts.update(
                account_id=self.account_id,
                script_name=worker_name,
                content=script_content,
                metadata={
                    "main_module": script_path.split("/")[-1],
                    "compatibility_date": "2026-11-01",
                    # Указываем Durable Object и миграцию для него
                    "bindings": [
                        {
                            "type": "durable_object_namespace",
                            "name": "WEBSOCKET_SERVER",
                            "class_name": "WebSocketServer"
                        }
                    ],
                    "migrations": {
                        "new_tag": "v1",
                        "steps": [
                            {
                                "new_sqlite_classes": ["WebSocketServer"]
                            }
                        ]
                    }
                }
            )
            logger.info(f"✅ Воркер {worker_name} с DO успешно развернут.")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка развертывания с DO: {e}")
            return False