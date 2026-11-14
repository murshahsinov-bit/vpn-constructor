import asyncio
import base64
import copy
import ipaddress
import logging
import os
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlencode, urlparse

import yaml

from aggregator.sources.loader import SourceLoader
from aggregator.fetcher.downloader import ConfigDownloader
from aggregator.converter.link_to_outbound import (
    PROFILE_XHTTP,
    TCP_FRAGMENT,
    VISION_FLOW,
    LinkToOutboundConverter,
)
from aggregator.formatter.to_json import build_subscription, save_config
from aggregator.formatter.to_txt import generate_txt
from aggregator.health.latency import outbound_identity, rank_by_latency

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


PROFILE_ORDER = ("xhttp", "tcp")
_LINK_PREFIXES = (
    "vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://",
)


@dataclass
class ServerRecord:
    """Один сервер и все его живые/поддерживаемые профили."""
    identity: tuple[str, int, str]
    variants: dict[str, dict] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    sources: set[str] = field(default_factory=set)
    delays: dict[str, int] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)

    @property
    def alive_profiles(self) -> list[str]:
        return [p for p in PROFILE_ORDER if p in self.delays and p in self.variants]

    @property
    def delay_ms(self) -> int:
        return min(self.delays.values()) if self.delays else 10 ** 9


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


def _security(outbound: dict) -> str:
    return str((outbound.get("streamSettings") or {}).get("security", "")).strip().lower()


def _server_name(outbound: dict) -> str:
    stream = outbound.get("streamSettings") or {}
    reality = stream.get("realitySettings") or {}
    tls = stream.get("tlsSettings") or {}
    return str(reality.get("serverName") or tls.get("serverName") or "").strip().lower()


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _alternate_variant(source: dict, target_profile: str) -> dict | None:
    """
    Строит второй профиль из той же пары address/port/uuid/pbk/sni.

    Такой профиль — гипотеза: сервер мог поднять только один транспорт.
    Поэтому он проходит реальную проверку xray-knife и попадает в JSON
    только если действительно работает. Если сервер поддерживает оба
    транспорта, клиент получает proxy-xhttp-N и proxy-tcp-N.
    """
    if _security(source) != "reality":
        return None
    if target_profile not in PROFILE_ORDER:
        return None

    variant = copy.deepcopy(source)
    stream = variant.setdefault("streamSettings", {})
    reality = stream.get("realitySettings") or {}
    reality["fingerprint"] = "firefox"
    stream["realitySettings"] = reality
    server_name = str(reality.get("serverName", "")).strip()
    users = (variant.get("settings") or {}).get("vnext", [{}])[0].get("users", [{}])
    if not users:
        return None
    user = users[0]

    if target_profile == "tcp":
        stream.pop("xhttpSettings", None)
        stream["network"] = "tcp"
        user["flow"] = VISION_FLOW
        variant["fragment"] = dict(TCP_FRAGMENT)
        variant["_flow"] = VISION_FLOW
    else:
        stream["network"] = "xhttp"
        user["flow"] = ""
        xhttp_settings = {"mode": "stream-one", "path": "/"}
        if server_name and not _is_ip(server_name):
            xhttp_settings["host"] = server_name
        stream["xhttpSettings"] = xhttp_settings
        variant.pop("fragment", None)
        variant["_flow"] = ""

    variant["_profile"] = target_profile
    variant["_network"] = target_profile
    variant["_synthetic"] = True
    return variant


