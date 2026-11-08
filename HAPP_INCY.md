# Happ, INCY и v2RayTun: импорт подписки

Подписка отдаёт полный Xray-конфиг:

- `Content-Type: application/json`;
- до 30 серверов в `auto.json`, отсортированных по задержке;
- у каждого сервера может быть **два профиля**:
  - `proxy-xhttp-N` — XHTTP + Reality (или XHTTP + TLS для Cloudflare CDN),
    основной профиль для Android и десктопа;
  - `proxy-tcp-N` — TCP + Reality + Vision + фрагментация TLS ClientHello,
    резервный профиль для iOS и старых ядер;
- `fingerprint: "firefox"` во всех Reality/TLS-профилях;
- `fragment` только у TCP-профилей;
- без `ws`, `mux`, `sockopt` (кроме осознанной whitelist-цепочки),
  `balancers`, `burstObservatory`, `geoip:ru`, `geosite:category-ru`.

В `whitelist.json` — до 10 зарубежных серверов из auto, каждый подключён
через цепочку:

```text
клиент → RU relay (Timeweb/VDSina/Selectel, SNI=gosuslugi.ru) → зарубежный VPS
```

В JSON это выглядит так: у каждого `wl-proxy-*` есть
`streamSettings.sockopt.dialerProxy = "wl-relay"`, а сам `wl-relay` идёт
напрямую. Первым outbound остаётся целевой сервер, поэтому Xray не пускает
трафик напрямую в RU relay без второго плеча.

Ссылка выглядит так:

```text
https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>
```

`<TOKEN>` — персональный токен клиента. Не публикуйте его и не пересылайте
в открытых чатах: по нему любой получит вашу подписку.

---

## Какой профиль выбирать

| Клиент | Приоритет | Если не работает |
|---|---|---|
| Happ Android | `proxy-xhttp-*` (XHTTP + Reality) | `proxy-tcp-*` (Vision + fragment) |
| Happ iOS | `proxy-tcp-*` (Vision + fragment) | `proxy-xhttp-*`, если ядро свежее |
| INCY Android | `proxy-xhttp-*` | `proxy-tcp-*` |
| INCY iOS | `proxy-tcp-*` | `proxy-xhttp-*` |
| v2RayTun Android | `proxy-xhttp-*` | `proxy-tcp-*` |
| v2RayTun iOS | `proxy-tcp-*` | `proxy-xhttp-*` |

Почему так:

- XHTTP маскирует соединение под обычный HTTP/2-трафик и лучше проходит
  там, где ТСПУ режет нестандартные TLS-потоки.
- Vision + фрагментация ClientHello надёжнее на iOS: старые Network
  Extension-ядра не всегда понимают XHTTP.
- Номер `N` общий для пары: `proxy-xhttp-7` и `proxy-tcp-7` — один и тот же
  сервер. Если один профиль не подключается, переключитесь на второй с тем
  же номером.

---

## Happ

### Android

1. Установите Happ из Google Play или с официального сайта.
2. Откройте приложение и нажмите **«+»** на главном экране.
3. Выберите **«Добавить подписку»** (может называться «Импорт по ссылке»).
4. Вставьте ссылку `https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>`.
5. Нажмите **«Добавить»** и дождитесь загрузки профиля.
6. В списке серверов выберите `proxy-xhttp-1` (лучший по задержке).
7. Нажмите большую кнопку подключения и разрешите VPN в системном диалоге.
8. Если `proxy-xhttp-1` не подключается, выберите `proxy-tcp-1`.

### iOS

1. Установите Happ из App Store.
2. Нажмите **«+»** → **«Подписка»**.
3. Вставьте ссылку с токеном и подтвердите.
4. Разрешите добавление VPN-конфигурации (Face ID / Touch ID / пароль).
5. Выберите `proxy-tcp-1` (Vision + fragment) — это самый совместимый
   профиль для iOS.
6. Включите переключатель подключения.

Если Happ предлагает только один профиль на сервер, значит сервер
поддерживает только TCP или только XHTTP. Это нормально: номер `N`
по-прежнему соответствует месту в топе.

---

## INCY

### Android

1. Установите INCY.
2. На главном экране нажмите **«+»**.
3. Выберите **«Добавить подписку»** / **«Импорт из ссылки»**.
4. Вставьте ссылку с токеном.
5. Сохраните и выберите `proxy-xhttp-1`.
6. Нажмите **«Подключить»** и подтвердите запрос на VPN.

### iOS

