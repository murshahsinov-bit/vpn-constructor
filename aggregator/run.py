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
                        continue # Пропускаем всё, что не TLS/Reality
                        
                    parsed_outbounds.append(outbound)
                    raw_valid_links.append(line)

    logger.info(f"📄 Всего спарсено безопасных серверов: {len(parsed_outbounds)}")
    
    unique_outbounds = Deduplicator.deduplicate(parsed_outbounds)
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
    
    # 1. Сохраняем JSON
    template_path = os.path.join(config['paths']['templates_dir'], f"{mode}_template.json")
    final_config = build_subscription(final_outbounds, template_path)
    
    output_json = os.path.join(config['paths']['output_dir'], f"{mode}.json")
    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    save_config(final_config, output_json)
    
    # 2. Сохраняем TXT
    txt_content = generate_txt(final_raw_links)
    output_txt = os.path.join(config['paths']['output_dir'], f"{mode}_all.txt")
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(txt_content)