def _outbound_to_link(outbound: dict) -> str | None:
    """Собирает share-ссылку для проверки синтетического профиля."""
    vnext = (outbound.get("settings") or {}).get("vnext") or [{}]
    node = vnext[0]
    users = node.get("users") or [{}]
    user = users[0]
    address = str(node.get("address", "")).strip()
    port = int(node.get("port") or 0)
    user_id = str(user.get("id", "")).strip()
    if not address or not port or not user_id:
        return None

    stream = outbound.get("streamSettings") or {}
    profile = str(outbound.get("_profile") or stream.get("network") or "tcp").lower()
    security = str(stream.get("security", "")).lower()
    reality = stream.get("realitySettings") or {}
    tls = stream.get("tlsSettings") or {}

    params = {
        "type": profile,
        "security": security,
        "encryption": "none",
        "fp": "firefox",
    }
    if security == "reality":
        params["pbk"] = str(reality.get("publicKey", "")).strip()
        params["sid"] = str(reality.get("shortId", "")).strip()
        params["sni"] = str(reality.get("serverName", "")).strip()
    else:
        params["sni"] = str(tls.get("serverName", "")).strip()
        alpn = tls.get("alpn")
        if isinstance(alpn, list) and alpn:
            params["alpn"] = ",".join(str(item) for item in alpn)

    if profile == "tcp":
        params["flow"] = VISION_FLOW
    else:
        xhttp = stream.get("xhttpSettings") or {}
        params["path"] = str(xhttp.get("path") or "/")
        params["mode"] = "stream-one"
        host = str(xhttp.get("host", "")).strip()
        if host:
            params["host"] = host

    host_part = f"[{address}]" if ":" in address else address
    query = urlencode(params, quote_via=quote, safe="")
    return f"vless://{user_id}@{host_part}:{port}?{query}#synthetic-{profile}"


def _parse_sources(
    mode: str,
    raw_texts: dict[str, str],
    source_by_url: dict[str, dict],
    allow_tls_vision: bool = False,
) -> list[ServerRecord]:
    """
    Парсит ссылки и собирает серверы вместе с профилями.

    Один и тот же сервер может публиковаться двумя ссылками: XHTTP и TCP.
    Обе сохраняются в ``variants``, чтобы formatter отдал клиенту два
    outbound с одинаковым номером.
    """
    converter = LinkToOutboundConverter(
        allow_tls_vision=allow_tls_vision,
        allow_xhttp_tls=True,
    )
    records: dict[tuple[str, int, str], ServerRecord] = {}

    for url, text in raw_texts.items():
        source = source_by_url.get(url, {})
        source_name = str(source.get("name") or url)
        text = _decode_source(text, str(source.get("format") or "text"))

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("vless://"):
                # Пайплайн собирает только VLESS. WS/gRPC и Hysteria
                # отбрасываются ещё до проверки задержки.
                continue

            outbound = converter.convert(line)
            if not outbound:
                continue

            profile = str(outbound.get("_profile") or "").strip().lower()
            if profile not in PROFILE_ORDER:
                continue

            identity = outbound_identity(outbound)
            record = records.get(identity)
            if record is None:
                record = ServerRecord(identity=identity)
                records[identity] = record

            existing = record.variants.get(profile)
            replace = existing is None
            if existing is not None and _security(existing) != "reality" and _security(outbound) == "reality":
                # Reality предпочтительнее TLS при одном и том же профиле.
                replace = True
            if replace:
                record.variants[profile] = outbound
                record.links[profile] = line
            else:
                record.links.setdefault(profile, line)

            record.sources.add(source_name)

    logger.info(
        "Режим %s: серверов %d (xhttp=%d, tcp=%d, оба=%d)",
        mode,
        len(records),
        sum(1 for r in records.values() if "xhttp" in r.variants),
        sum(1 for r in records.values() if "tcp" in r.variants),
        sum(1 for r in records.values() if len(r.variants) > 1),
    )
    return list(records.values())


def _candidates(records: list[ServerRecord]) -> list[tuple[dict, str]]:
    candidates: list[tuple[dict, str]] = []
    for record in records:
        for profile, outbound in record.variants.items():
            link = record.links.get(profile)
            if link:
                candidates.append((outbound, link))
    return candidates


async def _rank_records_async(
    records: list[ServerRecord],
    latency_config: dict,
) -> list[ServerRecord]:
    candidates = _candidates(records)
    if not candidates:
        return []

    ranked = await rank_by_latency(candidates, latency_config)

    by_identity = {record.identity: record for record in records}
    for node in ranked:
        record = by_identity.get(outbound_identity(node.outbound))
        if record is None:
            continue
        profile = str(node.outbound.get("_profile") or "").strip().lower()
        if profile not in PROFILE_ORDER:
            continue
        previous = record.delays.get(profile)
        if previous is None or node.delay_ms < previous:
            record.delays[profile] = node.delay_ms
            record.statuses[profile] = node.status

    alive = [record for record in records if record.delays]
    # Сортировка по лучшей задержке; при равенстве — больше профилей.
    alive.sort(key=lambda record: (record.delay_ms, -len(record.alive_profiles)))
    return alive


