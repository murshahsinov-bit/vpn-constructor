# Happ, INCY и v2RayTun: подписка, заголовки и импорт

Воркер отдаёт один и тот же набор серверов в нескольких форматах:

| Маршрут | Формат | Кому |
|---|---|---|
| `/sub/auto.json` | полный Xray JSON | Happ, INCY, v2RayTun |
| `/sub/whitelist.json` | Xray JSON с цепочкой RU relay | Happ, INCY, v2RayTun |
| `/sub/auto.txt` | share-ссылки с фрагментацией INCY | INCY |
| `/sub/auto_happ.txt` | share-ссылки с фрагментацией Happ | Happ |
| `/sub/whitelist.txt` | whitelist-ссылки INCY | INCY |
| `/sub/whitelist_happ.txt` | whitelist-ссылки Happ | Happ |
| `/sub/webrtc.txt` | инструкция + SOCKS5 | ручной WebRTC-профиль |

Любой маршрут требует персональный `?token=<TOKEN>`. Без токена или после
срока действия возвращается `403 forbidden`.

---

## 1. HTTP-заголовки подписки

Воркер добавляет заголовки к JSON и TXT-ответам. Клиент читает их при
каждом обновлении подписки.

| Заголовок | Happ | INCY | Что делает |
|---|---|---|---|
| `profile-title` | да | да | имя подписки, максимум 25 символов |
| `profile-update-interval` | да | да | автообновление в часах (`1`) |
| `subscription-userinfo` | да | да | трафик и дата окончания |
| `profile-web-page-url` | да | да | кнопка «сайт» / тариф |
| `support-url` | да | да | кнопка поддержки в Telegram |
| `hide-url` | да | — | скрывает URL в «Поделиться» (Happ) |
| `subscription-always-hwid-enable` | да | — | HWID нельзя отключить в настройках |
| `no-limit-xhttp-enabled` | да | — | снимает лимит RAM для XHTTP (Happ iOS) |
| `sub-expire` | да | — | включает баннер окончания подписки |
| `sub-expire-button-link` | да | — | ссылка кнопки «Продлить» |
| `announce` | да | да | текст объявления, можно в base64 |

Пример реального ответа:

```http
HTTP/2 200
content-type: application/json
profile-title: VPN Constructor
profile-update-interval: 1
subscription-userinfo: upload=0; download=0; total=107374182400; expire=1796687999
hide-url: 1
subscription-always-hwid-enable: 1
no-limit-xhttp-enabled: 1
```

### Важное про `sub-expire`

В актуальной документации Happ `sub-expire` — это **boolean-включатель**,
а не текст:

```http
sub-expire: 1
sub-expire-button-link: https://t.me/your_bot
```

Happ сам показывает локализованное сообщение «Ваша подписка заканчивается
через N д.» за 3 дня до окончания. Поэтому воркер отправляет `sub-expire: 1`
только когда до окончания осталось не больше `SUB_EXPIRE_DAYS` дней.

Текст вида «Подписка истекает 2026-12-07. Продлите вовремя.» передаётся
отдельным заголовком `announce` в base64 — его понимают и Happ, и INCY.
Так кириллица не ломает HTTP-заголовки (в них допустим только latin-1).

### `subscription-userinfo`

```text
upload=0; download=0; total=107374182400; expire=<unix_timestamp>
```

- `total` — 100 GiB по умолчанию (`SUBSCRIPTION_TOTAL_BYTES`);
- `expire` — конец дня `expires_at` из `clients.json` в Unix-секундах;
- если дата в `clients.json` некорректна, поле `expire` не отправляется.

### `profile-title`

Ограничение — 25 символов. Если задать кириллическое имя, воркер
автоматически кодирует его как `base64:<UTF-8>`, потому что Happ и INCY
поддерживают такой формат.

---

## 2. Два профиля на один сервер

Для каждого живого сервера в `auto.json` может быть два outbound:

