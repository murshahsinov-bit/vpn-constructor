import requests
from cloudflare import Cloudflare

class PagesDeployer:
    """
    Автоматизирует развертывание edgetunnel в Cloudflare Pages.
    """
    def __init__(self, api_token: str, account_id: str):
        self.client = Cloudflare(api_token=api_token)
        self.account_id = account_id

    def download_edgetunnel(self, save_path: str = "main.zip") -> str:
        """Скачивает актуальный архив edgetunnel с GitHub."""
        url = "https://github.com/cmliu/edgetunnel/raw/main/main.zip" # Проверь актуальную ссылку в репозитории
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return save_path

    def deploy(self, project_name: str, admin_password: str, uuid: str, zip_path: str):
        """
        Создает проект и загружает в него архив.
        """
        # 1. Создаем проект (если его еще нет)
        try:
            self.client.pages.projects.create(
                account_id=self.account_id,
                name=project_name,
                production_branch="main"
            )
        except Exception:
            pass # Проект уже существует

        # 2. Настраиваем переменные окружения
        self.client.pages.projects.edit(
            account_id=self.account_id,
            project_name=project_name,
            deployment_configs={
                "production": {
                    "env_vars": {
                        "ADMIN": {"value": admin_password, "type": "secret"},
                        "UUID": {"value": uuid, "type": "secret"},
                    }
                }
            }
        )

        # 3. Загружаем архив (прямой upload)
        # В SDK Cloudflare для Python нет прямого метода загрузки архива,
        # поэтому используем прямой HTTP-запрос к API.
        with open(zip_path, "rb") as f:
            files = {"file": (zip_path, f, "application/zip")}
            headers = {"Authorization": f"Bearer {self.client.api_token}"}
            resp = requests.post(
                f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/pages/projects/{project_name}/deployments",
                headers=headers,
                files=files
            )
            resp.raise_for_status()
            return resp.json()["result"]