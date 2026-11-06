import pytest
from aggregator.converter.link_to_outbound import LinkToOutboundConverter

@pytest.fixture
def converter():
    return LinkToOutboundConverter()

def test_convert_vless_reality(converter):
    uri = "vless://e0c8c4a3-4d56-49c1-b403-40cbd757473b@85.11.187.26:443?security=reality&sni=www.microsoft.com&pbk=abc&sid=def&type=tcp&flow=xtls-rprx-vision"
    outbound = converter.convert(uri, tag="proxy-1")
    
    assert outbound["tag"] == "proxy-1"
    assert outbound["protocol"] == "vless"
    assert outbound["settings"]["vnext"][0]["address"] == "85.11.187.26"
    assert outbound["streamSettings"]["security"] == "reality"
    assert outbound["streamSettings"]["realitySettings"]["serverName"] == "www.microsoft.com"

def test_convert_hysteria2(converter):
    uri = "hysteria2://password123@45.139.184.187:3478?sni=example.com&obfs=salamander&obfs-password=mypass"
    outbound = converter.convert(uri, tag="proxy-2")
    
    assert outbound["tag"] == "proxy-2"
    assert outbound["protocol"] == "hysteria"
    assert outbound["settings"]["version"] == 2
    assert outbound["streamSettings"]["hysteriaSettings"]["auth"] == "password123"
    # Проверяем, что маскировка UDP применилась
    assert "finalmask" in outbound["streamSettings"]