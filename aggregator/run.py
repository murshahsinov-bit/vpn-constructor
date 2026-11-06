import asyncio
import yaml
import logging
import os
import sys
import base64

from aggregator.sources.loader import SourceLoader
from aggregator.fetcher.downloader import ConfigDownloader
from aggregator.parsers.vless import parse_vless_uri
from aggregator.parsers.hysteria2 import parse_hysteria2_uri
from aggregator.converter.link_to_outbound import LinkToOutboundConverter
from aggregator.filter.deduplicator import Deduplicator
from aggregator.filter.scorer import ConfigScorer
from aggregator.health.checker import HealthChecker
from aggregator.formatter.to_json import build_subscription, save_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def process_mode(mode: str, config: dict):
    logger.info(f"🚀 Начинаю сборку режима: {mode}")
    
    loader = SourceLoader()
    urls = loader.get_urls(mode)
    if not urls:
        return

    async with ConfigDownloader() as downloader:
        raw_texts = await downloader.fetch_many(urls)
    
    converter = LinkToOutboundConverter()
    parsed_outbounds = []
    
    for url, text in raw_texts.items():
        # Пытаемся расшифровать Base64 (для некоторых источников)
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
            
            if line.startswith("vless://") or line.startswith("hysteria2://") or line.startswith("hy2://"):
                outbound = converter.convert(line)
                if outbound:
                    parsed_outbounds.append(outbound)
    
    logger.info(f"🔍 Спарсено {len(parsed_outbounds)} серверов")
    unique_outbounds = Deduplicator.deduplicate(parsed_outbounds)
    logger.info(f"🧹 После удаления дубликатов осталось {len(unique_outbounds)}")
    
    # Для "Авто" режима мы НЕ проверяем серверы на GitHub, 
    # чтобы не отсеять те, что работают в РФ. INCY проверит их сам.
    if mode == "auto":
        alive_outbounds = unique_outbounds
        logger.info("⏩ Пропускаем health_check для режима auto (собираем кладбище)")
    else:
        checker = HealthChecker(
            timeout=config['aggregator']['health_check']['timeout_seconds'],
            concurrency=config['aggregator']['health_check']['concurrency']
        )
        alive_outbounds = await checker.check_many(unique_outbounds)
    
    scored_outbounds = ConfigScorer.sort_by_score(alive_outbounds)
    
    max_servers = config['aggregator']['max_servers_per_subscription']
    final_outbounds = scored_outbounds[:max_servers]
    
    template_path = os.path.join(config['paths']['templates_dir'], f"{mode}_template.json")
    if not os.path.exists(template_path):
        logger.error(f"Шаблон не найден: {template_path}")
        return
        
    final_config = build_subscription(final_outbounds, template_path)
    
    output_path = os.path.join(config['paths']['output_dir'], f"{mode}.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    save_config(final_config, output_path)
    logger.info(f"💾 Сохранено: {output_path} (серверов: {len(final_outbounds)})")

async def main():
    with open("aggregator/config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    modes = config['aggregator']['modes']
    logger.info(f"Запуск агрегатора для режимов: {modes}")
    
    for mode in modes:
        await process_mode(mode, config)
    
    logger.info("🏁 Работа агрегатора завершена.")

if __name__ == "__main__":
    asyncio.run(main())