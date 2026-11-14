# ShieldVPN

Брендированный VPN-клиент на базе **v2rayNG 2.4.0** (Xray-core), заточенный под нашу
подписку `vpn-auth.de1.netrun.io`. Пользователь открывает приложение → подписка
скачивается сама → первый сервер подключается сам → при сбое автоматически
пробуются следующие серверы.

---

## 1. Почему база — v2rayNG, а не Xray-master и не HiddifyNG

| Проект | Что умеет | Почему не взят как основа |
|---|---|---|
| `Xray-master` | TUN + hev-socks5-tunnel, `XrayCore.aar`, Room, минимальный XML-UI | Нет менеджера подписок, нет импорта share-link списков, нет AAR/JNI в репозитории; UI пришлось бы писать с нуля |
| `HiddifyNG-master` | Форк v2rayNG, но версии 1.8.17 | Deprecated, **нет XHTTP**, старый `libv2ray.aar` с API `Libv2ray` (несовместим с `CoreController`) |
| **`v2rayNG-master` 2.4.0** | XHTTP (`mode`, `extra`, `pcs`), Reality, VLESS, TCP/TLS, VLESS-fragment, подписки Xray JSON + TXT/share-links, Compose, `CoreController` | — |

Итог: **не клеим «франкенштейна»**, а кастомизируем v2rayNG. Из Xray-master взята
только идея «одна кнопка + TUN через hev», из HiddifyNG — ничего (его AAR не
подходит по API).

`ShieldVPN/` — это самостоятельная копия `v2rayNG-master/V2rayNG`, оригинал не тронут.

---

## 2. Что изменено / добавлено

### Новые файлы

| Файл | Назначение |
|---|---|
| `app/src/main/java/com/v2ray/ang/shield/ShieldConfig.kt` | Единственное место с URL подписки, таймаутами и ключами настроек |
| `app/src/main/java/com/v2ray/ang/shield/ShieldPrefs.kt` | Флаги «первый запуск» и «автоподключение» в MMKV |
| `app/src/main/java/com/v2ray/ang/shield/ShieldRepository.kt` | Импорт/обновление подписки, список серверов, SOCKS5 health-check |
| `app/src/main/java/com/v2ray/ang/shield/ShieldVpnController.kt` | Автоподключение, перебор серверов, состояния UI |
| `app/src/main/java/com/v2ray/ang/shield/ShieldViewModel.kt` | Живёт дольше Activity (переживает поворот экрана) |
| `app/src/main/java/com/v2ray/ang/ui/shield/ShieldActivity.kt` | Минималистичный Compose-экран: большая кнопка, статус, выбор сервера |
| `app/libs/libv2ray.aar` | Xray-core (AndroidLibXrayLite v26.11.9), скачивается скриптом |
| `app/libs/<abi>/libhev-socks5-tunnel.so` | hev-socks5-tunnel 2.19.3: из официального AAR извлекаются только `.so` |
| `scripts/fetch-libs.sh` / `.ps1` | Загрузка AAR Xray и распаковка hev `.so` (сам hev-AAR в сборку не попадает) |
| `scripts/build-release.ps1` | Сборка одной командой на Windows |
| `scripts/generate_icons.py` | Генерация иконки-щита во все mipmap-плотности |
| `.github/workflows/build-shieldvpn.yml` | CI-сборка APK |

### Изменённые файлы

