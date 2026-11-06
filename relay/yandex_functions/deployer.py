import os
import json
import zipfile
import tempfile
import logging
import subprocess
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class YandexFunctionsDeployer:
    """Автоматизация деплоя функции в Yandex Cloud."""

    def __init__(self, folder_id: str, sa_key_path: str, function_name: str = "vpn-relay-node"):
        self.folder_id = folder_id
        self.sa_key_path = sa_key_path
        self.function_name = function_name
        self.env = {**os.environ, "YC_SA_KEY_FILE": sa_key_path}

    def _create_zip(self, source_dir: str = "relay/yandex_functions") -> str:
        """Упаковка файлов функции в ZIP-архив."""
        zip_path = os.path.join(tempfile.gettempdir(), f"{self.function_name}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(source_dir):
                for file in files:
                    if file.endswith(".py") or file.endswith(".yaml"):
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, source_dir)
                        zf.write(full_path, arcname)
        logger.info(f"Создан архив: {zip_path}")
        return zip_path

    def deploy(self, memory_mb: int = 256, timeout_sec: int = 60) -> bool:
        """Деплой новой версии функции через YC CLI."""
        zip_path = self._create_zip()
        
        cmd = [
            "yc", "serverless", "function", "version", "create",
            "--function-name", self.function_name,
            "--runtime", "python311",
            "--entrypoint", "socks5_handler.relay_handler",
            "--memory", f"{memory_mb}MB",
            "--execution-timeout", f"{timeout_sec}s",
            "--source-path", zip_path,
            "--folder-id", self.folder_id
        ]
        
        try:
            logger.info(f"Запуск деплоя функции {self.function_name}...")
            result = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
            if result.returncode == 0:
                logger.info(f"✅ Функция успешно задеплоена: {result.stdout.strip()}")
                return True
            else:
                logger.error(f"❌ Ошибка деплоя: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Исключение при деплое: {e}")
            return False
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)