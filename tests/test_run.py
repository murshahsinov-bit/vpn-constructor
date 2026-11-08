from aggregator.run import (
    ServerRecord,
    _alternate_variant,
    _outbound_to_link,
    _relay_from_records,
)


def make_xhttp(uuid: str = "uuid-1") -> dict:
    return {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": "198.51.100.7",
                "port": 443,
                "users": [{"id": uuid, "flow": ""}],
            }]
        },
        "streamSettings": {
            "network": "xhttp",
            "security": "reality",
            "realitySettings": {
                "serverName": "download.example.com",
                "publicKey": "pbk",
                "shortId": "sid",
            },
            "xhttpSettings": {"mode": "stream-one", "path": "/cdn"},
        },
        "_profile": "xhttp",
    }


def make_record(status: str) -> ServerRecord:
    outbound = make_xhttp()
    return ServerRecord(
        identity=("198.51.100.7", 443, "uuid-1"),
        variants={"xhttp": outbound},
        links={"xhttp": "vless://uuid-1@198.51.100.7:443?type=xhttp"},
        sources={"igareck_sni_whitelist"},
        delays={"xhttp": 42},
        statuses={"xhttp": status},
    )


def test_alternate_variant_builds_tcp_with_vision_and_fragment():
    variant = _alternate_variant(make_xhttp(), "tcp")

    assert variant is not None
    assert variant["_profile"] == "tcp"
    assert variant["streamSettings"]["network"] == "tcp"
    assert "xhttpSettings" not in variant["streamSettings"]
    assert variant["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
    assert variant["fragment"] == {
        "packets": "tlshello", "length": "100-200", "interval": "10-20"
    }
    assert variant["streamSettings"]["realitySettings"]["fingerprint"] == "firefox"


def test_alternate_variant_builds_xhttp_without_fragment():
    tcp_source = _alternate_variant(make_xhttp(), "tcp")
    assert tcp_source is not None
    variant = _alternate_variant(tcp_source, "xhttp")
    assert variant is not None
    assert variant["streamSettings"]["network"] == "xhttp"
    assert variant["streamSettings"]["xhttpSettings"]["mode"] == "stream-one"
    assert variant["settings"]["vnext"][0]["users"][0]["flow"] == ""
    assert "fragment" not in variant

    link = _outbound_to_link(variant)
    assert "type=xhttp" in link
    assert "security=reality" in link
    assert "fp=firefox" in link


def test_relay_rejects_tcp_fallback_by_default():
    record = make_record("tcp")
    relay, identity, link = _relay_from_records([record], {})
    assert relay is None
    assert identity is None
    assert link is None

    relay, identity, link = _relay_from_records([record], {"allow_tcp_fallback": True})
    assert relay is not None
    assert identity == record.identity
    assert link == record.links["xhttp"]


def test_relay_accepts_only_real_check():
    record = make_record("passed")
    relay, identity, _link = _relay_from_records([record], {})
    assert relay is not None
    assert identity == record.identity
    assert relay["tag"] == "wl-relay"


def test_relay_rejects_yandex_sni_and_host():
    record = make_record("passed")
    record.variants["xhttp"]["streamSettings"]["realitySettings"]["serverName"] = (
        "storage.yandexcloud.net"
    )
    relay, _identity, _link = _relay_from_records([record], {})
    assert relay is None
