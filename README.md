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
# 1. Baza va tizim holatini tekshirish
python install.py

# 2. Serverni ishga tushirish
python server.py
# yoki
.\start_clinic.bat
```

Brauzerda: `http://localhost:3000` (avtomatik ravishda `superpage.html` ochiladi).

---

## 🌐 Domen & Bog'lanish

- **CRM Domeni**: `https://crm.fayzmedical.uz` (yoki `https://crm.sayt.uz`)
- **Veb-sayt bilan aloqa**: `D:\01.Projects\website-main` dagi rasmiy veb-sayt foydalanuvchilari qabulga yozilganda, arizalar avtomatik ravishda mazkur CRM serverining `/api/reception/appointment` va `/api/reception/call-log` endpointlariga tushadi.
