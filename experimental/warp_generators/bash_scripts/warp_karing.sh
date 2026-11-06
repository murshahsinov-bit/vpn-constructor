#!/usr/bin/env bash
# Генерация конфига Cloudflare WARP для Karing / Hiddify
# Запускать в изолированной среде

set -e

echo "[*] Загрузка генератора WARP для Karing/Hiddify..."
bash <(wget -qO- https://raw.githubusercontent.com/DikozImpact/bash-warp-generator/refs/heads/patch-1/warp_generator_karing.sh)

echo -e "\n[+] Готово. Импортируйте полученный конфиг в Karing."
echo "[*] Для варианта WARP-in-WARP выполните:"
echo "bash <(wget -qO- https://raw.githubusercontent.com/DikozImpact/bash-warp-generator/refs/heads/patch-1/warp_in_warp.sh)"