import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)

class NodeScheduler:
    """
    Управляет жизненным циклом экспериментальных нод.
    Следит за лимитами и ротирует упавшие серверы.
    """
    def __init__(self, max_nodes: int = 5, lifespan_minutes: int = 60):
        self.max_nodes = max_nodes
        self.lifespan = timedelta(minutes=lifespan_minutes)
        # Хранилище активных нод: {node_id: {"type": "cf_worker", "created": timestamp}}
        self.active_nodes: Dict[str, dict] = {}

    async def _deploy_new_node(self, node_type: str):
        """Заглушка для вызова конкретного деплойщика (Worker, WARP, Codespace)."""
        logger.info(f"Развертывание новой ноды типа: {node_type}")
        # Здесь должен быть вызов твоих deployer.py из cloudflare_workers / codespaces
        # Например: await WorkerProxyDeployer(...).deploy_simple_proxy()
        node_id = f"{node_type}_{int(datetime.utcnow().timestamp())}"
        return node_id

    async def _destroy_node(self, node_id: str):
        """Удаляет ноду и освобождает ресурсы."""
        logger.info(f"Удаление мертвой/устаревшей ноды: {node_id}")
        # Вызов API для удаления воркера или остановки сессии
        self.active_nodes.pop(node_id, None)

    async def _rotate_nodes(self):
        """Проверяет, не пора ли заменить устаревшие ноды."""
        now = datetime.utcnow()
        for node_id, data in list(self.active_nodes.items()):
            if now - data["created"] > self.lifespan:
                logger.warning(f"Нода {node_id} превысила лимит времени.")
                await self._destroy_node(node_id)

    async def run_loop(self):
        """Основной цикл планировщика."""
        while True:
            await self._rotate_nodes()
            
            # Если нод меньше лимита — добавляем новые
            if len(self.active_nodes) < self.max_nodes:
                # В реальности тут нужно чередовать типы (CF -> Codespaces -> WARP)
                new_id = await self._deploy_new_node(node_type="cloudflare_worker")
                if new_id:
                    self.active_nodes[new_id] = {"type": "cloudflare_worker", "created": datetime.utcnow()}
            
            await asyncio.sleep(300) # Проверка каждые 5 минут