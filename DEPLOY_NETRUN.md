# Деплой на Netrun

Сервис `netrun_worker/` — это **не VPN-сервер и не прокси**. Он только проверяет токен и отдаёт JSON-подписку. Сами VLESS/Reality-узлы остаются внешними: Netrun запрещает размещать Xray/V2Ray/VLESS/Trojan/Shadowsocks-серверы, но не запрещает API, который отдаёт список конфигов.

## 0. Главное про защиту

Проверка токена имеет смысл только тогда, когда `auto.json` нельзя получить в обход Netrun.

Перед деплоем сделайте одно из двух:

1. **Рекомендуется:** отключите GitHub Pages и сделайте репозиторий приватным. Netrun будет читать `auto.json` через GitHub API по токену.
2. Либо оставьте репозиторий публичным, но не публикуйте `auto.json` через GitHub Pages и не храните его в открытом виде. Иначе любой сможет открыть файл напрямую и токен не нужен.

Как отключить GitHub Pages:

- GitHub → репозиторий → **Settings** → **Pages** → **Source** → **None** / **Unpublish**.

Если репозиторий приватный, GitHub Actions на private-репозиториях расходует бесплатные минуты (2000 в месяц). Чтобы не выйти за лимит, уменьшите частоту запуска в `.github/workflows/aggregator.yml`, например с `*/15 * * * *` до `0 * * * *` (раз в час).

## 1. Регистрация в Netrun

1. Откройте <https://netrun.io> и нажмите **Начать**.
2. Войдите по e-mail: введите почту, получите одноразовый код и подтвердите вход. Пароль и банковская карта не нужны. Можно войти через Google.
3. На бесплатном тарифе доступен **один проект**: 256 МБ RAM, 0.25 vCPU, 2 ГБ диска, поддомен `*.netrun.io`. Сайт засыпает после 15 минут простоя и просыпается при первом запросе.

## 2. Подготовьте ZIP

В корне проекта выполните:

```bash
python manager.py sync
```

Команда:

- пересоберёт ссылки под `NETRUN_BASE_URL`;
- создаст `netrun_worker/clients.json`;
- скопирует `web/subscriptions/auto.json` в `netrun_worker/auto.json` как резервный источник.

Затем соберите архив **из содержимого** папки `netrun_worker`, чтобы `Dockerfile`, `app.py`, `requirements.txt` и `clients.json` лежали в корне ZIP.

Windows PowerShell:

```powershell
Compress-Archive -Path .\netrun_worker\* -DestinationPath .\netrun-worker.zip -Force
```

Linux/macOS:

```bash
cd netrun_worker
zip -r ../netrun-worker.zip . -x '__pycache__/*' '*.pyc' '.venv/*'
cd ..
```

Проверьте, что внутри ZIP нет вложенной папки `netrun_worker/`: `app.py` и `Dockerfile` должны быть в корне архива.

> `clients.json` и `auto.json` находятся в `.gitignore` и не попадают в GitHub. В ZIP они попадут, потому что лежат локально. Не публикуйте этот архив в открытых источниках.

## 3. Загрузите проект в Netrun

1. В кабинете Netrun нажмите **Создать проект** / **Начать**.
2. Выберите загрузку **архивом (ZIP)**.
3. Загрузите `netrun-worker.zip`.
4. Если платформа спросит тип проекта, выберите **Docker** / **Dockerfile**. Если не спросит — Netrun сам найдёт `Dockerfile`.
5. Укажите имя проекта. Оно станет частью адреса: `https://<имя>.netrun.io` или `https://<имя>.de1.netrun.io` — точный URL покажет кабинет.
6. Порт указывать не нужно: в `Dockerfile` стоит `EXPOSE 8080`, Netrun передаст приложению переменную `PORT`.
7. Нажмите **Опубликовать** и дождитесь статуса «Работает».

## 4. Настройте переменные окружения

Откройте проект → вкладка **Секреты** / **Переменные окружения**.

Обязательные или полезные значения:

| Переменная | Значение | Зачем |
|---|---|---|
| `GITHUB_REPO` | `USER/REPO` | Откуда брать подписки |
| `GITHUB_BRANCH` | `main` | Ветка репозитория |
| `CONFIG_PATH` | `web/subscriptions/auto.json` | Путь к `auto.json` |
| `SUBSCRIPTIONS_DIR` | `web/subscriptions` | Путь к TXT/whitelist |
| `GITHUB_TOKEN` | fine-grained PAT | Нужен для приватного репозитория; права **Contents: Read-only** |
| `CLIENTS_JSON` | JSON или base64(JSON) | Альтернатива файлу `clients.json` |
| `CACHE_TTL` | `60` | Сколько секунд кэшировать файлы подписки |
| `CONFIG_URL` | прямой URL | Необязательно; если не хотите использовать GitHub API |
| `PROFILE_TITLE` | `VPN Constructor` | Имя подписки (<=25 символов) |
| `SUBSCRIPTION_TOTAL_BYTES` | `107374182400` | Лимит трафика в `subscription-userinfo` |
| `SUPPORT_URL` | `https://t.me/...` | Кнопка поддержки |
| `SUB_EXPIRE_BUTTON_LINK` | `https://t.me/your_bot` | Кнопка «Продлить» |
| `WEBRTC_SOCKS5` | `socks5://...` | Адрес для `/sub/webrtc.txt` |
| `PORT` | не задавайте | Netrun подставит сам; запасное значение — 8080 |

