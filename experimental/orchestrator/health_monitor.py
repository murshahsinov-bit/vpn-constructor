import asyncio
import logging
import aiohttp

logger = logging.getLogger(__name__)

class NodeHealthMonitor:
    """
    Агрессивный мониторинг экспериментальных нод.
    """
    def __init__(self, ping_url: str = "http://www.gstatic.com/generate_204", timeout: int = 5):
        self.ping_url = ping_url
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def check_node(self, proxy_url: str) -> bool:
        """
        Проверяет ноду через реальный HTTP-запрос (через прокси).
        proxy_url: socks5://user:pass@host:port или http://host:port
        """
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # aiohttp поддерживает передачу прокси
                async with session.get(self.ping_url, proxy=proxy_url) as resp:
                    return resp.status == 204
        except Exception:
            return False

    async def start_monitoring(self, nodes: list[dict]):
        """
        Принимает список нод, проверяет их и удаляет мертвые из пула.
        """
        tasks = [self.check_node(node["proxy_url"]) for node in nodes]
        results = await asyncio.gather(*tasks)
        
        alive_nodes = []
        for node, is_alive in zip(nodes, results):
            if is_alive:
                alive_nodes.append(node)
            else:
                logger.warning(f"💀 Нода {node.get('id')} не отвечает. Удалена из пула.")
                
        return alive_nodes