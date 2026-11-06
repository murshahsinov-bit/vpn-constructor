import requests
import logging
from cloudflare import Cloudflare

logger = logging.getLogger(__name__)

class BPBDeployer:
    """
    Автоматизирует развертывание BPB Panel в Cloudflare Workers.
    """
    def __init__(self, api_token: str, account_id: str):
        self.client = Cloudflare(api_token=api_token)
        self.account_id = account_id
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

    def download_worker_script(self, save_path: str = "worker.js") -> str:
        """Скачивает последнюю версию worker.js из релиза BPB Panel."""
        url = "https://github.com/bia-pain-bache/BPB-Worker-Panel/releases/latest/download/worker.js"
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Скрипт воркера загружен в {save_path}")
        return save_path

    def create_kv_namespace(self, title: str = "bpb_kv") -> str:
        """Создает KV Namespace и возвращает его ID."""
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/storage/kv/namespaces"
        resp = requests.post(url, headers=self.headers, json={"title": title})
        resp.raise_for_status()
        namespace_id = resp.json()["result"]["id"]
        logger.info(f"Создан KV Namespace: {namespace_id}")
        return namespace_id

    def deploy_worker(self, worker_name: str, script_content: str, kv_id: str, secrets: dict) -> bool:
        """
        Загружает скрипт воркера, привязывает KV и устанавливает секреты.
        """
        # 1. Загрузка скрипта
        script_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/workers/scripts/{worker_name}"
        resp = requests.put(
            script_url,
            headers={"Authorization": f"Bearer {self.client.api_token}", "Content-Type": "application/javascript"},
            data=script_content
        )
        resp.raise_for_status()
        logger.info(f"Скрипт воркера {worker_name} загружен.")

        # 2. Привязка KV Namespace (через настройки воркера)
        bindings_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/workers/scripts/{worker_name}/bindings"
        bindings_payload = {
            "bindings": [
                {"name": "bpb", "type": "kv_namespace", "namespace_id": kv_id}
            ]
        }
        resp = requests.put(bindings_url, headers=self.headers, json=bindings_payload)
        resp.raise_for_status()
        logger.info(f"KV Namespace привязан к {worker_name}.")

        # 3. Установка переменных окружения (секретов)
        secrets_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/workers/scripts/{worker_name}/secrets"
        for key, value in secrets.items():
            secret_payload = {"name": key, "text": value, "type": "secret_text"}
            resp = requests.put(secrets_url, headers=self.headers, json=secret_payload)
            resp.raise_for_status()
            logger.info(f"Секрет {key} установлен.")
        
        return True