# Деплой на Oracle Cloud (Always Free)

## 1. Створити VM в OCI Console

1. https://cloud.oracle.com → увійти (Cloud Account Name → далі логін/пароль).
2. Меню ☰ → **Compute → Instances → Create instance**.
3. **Name:** `lis-bot`
4. **Image and shape:**
   - Image: **Canonical Ubuntu 22.04**
   - Shape → *Change shape* → **Ampere (ARM)** → `VM.Standard.A1.Flex` → 1 OCPU / 6 GB
     (мітка *Always Free eligible*). Якщо «Out of host capacity» — постав
     **`VM.Standard.E2.1.Micro`** (AMD, 1 GB, теж Always Free).
5. **Networking:** лишити як є — нова VCN, публічний IPv4 увімкнено.
6. **SSH keys:** *Generate a key pair for me* → **завантажити приватний ключ**
   (або вставити свій `~/.ssh/id_ed25519.pub`).
7. **Boot volume:** дефолт (~47 GB), нічого не міняти.
8. **Create.** За ~1 хв інстанс *Running* — скопіювати **Public IP address**.

> У режимі `polling` (за замовчуванням) вхідні порти не потрібні — бот лише
> робить вихідні зʼєднання. Для режиму `webhook` див. розділ 6.

## 2. Зайти на VM

Windows (Git Bash або PowerShell):

```bash
chmod 600 ./ssh-key-*.key            # тільки Git Bash/Linux
ssh -i ./ssh-key-2026-xx-xx.key ubuntu@<PUBLIC_IP>
```

(користувач для Ubuntu-образу — `ubuntu`).

## 3. Поставити бота

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git

git clone https://github.com/<ТВІЙ_ЮЗЕР>/lis-price-bot.git
cd lis-price-bot

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
nano .env
#   TELEGRAM_TOKEN=<новий токен від BotFather>
#   DB_PATH=/home/ubuntu/lis-price-bot/bot.db
```

Перевірка вручну:

```bash
.venv/bin/python -m bot      # маєш побачити "catalog updated: ~23000 skins"; Ctrl+C
```

## 4. Запустити як сервіс (always-on, автозапуск після краху/ребуту)

```bash
sudo cp deploy/lis-price-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lis-price-bot

systemctl status lis-price-bot
journalctl -u lis-price-bot -f        # живі логи
```

## 5. Оновлення після змін у коді

```bash
cd ~/lis-price-bot
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart lis-price-bot
```

## 6. Перехід на вебхук (опційно)

За замовчуванням бот працює на long polling (`MODE=polling`). У режимі
`MODE=webhook` Telegram сам надсилає апдейти на `https://<домен>/webhook`.
Потрібні: домен, що вказує на Public IP VM, і reverse proxy з TLS (Caddy).
Фонові цикли (перевірка цін, глибина, історія) працюють так само.

### 6.1 Домен

Свій домен або безкоштовний піддомен (напр. DuckDNS) з A-записом на Public IP VM.
Перевірка (має вивести IP VM):

```bash
dig +short <ДОМЕН>
```

### 6.2 Відкрити порти 80 і 443

**В OCI Console:** ☰ → Networking → Virtual Cloud Networks → ваша VCN → Security →
Security Lists → Default Security List → **Add Ingress Rules**: Source CIDR `0.0.0.0/0`,
IP Protocol `TCP`, Destination Port Range `80`; те саме окремим правилом для `443`.

**На самій VM** Ubuntu-образ Oracle за замовчуванням відкидає все, крім SSH. Подивіться
номер рядка з `REJECT`:

```bash
sudo iptables -L INPUT -n --line-numbers
```

Вставте правила **перед** `REJECT` (нижче номер 5 — підставте свій, якщо відрізняється),
а потім збережіть, щоб вони пережили перезавантаження:

```bash
sudo iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 5 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Якщо `netfilter-persistent` немає: `sudo apt install -y iptables-persistent`.

### 6.3 Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

Покладіть `deploy/Caddyfile` у `/etc/caddy/Caddyfile`, замінивши `YOUR_DOMAIN` на свій
домен, і перезавантажте Caddy:

```bash
sudo cp ~/lis-price-bot/deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

### 6.4 Увімкнути вебхук у боті

Секрет згенеруйте на VM (у чат/git не вставляйте):

```bash
openssl rand -hex 32
```

Додайте в `~/lis-price-bot/.env` (значення секрету — з команди вище):

```
MODE=webhook
WEBHOOK_BASE_URL=https://<ДОМЕН>
WEBHOOK_SECRET=<секрет>
```

```bash
cd ~/lis-price-bot
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart lis-price-bot
journalctl -u lis-price-bot -n 30 --no-pager      # має бути "update mode: webhook" і "webhook set: ..."
```

Перевірка на боці Telegram (токен береться з `.env`, у історію shell не потрапляє):

```bash
set -a; . ./.env; set +a; curl -s "https://api.telegram.org/bot$TELEGRAM_TOKEN/getWebhookInfo"
```

У відповіді `url` — ваш домен, `last_error_message` — відсутнє. Далі напишіть боту в Telegram.

### 6.5 Відкат на polling

У `.env` поставте `MODE=polling` (або видаліть рядок) і:

```bash
sudo systemctl restart lis-price-bot
```

У режимі `polling` бот сам знімає вебхук при старті. Апдейти, що накопичились, не губляться.

---

### Альтернатива без GitHub — залити папку напряму

З Windows, з каталогу `F:\Новая папка (2)`:

```powershell
scp -i C:\шлях\до\ключа.key -r lis-price-bot ubuntu@<PUBLIC_IP>:/home/ubuntu/
```

Далі кроки 3–4, але без `git clone` (папка вже на місці) і без `git pull` для оновлень
(повторюй `scp`).
