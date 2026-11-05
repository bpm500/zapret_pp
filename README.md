<div align="center">

<img src="icons/ico.ico" alt="zapret++" width="80" height="80"/>

# zapret++

<a href="https://www.donationalerts.com/r/bpm500" target="_blank">
  <img src="https://img.shields.io/badge/%D0%9F%D0%BE%D0%B4%D0%B4%D0%B5%D1%80%D0%B6%D0%BA%D0%B0_%D0%B0%D0%B2%D1%82%D0%BE%D1%80%D0%B0-DonationAlerts-FF5900?style=for-the-badge&logo=donationalerts&logoColor=white" alt="Поддержка автора DonationAlerts"/>
</a>

<br/>

**GUI-оболочка для Zapret — Discord, YouTube, SoundCloud и другие заблокированные сервисы**

[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/bpm500/zapret_pp)
[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-GUI-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

<br/>

> Форк [ZapretTester](https://github.com/bpm500/ZapretTester).  
> Подключение в один клик, автоматический подбор рабочей стратегии (106+ вариантов), тест конфигов с Multi-ping, встроенный Telegram WebSocket Proxy, поддержка кастомных обоев (фото/GIF/видео), редактор списков IP/SoundCloud и автообновление exe в один клик.

</div>

---

## ⚡ Что такое zapret++?

**zapret++** — это современная GUI-обёртка для [zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) и [tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy), которая превращает запуск `.bat` файлов и прокси в стильный минималистичный интерфейс. Помимо запуска готовых конфигов, программа умеет **сама генерировать и подбирать рабочие стратегии обхода DPI**, предоставляет встроенный WebSocket мост для Telegram, гибкую кастомизацию внешнего вида и автоматическое обновление.

**Ключевые возможности:**
- **Запуск любого `.bat` конфига zapret** одним нажатием (кнопка питания с индикацией: выключено / подключение / активно)
- **Автоматический генератор маршрутов (Create Route)** — расширенная база из **106 реальных DPI-стратегий** с генерацией от 1 до 10 рабочих `.bat` конфигов
- **Умная дедупликация** — автоматическое исключение повторяющихся стратегий и дубликатов в списках
- **Multi-ping по умолчанию** — параллельное тестирование конфигов и создание маршрутов в 3 изолированных слотах
- **Поддержка кастомных обоев (Set as wallpaper)** — установка любых изображений, анимированных GIF и видео без звука на фон приложения с адаптивным масштабированием без искажений
- **Редактор списков (Set IP)** — удобное добавление доменов/IP в `list-general.txt` и кнопка быстрого добавления 27 доменов **SoundCloud** с защитой от дубликатов
- **Встроенный автоапдейтер (Auto-download)** — проверка обновлений и самообновление исполняемого файла в один клик без перехода в браузер
- **Встроенный Telegram WebSocket Bridge Proxy (TG WS Proxy)** во вкладке **Utils** с независимым автозапуском, тестами Cloudflare Proxy / Worker и прямым открытием в Telegram
- **Автозапуск и автоподключение** — независимый старт с Windows и авто-коннект к выбранному конфигу
- **Сворачивание в системный трей** с контекстным меню быстрого управления

---

## 🖥️ Системные требования

| Параметр | Требование |
|---|---|
| ОС | Windows 10 (1903+) / Windows 11 |
| Права | **Администратор** (обязательно для winws.exe) |
| Python | 3.13+ (только для запуска из исходников) |
| Зависимости | PyQt6, psutil, requests, ping3 |

---

## 🚀 Быстрый старт

### Шаг 1 — Скачайте zapret++

Скачайте `zapret++.exe` из раздела **[Releases](https://github.com/bpm500/zapret_pp/releases)**.

### Шаг 2 — Скачайте zapret

Скачайте архив из репозитория **[zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube/releases)**.

### Шаг 3 — Структура папок

Распакуйте архив zapret рядом с программой. Название папки может быть **любым** — программа сама обнаружит папку с `.bat` файлами и `bin\winws.exe`:

```
📁 Любая папка/
├── zapret++.exe                       ← исполняемый файл программы
├── 📁 settings/                        ← папка настроек и обоев (создаётся автоматически)
└── 📁 zapret-discord-youtube-x.x.x/    ← папка zapret (имя любое)
    ├── bin/
    │   └── winws.exe
    ├── lists/
    │   └── list-general.txt
    ├── general.bat
    ├── discord.bat
    └── ...
```

### Шаг 4 — Запуск

Запустите `zapret++.exe` **от имени администратора** (ПКМ → «Запуск от имени администратора»).

---

## 📋 Разделы и функционал

### 1. Вкладка Connect

| Элемент | Назначение |
|---|---|
| **Кнопка питания** | Включение / отключение winws. Индикация: OFF / PENDING / ON |
| **Выбор конфига** | Выпадающий список всех `.bat` файлов. При смене конфига на лету происходит быстрое переподключение |
| **Autostart** | Добавление программы в автозагрузку Windows через реестр |
| **Auto-connect** | Автоматическое подключение к последнему выбранному конфигу при старте |
| **settings** | Переход в меню настроек (UI, обои, Set IP, Auto-update, About) |

---

### 2. Вкладка Create — Route Builder (Генератор маршрутов)

| Элемент | Назначение |
|---|---|
| **Create Route** | Поочередно запускает стратегии из базы **106 комбинаций** (hostfakesplit, fakedsni, sniext, autottl, badseq-increment, 5ka/max/4pda payloads, padenc/padsni TLS mods, multisplit, fake, multidisorder и др.) и тестирует доступность Discord и YouTube |
| **Количество маршрутов** | Ползунок от **1 до 10** для подбора нужного числа рабочих конфигураций |
| **Discord / YouTube** | Выбор целевых сервисов для проверки |
| **Stop** | Мгновенная остановка перебора |
| **Дедупликация** | Если рабочая стратегия уже есть в файлах zapret, выводится статус `That config already exists.`, а перебор продолжается до нахождения уникальной |
| **Output** | Консоль лога в реальном времени с цветовой подсветкой статусов |

Найденные конфигурации автоматически сохраняются как `custom_1.bat`, `custom_2.bat`, ... в папку zapret и сразу готовы к использованию.

---

### 3. Вкладка Test — Тестирование конфигов

| Элемент | Назначение |
|---|---|
| **Multi-ping** | **Включён по умолчанию**. Тестирует по 3 конфига одновременно в параллельных изолированных слотах, ускоряя проверку в разы |
| **Test All Configs** | Полная проверка каждого конфига: замер доступности сервисов и измерение задержки (ping) |
| **Run service.bat** | Быстрый запуск `service.bat` из папки zapret |
| **Results** | Вывод ТОП-3 лучших конфигураций по доступности и минимальному пингу |
| **Clear Log** | Очистка окна лога |

---

### 4. Вкладка Utils — Telegram WebSocket Proxy (TG WS Proxy)

Встроенный клиент моста [tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy) для мгновенного разблокирования Telegram Desktop:

| Элемент | Назначение |
|---|---|
| **Start / Stop Proxy** | Запуск локального WebSocket прокси (по умолчанию порт `1080`) |
| **Open in Telegram** | Подключение созданного прокси в Telegram Desktop в один клик (`tg://proxy`) |
| **Copy Proxy Link** | Копирование ссылки подключения в буфер обмена |
| **Auto-connect with start** | Автозапуск TG Proxy вместе с приложением |
| **CF Proxy Test / Worker Test** | Проверка пинга и доступности серверов Cloudflare в реальном времени |
| **Конфигурация** | Тонкая настройка хостов, секретов MTProto, параметров Worker / Reverse Proxy, буферов и TLS |

---

### 5. Настройки (Меню settings)

Открывается кнопкой **settings** на вкладке Connect:

#### 🎨 Подраздел UI
- **Цветовая палитра**: выбор **Color 1** (фон), **Color 2** (акценты/кнопки) и **Text color** (текст) с мгновенным применением.
- **Set Default**: сброс цветовой темы к стандартному монохромному оформлению.
- **Прозрачность окна**: настройка от 30% до 100% (слайдер + поле точного ввода).
- **Set as wallpaper**:
  - Установка любого изображения (PNG, JPG, BMP, WebP), анимированного GIF или видеофайла без звука (MP4, MKV, AVI, WebM) на фон приложения.
  - Автоматическое масштабирование (`KeepAspectRatioByExpanding`) — фон пропорционально заполняет окно без искажений и растягивания при любых размерах (рекомендуемый размер: `800x600`).
  - Все выбранные медиафайлы автоматически сохраняются в папку `settings/`.
  - Кнопка **Clear** для быстрого удаления фона и возврата к сплошному цвету Color 1.

#### 🌐 Подраздел Set IP
- **Добавление собственных доменов и IP**: поле ввода с кнопкой **add** для мгновенного добавления записи в `list-general.txt` zapret.
- **Кнопка add ip SoundCloud**: добавляет полный пул из **27 доменов SoundCloud** (`soundcloud.com`, `api-v2.soundcloud.com`, `sndcdn.com`, `cf-media.sndcdn.com` и др.) в самый низ списка.
- **Защита от дубликатов**: при попытке добавить уже существующий домен/IP программа выводит предупреждение и не засоряет файл.
- **Live Preview**: блок предпросмотра актуального содержимого `list-general.txt`.

#### 🔄 Подраздел Update
- **check-update**: тумблер автоматической проверки новых релизов на GitHub при старте программы.
- **auto-download**:
  - При обнаружении нового релиза на GitHub выводится окно **New update** с кнопками **install auto** и **cancel**.
  - Нажатие **cancel** закрывает окно и позволяет продолжить работу.
  - Нажатие **install auto** напрямую загружает обновлённый `.exe`, показывает прогресс скачивания в МБ/% и автоматически заменяет текущий файл с мгновенным перезапуском.
- **Check for Updates Now**: кнопка принудительной проверки обновлений вручную.

#### ℹ️ Подраздел About
- Информация об авторе (`@bpm500`) и прямая ссылка на репозиторий GitHub.

---

## 🔧 Сборка из исходников

### Требования

- Python 3.13+
- Git

### Установка зависимостей

```bash
git clone https://github.com/bpm500/zapret_pp.git
cd zapret_pp
pip install -r requirements.txt
```

### Запуск из исходного кода

```bash
python zapret_pp.py
```

### Сборка автономного EXE

Для сборки автономного исполняемого файла используйте готовый скрипт:

```bash
build.bat
```

Собранный файл появится в папке `dist/zapret++.exe`.

---

## 📁 Структура проекта

```
zapret_pp/
├── zapret_pp.py           ← основной GUI-интерфейс и бизнес-логика (PyQt6)
├── tg_proxy_service.py    ← менеджер Telegram WebSocket Proxy
├── autostart.py           ← интеграция с автозагрузкой Windows (реестр)
├── zapret_pp.spec         ← конфигурация PyInstaller для сборки
├── build.bat              ← автоматическая сборка автономного EXE
├── requirements.txt       ← зависимости проекта
├── proxy/                 ← реализация tg-ws-proxy
│   └── tg_ws_proxy.py
├── settings/              ← сохранённые конфигурации и обои
│   ├── zapret_settings.json
│   ├── app_settings.json
│   └── tg_proxy_settings.json
└── icons/                 ← графические ресурсы приложения
    ├── ico.ico
    ├── on.png
    ├── off.png
    └── pending.png
```

---

## ❓ Частые вопросы (FAQ)

<details>
<summary><b>Программа не видит .bat файлы</b></summary>

Программа ищет рядом с `.exe` любую папку, в которой содержатся `.bat` файлы и `bin\winws.exe`. Название папки может быть любым (например, `zapret-discord-youtube-1.10.1`), кроме служебных имён (`icons`, `build`, `dist`, `.git`).
</details>

<details>
<summary><b>Зачем нужны права администратора?</b></summary>

Для перехвата и модификации сетевых пакетов драйвером WinDivert/winws требуются администраторские привилегии Windows. Всегда запускайте программу от имени администратора.
</details>

<details>
<summary><b>Как восстановить стандартные цвета или убрать обои?</b></summary>

В меню **settings → UI** нажмите **Set Default** для сброса палитры или кнопку **Clear** рядом с надписью Wallpaper для удаления фонового медиафайла.
</details>

<details>
<summary><b>Как добавить свои домены для обхода?</b></summary>

В меню **settings → Set IP** введите домен или IP (например, `example.com`) и нажмите **add**, либо воспользуйтесь кнопкой **add ip SoundCloud** для автоматического добавления всех аудиосерверов SoundCloud.
</details>

---

<div align="center">

Сделано с ❤️ by [bpm500](https://github.com/bpm500)

**[⭐ Поставьте звезду, если проект оказался полезным!](https://github.com/bpm500/zapret_pp)**

</div>