async def _synthesize_and_rank(
    records: list[ServerRecord],
    latency_config: dict,
    candidate_limit: int = 60,
) -> list[ServerRecord]:
    """
    Пробует второй транспорт для лучших серверов.

    Проверяются только гипотезы: если сервер не поднял XHTTP/TCP на том же
    порту, xray-knife отбросит профиль. В JSON попадут только рабочие.
    """
    synthetic: list[tuple[ServerRecord, str, dict, str]] = []
    for record in records[:max(1, candidate_limit)]:
        if len(record.variants) >= 2:
            continue
        source_profile = next(iter(record.variants), None)
        if source_profile is None:
            continue
        source = record.variants[source_profile]
        for target_profile in PROFILE_ORDER:
            if target_profile == source_profile or target_profile in record.variants:
                continue
            variant = _alternate_variant(source, target_profile)
            if variant is None:
                continue
            link = _outbound_to_link(variant)
            if link:
                synthetic.append((record, target_profile, variant, link))

    if not synthetic:
        return records

    logger.info("Проверяю второй профиль для %d серверов (XHTTP/TCP)", len(synthetic))
    ranked = await rank_by_latency(
        [(variant, link) for _record, _profile, variant, link in synthetic],
        latency_config,
    )

    by_link = {
        link: (record, profile, variant)
        for record, profile, variant, link in synthetic
    }
    added = 0
    for node in ranked:
        # Второй профиль — гипотеза. TCP-fallback и SKIP_LATENCY её не
        # подтверждают, поэтому принимаем только реальный HTTP-тест.
        if node.status not in ("passed", "semi-passed"):
            continue
        match = by_link.get(node.link.strip())
        if match is None:
            continue
        record, profile, variant = match
        if profile in record.variants:
            continue
        record.variants[profile] = variant
        record.links[profile] = node.link
        record.delays[profile] = node.delay_ms
        record.statuses[profile] = node.status
        added += 1

    records.sort(key=lambda record: (record.delay_ms, -len(record.alive_profiles)))
    logger.info("Второй профиль подтверждён у %d серверов", added)
    return records


def _select_records(
    records: list[ServerRecord],
    limit: int,
    xhttp_share: float = 0.6,
) -> list[ServerRecord]:
    """
    Отбирает серверы для подписки, отдавая приоритет XHTTP.

    XHTTP — основной профиль (Android/desktop). TCP-only серверы остаются
    резервом для iOS и старых ядер, поэтому им гарантируется часть слотов,
    но они не вытесняют XHTTP из топа. Внутри каждой группы сохраняется
    порядок по задержке: ``records`` уже отсортированы rank_by_latency.
    """
    limit = max(1, int(limit))
    ordered = sorted(
        records,
        key=lambda record: (record.delay_ms, -len(record.alive_profiles)),
    )

    xhttp_records = [
        record for record in ordered
        if PROFILE_XHTTP in record.alive_profiles
    ]
    other_records = [
        record for record in ordered
        if PROFILE_XHTTP not in record.alive_profiles
    ]

    share = min(1.0, max(0.0, float(xhttp_share)))
    xhttp_slots = min(len(xhttp_records), max(1, round(limit * share))) if xhttp_records else 0
    selected = (
        xhttp_records[:xhttp_slots]
        + other_records[:max(0, limit - xhttp_slots)]
    )

    # Если одного типа не хватило, добираем оставшиеся в порядке задержки.
    if len(selected) < limit:
        chosen = {id(record) for record in selected}
        for record in ordered:
            if len(selected) >= limit:
                break
            if id(record) not in chosen:
                selected.append(record)
                chosen.add(id(record))
    return selected


