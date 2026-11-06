# sources_local/nikita29a_fetcher.py
import aiohttp
import asyncio
import logging

class Nikita29aFetcher:
    # Ежедневное автообновление подписок mirror/1..5.txt[reference:1]
    BASE_URL = "https://raw.githubusercontent.com/nikita29a/FreeProxyList/main/mirror/{}.txt"

    @staticmethod
    async def fetch_all_mirrors() -> str:
        combined = []
        async with aiohttp.ClientSession() as session:
            async def _get(idx: int):
                try:
                    async with session.get(Nikita29aFetcher.BASE_URL.format(idx), timeout=10) as resp:
                        if resp.status == 200:
                            return await resp.text()
                except Exception:
                    return ""
            results = await asyncio.gather(*[_get(i) for i in range(1, 6)])
            for text in results:
                if text:
                    combined.append(text.strip())
        return "\n".join(combined)