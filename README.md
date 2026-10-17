# Manavi — Saqla va ulash

<img src="assets/manavibot-logo.png" alt="Manavi logo" width="160">

[@manavibot](https://t.me/manavibot) — kerakli matn va fayllaringizni saqlash, topish va inline rejimda ulashish uchun shaxsiy Telegram bot.

O‘zbek tilidagi shaxsiy Telegram kutubxonasi. Python 3.12+, aiogram 3, SQLite va Linux systemd bilan ishlaydi.

## Foydalanish

Botga matn, havola, rasm, video, hujjat, ovozli xabar, audio yoki GIF yuboring/forward qiling. Keyingi oddiy matnni nom sifatida yuboring (1–100 belgi). Albom fayllari kelgan tartibida navbatga olinadi: har biriga alohida nom yuboring. Matnni saqlayotganda navbatdagi oddiy matn nom hisoblanadi. `/cancel` barcha tugallanmagan amallarni bekor qiladi.

`📚 Ma’lumotlarim` yoki `/list` orqali yozuvni ko‘rish va boshqarish mumkin. Istalgan chatda `@manavibot qidiruv` yozing yoki yozuvdagi `↗️ Ulashish` tugmasi orqali chat tanlab, natijani yuboring. Nom yuborilgan mazmunga qo‘shilmaydi. Boshqa akkauntlar kutubxonani ko‘ra olmaydi, siz ulashgan xabarni esa qabul qiluvchi ko‘radi.

Saqlangan yozuvlar qayta ishga tushganda qoladi. Hali nom berilmagan navbat va tahrirlash holati xotirada: restartdan keyin qayta yuborish kerak. Fayllar Telegramda saqlanadi, diskka yuklanmaydi. O‘chirish ilgari boshqa chatga yuborilgan nusxalarni o‘chirmaydi.

## Yangi imkoniyatlar

| Funksiya | Foydalanish |
| --- | --- |
| 🗂 Kategoriya | Yozuvdagi «Kategoriya» tugmasi, 40 belgigacha nom; `/categories` orqali ko‘rish. |
| 🏷 Teglar | Yozuvdagi «Teglar» tugmasi, vergul bilan ajratilgan 10 tagacha teg (har biri 30 belgi). |
| ⭐ Sevimlilar | Yozuvdagi yulduz tugmasi; `/favorites`. Mos kelgan sevimlilar qidiruvda ham avval chiqadi. |
| ↗️ Ulashish | Chat tanlab, aynan shu yozuvni inline orqali yuborish. Maxfiy yozuvda tugma ko‘rinmaydi. |
| 🎤 Ovoz, 🎵 audio, 🎞 GIF | Oddiy fayl kabi yuboring va nomlang. Inline natijada audio nomi Telegramdagi audio metama’lumotidan olinadi. |
| 🔎 Aqlli qidiruv | `/search so‘z`, menyu yoki inline orqali nom, matn, izoh, kategoriya va teglardan izlash. Lotin/kirill, apostrof variantlari va 4+ belgili so‘zlarda kichik xatolar qo‘llanadi. |
| 🗑 Savat | O‘chirishdan keyin `/trash` orqali 30 kun ichida tiklash. So‘ng yozuv avtomatik o‘chadi. Eski SQLite zaxiralarida nusxa qolishi mumkin. |
| 📦 Eksport | `/export` — maxfiy va savatdagi yozuvlar, formatlash, kategoriya, teglar hamda belgilar JSON faylida. |
| 📥 Import | `/import`, JSON yuborish, tekshiruvdan keyin tugma bilan tasdiqlash. Mavjud UUID’lar o‘tkazib yuboriladi, eski yozuvlar almashtirilmaydi. |
| ⏰ Eslatmalar | Yozuvdagi «Eslatma»: `10 daqiqa`, `2 soat`, `1 kun` yoki `25.12.2026 09:00`. `/reminders` ro‘yxati; yozuvdan bekor qilish. |
| 🔐 Maxfiy yozuvlar | Yozuvdagi «Maxfiy qilish» tugmasi inline qidiruv va bevosita ulashishni yopadi. Egasi shaxsiy chatda ko‘ra oladi. |
| 📊 Statistika | `/stats`: faol yozuvlar, sevimlilar, maxfiylar, savat, eslatmalar va fayl turlari. |

Kategoriya yoki tegni tozalash uchun `-` yuboring. Yangi menyu uchun `/start` yuboring. Eski «Ma’lumotlarim» tugmasi ham ishlaydi.

Eslatma vaqti Toshkent (UTC+5), tekshirish oralig‘i 15 soniya. Har yozuvda bitta eslatma; qayta belgilash avvalgisini almashtiradi. Eslatma bazada saqlanadi; bot o‘chiq paytda muddati o‘tgan bo‘lsa, ishga tushgach yuboriladi. Telegramga ulanish xatosida qayta uriniladi. Eslatma faqat egasiga yozuvni ochish tugmasi bilan yuboriladi. Savatga ko‘chirish eslatmani bekor qiladi; tiklash uni qayta yoqmaydi. Yuborish va bazaga belgilash orasida jarayon to‘xtasa, eslatma takror kelishi mumkin.

Import/eksport chegarasi: 10 MB va 10 000 yozuv. JSON fayl Telegram fayllarining o‘zini emas, `file_id`larini saqlaydi va faqat shu botga import qilinadi. Eslatmalar JSON bilan ko‘chirilmaydi, ammo to‘liq SQLite zaxirasida saqlanadi. Tugallanmagan import tasdig‘i restart yoki `/cancel`dan keyin bekor bo‘ladi. Maxfiy qilish ilgari ulashilgan nusxalarni qaytarib olmaydi.

Baza migratsiyasi avtomatik va qo‘shimcha ustunlar orqali bajariladi: mavjud ID, matn, fayl va formatlash o‘zgarmaydi. Katta yangilanishdan oldin SQLite zaxirasini oling.

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
