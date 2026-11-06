import os
import subprocess
import logging
from typing import Optional, Dict, Any

from .parsers.amnezia_parser import AmneziaParser

logger = logging.getLogger(__name__)

class WarpRunner:
    """
    Оркестратор генерации конфигов Cloudflare WARP.
    Запускает bash-скрипты из папки bash_scripts/ и парсит результат.
    """
    def __init__(self, scripts_dir: str = "experimental/warp_generators/bash_scripts"):
        self.scripts_dir = scripts_dir
        self.parser = AmneziaParser()

    def _run_script(self, script_name: str, output_file: str = "warp.conf") -> bool:
        """
        Запускает bash-скрипт и ждет его завершения.
        Возвращает True, если файл output_file был создан.
        """
        script_path = os.path.join(self.scripts_dir, script_name)
        if not os.path.exists(script_path):
            logger.error(f"❌ Скрипт не найден: {script_path}")
            return False

        logger.info(f"🚀 Запуск скрипта: {script_name}")
        try:
            # Запускаем скрипт через bash
            result = subprocess.run(
                ["bash", script_path],
                capture_output=True,
                text=True,
                timeout=300  # 5 минут на генерацию
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Скрипт завершился с ошибкой (код {result.returncode}): {result.stderr}")
                return False

            # Проверяем, создался ли файл конфигурации
            if not os.path.exists(output_file):
                logger.warning(f"⚠️ Файл {output_file} не найден после выполнения скрипта.")
                return False

            logger.info(f"✅ Скрипт успешно выполнен. Файл {output_file} найден.")
            return True

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Таймаут выполнения скрипта {script_name}.")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка при запуске скрипта: {e}")
            return False

    def generate_amnezia_config(self, script_name: str = "warp_amnezia.sh", output_file: str = "warp.conf") -> Optional[Dict[str, Any]]:
        """
        Генерирует и парсит конфиг AmneziaWG.
        Возвращает словарь с параметрами для сохранения в JSON.
        """
        if not self._run_script(script_name, output_file):
            return None

        try:
            with open(output_file, "r", encoding="utf-8") as f:
                conf_content = f.read()

            parsed_conf = self.parser.parse_conf(conf_content)
            if not parsed_conf:
                logger.error("❌ Не удалось распарсить конфиг.")
                return None

            json_data = self.parser.to_json(parsed_conf)
            logger.info("✅ Конфиг AmneziaWG успешно распарсен.")
            return json_data

        except Exception as e:
            logger.error(f"❌ Ошибка при чтении или парсинге файла {output_file}: {e}")
            return None
        finally:
            # Опционально: удаляем временный файл после обработки
            if os.path.exists(output_file):
                os.remove(output_file)
                logger.info(f"🧹 Временный файл {output_file} удален.")

    def generate_karing_config(self, script_name: str = "warp_karing.sh", output_file: str = "warp.json") -> Optional[Dict[str, Any]]:
        """
        Генерирует конфиг для Karing/Hiddify (обычно JSON).
        Парсер для JSON-формата Karing можно добавить отдельно, 
        здесь показана базовая логика запуска.
        """
        if not self._run_script(script_name, output_file):
            return None

        try:
            import json
            with open(output_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"✅ Конфиг Karing успешно загружен.")
            return data
        except Exception as e:
            logger.error(f"❌ Ошибка чтения JSON для Karing: {e}")
            return None
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)