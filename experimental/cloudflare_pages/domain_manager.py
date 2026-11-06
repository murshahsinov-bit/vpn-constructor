from cloudflare import Cloudflare

class DomainManager:
    """
    Управляет кастомными доменами для Cloudflare Pages.
    """
    def __init__(self, api_token: str, account_id: str):
        self.client = Cloudflare(api_token=api_token)
        self.account_id = account_id

    def add_custom_domain(self, project_name: str, domain_name: str):
        """
        Привязывает домен к проекту Pages.
        Возвращает статус верификации.
        """
        domain = self.client.pages.projects.domains.create(
            account_id=self.account_id,
            project_name=project_name,
            name=domain_name,
        )
        return domain

    def verify_domain(self, project_name: str, domain_name: str):
        """
        Проверяет статус привязки домена.
        """
        # В SDK нет прямого метода get для одного домена, поэтому запрашиваем список
        domains = self.client.pages.projects.domains.list(
            account_id=self.account_id,
            project_name=project_name,
        )
        for d in domains:
            if d.name == domain_name:
                return d
        return None