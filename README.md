# VPN-Конструктор

Бесплатная сборка VPN-подписок: GitHub Actions раз в час собирает открытые VLESS/Reality-конфиги, проверяет реальную задержку через Xray-core и оставляет только **топ-30 живых серверов**. Небольшой Python-сервис на **Netrun** проверяет персональный токен и только после этого отдаёт `auto.json`.

Telegram-бота нет. Управление клиентами — локальный `manager.py` на стандартной библиотеке Python.

## Архитектура

```text
┌─────────────────────┐      каждый час          ┌──────────────────────────┐
│ Открытые источники  │ ───────────────────────> │ GitHub Actions           │
│ VLESS / Reality     │                          │ aggregator/run.py        │
└─────────────────────┘                          │ + xray-knife (latency)   │
                                                 └────────────┬─────────────┘
                                                              │ топ-30
                                                              v
                                                   web/subscriptions/auto.json
                                                              │
                                                              │ GitHub API / CONFIG_URL
                                                              v
┌─────────────────────┐     token + дата      ┌──────────────────────────────┐
│ Клиент (Happ,        │ ───────────────────> │ Netrun worker (Docker)       │
│ INCY, OneXray)       │  /sub/auto.json       │ Flask + gunicorn, порт 8080  │
│                     │ <─────────────────── │ проверка clients.json         │
└─────────────────────┘  200 JSON или 403     └──────────────────────────────┘
                                                              ^
                                                              │ sync
                                                   ┌─────────────────────┐
                                                   │ manager.py          │
                                                   │ clients.json        │
                                                   └─────────────────────┘
```

## Как работает защита ссылок

1. `manager.py add` генерирует случайный токен через `secrets` + `hashlib` и сохраняет клиента в `clients.json`.
2. Клиент получает ссылку:

   ```text
   https://<сервис>.netrun.io/sub/auto.json?token=<токен>
   ```

3. Netrun-воркер читает `clients.json` (из файла, секрета `CLIENTS_JSON` или `/data`) и ищет токен.
4. Если токена нет или `expires_at` уже в прошлом — ответ `403 Forbidden`.
5. Если токен действителен — воркер отдаёт содержимое `auto.json` с `Content-Type: application/json`.

Важно: **проверка токена работает только тогда, когда `auto.json` нельзя получить в обход**. Если файл одновременно опубликован через GitHub Pages или лежит в публичном репозитории, любой желающий скачает его напрямую. Поэтому:

- отключите GitHub Pages;
- сделайте репозиторий приватным и дайте Netrun токен с правом **Contents: Read-only**;
- либо не храните `auto.json` в открытом доступе.

Подробности — в [DEPLOY_NETRUN.md](DEPLOY_NETRUN.md).

## Структура

```text
aggregator/                 # сборщик конфигов
  sources/sources.json      # источники VLESS/Reality (auto + whitelist)
  health/latency.py         # xray-knife, проверка задержки, TCP-fallback
  run.py                    # точка входа: парсинг → пинг → топ-30 → JSON/TXT
web/subscriptions/          # auto.json, whitelist.json, *.txt (результат сборки)
netrun_worker/
  app.py                    # Flask-воркер с проверкой токена
  Dockerfile                # образ для Netrun, порт 8080
  requirements.txt          # Flask, gunicorn, requests
  clients.json              # создаётся manager.py sync (в .gitignore)
  auto.json                 # резервная копия подписки (в .gitignore)
manager.py                  # управление клиентами, только stdlib
clients.json                # локальная база клиентов (в .gitignore)
stats.txt                   # статистика (в .gitignore)
.github/workflows/
  aggregator.yml            # сборка и коммит конфигов
DEPLOY_NETRUN.md            # инструкция по Netrun
```

## Быстрый старт

### 1. Настройте `.env`

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Заполните:

```env
SUB_SECRET_KEY=случайная_строка
NETRUN_BASE_URL=https://<ваш-сервис>.netrun.io
```

`NETRUN_BASE_URL` — адрес без `/sub/auto.json`, точный URL покажет кабинет Netrun.

### 2. Разверните воркер

```bash
python manager.py sync
```

Соберите ZIP из содержимого `netrun_worker/` и загрузите на Netrun. Пошагово: [DEPLOY_NETRUN.md](DEPLOY_NETRUN.md).