def _builder_entries(records: list[ServerRecord], limit: int) -> list[dict]:
    """
    Преобразует записи в формат formatter: один entry = один сервер,
    внутри ``_variants`` лежат XHTTP/TCP outbound-ы.
    """
    entries: list[dict] = []
    for record in _select_records(records, limit):
        profiles = record.alive_profiles
        if not profiles:
            continue

        variants: dict[str, dict] = {}
        for profile in profiles:
            outbound = copy.deepcopy(record.variants[profile])
            outbound["tag"] = f"proxy-{profile}"
            outbound["_profile"] = profile
            outbound["_source"] = ", ".join(sorted(record.sources))
            outbound["_sources"] = sorted(record.sources)
            variants[profile] = outbound

        base = copy.deepcopy(variants[profiles[0]])
        base["_variants"] = variants
        base["_profiles"] = profiles
        base["_links"] = {p: record.links[p] for p in profiles if p in record.links}
        base["_delay_ms"] = record.delay_ms
        base["_sources"] = sorted(record.sources)
        entries.append(base)
    return entries


def _txt_links(records: list[ServerRecord], limit: int) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for record in _select_records(records, limit):
        for profile in record.alive_profiles:
            link = record.links.get(profile)
            if link and link not in seen:
                seen.add(link)
                links.append(link)
    return links


def _has_source_prefix(record: ServerRecord, prefixes: tuple[str, ...]) -> bool:
    return any(name.startswith(prefixes) for name in record.sources)


def _socks_outbound(raw: str, tag: str = "proxy-ycf-1") -> dict | None:
    """
    Дополнительный SOCKS5-профиль (например, релей внутри Yandex Cloud
    Functions). Задаётся переменной YANDEX_FUNCTIONS_SOCKS:

        socks5://user:pass@host:1080
    """
    raw = str(raw or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "socks5://" + raw
    try:
        parsed = urlparse(raw)
        host = parsed.hostname
        port = parsed.port or 1080
        if not host:
            return None
        users = []
        if parsed.username:
            users.append({
                "user": unquote(parsed.username),
                "pass": unquote(parsed.password or ""),
            })
        return {
            "tag": tag,
            "protocol": "socks",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": int(port),
                    "users": users,
                }]
            },
        }
    except (TypeError, ValueError):
        logger.warning("Не удалось разобрать YANDEX_FUNCTIONS_SOCKS")
        return None


def _ycf_outbound() -> dict | None:
    return _socks_outbound(os.getenv("YANDEX_FUNCTIONS_SOCKS", ""))


def _relay_from_link(link: str) -> dict | None:
    converter = LinkToOutboundConverter(allow_tls_vision=True, allow_xhttp_tls=True)
    outbound = converter.convert(link, tag="wl-relay")
    if outbound is None:
        logger.error("RU_RELAY_LINK не удалось разобрать как VLESS-релей")
        return None
    outbound["_profile"] = outbound.get("_profile") or "tcp"
    return outbound


