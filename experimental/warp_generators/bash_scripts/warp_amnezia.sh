#!/usr/bin/env bash
# Генерация конфига Cloudflare WARP для AmneziaWG
# Запускать в изолированной среде (Killercoda, Codespaces, Terminator)

set -e

echo "[*] Загрузка генератора WARP для AmneziaWG..."
# Используем -qO- для тихой загрузки и вывода в stdout
bash <(wget --inet4-only -qO- https://raw.githubusercontent.com/ImMALWARE/bash-warp-generator/main/warp_generator.sh)

echo -e "\n[+] Готово. Скопируйте конфиг выше или найдите файл warp.conf."