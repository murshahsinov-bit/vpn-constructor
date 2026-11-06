import json
import os

def build_subscription(outbounds: list, template_path: str) -> dict:
    # ФИНАЛЬНЫЙ ФИЛЬТР: проверяем, что security == tls или reality
    safe_outbounds = []
    for ob in outbounds:
        sec = ob.get("streamSettings", {}).get("security", "none").lower()
        if sec in ["tls", "reality"]:
            safe_outbounds.append(ob)
    
    prefix = "wl-proxy-" if "whitelist" in template_path else "proxy-"
    for i, ob in enumerate(safe_outbounds):
        ob["tag"] = f"{prefix}{i+1}"

    with open(template_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    config["outbounds"] = safe_outbounds + [
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"}
    ]

    selector_tags = [ob["tag"] for ob in safe_outbounds]

    if "routing" in config and "balancers" in config["routing"]:
        for balancer in config["routing"]["balancers"]:
            balancer["selector"] = selector_tags

    if "burstObservatory" in config:
        config["burstObservatory"]["subjectSelector"] = selector_tags

    return config

def save_config(config: dict, filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)