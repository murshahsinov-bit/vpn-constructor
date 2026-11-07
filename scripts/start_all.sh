#!/usr/bin/env bash
# Запуск агрегатора конфигов в фоновом режиме (без Telegram-бота).

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p logs
mkdir -p web/subscriptions

if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "⚠️ Папка venv не найдена. Убедитесь, что зависимости установлены."
    exit 1
fi

echo "🚀 Запуск фонового цикла агрегатора (каждые 15 минут)..."
(
    while true; do
        echo "[$(date)] Запуск агрегатора..." >> logs/aggregator.log
        python -m aggregator.run >> logs/aggregator.log 2>&1
        echo "[$(date)] Агрегатор завершил работу. Сон 15 минут..." >> logs/aggregator.log
        sleep 900
    done
) &
echo $! > logs/aggregator.pid
echo "✅ Агрегатор запущен (PID: $(cat logs/aggregator.pid))"
