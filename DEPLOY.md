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

> Вхідні порти не потрібні (бот працює на long polling, лише вихідні зʼєднання) —
> Security List / firewall не чіпати.

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

---

### Альтернатива без GitHub — залити папку напряму

З Windows, з каталогу `F:\Новая папка (2)`:

```powershell
scp -i C:\шлях\до\ключа.key -r lis-price-bot ubuntu@<PUBLIC_IP>:/home/ubuntu/
```

Далі кроки 3–4, але без `git clone` (папка вже на місці) і без `git pull` для оновлень
(повторюй `scp`).
