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
from aggregator.formatter.to_txt import generate_txt

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
    raw_valid_links = []
    
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
                    # ЖЕСТКАЯ ПРОВЕРКА: оставляем только TLS и Reality
                    security = outbound.get("streamSettings", {}).get("security", "none")
                    if security not in ["tls", "reality"]:
                        continue 
                        
                    parsed_outbounds.append(outbound)
                    raw_valid_links.append(line)

    logger.info(f"📄 Всего спарсено безопасных серверов: {len(parsed_outbounds)}")
    
    unique_outbounds = Deduplicator.deduplicate(parsed_outbounds)
    unique_raw_links = list(set(raw_valid_links))
    
    logger.info(f"🧹 Уникальных серверов: {len(unique_outbounds)}")
    
    max_servers = config['aggregator']['max_servers_per_subscription']
    final_raw_links = unique_raw_links[:max_servers]
    max_json_outbounds = int(config['aggregator'].get('json_max_outbounds', 1))

    # Проверяем TCP-доступность в обоих режимах: в JSON теперь попадает
    # один сервер, и он должен быть живым, иначе подписка бесполезна.
    # Идём пачками и останавливаемся, как только набрали нужное количество.
    health_cfg = config['aggregator'].get('health_check', {})
    checker = HealthChecker(
        timeout=float(health_cfg.get('timeout_seconds', 5.0)),
        concurrency=int(health_cfg.get('concurrency', 50)),
    )
    batch_size = max(1, int(health_cfg.get('batch_size', 200)))
    needed = max(1, max_json_outbounds)
    alive_outbounds = []
    checked = 0

    for start in range(0, len(unique_outbounds), batch_size):
        batch = unique_outbounds[start:start + batch_size]
        checked += len(batch)
        alive_outbounds.extend(await checker.check_many(batch))
        if len(alive_outbounds) >= needed:
            break

    logger.info(f"🔎 Проверено {checked} из {len(unique_outbounds)}, живых: {len(alive_outbounds)}")
    
    # 1. Сохраняем JSON.
    # В JSON берём все живые outbounds, а не только первые max_servers:
    # build_subscription сам отфильтрует hysteria/xhttp и оставит
    # не более json_max_outbounds совместимых VLESS-серверов.
    template_path = os.path.join(config['paths']['templates_dir'], f"{mode}_template.json")
    final_config = None
    try:
        final_config = build_subscription(alive_outbounds, template_path, max_json_outbounds)
    except ValueError as exc:
        logger.error(f"❌ JSON для режима {mode} не собран: {exc}")
        logger.error("Старый JSON оставлен без изменений; TXT-подписка будет обновлена.")

    output_json = os.path.join(config['paths']['output_dir'], f"{mode}.json")
    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    if final_config is not None:
        save_config(final_config, output_json)
    
    # 2. Сохраняем TXT
    txt_content = generate_txt(final_raw_links)
    output_txt = os.path.join(config['paths']['output_dir'], f"{mode}_all.txt")
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(txt_content)

async def main():
    with open("aggregator/config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    for mode in config['aggregator']['modes']:
        await process_mode(mode, config)

# ВОТ ЭТИ ДВЕ СТРОЧКИ САМЫЕ ВАЖНЫЕ! БЕЗ НИХ СКРИПТ ПРОСТО ЗАКРЫВАЕТСЯ.
if __name__ == "__main__":
    asyncio.run(main())