### 3. Добавьте клиента

```bash
python manager.py add --name "Иван" --days 30
```

Скрипт создаст токен, запишет клиента в `clients.json`, пересоберёт ссылки и обновит `netrun_worker/clients.json`.

### 4. Обновите данные в Netrun

- вариант A: загрузите новый ZIP;
- вариант B: обновите секрет `CLIENTS_JSON`;
- вариант C: замените `clients.json` в `/data`.

### 5. Проверьте

```bash
python manager.py stats
python manager.py check --status active
python manager.py check --status expired
```

## Команды `manager.py`

| Команда | Что делает |
|---|---|
| `python manager.py add --name "Иван" --days 30` | Добавить клиента |
| `python manager.py renew --name "Иван" --days 30` | Продлить подписку |
| `python manager.py stats` | Таблица в консоль + `stats.txt` |
| `python manager.py check --status active` | Только активные |
| `python manager.py check --status expired` | Только истёкшие |
| `python manager.py check --status all` | Все клиенты |
| `python manager.py check --name "Иван"` | Один клиент |
| `python manager.py sync` | Пересобрать ссылки и `netrun_worker/` |
| `python manager.py --base-url https://x.netrun.io sync` | Разово переопределить адрес |

## Автоматическая сборка конфигов

`.github/workflows/aggregator.yml` запускается раз в час и вручную:

1. ставит Python-зависимости и Go 1.25;
2. собирает `xray-knife` из исходников (`go install ...@v11.5.0`);
3. проверяет, из какой страны идёт запуск, и предупреждает, если это не РФ;
4. запускает `python -m aggregator.run`: парсинг → дедупликация → реальный
   HTTP-тест через Xray-core с конкурентностью 50 → сортировка по задержке →
   топ-30 в `auto.json` / `whitelist.json`;
5. коммитит изменения из `web/subscriptions/` в `main`.

Таймаут job — 45 минут. Cron — `0 * * * *`: частая массовая проверка прокси
повышает риск блокировки аккаунта GitHub.

Netrun-воркер забирает свежий `auto.json` через GitHub API или `CONFIG_URL` и кэширует его на `CACHE_TTL` секунд (по умолчанию 60). Пересобирать контейнер при обновлении конфигов не нужно.

### Проверка «из России»

`xray-knife` не умеет работать через внешний прокси, поэтому страну проверки
определяет раннер. GitHub-hosted раннер находится вне РФ, и его пинг — это
задержка из дата-центра GitHub, а не из России.

Для настоящего RU-отбора:

1. Подключите self-hosted runner в России (Linux).
2. В настройках репозитория → **Variables** создайте `RU_RUNNER_LABELS`:

   ```json
   ["self-hosted","linux","ru"]
   ```

3. Workflow автоматически выберет этот раннер вместо `ubuntu-latest`.
   Шаг «Show test origin» печатает страну и выдаёт `::warning::`, если это не RU.

Без RU-раннера сборка не падает: топ-30 строится по задержке из той точки,
где запущен workflow. Это лучше, чем ничего, но не гарантирует скорость
именно из России.

### Обновление топ-30

Топ пересобирается при каждом запуске workflow. Вручную:

```bash
python -m aggregator.run
```

Локально нужен `xray-knife`. Если его нет, включается TCP-fallback (TCP RTT,
без проверки самого прокси). Быстрая сборка без проверки — `SKIP_LATENCY=1`.

## Мобильные клиенты и совместимость

JSON-подписка (`auto.json`) собирается строго в одном формате:

- только `vless`;
- только `tcp`;
- только `security: "reality"`;
- только `flow: "xtls-rprx-vision"` (Reality Vision);
- `realitySettings` всегда содержит `serverName`, `publicKey`, `shortId` и `fingerprint: "chrome"`;
- без `fragment`, `mux`, `sockopt`, `xhttp`, `hysteria`, `ws`, `grpc`;
- без `balancers`, `burstObservatory` и `geoip`/`geosite`;
- до 30 серверов (`json_max_outbounds: 30`), отсортированных по задержке.

Whitelist-режим (`whitelist.json`) использует те же правила, но:

