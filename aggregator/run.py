import asyncio
import yaml
import logging
import os
import sys

# Импорт наших модулей
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
    """Полный цикл сборки для одного режима (auto или whitelist)."""
    logger.info(f"🚀 Начинаю сборку режима: {mode}")
    
    # 1. Загрузка источников
    loader = SourceLoader()
    urls = loader.get_urls(mode)
    if not urls:
        logger.warning(f"Нет источников для режима {mode}, пропускаю.")
        return

    # 2. Скачивание (параллельно)
    async with ConfigDownloader() as downloader:
        # fetch_many возвращает dict {url: text}, но нам нужны просто тексты
        raw_texts = await downloader.fetch_many(urls)
    
    if not raw_texts:
        logger.error(f"Не удалось скачать ни одного файла для режима {mode}")
        return

    # 3. Парсинг и конвертация
    converter = LinkToOutboundConverter()
    parsed_outbounds = []
    
    for url, text in raw_texts.items():
        # Если это JSON от tiagorrg (tiagorrg_keys), он может быть уже готовым списком
        # Для простоты обрабатываем как текст с VLESS-ссылками, но можно добавить обработку JSON
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            parsed_dict = None
            if line.startswith("vless://"):
                parsed_dict = parse_vless_uri(line)
            elif line.startswith("hysteria2://") or line.startswith("hy2://"):
                parsed_dict = parse_hysteria2_uri(line)
                
            if parsed_dict:
                # Конвертируем в outbound-объект Xray
                outbound = converter.convert(line)
                if outbound:
                    parsed_outbounds.append(outbound)
    
    logger.info(f"🔍 Спарсено и сконвертировано {len(parsed_outbounds)} серверов")
    
    # 4. Фильтрация (удаление дубликатов)
    unique_outbounds = Deduplicator.deduplicate(parsed_outbounds)
    logger.info(f"🧹 После удаления дубликатов осталось {len(unique_outbounds)} серверов")
    
    # 5. Health Check (проверка живости)
    checker = HealthChecker(
        timeout=config['aggregator']['health_check']['timeout_seconds'],
        concurrency=config['aggregator']['health_check']['concurrency']
    )
    alive_outbounds = await checker.check_many(unique_outbounds)
    
    # 6. Оценка и сортировка
    # Добавляем direct и block перед сортировкой, чтобы они были в конце
    alive_outbounds.extend([
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"}
    ])
    
    scored_outbounds = ConfigScorer.sort_by_score(alive_outbounds)
    
    # 7. Отсечение по минимальному баллу (опционально, если нужно)
    # Убираем direct/block из скоринга, так как у них нет streamSettings
    # В реальности нужно фильтровать по _score только прокси-серверы
    # (Для простоты пропускаем этот шаг или адаптируем логику)
    
    # 8. Ограничение количества серверов
    max_servers = config['aggregator']['max_servers_per_subscription']
    final_outbounds = scored_outbounds[:max_servers]
    
    logger.info(f"✅ Оставлено {len(final_outbounds)} лучших серверов для подписки")
    
    # 9. Сборка итогового JSON
    template_path = os.path.join(config['paths']['templates_dir'], f"{mode}_template.json")
    if not os.path.exists(template_path):
        logger.error(f"Шаблон не найден: {template_path}")
        return
        
    # Загружаем шаблон, чтобы модифицировать его
    import json
    with open(template_path, 'r', encoding='utf-8') as f:
        template = json.load(f)
        
    # Переопределяем outbounds в шаблоне
    template['outbounds'] = final_outbounds
    # Обновляем селектор балансировщика, чтобы он указывал на наши теги
    # (to_json.py уже делает это, но здесь мы собираем вручную для примера)
    # В идеале нужно использовать build_subscription из to_json.py
    # Но для упрощения покажем логику:
    
    from aggregator.formatter.to_json import build_subscription
    # build_subscription создаст конфиг с нуля, но мы можем использовать его как базу
    final_config = build_subscription(final_outbounds)
    
    # Сохраняем
    output_path = os.path.join(config['paths']['output_dir'], f"{mode}.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    save_config(final_config, output_path)
    logger.info(f"💾 Сохранено: {output_path}")

async def main():
    # Загрузка конфигурации
    with open("aggregator/config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    modes = config['aggregator']['modes']
    logger.info(f"Запуск агрегатора для режимов: {modes}")
    
    # Запускаем обработку каждого режима параллельно
    tasks = [process_mode(mode, config) for mode in modes]
    await asyncio.gather(*tasks)
    
    logger.info("🏁 Работа агрегатора завершена.")

if __name__ == "__main__":
    asyncio.run(main())