def _relay_from_records(
    records: list[ServerRecord],
    relay_config: dict,
) -> tuple[dict | None, tuple[str, int, str] | None, str | None]:
    """
    Выбирает RU relay из whitelist-источников.

    igareck публикует white-list конфиги, которые и есть входные RU VPS.
    Предпочитаем SNI gosuslugi.ru и источники igareck_, исключаем Yandex
    Cloud (его AS блокируется).
    """
    prefixes = tuple(relay_config.get("require_source_prefixes") or ["igareck_"])
    preferred_sni = [
        str(item).strip().lower()
        for item in (relay_config.get("preferred_sni") or ["gosuslugi.ru"])
        if str(item).strip()
    ]
    # Для входа в whitelist-цепочку SNI должен быть из белого списка
    # оператора. Если preferred_sni задан, остальные узлы не подходят:
    # это не «красивый бонус», а условие прохождения первого прыжка.
    require_preferred = bool(relay_config.get("require_preferred_sni", True))
    excluded_sni = [
        str(item).strip().lower()
        for item in (relay_config.get("exclude_sni_suffixes") or [
            "yandex", "yandexcloud.net", "cloud.yandex",
        ])
        if str(item).strip()
    ]

    # TCP-fallback проверяет только открытый порт. Такой узел нельзя
    # ставить входным relay: он может быть мёртвым прокси.
    allow_tcp_fallback = bool(relay_config.get("allow_tcp_fallback", False))
    real_statuses = ("passed", "semi-passed")

    best: tuple[tuple[int, int, int, int], ServerRecord, str] | None = None
    for record in records:
        if not record.delays:
            continue
        if prefixes and not _has_source_prefix(record, prefixes):
            continue

        # TCP+Vision совместимее с iOS и старыми ядрами, поэтому он
        # приоритетнее XHTTP при выборе входного RU relay.
        for profile in ("tcp", "xhttp"):
            if profile not in record.delays or profile not in record.variants:
                continue
            status = record.statuses.get(profile, "")
            if not allow_tcp_fallback and status not in real_statuses:
                continue
            outbound = record.variants[profile]
            sni = _server_name(outbound)
            host = outbound_identity(outbound)[0].lower()
            if any(marker in sni or marker in host for marker in excluded_sni):
                continue
            matches_preferred = any(
                marker in sni or marker in host for marker in preferred_sni
            )
            if require_preferred and preferred_sni and not matches_preferred:
                continue
            preferred = 0 if matches_preferred else 1
            security_rank = 0 if _security(outbound) == "reality" else 1
            source_rank = 0 if _has_source_prefix(record, prefixes) else 1
            score = (preferred, security_rank, source_rank, record.delays[profile])
            if best is None or score < best[0]:
                best = (score, record, profile)

    if best is None:
        return None, None, None

    _score, record, profile = best
    outbound = copy.deepcopy(record.variants[profile])
    outbound["tag"] = "wl-relay"
    outbound["_profile"] = profile
    outbound["_source"] = ", ".join(sorted(record.sources))
    logger.info(
        "Whitelist: выбран RU relay %s:%s (%s, SNI=%s, %d ms)",
        outbound_identity(outbound)[0],
        outbound_identity(outbound)[1],
        profile,
        _server_name(outbound) or "-",
        record.delays[profile],
    )
    return outbound, record.identity, record.links.get(profile)


def _write_txt(mode: str, links: list[str], config: dict) -> None:
    """
    Пишет два TXT-варианта одного режима.

    INCY и Happ используют разный синтаксис фрагментации в share-ссылке,
    поэтому ``auto_all.txt``/``whitelist_all.txt`` — для INCY, а
    ``*_all_happ.txt`` — для Happ.
    """
    output_dir = config['paths']['output_dir']
    os.makedirs(output_dir, exist_ok=True)

    for client, suffix in (("incy", ""), ("happ", "_happ")):
        txt_content = generate_txt(links, client=client)
        output_txt = os.path.join(output_dir, f"{mode}_all{suffix}.txt")
        with open(output_txt, "w", encoding="utf-8") as file:
            file.write(txt_content)
        logger.info(
            "💾 %s: %d ссылок (%s)", output_txt, len(links), client
        )


