# Fayz Medical House — Hospital Management & Clinical EMR Suite

Toshkent shahridagi **"Fayz Medical House"** xususiy klinikasi uchun to'liq integratsiyalashgan, xavfsiz va SQLite ma'lumotlar bazasiga ulangan avtonom shifoxona boshqaruv tizimi (Hospital Information System / EMR & CRM).

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
crm-suite/
├── superpage.html          # 10 Bo'limli Yagona Boshqaruv Super-Portali (Default /)
├── doctor.html             # Shifokor Posti, EMR, Kasallik Tarixi & Retseptlar
├── crm.html                # Bemorlar CRM & Kasallik Tarixi Portali
├── building_management.html # 1-Bino 14-karavotli statsionar boshqaruv pulti
├── accounting.html         # Buxgalteriya, kassa, to'lovlar va moliya
├── hr.html                 # Inson resurslari, davomat, smenalar va maosh
├── reception.html          # Qabulxona, navbatlar va qo'ng'iroqlar
├── medical_blank.html      # A4 Tibbiy Epikriz va blank chop etish
├── server.py               # SQLite REST API & Web Server (Auto-redirect / -> superpage.html)
├── pdf_generator.py        # ReportLab A4 rasmiy tibbiy epikriz generatori
├── install.py              # Baza va modullarni o'rnatish tekshiruvi
├── start_clinic.bat        # Windows bir-bosishda ishga tushirish skripti
├── run_clinic_server.ps1   # PowerShell orqali ishga tushirish skripti
├── api.php                 # Apache / cPanel uchun API proksi
├── DEPLOYMENT_AND_DOMAINS.md # Domen va serverga o'rnatish qo'llanmasi
├── robots.txt              # Maxfiylik nazorati (barcha qidiruv botlarini bloklaydi)
├── css/
│   ├── crm.css
│   ├── doctor.css
│   ├── superpage.css
│   ├── building_management.css
│   ├── accounting.css
│   ├── hr.css
│   ├── reception.css
│   ├── unified_header.css  # Yagona navigatsiya tizimi
│   └── unified_print.css   # Chop etish tizimi
├── js/
│   ├── crm.js
│   ├── doctor.js
│   ├── superpage.js
│   ├── building_management.js
│   ├── accounting.js
│   ├── hr.js
│   ├── reception.js
│   └── xlsx.full.min.js
└── data/
    ├── fayz_clinic.db      # SQLite relational production baza
    ├── schema.sql          # DB relyatsion sxemasi
    ├── seed_data.sql       # Boshlang'ich klinik ma'lumotlar
    ├── hr_db.json
    ├── accounting_db.json
    ├── reception_db.json
    ├── clinic_rooms.json
    └── pharmacology_db.json
```

---

## 🚀 Ishga Tushirish

```powershell
# 0. Talab qilinadigan kutubxonalar
python -m pip install PyMySQL reportlab

# 1. Baza sozlamalarini yaratish
#    (db_config.example.json -> db_config.json, o'z parolingizni kiriting)
copy db_config.example.json db_config.json

# 2. Baza va tizim holatini tekshirish
python install.py

# 3. Serverni ishga tushirish
python server.py
# yoki
.\start_clinic.bat
```

Brauzerda: `http://localhost:3000` → `login.html` ochiladi. Tizimga
kirgandan so'ng `superpage.html` ga o'tadi.

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
