import asyncio
import aiohttp
import logging
from urllib.parse import urlparse, urlunparse
from typing import Optional

logger = logging.getLogger(__name__)

class ConfigDownloader:
    """
    Асинхронный загрузчик конфигов с поддержкой зеркал и повторных попыток.
    Решает проблему блокировок raw.githubusercontent.com в РФ.
    """

    # Список зеркал в порядке приоритета (прокси и CDN)
    # GitHack рекомендуется как самый надежный прокси, jsDelivr может кэшировать с задержкой
    MIRRORS = [
        None,  # Оригинал (raw.githubusercontent.com)
        "raw.githack.com",  # GitHack (прокси)
        "cdn.jsdelivr.net",  # jsDelivr (CDN, только для файлов, путь меняется)
        "git.sr.ht",  # SourceHut (частный проект)
    ]

    def __init__(self, timeout: int = 30, max_retries: int = 3, proxy: Optional[str] = None):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.proxy = proxy
        # Семафор ограничивает количество одновременных подключений, чтобы не забанили
        self.semaphore = asyncio.Semaphore(10)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Создаем сессию с пулом соединений при входе в контекст."""
        connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(connector=connector, timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрываем сессию."""
        if self.session:
            await self.session.close()

    def _build_mirror_url(self, original_url: str, mirror: str) -> str:
        """Преобразует оригинальный URL GitHub в URL зеркала."""
        if mirror is None:
            return original_url
        
        parsed = urlparse(original_url)
        # Для GitHack (raw.githack.com) формат: https://raw.githack.com/user/repo/branch/file
        if "githack" in mirror:
            # Пример: https://raw.githubusercontent.com/user/repo/main/file -> https://raw.githack.com/user/repo/main/file
            path = parsed.path.replace("/raw.githubusercontent.com/", "")
            return f"https://{mirror}{path}"
        
        # Для jsDelivr формат: https://cdn.jsdelivr.net/gh/user/repo@branch/file
        elif "jsdelivr" in mirror:
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 4: # user/repo/branch/file...
                user, repo, branch = path_parts[0], path_parts[1], path_parts[2]
                file_path = "/".join(path_parts[3:])
                return f"https://{mirror}/gh/{user}/{repo}@{branch}/{file_path}"
        
        # Для остальных зеркал (SourceHut и т.д.) пробуем прямую замену домена
        return urlunparse(parsed._replace(netloc=mirror))

    async def fetch(self, url: str) -> Optional[str]:
        """
        Загружает конфиг по URL. Пробует оригинал, затем зеркала.
        Возвращает текст файла или None в случае неудачи.
        """
        if not self.session:
            raise RuntimeError("Downloader must be used within 'async with' context")

        for attempt in range(self.max_retries):
            for mirror in self.MIRRORS:
                target_url = self._build_mirror_url(url, mirror)
                try:
                    async with self.semaphore:
                        async with self.session.get(target_url, proxy=self.proxy) as response:
                            # Успех
                            if response.status == 200:
                                text = await response.text()
                                logger.info(f"✅ Загружено с {mirror or 'оригинала'}: {target_url}")
                                return text
                            
                            # Слишком много запросов или ошибка сервера — ждем и пробуем снова
                            elif response.status in (429, 500, 502, 503, 504):
                                logger.warning(f"⚠️ Ошибка {response.status} на {mirror or 'оригинале'}. Повтор...")
                                await asyncio.sleep(2 ** attempt) # Экспоненциальная задержка
                            
                            # 404 — файл не найден, нет смысла пробовать другие зеркала для этого URL
                            elif response.status == 404:
                                logger.error(f"❌ 404 Not Found: {target_url}")
                                break 

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(f"🔌 Сетевая ошибка на {mirror or 'оригинале'}: {e}")
                    continue # Пробуем следующее зеркало

        logger.error(f"💀 Не удалось загрузить после всех попыток: {url}")
        return None

    async def fetch_many(self, urls: list[str]) -> dict[str, str]:
        """Параллельно скачивает несколько URL."""
        tasks = [self.fetch(url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        # Возвращаем только успешные загрузки
        return {url: text for url, text in zip(urls, results) if text is not None}