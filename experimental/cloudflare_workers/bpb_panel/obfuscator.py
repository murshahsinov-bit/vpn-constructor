import subprocess
import os
import logging

logger = logging.getLogger(__name__)

class CodeObfuscator:
    """
    Обфусцирует JavaScript-код worker.js с помощью javascript-obfuscator.
    Требуется Node.js и глобально установленный пакет:
    npm install -g javascript-obfuscator
    """
    def __init__(self, input_file: str, output_file: str = "_worker.js"):
        self.input_file = input_file
        self.output_file = output_file

    def obfuscate(self):
        """Запускает процесс обфускации."""
        if not os.path.exists(self.input_file):
            raise FileNotFoundError(f"Исходный файл {self.input_file} не найден.")

        cmd = [
            "javascript-obfuscator",
            self.input_file,
            "--output", self.output_file,
            "--compact", "true",
            "--control-flow-flattening", "true",
            "--control-flow-flattening-threshold", "1",
            "--dead-code-injection", "true",
            "--dead-code-injection-threshold", "1",
            "--identifier-names-generator", "hexadecimal",
            "--rename-globals", "true",
            "--string-array", "true",
            "--string-array-encoding", "rc4",
            "--string-array-threshold", "1",
            "--transform-object-keys", "true",
            "--unicode-escape-sequence", "true"
        ]

        try:
            logger.info(f"Запуск обфускации {self.input_file}...")
            subprocess.run(cmd, check=True)
            logger.info(f"Обфусцированный код сохранен в {self.output_file}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка обфускации: {e}")
            raise