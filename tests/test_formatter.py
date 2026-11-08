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
    assert servers[0]["tag"] == "proxy-1"
    assert servers[0]["streamSettings"]["security"] == "reality"
    assert servers[0]["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"

    assert config["outbounds"][-2]["tag"] == "direct"
    assert config["outbounds"][-1]["tag"] == "block"
    assert config["routing"]["rules"][0]["outboundTag"] == "direct"


def test_build_subscription_limits_to_30():
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
    assert server["streamSettings"]["security"] == "tls"
    assert server["streamSettings"]["tlsSettings"]["serverName"] == "ripelever.net"

    routing = json.dumps(config["routing"]).lower()
    assert "geoip:ru" not in routing
    assert "geosite:category-ru" not in routing
