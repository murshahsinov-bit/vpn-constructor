#!/usr/bin/env bash
# Генерация конфига Cloudflare WARP для NekoRay / Exclave
# Запускать в изолированной среде

set -e

echo "[*] Загрузка генератора WARP для NekoRay/Exclave..."
bash <(wget -qO- https://raw.githubusercontent.com/DikozImpact/bash-warp-generator/refs/heads/patch-1/warp_generator_neko.sh)

echo -e "\n[+] Готово. Скопируйте JSON-конфиг и импортируйте его в NekoRay."