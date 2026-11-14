"""Отбраковка Reality-конфигов, спрятанных за CDN.

Reality — протокол «точка-точка»: TLS-рукопожатие должно происходить
непосредственно с целевым сервером, чей сертификат подделывается через
``serverName``. Если трафик идёт через Cloudflare/Fastly/Akamai, CDN
терминирует TLS на своей стороне, Reality-рукопожатие ломается, а сам
клиент начинает светить SNI перед CDN — то есть ровно то, что Reality
должен скрывать.

Поэтому Reality-профили с CDN-адресом или CDN-SNI отбрасываются. TLS
(XHTTP поверх Cloudflare) этим правилом не затрагивается: там CDN —
штатная часть схемы.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# Домены, которые обслуживают CDN-фронты. Сравнение идёт по метке домена,
# поэтому "cdn.example.com" не совпадёт с "example.com".
CDN_HOST_MARKERS = (
    "cloudflare.com",
    "cloudflare.net",
    "cloudflare-dns.com",
    "cloudflareclient.com",
    "workers.dev",
    "pages.dev",
    "r2.dev",
    "fastly.net",
    "fastlylb.net",
    "global.ssl.fastly.net",
    "akamaiedge.net",
    "akamaized.net",
    "akamaitechnologies.com",
    "edgesuite.net",
    "edgekey.net",
    "cdn77.org",
    "bunnycdn.com",
    "b-cdn.net",
    "stackpathdns.com",
    "stackpathcdn.com",
    "azureedge.net",
    "cloudfront.net",
    "vercel.app",
    "netlify.app",
    "netlify.com",
    "github.io",
    "herokuapp.com",
    "trafficmanager.net",
)

# Официальные диапазоны Cloudflare: https://www.cloudflare.com/ips/
CLOUDFLARE_NETWORKS = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)

_CLOUDFLARE = tuple(ipaddress.ip_network(cidr) for cidr in CLOUDFLARE_NETWORKS)


def host_only(value: str | None) -> str:
    """Возвращает hostname без схемы, порта, userinfo и квадратных скобок."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        text = urlparse(text).hostname or ""
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    # host:port — режем только если после двоеточия действительно порт.
    if text.count(":") == 1:
        host, _, port = text.partition(":")
        if port.isdigit():
            text = host
    return text.strip(".").strip()


def is_cloudflare_ip(host: str) -> bool:
    """True, если host — IP-адрес внутри сетей Cloudflare."""
    try:
        address = ipaddress.ip_address(host_only(host))
    except ValueError:
        return False
    return any(address in network for network in _CLOUDFLARE)


def is_cdn_host(host: str) -> bool:
    """True, если hostname принадлежит известному CDN-домену."""
    hostname = host_only(host)
    if not hostname:
        return False
    return any(
        hostname == marker or hostname.endswith("." + marker)
        for marker in CDN_HOST_MARKERS
    )


def is_cdn_endpoint(*values: str | None) -> bool:
    """True, если хотя бы одно из значений (address/SNI/host) указывает на CDN."""
    return any(is_cloudflare_ip(value) or is_cdn_host(value) for value in values if value)
