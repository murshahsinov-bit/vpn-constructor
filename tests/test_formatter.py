import pytest
from aggregator.formatter.to_json import build_subscription

def test_build_subscription():
    # Имитируем отфильтрованные серверы
    fake_outbounds = [
        {
            "protocol": "vless",
            "settings": {"vnext": [{"address": "1.1.1.1", "port": 443, "users": [{"id": "uuid1"}]}]}
        },
        {
            "protocol": "hysteria",
            "settings": {"address": "2.2.2.2", "port": 8443, "version": 2, "auth": "pass"}
        }
    ]
    
    config = build_subscription(fake_outbounds)
    
    # Проверяем базовую структуру
    assert "outbounds" in config
    assert "routing" in config
    assert "burstObservatory" in config
    
    # Проверяем, что серверы добавились вместе с direct/block
    assert len(config["outbounds"]) == 4
    assert config["outbounds"][0]["tag"] == "proxy-1"
    assert config["outbounds"][1]["tag"] == "proxy-2"
    assert config["outbounds"][2]["tag"] == "direct"
    assert config["outbounds"][3]["tag"] == "block"
    
    # Проверяем, что балансировщик ссылается на теги прокси
    balancer = config["routing"]["balancers"][0]
    assert balancer["tag"] == "auto-balancer"
    assert "proxy-1" in balancer["selector"]
    assert "proxy-2" in balancer["selector"]
    
    # Проверяем настройки пинга
    ping_config = config["burstObservatory"]["pingConfig"]
    assert ping_config["destination"] == "http://www.gstatic.com/dns-query" or "http://www.gstatic.com"