from aggregator.run import (
    ServerRecord,
    _alternate_variant,
    _outbound_to_link,
    _relay_from_records,
    _select_records,
    _write_txt,
)
from urllib.parse import parse_qs, urlsplit


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
                "serverName": "gosuslugi.ru",
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


def test_relay_requires_preferred_sni_by_default():
    record = make_record("passed")
    record.variants["xhttp"]["streamSettings"]["realitySettings"]["serverName"] = (
        "download.example.com"
    )

    relay, _identity, _link = _relay_from_records([record], {})
    assert relay is None

    relay, identity, _link = _relay_from_records(
        [record], {"require_preferred_sni": False}
    )
    assert relay is not None
    assert identity == record.identity


def test_write_txt_creates_incy_and_happ_variants(tmp_path):
    link = (
        "vless://uuid@198.51.100.7:443?encryption=none&flow=xtls-rprx-vision"
        "&security=reality&sni=example.com&type=tcp#Germany"
    )
    config = {"paths": {"output_dir": str(tmp_path)}}

    _write_txt("auto", [link], config)

    incy_file = tmp_path / "auto_all.txt"
    happ_file = tmp_path / "auto_all_happ.txt"
    assert incy_file.exists()
    assert happ_file.exists()

    incy_query = parse_qs(urlsplit(incy_file.read_text(encoding="utf-8")).query)
    happ_query = parse_qs(urlsplit(happ_file.read_text(encoding="utf-8")).query)

    assert incy_query["fragmentPackets"] == ["tlshello"]
    assert happ_query["fragment"] == ["100-200,10-20,tlshello"]
    assert "fragment" not in incy_query
    assert "fragmentPackets" not in happ_query


def _record(profile: str, address: str, delay: int) -> ServerRecord:
    outbound = make_xhttp()
    outbound["streamSettings"]["network"] = profile
    outbound["_profile"] = profile
    return ServerRecord(
        identity=(address, 443, f"uuid-{address}"),
        variants={profile: outbound},
        links={profile: f"vless://uuid@{address}:443?type={profile}"},
        sources={"test"},
        delays={profile: delay},
        statuses={profile: "passed"},
    )


def test_select_records_prioritizes_xhttp_and_keeps_tcp_fallback():
    tcp_fast = _record("tcp", "10.0.0.1", 10)
    tcp_next = _record("tcp", "10.0.0.2", 20)
    xhttp_slow = _record("xhttp", "10.0.0.3", 300)

    selected = _select_records([tcp_fast, tcp_next, xhttp_slow], 3, xhttp_share=0.6)

    assert len(selected) == 3
    assert selected[0].identity[0] == "10.0.0.3", "XHTTP должен идти первым"
    assert {r.identity[0] for r in selected} == {"10.0.0.1", "10.0.0.2", "10.0.0.3"}


def test_select_records_reserves_slots_for_tcp_only():
    records = [_record("xhttp", f"10.1.0.{i}", i * 10) for i in range(1, 6)]
    records.append(_record("tcp", "10.2.0.1", 5))

    selected = _select_records(records, 3, xhttp_share=0.6)

    assert len(selected) == 3
    assert sum(1 for r in selected if "xhttp" in r.alive_profiles) == 2
    assert sum(1 for r in selected if "xhttp" not in r.alive_profiles) == 1
