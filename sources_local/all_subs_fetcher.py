# sources_local/all_subs_fetcher.py
import aiohttp

class AllSubsFetcher:
    # Эндпоинты обновляются каждую минуту: final_sorted / random с параметром ?n=[reference:2]
    ENDPOINTS = [
        "https://final-sorted.solovyov-jenya2004.workers.dev/",
        "https://final-sorted-base64.solovyov-jenya2004.workers.dev/",
        "https://random.solovyov-jenya2004.workers.dev/?n=100"
    ]

    @staticmethod
    async def fetch_whitelist() -> str:
        combined = []
        async with aiohttp.ClientSession() as session:
            for url in AllSubsFetcher.ENDPOINTS:
                try:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            combined.append((await resp.text()).strip())
                except Exception:
                    continue
        return "\n".join(combined)