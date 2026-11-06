import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CodespacesDeployer:
    """
    Управляет развёртыванием и запуском Codespace через GitHub REST API.
    """
    def __init__(self, github_token: str):
        self.github_token = github_token
        self.headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        self.base_url = "https://api.github.com"

    async def create_codespace(self, owner: str, repo: str, machine_type: str = "basicLinux32gb") -> Optional[dict]:
        """Создаёт Codespace в указанном репозитории."""
        url = f"{self.base_url}/repos/{owner}/{repo}/codespaces"
        payload = {"machine": machine_type}
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    logger.info(f"✅ Codespace создан: {data.get('name')}")
                    return data
                else:
                    logger.error(f"❌ Ошибка создания Codespace ({resp.status}): {await resp.text()}")
                    return None

    async def start_codespace(self, codespace_name: str) -> bool:
        """Запускает остановленный Codespace."""
        url = f"{self.base_url}/user/codespaces/{codespace_name}/start"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(url) as resp:
                if resp.status in (200, 202):
                    logger.info(f"✅ Codespace {codespace_name} запущен.")
                    return True
                logger.error(f"❌ Ошибка запуска Codespace ({resp.status}): {await resp.text()}")
                return False

    async def stop_codespace(self, codespace_name: str) -> bool:
        """Останавливает Codespace."""
        url = f"{self.base_url}/user/codespaces/{codespace_name}/stop"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(url) as resp:
                if resp.status in (200, 204):
                    logger.info(f"✅ Codespace {codespace_name} остановлен.")
                    return True
                logger.error(f"❌ Ошибка остановки Codespace ({resp.status})")
                return False