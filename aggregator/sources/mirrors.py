import logging
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

class GitHubMirror:
    """Преобразует raw-ссылки GitHub в рабочие зеркала для обхода блокировок."""

    MIRRORS = [
        None,  # Оригинал (может не работать в РФ)
        "raw.githack.com",  # GitHack (прокси)
        "cdn.jsdelivr.net",  # jsDelivr (CDN)
    ]

    @classmethod
    def build_url(cls, original_url: str, mirror: str | None) -> str:
        """Строит URL для конкретного зеркала."""
        if mirror is None:
            return original_url

        parsed = urlparse(original_url)
        
        if "githack" in mirror:
            # https://raw.githubusercontent.com/user/repo/branch/file 
            # -> https://raw.githack.com/user/repo/branch/file
            path = parsed.path.replace("/raw.githubusercontent.com/", "")
            return f"https://{mirror}{path}"
            
        elif "jsdelivr" in mirror:
            # https://raw.githubusercontent.com/user/repo/branch/file
            # -> https://cdn.jsdelivr.net/gh/user/repo@branch/file
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 4:
                user, repo, branch = path_parts[0], path_parts[1], path_parts[2]
                file_path = "/".join(path_parts[3:])
                return f"https://{mirror}/gh/{user}/{repo}@{branch}/{file_path}"
        
        # Fallback: простая замена домена (для нестандартных зеркал)
        return urlunparse(parsed._replace(netloc=mirror))

    @classmethod
    def get_mirror_urls(cls, original_url: str) -> list[str]:
        """Возвращает список всех доступных URL (оригинал + зеркала) в порядке приоритета."""
        return [cls.build_url(original_url, m) for m in cls.MIRRORS]