# Fayz Medical House — Hospital Management & Clinical EMR Suite

Toshkent shahridagi **"Fayz Medical House"** xususiy klinikasi uchun to'liq integratsiyalashgan, xavfsiz va MySQL 8 ma'lumotlar bazasiga ulangan avtonom shifoxona boshqaruv tizimi (Hospital Information System / EMR & CRM).

---

## 🌟 Asosiy Tizim Modullari

1. **Super-Portal (`superpage.html`)**:
   - 10 ta asosiy bo'limni (Boshqaruv, Statsionar, Kassa, Farmakologiya, Qabulxona, EMR, Hamshiralar, Oshxona, HR, CRM) yagona oynada birlashtiruvchi Live BI boshqaruv markazi.
2. **Bemorlar CRM & Kasallik Tarixi (`crm.html`)**:
   - 100% anonim va maxfiy bemorlar kartotekasi (`FMH-2026-XXXX`), shaxsiy dossier, yotishlar xronologiyasi, dori allergiyalari nazorati va SheetJS ko'p varaqli Excel eksport moduli.
3. **Shifokor Posti & Klinik EMR (`doctor.html`)**:
   - Shikoyatlar, Anamnesis Morbi & Vitae, somatik/psixik status, XKT-10 tashxis, 206 klinik dori vositasi bo'yicha retseptlar (List Naznacheniy), Dnevnik Obxoda va chiqarish epikrizi chop etish.
4. **Statsionar Bino Boshqaruvi (`building_management.html`)**:
   - 1-bino 14-karavotli statsionarining interaktiv xaritasi (CAD Floor Plan), real-vaqtda karavotlar bandligi va bemorlarni xonalarga joylashtirish.
5. **Qabulxona & Resepshn (`reception.html`)**:
   - Birlamchi bemorlar triaji, navbatlar monitoringi, qo'ng'iroqlar jurnali (Call Log) va rasmiy veb-saytdan tushgan qabul arizalarini qabul qilish.
6. **Buxgalteriya & Kassa (`accounting.html`)**:
   - Kirim-chiqim kassa operatsiyalari, shifokorlar xizmat haqi va moliyaviy hisobotlar.
7. **Inson Resurslari & HR (`hr.html`)**:
   - Shifokor va xodimlar bazasi, 24/7 navbatchilik jadvali, T-13 tabel, maosh hisob-kitobi va Pay Slip chop etish.
8. **A4 Tibbiy Blanklar (`medical_blank.html`)**:
   - Rasmiy tibbiy epikriz va konsultatsiya blankalarini chop etish (PDF Generator integratsiyasi).

---

## 📁 Fayllar Strukturasi

```
fayzcontrol.uz/
├── server.py               # HTTP server va butun API (kirish, ruxsatlar, statik fayllar)
├── db.py                   # MySQL ulanish, qabul/ko'chirish/chiqarish mantig'i, migratsiyalar
├── auth.py                 # Parol xeshi, sessiyalar, kirish cheklovi
├── permissions.py          # Rollar va API/sahifa ruxsatlari
├── audit.py                # Audit jurnali (kim nimani o'zgartirdi)
├── consultation.py         # Konsultatsiya anketasi va davolash rejalari
├── nursery.py              # Hamshira dori aylanmasi, ko'rsatkichlar, statsionar ko'rigi
├── payroll.py              # Maosh hisobi (navbatchilik jadvali asosida)
├── owner_report.py         # Klinika egasi uchun pul hisoboti
├── pdf_generator.py        # ReportLab A4 PDF hujjatlar
├── telegram_service.py     # Telegram guruh xabarlari (token bo'lmasa o'chiq)
├── install.py              # Baza va modullarni tekshirish (faqat o'qiydi)
├── login.html, change-password.html
├── superpage.html          # Super-Portal (boshqaruv markazi)
├── reception.html          # Qabulxona: qabul, xonalar, saytdan so'rovlar, navbat, qo'ng'iroqlar
├── crm.html                # Bemorlar kartotekasi
├── consultation.html       # Shifokor konsultatsiyasi va davolash rejasi
├── doctor.html             # Shifokor posti (EMR, retseptlar, kundalik ko'rik)
├── ward.html               # Statsionar kunlik ko'rigi
├── nurse.html              # Hamshiralar posti
├── building_management.html # Karavotlar paneli
├── accounting.html         # Buxgalteriya va kassa
├── owner.html              # Klinika egasi hisoboti
├── hr.html                 # Kadrlar, davomat, maosh
├── duty_schedule.html      # Navbatchilik jadvali
├── medical_blank.html      # A4 tibbiy blanklar
├── index.html              # superpage.html ga yo'naltiradi
├── css/                    # Har sahifa uchun <sahifa>.css + unified_header.css, unified_print.css
├── js/                     # Har sahifa uchun <sahifa>.js + umumiy fayllar:
│                           #   fmh_dialogs.js (xabarlar, menyu), fmh_pricing.js (narxlar),
│                           #   fmh_plan_view.js (davolash rejasi ko'rinishi), theme_engine.js,
│                           #   unified_print_engine.js, xlsx.full.min.js
├── data/
│   ├── schema.mysql.sql    # MySQL sxemasi (yagona to'g'ri sxema)
│   ├── seed_data.sql       # Boshlang'ich ma'lumotlar
│   ├── users.json          # Foydalanuvchilar (server yozadi)
│   ├── clinic_rooms.json, pricing_config.json, duty_schedule.json  # server yozadi
│   └── pharmacology_db.json, fayz_house_meds.json                  # dori katalogi
├── scripts/                # backup.sh, restore-test.sh, prune-audit.py, cron fayli
├── tests/test_clinic.py    # Avtomatik testlar (server ishlab turganda)
├── README.md, CHANGES.md, DEPLOYMENT_AND_DOMAINS.md
└── robots.txt
```

