# sources_local/igareck_mirror.py
import aiohttp
import logging

class IgareckMirrorFetcher:
    # Зеркала из официального MIRRORS.md с сохранением актуального пути[reference:0]
    MIRRORS = [
        "https://raw.githack.com/igareck/vpn-configs-for-russia/main/",
        "https://gitlab.com/igareck/vpn-configs-for-russia/-/raw/main/",
        "https://git.sr.ht/~igareck/vpn-configs-for-russia/blob/main/",
        "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/"
    ]

    @staticmethod
    async def fetch_subscription(filename: str = "BLACK_VLESS_RUS_mobile.txt") -> str:
        async with aiohttp.ClientSession() as session:
            for mirror in IgareckMirrorFetcher.MIRRORS:
                try:
                    url = f"{mirror}{filename}"
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            return await resp.text()
                except Exception as e:
                    logging.debug(f"Зеркало {mirror} недоступно: {e}")
            return ""