| Профиль | Транспорт | Для кого |
|---|---|---|
| `proxy-xhttp-N` | XHTTP + Reality или XHTTP + TLS (Cloudflare) | **Android**, десктоп |
| `proxy-tcp-N` | TCP + Reality/TLS + Vision + фрагментация | **iOS**, старые ядра |

Номер `N` общий: `proxy-xhttp-7` и `proxy-tcp-7` — один и тот же сервер.
Если один профиль не подключается, переключитесь на второй с тем же номером.

| Клиент | Приоритет | Если не работает |
|---|---|---|
| Happ Android | `proxy-xhttp-*` | `proxy-tcp-*` |
| **Happ iOS** | **`proxy-tcp-*`** | `proxy-xhttp-*`, если ядро свежее |
| INCY Android | `proxy-xhttp-*` | `proxy-tcp-*` |
| **INCY iOS** | **`proxy-tcp-*`** | `proxy-xhttp-*` |
| v2RayTun Android | `proxy-xhttp-*` | `proxy-tcp-*` |
| v2RayTun iOS | `proxy-tcp-*` | `proxy-xhttp-*` |

Причины:

- XHTTP+Reality маскирует трафик под обычный HTTP/2 и лучше проходит ТСПУ;
- XHTTP+Reality **не поддерживается на iOS** в Happ — там нужен TCP+Vision;
- Vision + фрагментация ClientHello надёжнее на старых Network Extension;
- `fingerprint: firefox` стоит во всех Reality/TLS-профилях.

Пара `proxy-xhttp-N` + `proxy-tcp-N` появляется только тогда, когда
агрегатор реально проверил оба транспорта на одном и том же сервере.
Если источник опубликовал только TCP, второго профиля не будет: это не
ошибка формата, а отсутствие подтверждённого транспорта. Docs-таблица
выше описывает приоритеты для случая, когда пара есть.

---

## 3. Фрагментация в TXT-ссылках

У INCY и Happ разный синтаксис, поэтому файлов два.

### INCY

```text
/sub/auto.txt
/sub/whitelist.txt
```

К TCP-ссылкам добавляются query-параметры:

```text
&fragmentPackets=tlshello&fragmentLength=100-200&fragmentInterval=10-20
```

Полный пример:

```text
vless://UUID@HOST:443?security=reality&sni=example.com&type=tcp&flow=xtls-rprx-vision&pbk=...&sid=...&fragmentPackets=tlshello&fragmentLength=100-200&fragmentInterval=10-20#🇩🇪 Berlin
```

### Happ

```text
/sub/auto_happ.txt
/sub/whitelist_happ.txt
```

К TCP-ссылкам добавляется один параметр:

```text
&fragment=100-200,10-20,tlshello
```

Формат Happ: `fragment=length,interval,packets[,maxSplit]`.

### Что важно

- фрагментация добавляется **только TCP/raw-ссылкам**;
- XHTTP-ссылки не меняются: у них уже есть свои `path`, `host`, `mode`;
- если источник уже прислал `fragment`, `fragmentPackets`,
  `fragmentLength`, `fragmentInterval` или `fragmentMaxSplit`, они
  заменяются, а не дублируются;
- имена серверов и флаги стран сохраняются в обоих файлах.

---

## 4. Импорт в Happ

### Android

1. Установите Happ из Google Play или с официального сайта.
2. На главном экране нажмите **«+»**.
3. Выберите **«Добавить подписку»**.
4. Вставьте:
   ```text
   https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>
   ```
   Это предпочтительный вариант: Happ получает полный Xray-конфиг
   с двумя профилями на сервер.
5. Дождитесь загрузки и выберите `proxy-xhttp-1`.
6. Если не подключается — `proxy-tcp-1`.

Если Happ не понимает JSON-подписку в вашей версии, используйте
`/sub/auto_happ.txt?token=<TOKEN>` — там те же серверы share-ссылками
с правильной фрагментацией Happ.

