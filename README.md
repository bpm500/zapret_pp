<div align="center">

<img src="icons/ico.ico" alt="zapret++" width="80" height="80"/>

# zapret++

<a href="https://www.donationalerts.com/r/bpm500" target="_blank">
  <img src="https://img.shields.io/badge/%D0%9F%D0%BE%D0%B4%D0%B4%D0%B5%D1%80%D0%B6%D0%BA%D0%B0_%D0%B0%D0%B2%D1%82%D0%BE%D1%80%D0%B0-DonationAlerts-FF5900?style=for-the-badge&logo=donationalerts&logoColor=white" alt="Поддержка автора DonationAlerts"/>
</a>

<br/>

**GUI-оболочка для Zapret — Discord, YouTube и другие заблокированные сервисы**

[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/bpm500/zapret_pp)
[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-GUI-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.0-blue?style=for-the-badge)](https://github.com/bpm500/zapret_pp/releases)

<br/>

> Форк [ZapretTester](https://github.com/bpm500/ZapretTester).  
> Подключение в один клик, автоматический подбор рабочей стратегии, тест всех конфигов, встроенный Telegram WebSocket Proxy, автозапуск с Windows.

</div>

---

## ⚡ Что такое zapret++?

**zapret++** — это GUI-обёртка для [zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) и [tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy), которая превращает запуск `.bat` файлов и прокси в удобный тёмный интерфейс. Помимо запуска готовых конфигов, программа умеет **сама генерировать и подбирать рабочую стратегию обхода DPI**, если ни один из готовых конфигов не подошёл, а также предоставляет встроенный WebSocket мост для Telegram.

**Что умеет:**
- Запуск любого `.bat` конфига zapret одним нажатием (кнопка питания с состояниями off / подключение / on)
- **Автоматический подбор стратегии** — перебирает встроенные DPI-стратегии, тестирует каждую по Discord и YouTube и сохраняет рабочие как готовые `.bat` конфиги
- **Умная дедупликация стратегий** — если при создании нового маршрута найдена стратегия, которая уже есть в папке, она помечается как существующая (*That config already exists.*), и перебор продолжается до нахождения уникальной
- Автоматический тест всех существующих конфигов с замером пинга и доступности сервисов, вывод ТОП-3
- **Встроенный Telegram WebSocket Bridge Proxy (TG WS Proxy)** во вкладке **Utils** с независимым автозапуском, тестами Cloudflare Proxy / Worker, прямым открытием в Telegram и копированием ссылок
- Автозапуск при старте Windows (через реестр)
- Автоподключение при запуске программы (Zapret и TG Proxy настраиваются независимо)
- Сворачивание в системный трей с полным управлением через контекстное меню (Connect / Disconnect / on\off TG Proxy)
- Скрытие окна `winws.exe` из панели задач

---

## 🖥️ Системные требования

| Параметр | Требование |
|---|---|
| ОС | Windows 10 (1903+) / Windows 11 |
| Права | **Администратор** (обязательно) |
| Python | 3.13+ (только для запуска из исходников) |
| Зависимости | PyQt6, psutil, requests, ping3 |

---

## 🚀 Быстрый старт

### Шаг 1 — Скачайте zapret++

Скачайте `zapret++.exe` из раздела **[Releases](https://github.com/bpm500/zapret_pp/releases)**

### Шаг 2 — Скачайте zapret

Скачайте архив из репозитория **[zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube/releases)**

### Шаг 3 — Структура папок

Распакуйте архив zapret рядом с программой. Название папки может быть **любым** — программа сама находит папку, в которой лежат `.bat` файлы и `bin\winws.exe`:

```
📁 Любая папка/
├── zapret++.exe                 ← сама программа
├── 📁 settings/                  ← создаётся автоматически (настройки)
└── 📁 zapret-discord-youtube-x.x.x/   ← содержимое архива (имя папки любое)
    ├── bin/
    │   └── winws.exe
    ├── lists/
    ├── general.bat
    ├── discord.bat
    ├── service.bat
    └── ... (остальные .bat файлы)
```

### Шаг 4 — Запуск

Запустите `zapret++.exe` **от имени администратора** (ПКМ → «Запуск от имени администратора»)

---

## 📋 Функционал

### Вкладка Connect

| Элемент | Описание |
|---|---|
| **Кнопка питания** | Клик — подключение / отключение. Три состояния: выключено / подключение (pending) / подключено |
| **Список конфигов** | Выбор `.bat` конфига из найденной папки zapret |
| **Autostart** | Добавляет программу в автозапуск Windows через реестр |
| **Auto-connect** | При запуске программы автоматически подключается к последнему выбранному конфигу |

При смене конфига во время активного подключения программа сама переподключается на новый.

### Вкладка Create — Route Builder

| Элемент | Описание |
|---|---|
| **Create Route** | Перебирает встроенный набор DPI-стратегий (multisplit, fake, fakedsplit, multidisorder, syndata, split, disorder и их комбинации), для каждой запускает `winws`, проверяет доступность Discord и YouTube |
| **Stop** | Останавливает перебор в любой момент |
| **Checkboxes (Discord / YouTube)** | Выбор целевых сервисов для проверки при генерации |
| **Количество маршрутов** | Слайдер выбора числа создаваемых рабочих конфигураций (от 1 до 5) |
| **Multi-ping** | Параллельная проверка в изолированных слотах при включении опции в Settings |
| **Output** | Лог перебора в реальном времени с подсветкой статусов |

Как только находится уникальная рабочая стратегия, она сохраняется как `custom_N.bat` в папке zapret и сразу появляется в списке конфигов на вкладке Connect. Если проверенная рабочая стратегия уже существует в вашей папке zapret, выводится фиолетовое сообщение `That config already exists.`, и поиск продолжается дальше.

### Вкладка Utils — Telegram WebSocket Proxy (TG WS Proxy)

Интегрированный клиент прокси-моста [tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy) для обхода блокировок и ускорения Telegram Desktop через WebSocket и Cloudflare Workers / Reverse Proxy:

| Элемент | Описание |
|---|---|
| **Start / Stop Proxy** | Запуск и остановка локального прокси-сервера (по умолчанию `127.0.0.1:1080`) |
| **Open in Telegram** | Подключение созданного прокси в Telegram Desktop в один клик через `tg://proxy` |
| **Copy Proxy Link** | Копирование ссылки подключения `tg://proxy?server=...` в буфер обмена |
| **Open Log File** | Открытие подробного лог-файла работы прокси |
| **Auto-connect with start** | Независимый автозапуск TG WS Proxy при открытии приложения |
| **CF Proxy Test** | Тестирование доступности и задержки Cloudflare Reverse Proxy IP |
| **Worker Test** | Тестирование задержки и отклика Cloudflare Worker в реальном времени |
| **Панель конфигурации** | Настройка портов, целевых хостов Telegram DC, секретов MTProto, параметров Worker / Reverse Proxy, TLS, SNI и буферов с сохранением в `settings/tg_proxy_settings.json` |

### Вкладка Settings

| Элемент | Описание |
|---|---|
| **Run service.bat** | Запускает `service.bat` из папки zapret |
| **Test All Configs** | Тестирует каждый `.bat` файл: проверяет доступность YouTube и Discord, замеряет пинг до Discord / YouTube / Yandex |
| **Multi-ping** | Переключатель между последовательным и параллельным тестированием (3 слота) |
| **Clear Log** | Очищает консоль |
| **Results** | ТОП-3 конфига, отсортированных по количеству доступных сервисов и среднему пингу |
| **Console** | Лог всех действий в реальном времени |

### Системный трей

- **Левый клик** по иконке — открыть окно
- **Правый клик** — меню: Open / Connect / Disconnect / on\off tg-proxy / Exit
- Иконка чёрно-белая: тёмная = отключено, светлая = подключено
- Закрытие окна сворачивает программу в трей (не завершает работу)

---

## 🔬 Как работает автоподбор (Create Route)

При нажатии **Create Route** программа:

1. Останавливает текущий процесс `winws`
2. Генерирует `.bat` со следующей стратегией из встроенного набора (порядок рандомизируется)
3. Запускает его и ждёт старта `winws`
4. Проверяет доступность Discord и YouTube в соответствии с выбранными чекбоксами
5. Если сервисы доступны:
   - Проверяет, нет ли уже такого конфига среди имеющихся в папке zapret (`custom_*.bat`, `general*.bat` и др.).
   - Если такой конфиг уже есть — выводит фиолетовое сообщение *"That config already exists."* и продолжает поиск.
   - Если найден уникальный рабочий конфиг — сохраняет его как `custom_N.bat` и обновляет список в интерфейсе.
6. Если доступа нет — удаляет временный файл и сразу переходит к следующей стратегии.

Подбор можно остановить в любой момент кнопкой **Stop**.

---

## 🔧 Сборка из исходников

### Требования

- Python 3.13+
- Git

### Установка

```bash
git clone https://github.com/bpm500/zapret_pp.git
cd zapret_pp
pip install -r requirements.txt
```

### Запуск без сборки

```bash
python zapret_pp.py
```

### Сборка EXE

```bash
# Запустить build.bat — сам поставит зависимости и соберёт exe через PyInstaller
build.bat
```

Готовый EXE появится в папке `dist/`. Он автономен — Python не требуется.

---

## 📁 Структура репозитория

```
zapret_pp/
├── zapret_pp.py           ← основной GUI-интерфейс (PyQt6)
├── tg_proxy_service.py    ← сервис управления Telegram WebSocket Proxy
├── autostart.py           ← модуль управления автозапуском Windows
├── zapret_pp.spec         ← конфиг сборки PyInstaller
├── build.bat              ← скрипт сборки автономного EXE
├── requirements.txt       ← зависимости Python
├── proxy/                 ← реализация Telegram WS Proxy
│   └── tg_ws_proxy.py
├── settings/              ← файлы сохранённых настроек
│   ├── zapret_settings.json
│   └── tg_proxy_settings.json
└── icons/                 ← графические ресурсы
    ├── ico.ico            ← иконка приложения
    ├── on.png             ← кнопка питания (подключено)
    ├── off.png            ← кнопка питания (отключено)
    └── pending.png        ← кнопка питания (подключение)
```

---

## ❓ Частые вопросы

<details>
<summary><b>Программа не видит .bat файлы</b></summary>

Программа ищет рядом с exe папку, в которой одновременно есть `.bat` файлы и `bin\winws.exe` (или `winws.exe` в корне). Название папки может быть любым, кроме служебных (`icons`, `build`, `dist`, `.git` и т.п.).

</details>

<details>
<summary><b>Ошибка "требуются права администратора"</b></summary>

Zapret запускает драйвер `winws.exe`, который требует прав администратора. Запускайте `zapret++.exe` через ПКМ → «Запуск от имени администратора».

</details>

<details>
<summary><b>Автозапуск добавляется, но не работает</b></summary>

Программа добавляет себя в реестр: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. Проверьте, что антивирус не блокирует запись в реестр, и включайте автозапуск от администратора.

</details>

<details>
<summary><b>Окно winws.exe всё равно появляется</b></summary>

Программа скрывает окно с задержкой ~2 секунды после запуска. Если окно мелькает — это нормально, оно скроется автоматически.

</details>

<details>
<summary><b>Create Route долго ничего не находит</b></summary>

Перебор идёт по встроенным стратегиям и может занять время — на каждую стратегию уходит несколько секунд на старт `winws` и проверку сервисов. Если ни одна стратегия не сработала — вероятно, провайдер использует более агрессивную блокировку; попробуйте вручную протестировать дефолтные конфиги во вкладке Settings.

</details>

<details>
<summary><b>Как подключить Telegram к встроенному прокси?</b></summary>

Перейдите во вкладку **Utils**, нажмите **Start Proxy**, затем нажмите **Connect a Telegram proxy** — Telegram Desktop автоматически откроет окно добавления прокси, где нужно нажать «Включить».

</details>

---

## 📄 Лицензия

MIT License — см. файл [LICENSE](LICENSE)

---

<div align="center">


<br/><br/>

Сделано с ❤️ by [bpm500](https://github.com/bpm500)

**[⭐ Поставьте звезду если программа помогла!](https://github.com/bpm500/zapret_pp)**

</div>
