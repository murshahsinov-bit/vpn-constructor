import asyncio
import yaml
import logging
import os
import sys
import base64

from aggregator.sources.loader import SourceLoader
from aggregator.fetcher.downloader import ConfigDownloader
from aggregator.converter.link_to_outbound import LinkToOutboundConverter
from aggregator.filter.deduplicator import Deduplicator
from aggregator.health.checker import HealthChecker
from aggregator.formatter.to_json import build_subscription, save_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def process_mode(mode: str, config: dict):
    print(f"\n=== ЗАПУСК СБОРКИ ДЛЯ РЕЖИМА: {mode} ===")
    
    loader = SourceLoader()
    urls = loader.get_urls(mode)
    if not urls:
        print(f"❌ Нет источников для {mode}")
        return

    async with ConfigDownloader() as downloader:
        raw_texts = await downloader.fetch_many(urls)
    
    print(f"📥 Успешно скачано файлов: {len(raw_texts)} из {len(urls)}")
    
    converter = LinkToOutboundConverter()
    parsed_outbounds = []
    total_lines = 0
    
    for url, text in raw_texts.items():
        # Пытаемся расшифровать Base64
        try:
            decoded = base64.b64decode(text).decode('utf-8')
            if "://" in decoded:
                text = decoded
        except Exception:
            pass

        lines = text.splitlines()
        total_lines += len(lines)
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            if line.startswith(("vless://", "hysteria2://", "hy2://")):
                outbound = converter.convert(line)
                if outbound:
                    parsed_outbounds.append(outbound)
    
    print(f"📄 Всего строк скачано: {total_lines}")
    print(f"🔍 Успешно спарсено серверов: {len(parsed_outbounds)}")
    
    unique_outbounds = Deduplicator.deduplicate(parsed_outbounds)
    print(f"🧹 После удаления дубликатов: {len(unique_outbounds)}")
    
    # Для "Авто" не проверяем на сервере, отдаем как есть
    if mode == "auto":
        alive_outbounds = unique_outbounds
        print("⏩ Пропускаем health_check для auto")
    else:
        checker = HealthChecker(timeout=5.0, concurrency=50)
        alive_outbounds = await checker.check_many(unique_outbounds)
        print(f"💓 Живых серверов: {len(alive_outbounds)}")
    
    max_servers = config['aggregator']['max_servers_per_subscription']
    final_outbounds = alive_outbounds[:max_servers]
    print(f"✅ Итоговое количество в файле: {len(final_outbounds)}")
    
    template_path = os.path.join(config['paths']['templates_dir'], f"{mode}_template.json")
    final_config = build_subscription(final_outbounds, template_path)
    
    output_path = os.path.join(config['paths']['output_dir'], f"{mode}.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    save_config(final_config, output_path)
    print(f"💾 Сохранено: {output_path}")

async def main():
    with open("aggregator/config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    for mode in config['aggregator']['modes']:
        await process_mode(mode, config)

if __name__ == "__main__":
    asyncio.run(main())