### iOS

1. Установите Happ из App Store.
2. **«+»** → **«Подписка»**.
3. Вставьте `/sub/auto.json?token=<TOKEN>`.
4. Разрешите добавление VPN-конфигурации (Face ID / Touch ID).
5. Выберите **`proxy-tcp-1`** (Vision + fragment).
6. Включите подключение.

На iOS не выбирайте `proxy-xhttp-*`: XHTTP+Reality там не работает.
Если хочется share-ссылки, используйте `/sub/auto_happ.txt?token=<TOKEN>`.

---

## 5. Импорт в INCY

### Android

1. Установите INCY.
2. На главном экране нажмите **«+»**.
3. Выберите **«Добавить подписку»** / **«Импорт из ссылки»**.
4. Вставьте:
   ```text
   https://vpn-auth.de1.netrun.io/sub/auto.txt?token=<TOKEN>
   ```
   INCY отлично работает с share-ссылками и читает
   `fragmentPackets/fragmentLength/fragmentInterval` прямо из URL.
5. Сохраните и выберите `proxy-xhttp-1`.
6. Нажмите **«Подключить»**.

JSON-вариант `/sub/auto.json?token=<TOKEN>` тоже поддерживается.

### iOS

1. Установите INCY из App Store.
2. **«+»** → **«Подписка»**.
3. Вставьте `/sub/auto.txt?token=<TOKEN>`.
4. Разрешите добавление VPN-конфигурации.
5. Выберите `proxy-tcp-1`.

Если импорт по ссылке не появляется, скопируйте ссылку и используйте
**«Импорт из буфера обмена»**.

---

## 6. v2RayTun

1. **«+»** → **«Импорт подписки»**.
2. Вставьте `/sub/auto.json?token=<TOKEN>` (или TXT-вариант).
3. На Android выберите `proxy-xhttp-1`, на iOS — `proxy-tcp-1`.

---

## 7. Whitelist-подписка и RU relay

Ссылки:

```text
https://vpn-auth.de1.netrun.io/sub/whitelist.json?token=<TOKEN>
https://vpn-auth.de1.netrun.io/sub/whitelist.txt?token=<TOKEN>
https://vpn-auth.de1.netrun.io/sub/whitelist_happ.txt?token=<TOKEN>
```

Схема:

```text
телефон → RU VPS (разрешённый IP/SNI) → зарубежный VPS → интернет
```

В `whitelist.json`:

- первый outbound — **целевой** зарубежный сервер, а не relay;
- у каждого `wl-proxy-*` есть
  `streamSettings.sockopt.dialerProxy = "wl-relay"`;
- `wl-relay` идёт последним среди proxy-outbound и напрямую, без `sockopt`;
- `geoip:ru` и `geosite:category-ru` отсутствуют полностью.

Порядок outbound важен: первый outbound становится default. Если бы
первым был `wl-relay`, клиент пустил бы весь трафик в RU VPS без второго
плеча. Поэтому цепочка задаётся через `dialerProxy`, а не порядком.

> **Важно.** В TXT-варианте (`/sub/whitelist.txt` и
> `/sub/whitelist_happ.txt`) цепочку `dialerProxy` выразить нельзя: это
> просто список share-ссылок, где первой идёт RU relay, а затем целевые
> серверы. Для настоящей цепочки «клиент → RU relay → зарубежный VPS»
> используйте **`whitelist.json`**.

### Требования к RU relay

- Timeweb, VDSina или Selectel (не Yandex Cloud: его AS блокируется);
- VLESS + Reality + Vision;
- SNI `gosuslugi.ru` или другой домен из белого списка оператора;
- порт 443.

### Как включить

