import json
import os

def build_subscription(outbounds: list, template_path: str) -> dict:
    """
    Берет шаблон из папки templates, вставляет туда серверы 
    и настраивает балансировщик.
    """
    # Присваиваем уникальные теги
    for i, ob in enumerate(outbounds):
        ob["tag"] = f"proxy-{i+1}"

    # Читаем шаблон
    with open(template_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Вставляем серверы + direct и block
    config["outbounds"] = outbounds + [
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"}
    ]

    # Собираем теги для балансировщика
    selector_tags = [ob["tag"] for ob in outbounds]

    # Обновляем балансировщик и burstObservatory, чтобы они знали про наши серверы
    if "routing" in config and "balancers" in config["routing"]:
        for balancer in config["routing"]["balancers"]:
            if balancer.get("tag") == "auto-balancer":
                balancer["selector"] = selector_tags

    if "burstObservatory" in config:
        config["burstObservatory"]["subjectSelector"] = selector_tags

    return config

def save_config(config: dict, filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)