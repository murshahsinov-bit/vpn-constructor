import json
from typing import List, Dict, Any

def build_subscription(
    outbounds: List[Dict[str, Any]], 
    balancer_tag: str = "auto-balancer",
    selector_prefix: str = "proxy-",
    probe_url: str = "http://www.gstatic.com/generate_204"
) -> Dict[str, Any]:
    """
    Собирает финальный JSON-конфиг для Xray/INCY с балансировщиком и burstObservatory.
    
    :param outbounds: Список готовых outbound-объектов (от конвертера и фильтра).
    :param balancer_tag: Тег балансировщика для routing.rules.
    :param selector_prefix: Префикс тегов серверов, которые попадут в балансировщик.
    :param probe_url: URL для проверки живости серверов в burstObservatory.
    :return: Полный JSON-конфиг (dict).
    """
    
    # 1. Присваиваем уникальные теги всем outbound'ам, чтобы балансировщик мог их найти
    for i, ob in enumerate(outbounds):
        ob["tag"] = f"{selector_prefix}{i+1}"

    # 2. Собираем список тегов для селектора балансировщика
    selector_tags = [ob["tag"] for ob in outbounds]

    # 3. Формируем итоговый конфиг
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks-in",
                "protocol": "socks",
                "port": 10808,
                "listen": "127.0.0.1",
                "settings": {"udp": True}
            }
        ],
        "outbounds": outbounds + [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"}
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "balancerTag": balancer_tag
                }
            ],
            "balancers": [
                {
                    "tag": balancer_tag,
                    "selector": selector_tags,
                    "strategy": {
                        "type": "leastLoad",
                        "settings": {
                            "expected": 2,
                            "maxRTT": "1500ms",
                            "tolerance": 0.4
                        }
                    },
                    "fallbackTag": "direct"
                }
            ]
        },
        "burstObservatory": {
            "subjectSelector": selector_tags,
            "pingConfig": {
                "destination": probe_url,
                "connectivity": "",
                "interval": "30s",
                "sampling": 2,
                "timeout": "5s",
                "httpMethod": "HEAD"
            }
        },
        "stats": {}
    }

    return config

def save_config(config: Dict[str, Any], filepath: str):
    """Сохраняет конфиг в файл."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)