1. Поднимите Xray на RU VPS.
2. Соберите ссылку:
   ```text
   vless://<UUID>@<RU_IP>:443?security=reality&sni=gosuslugi.ru&pbk=<PUBLIC_KEY>&sid=<SHORT_ID>&type=tcp&flow=xtls-rprx-vision#RU-Relay
   ```
3. В GitHub → **Settings → Secrets and variables → Actions** создайте
   секрет `RU_RELAY_LINK`.
4. Запустите workflow. В логе будет:
   ```text
   Whitelist: используется явный RU relay <IP>:443 (SNI=gosuslugi.ru)
   💾 web/subscriptions/whitelist.json: 10 серверов, 10 цепочек wl-relay → зарубежный VPS
   ```

### Автоматический fallback

Если `RU_RELAY_LINK` не задан, агрегатор ищет в `whitelist_records` узел:

- из источника `igareck_*`;
- с SNI из `preferred_sni` (`gosuslugi.ru`);
- прошедший реальную проверку `passed`/`semi-passed`;
- не из Yandex Cloud.

Для этого в `aggregator/config.yaml`:

```yaml
relay:
  preferred_sni:
    - "gosuslugi.ru"
  require_preferred_sni: true
  allow_tcp_fallback: false
```

`require_preferred_sni: true` означает: узел с другим SNI не будет выбран
входом цепочки. Если подходящего relay нет, `whitelist.json` и
`whitelist_all*.txt` **не перезаписываются** — лучше старый рабочий
конфиг, чем цепочка без входа.

---

## 8. Cloudflare CDN и XHTTP

Для сервера за Cloudflare используется `proxy-xhttp-*` с
`security: "tls"`. В JSON сохраняются:

- `xhttpSettings.host` — домен CDN (например, `web-tomcat.pages.dev`);
- `xhttpSettings.path` — путь из share-ссылки;
- `xhttpSettings.mode: "stream-one"`;
- `tlsSettings.serverName` — SNI CDN;
- `tlsSettings.fingerprint: "firefox"`.

Клиент видит только edge-IP Cloudflare, а не адрес VPS. Такой профиль
работает в Happ Android и INCY. На Happ iOS используйте парный
`proxy-tcp-*`.

---

## 9. Yandex Cloud Functions (`proxy-ycf-1`)

`functions.yandexcloud.net` часто в белых списках операторов. Если у вас
есть SOCKS5-релей внутри Yandex Cloud Functions, задайте секрет:

```text
YANDEX_FUNCTIONS_SOCKS=socks5://user:password@host:1080
```

Агрегатор добавит в `auto.json` **дополнительный** outbound
`proxy-ycf-1`. Reality-профили при этом не заменяются. YCF не даёт
гарантии скорости и не подходит для видео — это резерв, когда основные
профили недоступны.

---

## 10. WebRTC-туннель (`/sub/webrtc.txt`)

Экспериментальный ручной fallback. Автоматической подписки нет.

```text
https://vpn-auth.de1.netrun.io/sub/webrtc.txt?token=<TOKEN>
```

Маршрут отдаёт инструкцию и SOCKS5-адрес из `WEBRTC_SOCKS5`:

```text
WEBRTC_SOCKS5=socks5://user:pass@host:1080
```

Схема:

1. На зарубежном VPS поднимите WebRTC-бридж (TURN/STUN + DataChannel).
2. Запустите WebRTC-клиент, который отдаёт локальный SOCKS5.
3. Создайте комнату в Телемост/VK Calls и подключите клиент и бридж.
4. В Happ/INCY добавьте SOCKS5-профиль вручную.
5. Проверьте: `curl https://ipinfo.io/ip` показывает зарубежный IP.

Ограничения: скорость зависит от медиа-сервиса и NAT, нет health-check и
автопереключения. Только аварийный вариант.

---

## 11. Проверка заголовков

### PowerShell

