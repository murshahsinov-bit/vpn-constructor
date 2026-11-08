import json

import pytest

from aggregator.formatter.to_json import build_subscription


def make_reality(address: str = "1.1.1.1", user_id: str = "uuid1") -> dict:
    return {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": 443,
                "users": [{"id": user_id, "flow": "xtls-rprx-vision"}],
            }]
        },
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "serverName": "example.com",
                "publicKey": "pbk",
                "shortId": "sid",
            },
        },
    }


def make_xhttp_reality(address: str = "1.1.1.1", user_id: str = "uuid1") -> dict:
    return {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": 443,
                "users": [{"id": user_id, "flow": ""}],
            }]
        },
        "streamSettings": {
            "network": "xhttp",
            "security": "reality",
            "realitySettings": {
                "serverName": "example.com",
                "publicKey": "pbk",
                "shortId": "sid",
            },
            "xhttpSettings": {"mode": "auto", "path": "/cdn"},
        },
    }


def make_whitelist_tls(address: str = "2.2.2.2") -> dict:
    return {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": 443,
                "users": [{"id": "uuid-tls", "flow": "xtls-rprx-vision"}],
            }]
        },
        "streamSettings": {
            "network": "tcp",
            "security": "tls",
            "tlsSettings": {
                "serverName": "ripelever.net",
                "fingerprint": "chrome",
            },
        },
    }


def make_relay() -> dict:
    return {
        "tag": "wl-relay",
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": "203.0.113.10",
                "port": 443,
                "users": [{"id": "relay-uuid", "flow": "xtls-rprx-vision"}],
            }]
        },
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "serverName": "gosuslugi.ru",
                "publicKey": "relay-pbk",
                "shortId": "relay-sid",
            },
        },
    }


def test_build_subscription_filters_and_shapes():
    fake_outbounds = [
        make_reality(),
        {"protocol": "hysteria", "settings": {"address": "2.2.2.2"}},
    ]

    config = build_subscription(
        fake_outbounds, "aggregator/templates/auto_template.json", 30
    )

    assert "outbounds" in config
    assert "routing" in config
    assert "burstObservatory" not in config
    assert "balancers" not in config["routing"]

    servers = [o for o in config["outbounds"] if o["protocol"] == "vless"]
    assert len(servers) == 1
    assert servers[0]["tag"] == "proxy-tcp-1"
    assert servers[0]["streamSettings"]["security"] == "reality"
    assert servers[0]["streamSettings"]["realitySettings"]["fingerprint"] == "firefox"
    assert servers[0]["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
    assert servers[0]["fragment"] == {
        "packets": "tlshello", "length": "100-200", "interval": "10-20"
    }

    assert config["outbounds"][-2]["tag"] == "direct"
    assert config["outbounds"][-1]["tag"] == "block"
    assert config["routing"]["rules"][0]["outboundTag"] == "direct"


def test_build_subscription_limits_to_30_servers():
    many = [
        make_reality(address=f"h{i}.example.com", user_id=f"uuid{i}")
        for i in range(40)
    ]
    config = build_subscription(
        many, "aggregator/templates/auto_template.json", 30
    )
    servers = [o for o in config["outbounds"] if o["protocol"] == "vless"]
    assert len(servers) == 30


def test_tls_allowed_only_for_whitelist_template():
    with pytest.raises(ValueError):
        build_subscription(
            [make_whitelist_tls()], "aggregator/templates/auto_template.json", 30
        )

    config = build_subscription(
        [make_whitelist_tls()], "aggregator/templates/whitelist_template.json", 30
    )
    server = config["outbounds"][0]
    assert server["tag"] == "wl-proxy-tcp-1"
    assert server["streamSettings"]["security"] == "tls"
    assert server["streamSettings"]["tlsSettings"]["serverName"] == "ripelever.net"
    assert server["streamSettings"]["tlsSettings"]["fingerprint"] == "firefox"

    routing = json.dumps(config["routing"]).lower()
    assert "geoip:ru" not in routing
    assert "geosite:category-ru" not in routing


def test_dual_profiles_per_server():
    xhttp = make_xhttp_reality()
    tcp = make_reality()
    entry = dict(xhttp)
    entry["_variants"] = {"xhttp": xhttp, "tcp": tcp}
    entry["_profiles"] = ["xhttp", "tcp"]

    config = build_subscription(
        [entry], "aggregator/templates/auto_template.json", 30
    )

    servers = [o for o in config["outbounds"] if o["protocol"] == "vless"]
    assert [s["tag"] for s in servers] == ["proxy-xhttp-1", "proxy-tcp-1"]

    xhttp_out, tcp_out = servers
    assert xhttp_out["streamSettings"]["network"] == "xhttp"
    assert xhttp_out["streamSettings"]["xhttpSettings"]["mode"] == "stream-one"
    assert xhttp_out["settings"]["vnext"][0]["users"][0]["flow"] == ""
    assert "fragment" not in xhttp_out

    assert tcp_out["streamSettings"]["network"] == "tcp"
    assert tcp_out["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
    assert tcp_out["fragment"]["packets"] == "tlshello"

    assert xhttp_out["streamSettings"]["realitySettings"]["fingerprint"] == "firefox"
    assert tcp_out["streamSettings"]["realitySettings"]["fingerprint"] == "firefox"


def test_auto_json_has_no_forbidden_junk():
    config = build_subscription(
        [make_xhttp_reality(), make_reality(address="3.3.3.3", user_id="uuid2")],
        "aggregator/templates/auto_template.json",
        30,
    )
    serialized = json.dumps(config, ensure_ascii=False)
    for forbidden in (
        '"ws"', '"mux"', '"sockopt"', '"balancers"',
        '"burstObservatory"', "geoip:ru", "geosite:category-ru",
    ):
        assert forbidden not in serialized


def test_whitelist_relay_chain():
    targets = [
        {"_variants": {"xhttp": make_xhttp_reality(address="5.5.5.5", user_id="u5"),
                       "tcp": make_reality(address="5.5.5.5", user_id="u5")},
         "_profiles": ["xhttp", "tcp"]},
        {"_variants": {"tcp": make_reality(address="6.6.6.6", user_id="u6")},
         "_profiles": ["tcp"]},
    ]

    config = build_subscription(
        targets,
        "aggregator/templates/whitelist_template.json",
        10,
        allow_tls=True,
        relay=make_relay(),
    )

    outbounds = {ob["tag"]: ob for ob in config["outbounds"]}
    assert "wl-relay" in outbounds
    relay = outbounds["wl-relay"]
    assert relay["streamSettings"]["security"] == "reality"
    assert relay["streamSettings"]["realitySettings"]["serverName"] == "gosuslugi.ru"
    assert "sockopt" not in relay["streamSettings"]

    chained = [
        ob for ob in config["outbounds"]
        if ob.get("protocol") == "vless" and ob["tag"].startswith("wl-proxy-")
    ]
    assert len(chained) == 3
    for ob in chained:
        assert ob["streamSettings"]["sockopt"]["dialerProxy"] == "wl-relay"

    # первый outbound — целевой, а не relay: иначе default пошёл бы напрямую
    assert config["outbounds"][0]["tag"].startswith("wl-proxy-")
    assert config["outbounds"][-3]["tag"] == "wl-relay"

    serialized = json.dumps(config, ensure_ascii=False).lower()
    assert "geoip:ru" not in serialized
    assert "geosite:category-ru" not in serialized