async def _collect(mode: str, config: dict, allow_tls_vision: bool = False) -> list[ServerRecord]:
    logger.info(f"=== СБОР ДЛЯ РЕЖИМА: {mode} ===")

    loader = SourceLoader()
    sources = loader.get_sources(mode)
    if not sources:
        logger.error(f"Для режима {mode} нет источников")
        return []

    urls = [source["url"] for source in sources]
    source_by_url = {source["url"]: source for source in sources}

    async with ConfigDownloader() as downloader:
        raw_texts = await downloader.fetch_many(urls)

    records = _parse_sources(
        mode,
        raw_texts,
        source_by_url,
        allow_tls_vision=allow_tls_vision,
    )
    if not records:
        logger.error(f"❌ Для режима {mode} не найдено ни одного подходящего сервера")
        return []

    aggregator_cfg = config.get("aggregator", {}) or {}
    latency_config = dict(
        aggregator_cfg.get("latency_check")
        or config.get("latency_check")
        or {}
    )
    env_binary = os.getenv("XRAY_KNIFE_BIN", "").strip()
    if env_binary:
        # Переменная окружения важнее config.yaml: так локальная сборка
        # может указать полный путь к бинарнику.
        latency_config["binary"] = env_binary
    env_fragment = os.getenv("XRAY_KNIFE_FRAGMENT", "").strip()
    if env_fragment:
        # В workflow можно переопределить фрагментацию без правки config.yaml.
        latency_config["fragment"] = env_fragment
    if not latency_config.get("fragment"):
        latency_config["fragment"] = "tlshello,100-200,10-20"

    records = await _rank_records_async(records, latency_config)
    if not records:
        logger.error(
            f"❌ Для режима {mode} проверка задержки не дала живых серверов. "
            "TXT будет собран из непроверенных ссылок."
        )
        return []

    skip_latency = str(os.getenv("SKIP_LATENCY", "")).lower() in ("1", "true", "yes", "on")
    real_checked = any(
        status in ("passed", "semi-passed")
        for record in records
        for status in record.statuses.values()
    )
    if (
        bool(aggregator_cfg.get("synthesize_alternate_profiles", True))
        and not skip_latency
        and real_checked
    ):
        records = await _synthesize_and_rank(
            records,
            latency_config,
            int(aggregator_cfg.get("synthesis_candidates", 60)),
        )
    elif not real_checked:
        logger.warning(
            "Синтез второго профиля пропущен: нет реальной проверки "
            "(SKIP_LATENCY или TCP-fallback)"
        )

    logger.info(f"🏆 Живых серверов: {len(records)}")
    for record in records[:10]:
        host, port, _uuid = record.identity
        sources_text = ",".join(sorted(record.sources))
        profiles = "+".join(record.alive_profiles)
        logger.info(
            "    %5d ms  %s:%s  [%s] (%s)",
            record.delay_ms, host, port, profiles, sources_text,
        )
    return records


async def _process_auto(config: dict) -> list[ServerRecord]:
    records = await _collect("auto", config, allow_tls_vision=False)
    if not records:
        return []

    max_json = max(1, int(config['aggregator'].get('json_max_outbounds', 30)))
    max_servers = max(1, int(config['aggregator'].get('max_servers_per_subscription', 30)))

    entries = _builder_entries(records, max_json)
    template_path = os.path.join(config['paths']['templates_dir'], "auto_template.json")

    try:
        final_config = build_subscription(
            entries,
            template_path,
            max_outbounds=max_json,
            allow_tls=False,
            allow_xhttp_tls=True,
            extra_outbounds=[ob for ob in [_ycf_outbound()] if ob],
        )
    except ValueError as exc:
        logger.error(f"❌ JSON для режима auto не собран: {exc}")
        logger.error("Старый auto.json оставлен без изменений.")
    else:
        output_json = os.path.join(config['paths']['output_dir'], "auto.json")
        os.makedirs(os.path.dirname(output_json), exist_ok=True)
        save_config(final_config, output_json)
        profile_count = sum(
            1 for ob in final_config["outbounds"] if ob.get("protocol") == "vless"
        )
        logger.info(
            "💾 %s: %d серверов, %d outbound-профилей, %d байт",
            output_json,
            len(entries),
            profile_count,
            os.path.getsize(output_json),
        )

    _write_txt("auto", _txt_links(records, max_servers), config)
    return records