```powershell
$url = "https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>"
$r = Invoke-WebRequest $url -UseBasicParsing

$r.StatusCode
$r.Headers['Content-Type']
$r.Headers['profile-title']
$r.Headers['profile-update-interval']
$r.Headers['subscription-userinfo']
$r.Headers['hide-url']
$r.Headers['subscription-always-hwid-enable']
$r.Headers['no-limit-xhttp-enabled']
```

Ожидаемо:

```text
200
application/json
VPN Constructor
1
upload=0; download=0; total=107374182400; expire=1796687999
1
1
1
```

### curl

```bash
curl -sS -D - -o /dev/null \
  "https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>"
```

Проверка TXT:

```bash
curl -sS "https://vpn-auth.de1.netrun.io/sub/auto.txt?token=<TOKEN>" | head -n 2
curl -sS "https://vpn-auth.de1.netrun.io/sub/auto_happ.txt?token=<TOKEN>" | head -n 2
```

В INCY-файле должны быть `fragmentPackets=tlshello`,
`fragmentLength=100-200`, `fragmentInterval=10-20`.
В Happ-файле — `fragment=100-200,10-20,tlshello`.

Проверка whitelist-цепочки:

```powershell
$wl = (Invoke-WebRequest "https://vpn-auth.de1.netrun.io/sub/whitelist.json?token=<TOKEN>" -UseBasicParsing).Content | ConvertFrom-Json

$wl.outbounds | Select-Object -First 3 tag, protocol
$wl.outbounds | Where-Object tag -eq 'wl-relay' |
    Select-Object tag, @{n='sni';e={$_.streamSettings.realitySettings.serverName}}
$wl.outbounds | Where-Object { $_.streamSettings.sockopt.dialerProxy -eq 'wl-relay' } |
    Select-Object tag, @{n='dialerProxy';e={$_.streamSettings.sockopt.dialerProxy}}
```

Ожидаемо:

- первый outbound — `wl-proxy-*`;
- `wl-relay` присутствует и имеет SNI `gosuslugi.ru`;
- все `wl-proxy-*` имеют `dialerProxy = wl-relay`;
- в JSON нет `geoip:ru` и `geosite:category-ru`.

Проверка профилей:

```powershell
$cfg = (Invoke-WebRequest "https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>" -UseBasicParsing).Content | ConvertFrom-Json
$cfg.outbounds | Where-Object protocol -eq 'vless' |
    Select-Object tag,
                  @{n='network';e={$_.streamSettings.network}},
                  @{n='security';e={$_.streamSettings.security}},
                  @{n='flow';e={$_.settings.vnext[0].users[0].flow}},
                  @{n='fragment';e={$_.fragment.packets}},
                  @{n='fp';e={$_.streamSettings.realitySettings.fingerprint}}
```

Ожидаемо: `proxy-xhttp-N` и `proxy-tcp-N` с одинаковым `N`, у TCP
`flow=xtls-rprx-vision` и `fragment=tlshello`, у всех `fp=firefox`.

---

## 12. Если не подключается

1. **Проверьте срок токена.** Истёкший токен даёт `403 forbidden`.
2. **Попробуйте парный профиль** с тем же номером.
3. **iOS:** только `proxy-tcp-*`, XHTTP+Reality там не работает.
4. **Удалите старый профиль** и импортируйте заново: клиенты кэшируют
   подписку.
5. **Отключите другие VPN/Always-on VPN.**
6. **Смените сеть:** некоторые операторы режут нестандартные порты.
7. **Обновите Happ/INCY:** XHTTP и Vision требуют свежего Xray-core.
8. **Проверьте время на устройстве:** ошибка >2 минут ломает TLS/Reality.
9. **Whitelist:** убедитесь, что в `whitelist.json` есть `wl-relay`,
   а у целей — `dialerProxy: "wl-relay"`.
10. **Заголовки не видны:** проверьте, что запрос идёт на воркер, а не на
    GitHub Pages. GitHub Pages не отдаёт динамические заголовки и не
    проверяет токены.