`SUB_SECRET_KEY` в Netrun не нужен: токены уже сгенерированы `manager.py`.

### Варианты хранения клиентов

**A. `clients.json` внутри ZIP (проще всего)**

Файл уже собран командой `python manager.py sync`. После каждого добавления/продления клиента:

```bash
python manager.py sync
```

и загрузите новый ZIP в Netrun через кнопку обновления проекта. Публичный URL не изменится.

**B. Секрет `CLIENTS_JSON` (без пересборки)**

Получите base64 от файла:

```bash
python -c "import base64, pathlib; print(base64.b64encode(pathlib.Path('netrun_worker/clients.json').read_bytes()).decode())"
```

Вставьте результат в секрет `CLIENTS_JSON`. Сервис понимает и обычный JSON, и base64. При изменении клиентов обновляйте секрет — пересобирать проект не нужно.

**C. Постоянная папка `/data`**

Netrun сохраняет содержимое `/data` между перезапусками. Загрузите `clients.json` через вкладку **Данные** и задайте:

```env
CLIENTS_FILE=/data/clients.json
```

Тогда обновлять клиентов можно через вкладку «Данные» без пересборки.

## 5. Получите URL и проверьте защиту

Скопируйте публичный адрес из кабинета Netrun. Пропишите его в `.env` **без** `/sub/auto.json`:

```env
NETRUN_BASE_URL=https://<ваш-сервис>.netrun.io
```

Пересоберите ссылки:

```bash
python manager.py sync
```

Проверка валидного токена:

```bash
curl -i "https://<ваш-сервис>.netrun.io/sub/auto.json?token=<токен>"
```

Ожидается:

```text
HTTP/1.1 200 OK
Content-Type: application/json
```

Проверка неверного токена:

```bash
curl -i "https://<ваш-сервис>.netrun.io/sub/auto.json?token=invalid"
```

Ожидается:

```text
HTTP/1.1 403 Forbidden
{"error":"forbidden"}
```

Проверка здоровья сервиса:

```bash
curl -i "https://<ваш-сервис>.netrun.io/healthz"
```

## 6. Как обновлять данные

| Что меняется | Что делать |
|---|---|
| Конфиги в `web/subscriptions/auto.json` | Ничего: GitHub Actions обновляет файл, Netrun подхватывает его в течение `CACHE_TTL` секунд |
| Клиенты (`add`/`renew`) | `python manager.py sync`, затем обновить ZIP или секрет `CLIENTS_JSON`/файл в `/data` |
| Код воркера | Загрузить новый ZIP в Netrun; URL останется прежним |
| Адрес Netrun изменился | Поправить `NETRUN_BASE_URL` в `.env`, выполнить `python manager.py sync`, обновить ZIP |

## 7. Локальная проверка

```bash
cd netrun_worker
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
$env:CLIENTS_FILE="..\clients.json"
$env:AUTO_FILE="..\web\subscriptions\auto.json"
python app.py
```

Linux/macOS:

```bash
CLIENTS_FILE=../clients.json AUTO_FILE=../web/subscriptions/auto.json python app.py
```

Сервис будет доступен на `http://127.0.0.1:8080/sub/auto.json?token=...`.

## 8. Частые ошибки

| Симптом | Причина и решение |
|---|---|
| `502 Bad Gateway` | Приложение не слушает `0.0.0.0:PORT`. У нас это настроено через gunicorn; смотрите логи запуска |
| Всегда `403` | В контейнере нет `clients.json` или токен не совпадает. В логах должно быть `Загружено N клиентов` |
| `503 subscription source unavailable` | Нет доступа к `auto.json`. Проверьте `GITHUB_REPO`, `GITHUB_BRANCH`, `CONFIG_PATH`, `GITHUB_TOKEN` или положите `auto.json` в ZIP |
| GitHub API отвечает `401/404` | Неверный токен, репозиторий или путь. Для приватного репозитория нужен `GITHUB_TOKEN` с доступом Contents: Read-only |
| GitHub API отвечает `403 rate limit` | Установите `GITHUB_TOKEN`, чтобы поднять лимит |
| Сборка Docker падает на `COPY` | ZIP собран с вложенной папкой. Пересоберите архив из содержимого `netrun_worker/` |
| Сервис «спит» | Это нормально для Free Tier: первый запрос после 15 минут простоя разбудит контейнер за несколько секунд |
| Токен виден в логах Netrun | Мы отключили access-log gunicorn, но платформа может логировать URL запроса. Не публикуйте логи и используйте HTTPS |

## 9. Ограничения бесплатного тарифа

- 1 проект;
- 256 МБ RAM, 0.25 vCPU, 2 ГБ диска;
- сайт засыпает через 15 минут без запросов и просыпается при обращении;
- бесплатный поддомен `*.netrun.io`, свой домен — только на Pro;
- никаких VPN/прокси-серверов: этот проект — только API подписок.

Этого достаточно для небольшого числа клиентов: воркер хранит только JSON, не держит базу и не проксирует трафик.