async def _process_whitelist(
    config: dict,
    auto_records: list[ServerRecord],
) -> None:
    aggregator_cfg = config.get("aggregator", {}) or {}
    whitelist_cfg = (
        aggregator_cfg.get("whitelist")
        or config.get("whitelist")
        or {}
    )
    relay_cfg = whitelist_cfg.get("relay", {}) or {}
    max_json = max(1, int(whitelist_cfg.get("json_max_servers", 10)))
    max_servers = max(1, int(config['aggregator'].get('max_servers_per_subscription', 30)))

    allow_tls_vision = bool(whitelist_cfg.get("allow_tls_vision", True))
    whitelist_records = await _collect(
        "whitelist",
        config,
        allow_tls_vision=allow_tls_vision,
    )

    explicit_link = (
        os.getenv("RU_RELAY_LINK", "").strip()
        or str(relay_cfg.get("link", "")).strip()
    )

    relay_outbound: dict | None = None
    relay_identity: tuple[str, int, str] | None = None
    relay_link: str | None = None

    if explicit_link:
        relay_outbound = _relay_from_link(explicit_link)
        if relay_outbound is not None:
            relay_identity = outbound_identity(relay_outbound)
            relay_link = explicit_link
            logger.info(
                "Whitelist: используется явный RU relay %s:%s (SNI=%s)",
                relay_identity[0],
                relay_identity[1],
                _server_name(relay_outbound) or "-",
            )
        else:
            logger.warning("Явный RU relay не разобран, пробую igareck-узел")

    if relay_outbound is None:
        relay_outbound, relay_identity, relay_link = _relay_from_records(
            whitelist_records,
            relay_cfg,
        )

    # Цели: лучшие зарубежные серверы из auto, а не сами RU relay-узлы.
    if bool(whitelist_cfg.get("targets_from_auto", True)) and auto_records:
        targets = [r for r in auto_records if r.identity != relay_identity]
    else:
        targets = [r for r in whitelist_records if r.identity != relay_identity]
    targets = targets[:max_json]

    # Цепочка имеет смысл только на реально проверенных серверах:
    # TCP-fallback/SKIP_LATENCY проверяют лишь порт.
    real_statuses = ("passed", "semi-passed")
    targets = [
        record for record in targets
        if any(status in real_statuses for status in record.statuses.values())
    ]
    if not targets:
        logger.error(
            "Whitelist: нет реально проверенных целевых серверов. "
            "whitelist.json оставлен прежним."
        )
        return

    if relay_outbound is None and not bool(whitelist_cfg.get("allow_without_relay", False)):
        logger.error(
            "Whitelist: RU relay не найден. Задайте RU_RELAY_LINK (VLESS Reality "
            "SNI=gosuslugi.ru на Timeweb/VDSina/Selectel) или живой igareck-узел. "
            "whitelist.json и whitelist_all*.txt оставлены прежними, чтобы не "
            "отдавать клиентам конфиг без обхода белых списков."
        )
        return

    target_links = _txt_links(targets, max_json)
    if relay_link:
        _write_txt("whitelist", [relay_link] + target_links, config)
    elif whitelist_records:
        _write_txt("whitelist", _txt_links(whitelist_records, max_servers), config)
    else:
        logger.warning(
            "Whitelist: проверенных ссылок нет, whitelist_all*.txt оставлены прежними"
        )

    entries = _builder_entries(targets, max_json)
    template_path = os.path.join(config['paths']['templates_dir'], "whitelist_template.json")

    try:
        final_config = build_subscription(
            entries,
            template_path,
            max_outbounds=max_json,
            allow_tls=True,
            allow_xhttp_tls=True,
            relay=relay_outbound,
            extra_outbounds=[],
        )
    except ValueError as exc:
        logger.error(f"❌ JSON для режима whitelist не собран: {exc}")
        logger.error("Старый whitelist.json оставлен без изменений.")
        return

    output_json = os.path.join(config['paths']['output_dir'], "whitelist.json")
    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    save_config(final_config, output_json)

    relay_tag = "wl-relay" if relay_outbound else "none"
    chained = sum(
        1 for ob in final_config["outbounds"]
        if ((ob.get("streamSettings") or {}).get("sockopt") or {}).get("dialerProxy") == relay_tag
    )
    logger.info(
        "💾 %s: %d серверов, %d цепочек %s → зарубежный VPS, %d байт",
        output_json,
        len(entries),
        chained,
        relay_tag,
        os.path.getsize(output_json),
    )


async def main():
    config_path = os.getenv("AGGREGATOR_CONFIG", "aggregator/config.yaml")
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    modes = list(config['aggregator'].get('modes') or [])
    auto_records: list[ServerRecord] = []

    if "auto" in modes:
        auto_records = await _process_auto(config)

    if "whitelist" in modes:
        await _process_whitelist(config, auto_records)


if __name__ == "__main__":
    asyncio.run(main())