| Файл | Что изменено |
|---|---|
| `app/build.gradle.kts` | `applicationId = io.netrun.shieldvpn`, `versionName = 1.0.0`, universal APK вместо ABI-split, release-подпись из `keystore.properties` (иначе debug-ключ), имена файлов `ShieldVPN_*` |
| `settings.gradle.kts` | `rootProject.name = "ShieldVPN"` |
| `app/src/main/AndroidManifest.xml` | Лаунчером стала `.ui.shield.ShieldActivity`; `MainActivity` остался как «дополнительные настройки» без `MAIN/LAUNCHER` |
| `app/src/main/res/values/strings.xml` | `app_name = ShieldVPN` + строки ShieldVPN-экрана |
| `app/src/main/res/values/ic_launcher_background.xml`, `ic_banner_background.xml` | Тёмно-синий фон иконки |
| `app/src/main/res/mipmap-*/ic_launcher*.png` | Новый щит |
| `app/src/main/java/com/v2ray/ang/util/Utils.kt` | `isXray()` всегда `true` (мы действительно поставляем Xray-core; старая проверка была завязана на `applicationId.startsWith("com.v2ray.ang")`) |
| `app/src/main/java/com/v2ray/ang/handler/SettingsManager.kt` | `isUsingHevTun()` возвращает `false` на Android < 10: там VPN поднимается встроенным `tun`-инбаундом Xray, а не hev (его `.so` собран под API 29) |
| `app/src/{fdroid,dev,pre_release}/res/values/strings.xml` | Имя приложения без v2rayNG |
| `app/src/main/res/values-*/strings.xml` | Во всех локалях `app_name`/`app_widget_name`/`app_tile_name` заменены на ShieldVPN (иначе на телефоне с русской локалью ярлык назывался бы v2rayNG) |

---

## 3. Как это работает

```
ShieldActivity
   └── ShieldViewModel
         └── ShieldVpnController
               ├── ShieldRepository.ensureSubscription()   // IO: HTTP + MMKV
               │     └── AngConfigManager.updateConfigViaSub()
               │           └── VlessFmt / FmtBase  ->  ProfileItem
               ├── LauncherManager.startService(ctx, guid)
               │     └── CoreVpnService (:daemon)
               │           └── CoreServiceManager.startCoreLoop()
               │                 └── Libv2ray.newCoreController(...).startLoop(json, tunFd)
               └── ShieldRepository.probeSocks(10808)      // реальный SOCKS5 CONNECT
```

1. **Первый запуск.** `ShieldRepository.ensureSubscription()` создаёт подписку с
   фиксированным ID `shield_default_subscription`, скачивает её и раскладывает
   share-ссылки в `ProfileItem` (VLESS/Reality/XHTTP/TCP+TLS).
2. **Автоподключение.** `ShieldActivity.onStart()` → `requestConnect()` →
   `VpnService.prepare()` (системный диалог, его обойти нельзя) → `connect()`.
3. **Выбор сервера.** При первом запуске (после установки или обновления
   подписки) `ShieldRepository.selectFastestServer()` параллельно (12 потоков,
   TCP-таймаут 2,5 с, первые 24 сервера) замеряет задержку до `server:port` и
   выбирает самый быстрый. Дальше берётся выбранный ранее, иначе первый из
   подписки.
4. **Health-check.** После `MSG_STATE_START_SUCCESS` приложение открывает SOCKS5
   к `127.0.0.1:10808` и делает `CONNECT www.gstatic.com:443`. Успешный ответ =
   Reality/XHTTP-хендшейк прошёл и трафик реально ходит. До 3 попыток по 6 с.
5. **Fallback.** Если старт не удался, истёк таймаут 25 с или health-check не
   прошёл: `stopService()` → следующий сервер → повтор. Максимум 8 серверов.
6. **Обновление подписки.** Каждые 6 часов через `SubscriptionUpdater`
   (WorkManager), плюс кнопка «Обновить подписку» в UI.

---

## 4. Сборка

### 4.1 Требования

- **JDK 21** (`JAVA_HOME`), Android SDK с `platforms;android-37.0` и
  `build-tools;37.0.0` (`ANDROID_HOME` или `local.properties`).
  В репозитории платформа называется именно `android-37.0` (есть также 37.1/37.2),
  пакета `platforms;android-37` не существует.
- Интернет: Gradle скачает зависимости, скрипт — `libv2ray.aar` (~60 МБ) и
  hev-AAR (~0,6 МБ, из него берутся только `.so`).

**Минимальная версия Android — 7.0 (API 24).** На Android 10+ VPN поднимается
через hev-socks5-tunnel, на Android 7–9 — встроенным `tun`-инбаундом Xray
(см. `SettingsManager.isUsingHevTun()`). Это сделано потому, что официальный
`hev-socks5-tunnel.aar` объявляет `minSdk 29`; в APK попадают только его
нативные библиотеки, а не манифест.

