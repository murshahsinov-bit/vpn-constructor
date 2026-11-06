import pytest
from aggregator.parsers.vless import parse_vless_uri
from aggregator.parsers.hysteria2 import parse_hysteria2_uri

def test_parse_vless_reality():
    uri = "vless://e0c8c4a3-4d56-49c1-b403-40cbd757473b@85.11.187.26:443?security=reality&sni=www.microsoft.com&pbk=abc&sid=def&type=tcp&flow=xtls-rprx-vision#Germany"
    result = parse_vless_uri(uri)
    
    assert result is not None
    assert result["protocol"] == "vless"
    assert result["uuid"] == "e0c8c4a3-4d56-49c1-b403-40cbd757473b"
    assert result["address"] == "85.11.187.26"
    assert result["port"] == 443
    assert result["security"] == "reality"
    assert result["network"] == "tcp"
    assert result["name"] == "Germany"

def test_parse_vless_invalid():
    assert parse_vless_uri("http://wrong-protocol") is None
    assert parse_vless_uri("vless://") is None

def test_parse_hysteria2():
    uri = "hysteria2://password123@45.139.184.187:3478?sni=example.com&insecure=1&obfs=salamander#HysteriaNode"
    result = parse_hysteria2_uri(uri)
    
    assert result is not None
    assert result["protocol"] == "hysteria2"
    assert result["password"] == "password123"
    assert result["address"] == "45.139.184.187"
    assert result["port"] == 3478
    assert result["insecure"] is True
    assert result["obfs"] == "salamander"