1. Установите INCY из App Store.
2. Нажмите **«+»** → **«Подписка»**.
3. Вставьте ссылку с токеном.
4. Разрешите добавление VPN-конфигурации.
5. Выберите `proxy-tcp-1` и подключитесь.

Если INCY не показывает импорт по ссылке, скопируйте ссылку в буфер обмена
и используйте пункт **«Импорт из буфера обмена»**.

---

## v2RayTun

1. Установите v2RayTun (Android/iOS).
2. Нажмите **«+»** → **«Импорт подписки»**.
3. Вставьте ссылку с токеном.
4. На Android выберите `proxy-xhttp-1`, на iOS — `proxy-tcp-1`.
5. Подключитесь и разрешите VPN.

---

## Whitelist-подписка и RU relay

Ссылка:

```text
https://vpn-auth.de1.netrun.io/sub/whitelist.json?token=<TOKEN>
```

Этот профиль нужен там, где оператор блокирует всё, кроме «белых списков»
(госуслуги, банки, Яндекс, VK). Схема:

```text
телефон → RU VPS (разрешённый IP/SNI) → зарубежный VPS → интернет
```

Требования к RU relay:

- Timeweb, VDSina или Selectel (не Yandex Cloud: его AS блокируется);
- VLESS + Reality + Vision;
- SNI `gosuslugi.ru` или другой домен из белого списка оператора;
- порт 443.

Как включить:

1. Поднимите Xray/sing-box на RU VPS.
2. Соберите share-ссылку вида:

   ```text
   vless://<UUID>@<RU_IP>:443?security=reality&sni=gosuslugi.ru&pbk=<PUBLIC_KEY>&sid=<SHORT_ID>&type=tcp&flow=xtls-rprx-vision#RU-Relay
   ```

3. В GitHub → **Settings → Secrets and variables → Actions** создайте
   секрет `RU_RELAY_LINK` с этой ссылкой.
4. Запустите workflow вручную. В логе будет:

   ```text
   Whitelist: используется явный RU relay <IP>:443 (SNI=gosuslugi.ru)
   💾 web/subscriptions/whitelist.json: 10 серверов, 10 цепочек wl-relay → зарубежный VPS
   ```

5. Импортируйте `whitelist.json` в Happ/INCY и выберите `wl-proxy-tcp-1`
   (или `wl-proxy-xhttp-1`, если сервер поддерживает XHTTP).

Если `RU_RELAY_LINK` не задан, пайплайн попробует выбрать живой
igareck-узел с подходящим SNI. Если и его нет, `whitelist.json` **не
перезаписывается** — лучше старый рабочий конфиг, чем цепочка без входа.

---

## Cloudflare CDN и XHTTP

Если сервер опубликован за Cloudflare, используйте профиль `proxy-xhttp-*`
с `security: "tls"`. В нём сохраняются:

- `xhttpSettings.host` — домен CDN;
- `xhttpSettings.path` — путь из share-ссылки;
- `xhttpSettings.mode: "stream-one"`;
- `tlsSettings.serverName` — SNI.

Такой профиль сложнее заблокировать по IP: клиент видит только edge-IP
Cloudflare, а не адрес вашего VPS.

---

## Yandex Cloud Functions (экспериментально)

`functions.yandexcloud.net` часто находится в белых списках операторов.
Если у вас есть SOCKS5-релей, поднятый за Yandex Cloud Functions, задайте
секрет:

```text
YANDEX_FUNCTIONS_SOCKS=socks5://user:password@host:1080
```

Пайплайн добавит профиль `proxy-ycf-1` в `auto.json`. Это дополнительный
профиль, а не замена Reality: YCF не даёт гарантии скорости и не подходит
для видео. Используйте его как резерв, когда основные профили недоступны.

---

## WebRTC-туннель (крайний случай)

Это ручной fallback, автоматической подписки для него нет. Идея: поднять
WebRTC DataChannel через российский сервис, который не блокируется
(Телемост, VK Calls), и прогнать через него трафик до зарубежного бриджа.

Общая схема:

1. На зарубежном VPS поднимите WebRTC-бридж (UDP/TCP-порт, TURN/STUN).
2. На устройстве установите WebRTC-клиент, который умеет поднимать
   локальный SOCKS5/HTTP-прокси.
3. Создайте комнату в Телемост или VK Calls, подключите к ней клиент и
   бридж как участников.
4. В Happ/INCY укажите локальный SOCKS5-прокси клиента как отдельный
   профиль (не через подписку).