### 4.2 Windows (одна команда)

```powershell
cd ShieldVPN
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1
```

или вручную:

```powershell
cd ShieldVPN
powershell -ExecutionPolicy Bypass -File .\scripts\fetch-libs.ps1
.\gradlew.bat assemblePlaystoreRelease
```

### 4.3 Linux / macOS

```bash
cd ShieldVPN
bash scripts/fetch-libs.sh
./gradlew assemblePlaystoreRelease
```

### 4.4 Где APK

```
ShieldVPN/app/build/outputs/apk/playstore/release/ShieldVPN_1.0.0_universal.apk
```

Проверенный образец сборки: 45 272 700 байт (~43,2 МБ), SHA-256
`EC2529C51001AF7098D60A54BB338DED9C9F211D545C5F8B0BDD8E91261B740B`,
`versionCode=1`, `applicationId=io.netrun.shieldvpn`, `minSdk=24`,
`targetSdk=37`, внутри `lib/arm64-v8a` и `lib/armeabi-v7a` с `libgojni.so`
и `libhev-socks5-tunnel.so`.

Установка:

```bash
adb install -r ShieldVPN/app/build/outputs/apk/playstore/release/ShieldVPN_1.0.0_universal.apk
```

Уменьшенная сборка только под arm64:

```bash
./gradlew assemblePlaystoreRelease -PABI_FILTERS=arm64-v8a
```

### 4.5 Release-подпись

Создайте `ShieldVPN/keystore.properties`:

```properties
storeFile=shield-release.jks
storePassword=...
keyAlias=shieldvpn
keyPassword=...
```

Файл `shield-release.jks` положите в `ShieldVPN/`. Без `keystore.properties`
release-сборка подписывается debug-ключом — APK устанавливается, но не годится
для Google Play.

### 4.6 CI

`.github/workflows/build-shieldvpn.yml` собирает APK на `ubuntu-latest` по
`workflow_dispatch` или push в `main/master` при изменениях в `ShieldVPN/**`.
Готовый файл лежит в артефакте **ShieldVPN-apk**.

---

## 5. Что менять под себя

| Задача | Файл |
|---|---|
| Ссылка подписки / токен | `shield/ShieldConfig.kt` → `SUBSCRIPTION_URL` |
| Таймауты и число попыток fallback | `shield/ShieldConfig.kt` |
| Тексты экрана | `res/values/strings.xml` (`shield_*`) |
| Цвета экрана | `ui/shield/ShieldActivity.kt` (константы вверху файла) |
| Иконка | `python scripts/generate_icons.py` |
| Версия приложения | `app/build.gradle.kts` → `versionCode` / `versionName` |

### Форматы подписки

- `https://vpn-auth.de1.netrun.io/sub/auto_happ.txt?token=...` — TXT со
  share-ссылками (используется по умолчанию: каждая ссылка = отдельный сервер,
  а значит работает fallback).
- `/sub/auto.json` — один Xray-JSON. v2rayNG импортирует его как **один**
  custom-профиль, поэтому fallback по серверам внутри него не работает.

---

## 6. Известные ограничения

- `fragment=100-200,10-20,tlshello` из Happ-подписки v2rayNG **не разбирает**
  (в `fmt/*` нет обработки `fragment`); параметр просто игнорируется. Reality
  при этом работает, но без TLS-фрагментации.
- Системный диалог `VpnService.prepare()` показывается всегда при первом
  подключении — это требование Android, обойти его нельзя.
- На Android 7–9 (`API < 29`) hev-socks5-tunnel не используется: VPN там
  поднимает сам Xray-core своим `tun`-инбаундом. На Android 10+ работает hev.
- `MainActivity` (полный UI v2rayNG) доступен по кнопке «Дополнительные
  настройки»; при желании её можно убрать из `ShieldActivity`.
- В APK попадают только `arm64-v8a` и `armeabi-v7a` (универсальный `.apk`);
  для эмулятора собирайте с `-PABI_FILTERS=arm64-v8a;x86_64`.
