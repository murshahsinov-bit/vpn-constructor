#!/usr/bin/env bash
# Запуск Telegram-бота и агрегатора в фоновом режиме

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Создаем папку для логов, если её нет
mkdir -p logs
mkdir -p web/subscriptions

# Активация виртуального окружения
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "⚠️ Папка venv не найдена. Убедитесь, что зависимости установлены."
    exit 1
fi

echo "🚀 Запуск Telegram-бота..."
nohup python -m bot.main > logs/bot.log 2>&1 &
echo $! > logs/bot.pid
echo "✅ Бот запущен (PID: $(cat logs/bot.pid))"

echo "🚀 Запуск фонового цикла агрегатора (каждые 15 минут)..."
# Запускаем бесконечный цикл, который вызывает run.py и спит 900 секунд
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

echo "🎉 Все процессы успешно запущены в фоне."