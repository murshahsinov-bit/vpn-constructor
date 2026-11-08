import asyncio
import base64
import logging
import os

import yaml

from aggregator.sources.loader import SourceLoader
from aggregator.fetcher.downloader import ConfigDownloader
from aggregator.converter.link_to_outbound import LinkToOutboundConverter
from aggregator.filter.deduplicator import Deduplicator
from aggregator.formatter.to_json import build_subscription, save_config
from aggregator.formatter.to_txt import generate_txt
from aggregator.health.latency import RankedNode, outbound_identity, rank_by_latency

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


_LINK_PREFIXES = (
    "vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://",
)


def _try_base64(text: str) -> str | None:
    """Пытается декодировать base64-подписку, игнорируя переводы строк."""
    cleaned = "".join(text.split())
    if not cleaned:
        return None
    padded = cleaned + "=" * (-len(cleaned) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except Exception:
        return None
    if decoded.lstrip().startswith(_LINK_PREFIXES) or "vless://" in decoded:
        return decoded
    return None


def _decode_source(text: str, source_format: str = "text") -> str:
    """Декодирует base64-подписку, если источник отдаёт её в таком виде."""
    if source_format == "base64":
        decoded = _try_base64(text)
        if decoded is None:
            logger.debug("Источник помечен как base64, но декодировать не удалось")
            return text
        return decoded

    # Часть источников меняет формат без предупреждения, пробуем аккуратно.
    return _try_base64(text) or text


def _parse_sources(
    mode: str,
    raw_texts: dict[str, str],
    source_by_url: dict[str, dict],
    allow_tls_vision: bool = False,
) -> tuple[list[dict], dict[tuple[str, int, str], str], dict[tuple[str, int, str], set[str]]]:
    """
    Парсит ссылки и запоминает, из каких источников пришёл каждый сервер.

    sources_by_identity нужен, чтобы при дедупликации не потерять
    происхождение: один и тот же сервер может встречаться и в igareck,
    и в zieng2. Для whitelist-режима это критично.
    """
    converter = LinkToOutboundConverter(allow_tls_vision=allow_tls_vision)
    outbounds: list[dict] = []
    link_by_identity: dict[tuple[str, int, str], str] = {}
    sources_by_identity: dict[tuple[str, int, str], set[str]] = {}

    for url, text in raw_texts.items():
        source = source_by_url.get(url, {})
        source_name = str(source.get("name") or url)
        text = _decode_source(text, str(source.get("format") or "text"))

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("vless://"):
                # Пайплайн собирает только VLESS: Hysteria2/WS/gRPC
                # отбрасываются ещё до проверки задержки.
                continue

            outbound = converter.convert(line)
            if not outbound:
                continue

            identity = outbound_identity(outbound)
            outbound["_source"] = source_name
            outbounds.append(outbound)

            # Ссылка нужна для xray-knife: инструмент работает с share-ссылками.
            link_by_identity.setdefault(identity, line)
            sources_by_identity.setdefault(identity, set()).add(source_name)

    return outbounds, link_by_identity, sources_by_identity


def _attach_all_sources(
    outbounds: list[dict],
    sources_by_identity: dict[tuple[str, int, str], set[str]],
) -> None:
    """Проставляет каждому уникальному серверу полный список его источников."""
    for outbound in outbounds:
        identity = outbound_identity(outbound)
        sources = sources_by_identity.get(identity)
        if sources:
            outbound["_sources"] = sorted(sources)


def _has_source_prefix(outbound: dict, prefixes: tuple[str, ...]) -> bool:
    sources = set(outbound.get("_sources") or [])
    single = outbound.get("_source")
    if single:
        sources.add(str(single))
    return any(name.startswith(prefixes) for name in sources)


async def process_mode(mode: str, config: dict):
    logger.info(f"=== ЗАПУСК СБОРКИ ДЛЯ РЕЖИМА: {mode} ===")

    loader = SourceLoader()
    sources = loader.get_sources(mode)
    if not sources:
        logger.error(f"Для режима {mode} нет источников")
        return

    urls = [source["url"] for source in sources]
    source_by_url = {source["url"]: source for source in sources}

    whitelist_cfg = config.get("whitelist", {})
    # В whitelist-режиме источники igareck публикуют конфиги как
    # VLESS + TCP + TLS + Vision (SNI белого списка). Разрешаем их,
    # но Reality остаётся приоритетным: он идёт первым при сортировке
    # только если реально быстрее.
    allow_tls_vision = (
        mode == "whitelist" and bool(whitelist_cfg.get("allow_tls_vision", True))
    )

    async with ConfigDownloader() as downloader:
        raw_texts = await downloader.fetch_many(urls)

    parsed_outbounds, link_by_identity, sources_by_identity = _parse_sources(
        mode, raw_texts, source_by_url, allow_tls_vision=allow_tls_vision,
    )
    logger.info(f"📄 Всего спарсено подходящих серверов: {len(parsed_outbounds)}")

    unique_outbounds = Deduplicator.deduplicate(parsed_outbounds)
    _attach_all_sources(unique_outbounds, sources_by_identity)
    logger.info(f"🧹 Уникальных серверов: {len(unique_outbounds)}")

    if not unique_outbounds:
        logger.error(f"❌ Для режима {mode} не найдено ни одного подходящего сервера")
        return

    candidates: list[tuple[dict, str]] = []
    for outbound in unique_outbounds:
        link = link_by_identity.get(outbound_identity(outbound))
        if link:
            candidates.append((outbound, link))

    if not candidates:
        logger.error(f"❌ Для режима {mode} нет серверов с share-ссылкой")
        return

    # --- Проверка задержки: один раз по всем уникальным кандидатам ---
    # Для whitelist это важно: сначала проверяем всё, что есть (igareck +
    # zieng2), и только потом решаем, что попадёт в JSON.
    ranked_all: list[RankedNode] = await rank_by_latency(
        candidates,
        config.get("latency_check", {}),
    )

    max_json_outbounds = max(1, int(config['aggregator'].get('json_max_outbounds', 30)))
    max_servers = max(1, int(config['aggregator'].get('max_servers_per_subscription', 30)))

    # --- Определяем, какие живые серверы допустимы в JSON ---
    prefixes = tuple(whitelist_cfg.get("json_source_prefixes", ["igareck_"]))
    require_whitelist_sources = (
        mode == "whitelist" and bool(whitelist_cfg.get("require_whitelist_sources", True))
    )

    if not ranked_all:
        logger.error(
            "❌ Проверка задержки не дала живых серверов. "
            "JSON оставлен прежним, TXT будет собран из непроверенных ссылок."
        )
        txt_links = [link for _outbound, link in candidates[:max_servers]]
        json_ranked: list[RankedNode] = []
    else:
        if require_whitelist_sources:
            json_ranked = [
                node for node in ranked_all
                if _has_source_prefix(node.outbound, prefixes)
            ]
            if json_ranked:
                logger.info(
                    "Whitelist: в JSON допущены только источники %s (%d живых серверов)",
                    ", ".join(prefixes), len(json_ranked),
                )
            elif whitelist_cfg.get("fallback_to_any_source", False):
                logger.warning(
                    "Whitelist: живых серверов из %s нет. "
                    "fallback_to_any_source=true — в JSON пойдут остальные whitelist-источники.",
                    ", ".join(prefixes),
                )
                json_ranked = ranked_all
            else:
                logger.error(
                    "Whitelist: живых серверов из %s нет. "
                    "JSON оставлен прежним (чтобы не подсунуть клиентам не-igareck серверы). "
                    "TXT собран из всех проверенных whitelist-серверов.",
                    ", ".join(prefixes),
                )
        else:
            json_ranked = ranked_all

        if json_ranked:
            top_nodes = json_ranked[:max_json_outbounds]
            logger.info(
                "🏆 Топ-%d из %d по задержке (первая точка — лучшая):",
                len(top_nodes), len(json_ranked),
            )
            for node in top_nodes[:10]:
                host, port, _uuid = outbound_identity(node.outbound)
                sources_text = ",".join(node.outbound.get("_sources") or [node.outbound.get("_source", "?")])
                logger.info(
                    "    %5d ms  %s:%s  [%s] (%s)",
                    node.delay_ms, host, port, node.status, sources_text,
                )

            template_path = os.path.join(
                config['paths']['templates_dir'], f"{mode}_template.json"
            )
            try:
                final_config = build_subscription(
                    [node.outbound for node in top_nodes],
                    template_path,
                    max_json_outbounds,
                    allow_tls=allow_tls_vision,
                )
            except ValueError as exc:
                logger.error(f"❌ JSON для режима {mode} не собран: {exc}")
                logger.error("Старый JSON оставлен без изменений.")
            else:
                output_json = os.path.join(config['paths']['output_dir'], f"{mode}.json")
                os.makedirs(os.path.dirname(output_json), exist_ok=True)
                save_config(final_config, output_json)
                logger.info(
                    "💾 %s: %d серверов, %d байт",
                    output_json, len(top_nodes), os.path.getsize(output_json),
                )

        txt_links = [node.link for node in ranked_all[:max_servers]]

    # --- TXT-подписка: лучшие проверенные ссылки ---
    txt_content = generate_txt(txt_links)
    output_txt = os.path.join(config['paths']['output_dir'], f"{mode}_all.txt")
    os.makedirs(os.path.dirname(output_txt), exist_ok=True)
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(txt_content)
    logger.info("💾 %s: %d ссылок", output_txt, len(txt_links))


async def main():
    with open("aggregator/config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    for mode in config['aggregator']['modes']:
        await process_mode(mode, config)


if __name__ == "__main__":
    asyncio.run(main())
