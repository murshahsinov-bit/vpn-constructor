import asyncio
import logging
import socket
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class HealthChecker:
    """
    Асинхронная проверка доступности серверов (TCP handshake).
    Для VLESS/Hysteria2 проверяет, открыт ли порт.
    """

    def __init__(self, timeout: float = 3.0, concurrency: int = 50):
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(concurrency)

    async def _check_tcp(self, host: str, port: int) -> bool:
        """
        Пытается установить TCP-соединение с хостом.
        Возвращает True, если порт открыт, иначе False.
        """
        async with self.semaphore:
            try:
                # asyncio.open_connection создает TCP-соединение
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=self.timeout
                )
                writer.close()
                await writer.wait_closed()
                return True
            except (asyncio.TimeoutError, ConnectionRefusedError, socket.gaierror, OSError):
                return False

    def _extract_host_port(self, outbound: Dict[str, Any]) -> Optional[tuple]:
        """Извлекает адрес и порт из outbound-объекта."""
        protocol = outbound.get("protocol", "")
        
        if protocol == "vless":
            vnext = outbound.get("settings", {}).get("vnext", [{}])[0]
            return vnext.get("address"), vnext.get("port")
            
        elif protocol == "hysteria":
            settings = outbound.get("settings", {})
            return settings.get("address"), settings.get("port")
            
        return None

    async def check_many(self, outbounds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Принимает список outbound-объектов, возвращает только те, что прошли TCP-проверку.
        """
        tasks = []
        valid_outbounds = []

        for ob in outbounds:
            hp = self._extract_host_port(ob)
            if hp and hp[0] and hp[1]:
                host, port = hp
                tasks.append(self._check_tcp(host, port))
            else:
                # Если не удалось извлечь хост/порт, пропускаем
                tasks.append(asyncio.sleep(0, result=False))

        results = await asyncio.gather(*tasks)

        for ob, is_alive in zip(outbounds, results):
            if is_alive:
                valid_outbounds.append(ob)
            else:
                logger.debug(f"❌ Сервер мертв (TCP fail): {self._extract_host_port(ob)}")

        logger.info(f"✅ Health check: {len(valid_outbounds)}/{len(outbounds)} серверов живы.")
        return valid_outbounds