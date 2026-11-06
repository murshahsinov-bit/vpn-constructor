import asyncio
import yaml
import logging
import os
import base64

from aggregator.sources.loader import SourceLoader
from aggregator.fetcher.downloader import ConfigDownloader
from aggregator.converter.link_to_outbound import LinkToOutboundConverter
from aggregator.filter.deduplicator import Deduplicator
from aggregator.health.checker import HealthChecker
from aggregator.formatter.to_json import build_subscription, save_config
from aggregator.formatter.to_txt import generate_txt  # Импортируем новый генератор

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def process_mode(mode: str, config: dict):
    logger.info(f"=== ЗАПУСК СБОРКИ ДЛЯ РЕЖИМА: {mode} ===")
    
    loader = SourceLoader()
    urls = loader.get_urls(mode)
    if not urls:
        return

    async with ConfigDownloader() as downloader:
        raw_texts = await downloader.fetch_many(urls)
    
    converter = LinkToOutboundConverter()
    parsed_outbounds = []
    raw_valid_links = [] # Сюда собираем сами ссылки (vless://...)
    
    for url, text in raw_texts.items():
        try:
            decoded = base64.b64decode(text).decode('utf-8')
            if "://" in decoded:
                text = decoded
        except Exception:
            pass

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            if line.startswith(("vless://", "hysteria2://", "hy2://")):
                outbound = converter.convert(line)
                if outbound:
                    parsed_outbounds.append(outbound)
                    raw_valid_links.append(line) # Сохраняем оригинальную ссылку

    logger.info(f"📄 Всего спарсено: {len(parsed_outbounds)}")
    
    unique_outbounds = Deduplicator.deduplicate(parsed_outbounds)
    # Дедупликация для сырых ссылок (чтобы в txt не было дублей)
    unique_raw_links = list(set(raw_valid_links))
    
    logger.info(f"🧹 Уникальных серверов: {len(unique_outbounds)}")
    
    if mode == "auto":
        alive_outbounds = unique_outbounds
    else:
        checker = HealthChecker(timeout=5.0, concurrency=50)
        alive_outbounds = await checker.check_many(unique_outbounds)
    
    max_servers = config['aggregator']['max_servers_per_subscription']
    final_outbounds = alive_outbounds[:max_servers]
    final_raw_links = unique_raw_links[:max_servers]
    
    # 1. Сохраняем JSON (Умный автовыбор)
    template_path = os.path.join(config['paths']['templates_dir'], f"{mode}_template.json")
    final_config = build_subscription(final_outbounds, template_path)
    
    output_json = os.path.join(config['paths']['output_dir'], f"{mode}.json")
    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    save_config(final_config, output_json)
    logger.info(f"💾 Сохранено: {output_json} (серверов: {len(final_outbounds)})")
    
    # 2. Сохраняем TXT (Список стран с флагами)
    txt_content = generate_txt(final_raw_links)
    output_txt = os.path.join(config['paths']['output_dir'], f"{mode}_all.txt")
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(txt_content)
    logger.info(f"💾 Сохранено: {output_txt} (серверов: {len(final_raw_links)})")

async def main():
    with open("aggregator/config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    for mode in config['aggregator']['modes']:
        await process_mode(mode, config)

if __name__ == "__main__":
    asyncio.run(main())