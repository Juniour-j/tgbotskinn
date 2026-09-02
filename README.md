# lis-price-bot

Telegram-бот: кидаєш назву скіна й цільову ціну — отримуєш сповіщення, коли
найдешевший лот цього скіна на **lis-skins.com** падає до неї або нижче.

Працює на безкоштовному прайс-експорті `market_export_json/csgo.json` — **API-ключ
lis-skins не потрібен**. Перевірка раз на ~60 с (з `If-None-Match`, тож зайвого
трафіку майже нема).

## Команди

| Команда | Дія |
|---|---|
| `/watch <назва> <ціна>` | стежити, напр. `/watch AWP \| Asiimov (Field-Tested) 55` |
| `/find <текст>` | знайти точну назву скіна в каталозі |
| `/list` | мої стеження |
| `/unwatch <id>` | прибрати |
| `/mute <id>` / `/unmute <id>` | вимкнути / увімкнути сповіщення |
| `/whoami` | мій Telegram id (для `ALLOWED_USER_IDS`) |

Ціни в **доларах**. Сповіщення приходить один раз; знову спрацює, лише якщо ціна
підніметься вище цілі й потім знову впаде (re-arm).

Бот **багатокористувацький**: кожен, хто напише боту, має власний ізольований
список стежень і отримує лише свої сповіщення. Щоб пустити тільки певних людей —
задай `ALLOWED_USER_IDS` (їхні id через кому; свій дізнатись командою `/whoami`).
Порожнє значення — доступ відкритий усім.

## Обмеження

- Дані згруповані: тільки **мінімальна ціна + кількість** по назві скіна.
  Watch на конкретний float / стікери неможливий (для цього потрібен платний API).
- Затримка експорту lis-skins — кілька хвилин, миттєвих лотів бот не ловить.

## Локальний запуск (Windows / PowerShell)

```powershell
cd "F:\Новая папка (2)\lis-price-bot"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env      # вписати TELEGRAM_TOKEN, зберегти
.\.venv\Scripts\python.exe -m bot
```

`.env` — єдине місце для токена локально (у git не потрапляє, він у `.gitignore`):

```
TELEGRAM_TOKEN=8944xxxxxxx:AAF...новий_токен_від_BotFather
DB_PATH=bot.db
```

Без квадратних лапок і пробілів навколо `=`. Зупинка бота — `Ctrl+C`.

Тести:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

## Деплой на Railway

1. Запуш репо в GitHub, у Railway → **New Project → Deploy from GitHub**.
2. Railway (Nixpacks) сам підхопить Python з `requirements.txt` і команду з `Procfile`
   (`worker: python -m bot`). Dockerfile не потрібен. HTTP-порт не потрібен.
3. **Variables:**
   - `TELEGRAM_TOKEN` — новий токен від @BotFather
   - `DB_PATH` — `/data/bot.db`
   - (опційно) `POLL_INTERVAL`, `LIS_EXPORT_URL`
4. **Volume:** додай Volume і примонтуй у `/data`. Без нього SQLite-файл
   зітреться на кожному редеплої (ФС Railway ефемерна).
5. Бот працює на long polling — жоден вебхук/домен налаштовувати не треба.

> Always-on воркер потребує платного плану Railway (Hobby, ~$5/міс);
> на free trial вичерпаються години.