5. Проверьте, что трафик идёт через бридж: `curl https://ipinfo.io/ip`
   должен показать зарубежный IP.

Ограничения:

- скорость и стабильность зависят от сервиса и NAT;
- нет автопереключения и health-check;
- это обход через разрешённый медиа-сервис, а не полноценный VPN;
- не используйте этот способ для постоянной работы, только как аварийный.

---

## Почему это защищает от ТСПУ

| Метод | Что видит ТСПУ | Почему проходит |
|---|---|---|
| XHTTP + Reality | обычный HTTPS/HTTP-2 к чужому домену | нет характерного VLESS-заголовка, поток похож на браузер |
| TCP + Reality + Vision | TLS к чужому домену | Reality подставляет настоящий сертификат и SNI, Vision убирает TLS-in-TLS |
| Фрагментация ClientHello | несколько мелких TLS-записей | SNI не попадает в первый пакет, SNI-фильтр не срабатывает |
| `fingerprint: firefox` | JA3/JA4 Firefox | ТСПУ не видит отпечаток chrome/safari, который чаще блокируют |
| RU relay | подключение к разрешённому IP | первый прыжок не выглядит как выход за границу |
| Cloudflare CDN | edge-IP Cloudflare | блокировка IP VPS не помогает |
| WebRTC | медиа-трафик Телемоста/VK | сервис разрешён и не похож на VPN |

---

## Если не подключается

1. **Проверьте срок токена.** Истёкший токен возвращает `403 forbidden`.
   Откройте ссылку в браузере: должен скачаться JSON, а не
   `{"error":"forbidden"}`.
2. **Попробуйте парный профиль.** Если не работает `proxy-xhttp-N`,
   выберите `proxy-tcp-N` с тем же номером (и наоборот).
3. **Удалите старый профиль** и импортируйте ссылку заново: Happ и INCY
   кэшируют подписку и могут держать прежний WS+TLS-конфиг.
4. **Отключите другие VPN/Always-on VPN** на время проверки.
5. **Смените сеть.** Некоторые мобильные операторы блокируют нестандартные
   порты. Если сервер слушает не 443, попробуйте Wi-Fi или другого оператора.
6. **Обновите приложение.** XHTTP и Reality Vision требуют свежего
   Xray-core; старые версии Happ/INCY не понимают `flow: xtls-rprx-vision`
   и `xhttpSettings`.
7. **Проверьте время на устройстве.** Ошибка больше 2 минут ломает TLS/Reality.
8. **Для whitelist проверьте relay.** В `whitelist.json` должен быть
   outbound `wl-relay`, а у целевых профилей — `dialerProxy: "wl-relay"`.

## Как проверить ссылку вручную

```powershell
$url = "https://vpn-auth.de1.netrun.io/sub/auto.json?token=<TOKEN>"
$r = Invoke-WebRequest $url -UseBasicParsing
$r.StatusCode
$r.Headers['Content-Type']
$cfg = $r.Content | ConvertFrom-Json
$cfg.outbounds | Where-Object protocol -eq 'vless' |
    Select-Object tag,
                  @{n='network';e={$_.streamSettings.network}},
                  @{n='security';e={$_.streamSettings.security}},
                  @{n='flow';e={$_.settings.vnext[0].users[0].flow}},
                  @{n='fragment';e={$_.fragment.packets}}
```

Ожидаемый результат (первые строки, всего до 60 профилей):

```text
200
application/json
tag             network security flow               fragment
---             ------- -------- ----               --------
proxy-xhttp-1   xhttp   reality
proxy-tcp-1     tcp     reality  xtls-rprx-vision   tlshello
proxy-xhttp-2   xhttp   reality
proxy-tcp-2     tcp     reality  xtls-rprx-vision   tlshello
...
```

Проверка whitelist-цепочки:

```powershell
$wl = (Invoke-WebRequest "https://vpn-auth.de1.netrun.io/sub/whitelist.json?token=<TOKEN>" -UseBasicParsing).Content | ConvertFrom-Json
$wl.outbounds | Where-Object tag -eq 'wl-relay' |
    Select-Object tag, @{n='sni';e={$_.streamSettings.realitySettings.serverName}}
$wl.outbounds | Where-Object { $_.streamSettings.sockopt.dialerProxy -eq 'wl-relay' } |
    Select-Object tag, @{n='dialerProxy';e={$_.streamSettings.sockopt.dialerProxy}}
```

Ожидаемо: `wl-relay` с SNI `gosuslugi.ru` и все `wl-proxy-*` с
`dialerProxy = wl-relay`.
