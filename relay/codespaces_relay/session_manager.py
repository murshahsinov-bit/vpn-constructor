import logging
from typing import Optional, List
from .deployer import CodespacesDeployer
from .quota_tracker import CodespacesQuotaTracker
from .keepalive import CodespacesKeepAlive

logger = logging.getLogger(__name__)

class CodespacesSessionManager:
    """
    Оркестрирует жизненный цикл временных Relay-нод на Codespaces.
    Интегрирует создание, учёт квоты, keepalive и остановку.
    """
    def __init__(self, github_token: str, owner: str, repo: str):
        self.deployer = CodespacesDeployer(github_token)
        self.quota = CodespacesQuotaTracker()
        self.owner = owner
        self.repo = repo
        self.active_sessions: List[str] = []
        self.keepalive: Optional[CodespacesKeepAlive] = None

    async def spawn_session(self) -> Optional[str]:
        """Создаёт новую сессию, проверяя квоту."""
        # 1. Проверка квоты (нужно ~1 час * 2 ядра = 2 core-hours)
        if not self.quota.has_quota_remaining(required_hours=1.0, cores=2):
            logger.error("❌ Недостаточно квоты Codespaces для новой сессии.")
            return None

        # 2. Создание и запуск
        cs_data = await self.deployer.create_codespace(self.owner, self.repo)
        if not cs_data:
            return None
        
        cs_name = cs_data["name"]
        self.active_sessions.append(cs_name)
        
        # 3. Учёт квоты (предварительно закладываем 1 час работы)
        self.quota.log_usage(hours=1.0, cores=2)
        
        # 4. Запуск KeepAlive (если ещё не запущен)
        if not self.keepalive:
            self.keepalive = CodespacesKeepAlive(self.active_sessions, self.deployer)
            # Запуск в фоне через asyncio.create_task
            import asyncio
            asyncio.create_task(self.keepalive.start())
            
        return cs_name

    async def terminate_session(self, codespace_name: str) -> bool:
        """Принудительно останавливает и удаляет сессию."""
        if codespace_name in self.active_sessions:
            success = await self.deployer.stop_codespace(codespace_name)
            if success:
                self.active_sessions.remove(codespace_name)
                logger.info(f"🗑️ Сессия {codespace_name} удалена из менеджера.")
                return True
        return False