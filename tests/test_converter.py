import pytest

from aggregator.converter.link_to_outbound import (
    FORBIDDEN_FINGERPRINTS,
    SUPPORTED_FINGERPRINTS,
    LinkToOutboundConverter,
)


@pytest.fixture
def converter():
    return LinkToOutboundConverter()


def test_convert_vless_reality_tcp(converter):
    uri = (
        "vless://e0c8c4a3-4d56-49c1-b403-40cbd757473b@85.11.187.26:443"
        "?security=reality&sni=www.microsoft.com&pbk=abc&sid=def"
        "&type=tcp&flow=xtls-rprx-vision&fp=chrome"
    )
    outbound = converter.convert(uri, tag="proxy-1")

    assert outbound["tag"] == "proxy-1"
    assert outbound["protocol"] == "vless"
    assert outbound["_profile"] == "tcp"
    assert outbound["settings"]["vnext"][0]["address"] == "85.11.187.26"
    assert outbound["streamSettings"]["network"] == "tcp"
    assert outbound["streamSettings"]["security"] == "reality"
    assert outbound["streamSettings"]["realitySettings"]["serverName"] == "www.microsoft.com"
    # chrome из ссылки принудительно заменяется на firefox.
    assert outbound["streamSettings"]["realitySettings"]["fingerprint"] == "firefox"
    assert outbound["fragment"] == {
        "packets": "tlshello", "length": "100-200", "interval": "10-20"
    }


def test_convert_vless_reality_xhttp(converter):
    uri = (
        "vless://92b79c22-f68b-4713-8b21-52f264cb92f5@144.31.225.108:443"
        "?encryption=none&path=%2Fcdn%2Fassets%2Fv3"
        "&pbk=_wgNV4y_WpP2Itc3StvZcCKEari3CMGjnzaCCjm9Zko"
        "&security=reality&sni=downloadchache1.song69.fun&type=xhttp&fp=chrome&mode=auto"
    )
    outbound = converter.convert(uri, tag="proxy-xhttp")

    assert outbound["_profile"] == "xhttp"
    assert outbound["streamSettings"]["network"] == "xhttp"
    assert outbound["streamSettings"]["security"] == "reality"
    assert outbound["streamSettings"]["xhttpSettings"]["mode"] == "stream-one"
    assert outbound["streamSettings"]["xhttpSettings"]["path"] == "/cdn/assets/v3"
    assert outbound["settings"]["vnext"][0]["users"][0]["flow"] == ""
    assert outbound["streamSettings"]["realitySettings"]["fingerprint"] == "firefox"
    # fragment только для TCP.
    assert "fragment" not in outbound


def test_convert_xhttp_tls_for_cdn(converter):
    uri = (
        "vless://f219ffe2-bc36-495f-a83d-8f9ac4af05fd@185.173.179.218:443"
        "?security=tls&sni=ru1.cdn-space.org&alpn=h2&fp=firefox&type=xhttp"
        "&path=%2Fassets%2Fapi%2Fv3%2Fconnect%2F&host=ru1.cdn-space.org&mode=auto"
    )
    outbound = converter.convert(uri)

    assert outbound["_profile"] == "xhttp"
    assert outbound["streamSettings"]["security"] == "tls"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "ru1.cdn-space.org"
    assert outbound["streamSettings"]["tlsSettings"]["fingerprint"] == "firefox"
    assert outbound["streamSettings"]["xhttpSettings"]["host"] == "ru1.cdn-space.org"


def test_ws_is_rejected(converter):
    uri = (
        "vless://e0c8c4a3-4d56-49c1-b403-40cbd757473b@85.11.187.26:443"
        "?security=tls&sni=example.com&type=ws&path=%2Fws&flow=xtls-rprx-vision"
    )
    assert converter.convert(uri) is None


def test_tcp_tls_requires_whitelist_mode():
    uri = (
        "vless://e0c8c4a3-4d56-49c1-b403-40cbd757473b@85.11.187.26:443"
        "?security=tls&sni=ripelever.net&type=tcp&flow=xtls-rprx-vision"
    )
    assert LinkToOutboundConverter().convert(uri) is None

    whitelist = LinkToOutboundConverter(allow_tls_vision=True)
    outbound = whitelist.convert(uri)
    assert outbound["streamSettings"]["security"] == "tls"
    assert outbound["streamSettings"]["tlsSettings"]["fingerprint"] == "firefox"


def test_convert_hysteria2(converter):
    uri = "hysteria2://password123@45.139.184.187:3478?sni=example.com&obfs=salamander&obfs-password=mypass"
    outbound = converter.convert(uri, tag="proxy-2")

    assert outbound["tag"] == "proxy-2"
    assert outbound["protocol"] == "hysteria"
    assert outbound["settings"]["version"] == 2
    assert outbound["streamSettings"]["hysteriaSettings"]["auth"] == "password123"
    # Hysteria2 остаётся только для TXT-подписки; JSON-сборщик её отбрасывает.
    assert outbound["streamSettings"]["security"] == "tls"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "example.com"


def test_chrome_and_safari_are_forbidden_fingerprints():
    assert FORBIDDEN_FINGERPRINTS == {"chrome", "safari"}
    assert not (SUPPORTED_FINGERPRINTS & FORBIDDEN_FINGERPRINTS)
    assert "firefox" in SUPPORTED_FINGERPRINTS


@pytest.mark.parametrize(
    "address,sni",
    [
        ("104.16.1.1", "www.microsoft.com"),     # Cloudflare IPv4
        ("172.67.10.10", "example.com"),         # Cloudflare IPv4
        ("85.11.187.26", "edge.workers.dev"),    # Cloudflare Workers SNI
        ("85.11.187.26", "cdn.cloudflare.net"),  # Cloudflare SNI
        ("85.11.187.26", "app.netlify.app"),     # другой CDN
    ],
)
def test_reality_over_cdn_is_rejected(converter, address, sni):
    uri = (
        f"vless://e0c8c4a3-4d56-49c1-b403-40cbd757473b@{address}:443"
        f"?security=reality&sni={sni}&pbk=abc&sid=def&type=xhttp&path=%2F"
    )
    assert converter.convert(uri) is None


def test_xhttp_tls_over_cloudflare_is_still_allowed(converter):
    # TLS через CDN — штатная схема, запрет касается только Reality.
    uri = (
        "vless://e0c8c4a3-4d56-49c1-b403-40cbd757473b@104.16.1.1:443"
        "?security=tls&sni=cdn.example.com&type=xhttp"
        "&path=%2F&host=cdn.example.com"
    )
    outbound = converter.convert(uri)
    assert outbound is not None
    assert outbound["streamSettings"]["security"] == "tls"
    assert outbound["_profile"] == "xhttp"