---

## 🚀 Ishga Tushirish

```bash
# 0. Talab qilinadigan kutubxonalar
python3 -m pip install PyMySQL reportlab

# 1. Baza sozlamalarini yaratish
#    (db_config.example.json -> db_config.json, o'z parolingizni kiriting)
cp db_config.example.json db_config.json
chmod 600 db_config.json          # faqat egasi o'qiy olsin

# 2. Bazani yaratish — YANGI O'RNATISHDA MAJBURIY
#    Jadvallar avtomatik yaratilmaydi. Tartib muhim:
mysql -u <user> -p <database> < data/schema.mysql.sql   # jadvallar va view'lar
mysql -u <user> -p <database> < data/seed_data.sql      # 12 xona, 14 o'rin, xodimlar, katalog

# 3. Baza va tizim holatini tekshirish (faqat tekshiradi, yaratmaydi)
python3 install.py

# 4. Serverni ishga tushirish
python3 server.py 3000
```

`data/schema.mysql.sql` — **yagona to'g'ri sxema fayli**. Avval yana ikkitasi
bor edi (`data/schema_mysql.sql` va `data_mysql_dump.sql`); ikkalasi ham
eskirgan va `medication_administrations` jadvali yo'q edi — ya'ni ular bilan
o'rnatilgan tizimda hamshiralar posti ishlamasdi. Ular olib tashlandi.

`consultations` va `treatment_plans` jadvallari server birinchi marta shu
modullarga murojaat qilganda avtomatik yaratiladi.

Brauzerda: `http://localhost:3000` → `login.html` ochiladi. Tizimga
kirgandan so'ng `superpage.html` ga o'tadi.

### 💾 Zaxira Nusxa (Backup)

Bu tibbiy yozuvlar tizimi. Bazani yo'qotish — bemorlar tarixini yo'qotish
degani. Zaxira olish uchun tayyor skript bor:

```bash
./scripts/backup.sh            # zaxira oladi va eskilarini tozalaydi
./scripts/backup.sh --verify   # oladi va arxiv o'qilishini tekshiradi
./scripts/backup.sh --list     # hozir nima saqlanayotganini ko'rsatadi
```

Ulanish ma'lumotlarini `db_config.json` dan oladi — parol **buyruq satrida
ko'rinmaydi** (u vaqtinchalik `0600` faylga yoziladi va skript tugashi bilan
o'chiriladi).

Sozlamalar (ixtiyoriy):

| O'zgaruvchi | Ma'nosi | Standart |
| :--- | :--- | :--- |
| `FMH_BACKUP_DIR` | Zaxiralar papkasi | `/var/backups/fayzcontrol` |
| `FMH_BACKUP_KEEP_DAYS` | Necha kun saqlanadi | `30` |

**Har kecha avtomatik olish:**

