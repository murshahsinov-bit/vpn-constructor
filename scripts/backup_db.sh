#!/usr/bin/env bash
# Безопасный бэкап SQLite базы данных бота

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

DB_FILE="vpn_bot.db"
BACKUP_DIR="backups"
DATE=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="$BACKUP_DIR/vpn_bot_$DATE.sqlite"

# Создаем папку для бэкапов
mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
    echo "❌ Ошибка: Файл базы данных $DB_FILE не найден."
    exit 1
fi

echo "💾 Создание бэкапа базы данных..."
# Используем команду .backup для безопасного копирования без блокировки
sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'"

if [ $? -eq 0 ]; then
    echo "✅ Бэкап успешно создан: $BACKUP_FILE"
else
    echo "❌ Ошибка при создании бэкапа."
    exit 1
fi

# Удаляем бэкапы старше 7 дней
echo "🧹 Очистка старых бэкапов (старше 7 дней)..."
find "$BACKUP_DIR" -type f -name "vpn_bot_*.sqlite" -mtime +7 -exec rm {} \;
echo "✅ Очистка завершена."