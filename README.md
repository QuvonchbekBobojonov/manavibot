# Manavi — Saqla va ulash

<img src="assets/manavibot-logo.png" alt="Manavi logo" width="160">

[@manavibot](https://t.me/manavibot) — kerakli matn va fayllaringizni saqlash, topish va inline rejimda ulashish uchun shaxsiy Telegram bot.

O‘zbek tilidagi shaxsiy Telegram kutubxonasi. Python 3.12+, aiogram 3, SQLite va Linux systemd bilan ishlaydi.

## Foydalanish

Botga matn, havola, rasm, video yoki hujjat yuboring/forward qiling. Keyingi oddiy matnni nom sifatida yuboring (1–100 belgi). Albom fayllari kelgan tartibida navbatga olinadi: har biriga alohida nom yuboring. Matnni saqlayotganda navbatdagi oddiy matn nom hisoblanadi. `/cancel` barcha tugallanmagan amallarni bekor qiladi.

`Ma’lumotlarim` yoki `/list` orqali yozuvni tanlab ko‘rish, nomini o‘zgartirish, mazmun/faylini almashtirish va o‘chirish mumkin. Istalgan chatda `@manavibot qidiruv` yozing va natijani tanlang. Nom yuborilgan mazmunga qo‘shilmaydi. Qidiruv nom, matn va izoh bo‘yicha ishlaydi; bo‘sh so‘rov yangi yozuvlarni ko‘rsatadi. Boshqa akkauntlar kutubxonani ko‘ra olmaydi, siz ulashgan xabarni esa qabul qiluvchi ko‘radi.

Saqlangan yozuvlar qayta ishga tushganda qoladi. Hali nom berilmagan navbat va tahrirlash holati xotirada: restartdan keyin qayta yuborish kerak. Fayllar Telegramda saqlanadi, diskka yuklanmaydi. O‘chirish ilgari boshqa chatga yuborilgan nusxalarni o‘chirmaydi.

## Telegram sozlamalari

1. [BotFather](https://t.me/BotFather) orqali mavjud `@manavibot` botini tanlang va uning tokenini oling.
2. `/setinline` orqali `@manavibot`ni tanlang va qidiruv uchun izoh kiriting.
3. O‘z Telegram raqamli foydalanuvchi ID’ingizni `OWNER_ID` ga kiriting. Username yoki telefon raqamini kiritmang.
4. Bot bilan shaxsiy chatda `/start` yuboring.

## Linux serverga o‘rnatish (Ubuntu/Debian)

Loyiha fayllarini serverdagi `/opt/yordamchibot` ga ko‘chiring. Quyidagi buyruqlarni serverda bajaring:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv
sudo useradd --system --home-dir /var/lib/yordamchibot --shell /usr/sbin/nologin yordamchibot
sudo install -d -o yordamchibot -g yordamchibot -m 700 /var/lib/yordamchibot
cd /opt/yordamchibot
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements.txt
sudo install -m 600 .env.example /etc/yordamchibot.env
sudo nano /etc/yordamchibot.env
```

Sozlamalar:

```ini
BOT_TOKEN=BOTFATHER_TOKEN
OWNER_ID=123456789
DB_PATH=/var/lib/yordamchibot/bot.db
```

`.env` avtomatik o‘qilmaydi: systemd `EnvironmentFile` orqali muhitga yuklaydi. Tokenni Git’ga yoki loglarga yozmang. Kod va virtual muhit root egaligida, service foydalanuvchisiga o‘qish/ishga tushirish ruxsati bilan qolsin.

```bash
sudo install -m 644 deploy/yordamchibot.service deploy/yordamchibot-backup.service deploy/yordamchibot-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yordamchibot.service
sudo systemctl enable --now yordamchibot-backup.timer
sudo systemctl status yordamchibot --no-pager
sudo journalctl -u yordamchibot -n 50 --no-pager
```

Serverdan Telegram API’ga HTTPS chiqishi kerak. Long polling uchun domen yoki kiruvchi port kerak emas. Shu token bilan boshqa polling jarayoni yoki webhook ishlamasligi kerak; oldingi webhook bo‘lsa, uni avval o‘chiring.

## Boshqarish va yangilash

```bash
sudo systemctl restart yordamchibot
sudo systemctl stop yordamchibot
sudo journalctl -u yordamchibot -f
sudo systemctl list-timers yordamchibot-backup.timer
```

Yangilashdan oldin `sudo systemctl start yordamchibot-backup.service` bilan nusxa oling, botni to‘xtating, yangi kodni `/opt/yordamchibot` ga ko‘chiring, `.venv/bin/python -m pip install -r requirements.txt` ni sudo bilan bajaring, testlarni bajaring va serviceni qayta yoqing. Service fayllari o‘zgarsa ularni qayta o‘rnating va `daemon-reload` bajaring. Bazani yoki `/etc/yordamchibot.env` ni kod yangilashda almashtirmang.

## Zaxira va tiklash

Har kuni Toshkent vaqti bilan 03:00 da SQLite online backup olinadi. `/var/lib/yordamchibot/backups` ichida oxirgi 7 nusxa qoladi. Qo‘lda ishga tushirish va natijani tekshirish:

```bash
sudo systemctl start yordamchibot-backup.service
sudo journalctl -u yordamchibot-backup.service -n 20 --no-pager
sudo ls -l /var/lib/yordamchibot/backups
```

Tiklashda avval bot va timerni to‘xtating; ishlayotgan backup tugaganini tekshiring. Quyidagi `backup-TANLANGAN.db` o‘rniga haqiqiy nusxa nomini yozing. Eski baza va uning WAL/SHM fayllari alohida katalogda saqlanadi:

```bash
sudo systemctl stop yordamchibot-backup.timer yordamchibot.service
sudo systemctl stop yordamchibot-backup.service
sudo install -d -m 700 /var/lib/yordamchibot/before-restore
sudo mv /var/lib/yordamchibot/bot.db /var/lib/yordamchibot/before-restore/
sudo find /var/lib/yordamchibot -maxdepth 1 -type f \( -name 'bot.db-wal' -o -name 'bot.db-shm' \) -exec mv -t /var/lib/yordamchibot/before-restore/ {} +
sudo install -o yordamchibot -g yordamchibot -m 600 /var/lib/yordamchibot/backups/backup-TANLANGAN.db /var/lib/yordamchibot/bot.db
sudo systemctl start yordamchibot.service yordamchibot-backup.timer
```

Takroriy tiklashda eski `before-restore` katalogini avval boshqa nomga saqlang. Zaxiralar faqat baza va Telegram fayl identifikatorlarini o‘z ichiga oladi. Server diskidan tashqariga nusxa olish alohida tashkil etiladi.

## Tekshirish

```bash
.venv/bin/python -m unittest discover -s tests -v
sudo systemd-analyze verify /etc/systemd/system/yordamchibot.service /etc/systemd/system/yordamchibot-backup.service /etc/systemd/system/yordamchibot-backup.timer
```

Jonli qabul sinovi: matn (format bilan), rasm, video, hujjat va albomni saqlang; inline orqali boshqa chatga yuboring; tahrirlang/o‘chiring va qayta qidiring. Boshqa akkauntdan buyruq va inline so‘rov yuboring: yozuvlar chiqmasin. Serviceni va serverni qayta yoqing: yozuvlar qolsin. Backupni tiklab yana qidiring. Token/server bo‘lmagan muhitda faqat avtomatik testlar bajarilishi mumkin.

Manbalar: [Telegram inline](https://core.telegram.org/bots/inline), [Bot API](https://core.telegram.org/bots/api#inline-mode), [aiogram middleware](https://docs.aiogram.dev/en/latest/dispatcher/middlewares.html).