```bash
sudo cp scripts/fayzcontrol-backup.cron /etc/cron.d/fayzcontrol-backup
# ichidagi yo'l va foydalanuvchini o'z serveringizga moslang
```

Zaxira **bazadan boshqa diskda** turishi kerak — disk ishdan chiqsa,
baza bilan zaxira birga yo'qolmasin.

#### Tiklashni sinab ko'rish — bu majburiy

Tekshirilmagan zaxira zaxira emas. Buni bir marta bajaring:

```bash
./scripts/restore-test.sh
```

Skript eng oxirgi arxivni **alohida vaqtinchalik bazaga** tiklaydi, uni
jonli baza bilan jadval-ma-jadval solishtiradi va vaqtinchalik nusxani
o'chiradi. **Jonli bazaga tegmaydi.** Natija shunday bo'lishi kerak:

```
[restore-test] tables  live=24  restored=24
[restore-test] views   live=5   restored=5
[restore-test] RESULT: the archive reproduces the database exactly
```

Bunga `CREATE DATABASE` huquqi bor hisob kerak (masalan `root`) — ilovaning
o'z hisobida bunday huquq ataylab yo'q:

```bash
FMH_ADMIN_DB_USER=root FMH_ADMIN_DB_PASSWORD=... ./scripts/restore-test.sh
```

### 🔐 Avtorizatsiya

Barcha `/api/*` so'rovlari va portal sahifalari **tizimga kirishni talab
qiladi**. Sessiya `HttpOnly` cookie'da saqlanadi va standart holatda 12 soat
faol turadi (`FMH_SESSION_IDLE_SECONDS` bilan o'zgartirish mumkin).

Parollar `data/users.json` faylida **PBKDF2-SHA256** bilan xeshlanadi. Eski
ochiq matnli parollar server birinchi ishga tushganda avtomatik xeshlanadi —
xodimlar parollarini o'zgartirishi shart emas.

> ⚠️ Har bir hisob birinchi kirishda parolni almashtirishni talab qiladi
> (`must_change_password`). Boshlang'ich parollar tarqatilgan arxivda
> bo'lgani uchun ularni albatta almashtiring — hujjatlarda ular
> ataylab keltirilmagan.

### 👤 Rollar va Ruxsatlar

Har bir xodim faqat o'z ishiga tegishli bo'limlarni ko'radi. Rollar va ularning
ruxsatlari `permissions.py` faylida bir joyda belgilangan — rolni
o'zgartirsangiz, o'sha roldagi barcha xodimlarga darhol qo'llaniladi.

| Rol | Lavozim | Asosiy sahifa |
| :-- | :------ | :------------ |
| `superadmin` | Bosh administrator | Super-Portal |
| `admin` | Administrator | Super-Portal |
| `chief_doctor` | Bosh shifokor | Shifokor posti |
| `doctor` | Shifokor | Shifokor posti |
| `nurse` | Hamshira | Bemorlar (hamshira posti tayyorlanmoqda) |
| `receptionist` | Qabulxona xodimi | Qabulxona |
| `accountant` | Buxgalter / Kassir | Buxgalteriya |
| `hr_manager` | Kadrlar bo'limi | HR |
| `pharmacist` | Farmatsevt | Super-Portal |
| `ward_manager` | Statsionar menejeri | Statsionar |
| `kitchen_staff` | Oshxona xodimi | Statsionar |

Muhim ajratmalar:

- **Qabulxona** bemorni ro'yxatga oladi va statsionarga joylashtiradi, lekin
  **chiqarish va ko'chirish** — klinik qaror, shuning uchun statsionar va
  shifokorlarga tegishli.
- **Xonalarni sozlash** (qo'shish/o'chirish) faqat statsionar menejeri va
  administratorda.
- **Hamshira** retseptlarni o'qiydi, lekin yozmaydi; shifokor kabinetini
  ko'rmaydi.
- **Farmatsevt** retseptlarni ko'radi, lekin tayinlay olmaydi.
- **Kadrlar bo'limi** bemorlar ma'lumotlariga umuman kirmaydi.

Yangi ruxsat qoidasi yozilmagan endpoint **hamma uchun taqiqlanadi** (hatto
superadmin uchun ham) — bu yangi endpoint tasodifan ochiq qolishining oldini
oladi.

### 📝 Audit Jurnali

Har bir o'zgartirish, kirish va rad etilgan urinish `audit_logs` jadvaliga
yoziladi: kim, nima, qachon, qaysi IP dan. Sozlash shart emas.

```sql
SELECT entity_name, entity_id, action_type,
       JSON_UNQUOTE(JSON_EXTRACT(new_data_json,'$._actor')) AS actor,
       ip_address, timestamp
FROM audit_logs ORDER BY id DESC LIMIT 50;
```

**Saqlash muddati.** Jurnal o'z-o'zidan cheklanmaydi — sinov paytida bir necha
kunda 82 000 yozuvga yetdi. Endi `timestamp` bo'yicha indeks bor (usiz sana
bo'yicha qidiruv butun jadvalni o'qirdi) va tozalash skripti:

