import asyncio
import logging
from typing import Optional, Dict, Any, List
import aiohttp

logger = logging.getLogger(__name__)


class RegCloudProvisioner:
    """
    Асинхронный клиент для управления облачными серверами Рег.облако (CloudVPS).
    Автоматизирует создание узлов, мониторинг баланса и удаление инстансов.
    """
    def __init__(self, api_token: str, base_url: str = "https://api.cloudvps.reg.ru"):
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, endpoint: str, json_data: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        """Универсальный метод отправки HTTP-запросов к API CloudVPS."""
        url = f"{self.base_url}{endpoint}"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                async with session.request(method, url, json=json_data) as resp:
                    response_data = await resp.json()
                    if resp.status in (200, 201, 202):
                        return response_data
                    logger.error(f"❌ Reg.Cloud API error {resp.status}: {response_data}")
                    return None
            except Exception as e:
                logger.error(f"🔌 Ошибка сети при запросе к Reg.Cloud: {e}")
                return None

    async def get_balance(self) -> Optional[float]:
        """Получает текущий баланс аккаунта в рублях."""
        res = await self._request("GET", "/v1/balance_data")
        if res and "balance_data" in res:
            balance = res["balance_data"].get("balance", 0.0)
            logger.info(f"💰 Текущий баланс Reg.Cloud: {balance} RUB")
            return balance
        return None

    async def create_server(
        self,
        name: str,
        size: str = "cloud-1",
        image: str = "ubuntu-22.04",
        ssh_key_ids: Optional[List[str]] = None,
        backups: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Создает облачный сервер (реглет).
        Возвращает данные созданного сервера и ID фоновой задачи.
        """
        payload = {
            "name": name,
            "size": size,
            "image": image,
            "backups": str(backups).lower(),
        }
        if ssh_key_ids:
            payload["ssh_keys"] = ssh_key_ids

        logger.info(f"🚀 Запрос на создание сервера '{name}' (тариф: {size}, образ: {image})...")
        res = await self._request("POST", "/v1/reglets", json_data=payload)
        
        if res:
            server_info = res.get("reglet", {})
            task_info = res.get("links", {}).get("actions", [{}])[0]
            logger.info(f"✅ Сервер создан (ID: {server_info.get('id')}). Статус задачи: {task_info.get('status')}")
            return res
        return None

    async def list_servers(self) -> List[Dict[str, Any]]:
        """Возвращает список всех активных серверов в аккаунте."""
        res = await self._request("GET", "/v1/reglets")
        if res and "reglets" in res:
            return res["reglets"]
        return []

    async def delete_server(self, reglet_id: int) -> bool:
        """Удаляет сервер по его ID."""
        logger.warning(f"🗑️ Отправка запроса на удаление сервера ID {reglet_id}...")
        res = await self._request("DELETE", f"/v1/reglets/{reglet_id}")
        if res:
            logger.info(f"✅ Сервер {reglet_id} успешно поставлен в очередь на удаление.")
            return True
        return False

    async def check_task_status(self, task_id: int) -> Optional[str]:
        """Проверяет статус выполнения асинхронной операции в очереди задач."""
        res = await self._request("GET", f"/v1/tasks/{task_id}")
        if res and "task" in res:
            status = res["task"].get("status")
            logger.info(f"⏱️ Статус задачи {task_id}: {status}")
            return status
        return None