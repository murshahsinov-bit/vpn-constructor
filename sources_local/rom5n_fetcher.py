# sources_local/rom5n_fetcher.py
import aiohttp

class Rom5nFetcher:
    # Локальный HTTP-сервер на порту 55000 и умные лимиты /sub/50[reference:3]
    LOCAL_URL = "http://127.0.0.1:55000/sub/50"

    @staticmethod
    async def fetch_local_sub() -> str:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(Rom5nFetcher.LOCAL_URL, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.text()
            except aiohttp.ClientConnectorError:
                # Локальный агрегатор не запущен
                pass
        return ""