```bash
./scripts/prune-audit.py --dry-run   # nima o'chishini aytadi, o'chirmaydi
./scripts/prune-audit.py             # sozlangan muddatni qo'llaydi
./scripts/prune-audit.py --days 365  # bir marta boshqa muddat
```

Standart **730 kun (2 yil)** — ataylab uzoq, chunki bu tibbiy audit jurnali va
uni qancha saqlash klinika va nazorat organi qaroriga bog'liq.
`FMH_AUDIT_KEEP_DAYS=0` — hech narsa o'chirilmaydi.

Haftalik tozalash `scripts/fayzcontrol-backup.cron` ichida.

### 🩺 Servis Holati (monitoring)

```bash
curl https://fayzcontrol.uz/api/health
```

`{"status":"ok","database":"ok"}` va **200** — hammasi joyida.
Baza yiqilsa **503** va `"database":"unreachable"`.

Buni kuzatuvchi tizimga ulang. **Sahifaning o'zini tekshirish yetarli emas:**
baza o'chgan holatda ham `login.html` **200 qaytaradi** — sahifalar ochiladi,
lekin xodim hech narsa qila olmaydi. Faqat shu endpoint buni ko'rsatadi.

Endpoint avtorizatsiyasiz javob beradi (kuzatuvchi tizim tizimga kira olmaydi)
va ataylab hech qanday versiya, son yoki xato matnini bermaydi.

### 🔒 Kirishni Cheklash

Noto'g'ri parol bilan urinishlar hisoblanadi: bitta hisob uchun 8 marta
(`FMH_LOGIN_MAX_FAILURES`), bitta IP uchun 50 marta
(`FMH_LOGIN_MAX_IP_FAILURES`) — IP chegarasi ataylab yuqori, chunki Nginx
ortida butun klinika bitta manzil sifatida ko'rinadi va bir xodimning xatosi
hammani bloklab qo'ymasligi kerak. Bloklash muddati 15 daqiqa
(`FMH_LOGIN_LOCKOUT_SECONDS`).

### 🌐 Tarmoq sozlamalari

Server standart holatda **faqat `127.0.0.1`** manzilini tinglaydi, ya'ni
`DEPLOYMENT_AND_DOMAINS.md` da tavsiflangan Nginx reverse-proxy sxemasiga
mos keladi. Boshqa manzilda tinglash uchun:

```bash
BIND_HOST=0.0.0.0 python3 server.py 3000   # faqat proxy va TLS ortida!
BIND_PORT_80=1    python3 server.py 3000   # 80-portni ham egallash
```

### 🧪 Testlar

```bash
# server ishlab turgan holatda, boshqa terminalda:
python3 tests/test_clinic.py
python3 tests/test_clinic.py -v
python3 tests/test_clinic.py Overlap      # faqat mos keladigan testlar
```

Test to'plami avtorizatsiya chegarasi, karavot band qilish mantiqi, bir
vaqtdagi so'rovlar, moliyaviy hisob-kitob va PDF eksportini tekshiradi.
**Testlar haqiqiy yozuvlar yaratadi — ishlab chiqarish bazasida ishlatmang.**

---

## 🌐 Domen & Bog'lanish

- **CRM Domeni**: `https://crm.fayzmedical.uz` (yoki `https://crm.sayt.uz`)
- **Veb-sayt bilan aloqa**: `D:\01.Projects\website-main` dagi rasmiy veb-sayt foydalanuvchilari qabulga yozilganda, arizalar avtomatik ravishda mazkur CRM serverining `/api/reception/appointment` va `/api/reception/call-log` endpointlariga tushadi.