- в JSON попадают только серверы из источников `igareck_*`;
- источники `igareck` публикуют white-list конфиги как VLESS + TCP + TLS +
  Vision (SNI разрешённого домена), поэтому для whitelist разрешён
  `security: "tls"` (управляется `whitelist.allow_tls_vision`);
- если живых igareck-серверов нет, JSON **не перезаписывается** мёртвыми
  узлами; в логе будет ошибка, а TXT соберётся из проверенных ссылок;
- в `routing.rules` нет `geoip:ru` и `geosite:category-ru`: весь трафик идёт
  в туннель, а не напрямую.

Такой JSON отдаётся с `Content-Type: application/json` и содержит полный
Xray-конфиг с секциями `inbounds` и `outbounds`. Его понимают **Happ** и
**INCY** (Xray-core, Android/iOS), а также OneXray и v2rayNG (custom config).

WS + TLS, gRPC и XHTTP намеренно исключены из auto: в 2026 ТСПУ в России
блокирует их по TLS-отпечатку и характеру трафика. Reality Vision
маскируется под обычный TLS к чужому домену и неотличим от браузера.

Полный список серверов остаётся в `web/subscriptions/auto_all.txt` и
`whitelist_all.txt` — как резервная ссылочная подписка.

## Как проверить, что в JSON попали лучшие серверы

```bash
# 1. Посмотреть лог отбора: задержки и источники
python -m aggregator.run 2>&1 | Select-String "Топ-|ms  "

# 2. Проверить структуру auto.json
python - <<'PY'
import json
cfg = json.load(open("web/subscriptions/auto.json", encoding="utf-8"))
servers = [o for o in cfg["outbounds"] if o["protocol"] == "vless"]
print("серверов:", len(servers))
for o in servers[:5]:
    u = o["settings"]["vnext"][0]
    print(u["address"], u["port"], o["streamSettings"]["security"],
          o["settings"]["vnext"][0]["users"][0]["flow"])
assert len(servers) <= 30
assert all(o["streamSettings"]["network"] == "tcp" for o in servers)
assert all(o["streamSettings"]["security"] == "reality" for o in servers)
assert all(o["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision" for o in servers)
PY

# 3. Перепроверить топ вручную через xray-knife
xray-knife http -f web/subscriptions/auto_all.txt -t 50 -o check.json \
  -x json --sort --timeout 10000 --mdelay 8000 --prescan --diagnose=false
```

В `check.json` успешные серверы имеют `status: "passed"` или
`"semi-passed"` и положительный `delay`. Именно они попадают в топ-30.


## Переменные Netrun

Задаются в кабинете Netrun, не в `.env`:

| Переменная | Назначение |
|---|---|
| `GITHUB_REPO` | `USER/REPO`, откуда читать `auto.json` |
| `GITHUB_BRANCH` | Ветка, по умолчанию `main` |
| `CONFIG_PATH` | `web/subscriptions/auto.json` |
| `GITHUB_TOKEN` | Read-only токен для приватного репозитория |
| `CLIENTS_JSON` | JSON или base64(JSON) вместо файла клиентов |
| `CLIENTS_FILE` | Путь к файлу, например `/data/clients.json` |
| `AUTO_FILE` | Локальный резервный `auto.json` |
| `CONFIG_URL` | Прямой URL подписки |
| `CACHE_TTL` | Время кэша в секундах |
| `PORT` | Netrun задаёт сам |

## Ограничения

- Netrun Free Tier: 1 проект, 256 МБ RAM, 0.25 vCPU, 2 ГБ диска, сон после 15 минут простоя.
- Netrun запрещает размещать VPN/прокси-серверы. Этот проект — только API подписок; сами узлы Xray/VLESS остаются внешними.
- GitHub Pages не проверяет токены. Не используйте его как публичный источник `auto.json`, если нужна реальная защита.
- Если делаете репозиторий приватным, GitHub Actions расходует бесплатные минуты. Уменьшите частоту cron при необходимости.

## Локальная разработка

```bash
python -m aggregator.run          # собрать конфиги
python manager.py add --name Test --days 7
python manager.py stats

cd netrun_worker
python -m venv .venv
pip install -r requirements.txt
python app.py                     # http://127.0.0.1:8080
```
