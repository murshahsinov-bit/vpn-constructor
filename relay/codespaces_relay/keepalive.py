import asyncio
import logging
from typing import List

logger = logging.getLogger(__name__)

class CodespacesKeepAlive:
    """
    Поддерживает Codespace во включённом состоянии.
    Стучится каждые 25 минут (лимит idle timeout — 30 минут).
    """
    def __init__(self, codespace_names: List[str], deployer):
        self.codespace_names = codespace_names
        self.deployer = deployer
        self.keepalive_interval = 25 * 60  # 25 минут в секундах
        self._running = False

    async def start(self):
        """Запускает фоновый цикл поддержания активности."""
        self._running = True
        logger.info(f"🔄 Запущен KeepAlive для {len(self.codespace_names)} сессий.")
        while self._running:
            for name in self.codespace_names:
                # Отправка простого запроса на запуск (если спит) или пинг
                # GitHub API не имеет "ping", поэтому используем start (он же будит)
                await self.deployer.start_codespace(name)
                logger.debug(f"⏱️ KeepAlive отправлен для {name}")
            
            await asyncio.sleep(self.keepalive_interval)

    def stop(self):
        """Останавливает цикл KeepAlive."""
        self._running = False
        logger.info("⏹️ KeepAlive остановлен.")