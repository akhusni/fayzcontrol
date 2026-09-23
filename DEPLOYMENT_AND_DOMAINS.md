# Fayz Control (fayzcontrol.uz) — Serverga O'rnatish va FastPanel Qo'llanmasi

Ushbu qo'llanma **Fayz Medical House** shifoxona boshqaruvi, EMR va CRM tizimini yangi ro'yxatdan o'tkazilgan **`fayzcontrol.uz`** domenida ishga tushirish uchun to'liq yo'riqnomadir.

---

## 🌐 1. Tizim Arxitekturasi

| Loyiha | Domen | Vazifasi | Mahalliy Papka |
| :--- | :--- | :--- | :--- |
| **Klinika CRM & EMR** | **`https://fayzcontrol.uz`** | Shifokorlar, Bemorlar, EMR, Kassa, HR, Statsionar | `D:\01.Projects\fayzcontrol` (yoki `website`) |
| **Rasmiy Veb-Sayt** | **`https://fayzmedical.uz`** | Mijozlar uchun marketing, ma'lumot, qabulga yozilish | `D:\01.Projects\website-main` |

---

## 🔒 2. FastPanel'da SSL Sertifikatini Olish (Sizning Ekrangiz)

1. Ekranda ko'ringan oynada **"Issue"** tugmasini bosing:
   - **Domain**: `fayzcontrol.uz`
   - **Domain name**: `fayzcontrol.uz www.fayzcontrol.uz`
   - **Mailbox**: `webmaster@fayzcontrol.uz`
2. Agar domen DNS'i serveringiz IP manziliga to'g'ri yo'naltirilgan bo'lsa, Let's Encrypt bir necha soniyada bepul SSL sertifikatini o'rnatadi.
3. Sozlamalarda **"Redirect HTTP to HTTPS"** parametrini yoqing.

---

## 📂 3. CRM Fayllarini Serverga Yuklash

FastPanel File Manager (yoki SFTP/FileZilla) orqali `D:\01.Projects\fayzcontrol` papkasidagi barcha fayllarni saytingizning asosiy katalogiga yuklang:
```text
/var/www/<foydalanuvchi>/data/www/fayzcontrol.uz/
```

Katalog tarkibi quyidagicha bo'ladi:
- `superpage.html`
- `crm.html`
- `doctor.html`
- `reception.html`
- `building_management.html`
- `accounting.html`
- `hr.html`
- `medical_blank.html`
- `server.py`
- `.htaccess` (faqat himoya qoidalari)
- `robots.txt`
- `data/` (sxema va JSON konfiguratsiyalari — klinik ma'lumotlar MySQL'da)
- `db_config.json` (arxivda yo'q — `db_config.example.json` dan nusxa oling)
- `css/`
- `js/`
- `assets/`

---

## ⚙️ 4. Serverda Ishga Tushirish (Systemd + Nginx)

> **Diqqat — eski "Apache + `api.php`" usuli olib tashlandi.**
>
> Avvalgi qo'llanmada "eng oson" deb ko'rsatilgan usul xavfli edi va endi
> ishlamaydi:
>
> - `.htaccess` dagi `DirectoryIndex superpage.html` Apache'ga HTML
>   sahifalarni **to'g'ridan-to'g'ri diskdan** berishni buyurardi. Sahifa
>   himoyasi `server.py` ichida — ya'ni bu holda **hech qanday tekshiruv
>   ishlamaydi**: `doctor.html`, `crm.html`, `accounting.html` va boshqa
>   barcha portallar **istalgan odamga, parolsiz** ochilardi.
> - `api.php` cookie'ni `server.py` ga **uzatmasdi** va javobdagi
>   `Set-Cookie` ni qaytarmasdi, shuning uchun avtorizatsiya
>   **umuman ishlamas edi**.
> - `api.php?restart_backend` **hech qanday parolsiz** serverni o'chirib
>   qayta ishga tushirardi va `server_log.txt` ning oxirgi qismini
>   qaytarardi.
>
> `api.php` o'chirildi. `.htaccess` faqat himoya qoidalari sifatida
> qoldirildi (manba kodi, `db_config.json` va `data/` ni yuklab olishni
> taqiqlaydi).

Yagona qo'llab-quvvatlanadigan usul — `server.py` ni systemd xizmati
sifatida ishga tushirib, oldiga Nginx qo'yish.

1. Servis faylini yarating:
   ```bash
   sudo nano /etc/systemd/system/fayzcontrol.service
   ```
2. Quyidagi matnni qo'ying:
   ```ini
   [Unit]
   Description=Fayz Control CRM Service
   After=network.target mysql.service

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/var/www/fayzcontrol/data/www/fayzcontrol.uz
   ExecStart=/usr/bin/python3 server.py 3000
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   ```

   `server.py` faqat `127.0.0.1` ni tinglaydi — bu ataylab shunday.
   `BIND_HOST` ni o'zgartirmang.

3. Servisni yoqing va ishga tushiring:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now fayzcontrol.service
   sudo systemctl status fayzcontrol.service
   ```

4. FastPanel'da sayt sozlamalari → **Nginx** bo'limiga quyidagini qo'shing:
   ```nginx
   location / {
       proxy_pass http://127.0.0.1:3000;
       proxy_set_header Host              $host;
       proxy_set_header X-Real-IP         $remote_addr;
       proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

   **`X-Forwarded-Proto` majburiy.** Sessiya cookie'siga `Secure`
   belgisi aynan shu sarlavhaga qarab qo'yiladi; usiz cookie HTTPS
   talab qilmaydigan holatda yuboriladi.

   **`X-Real-IP` ham majburiy.** Kirishni cheklash va audit jurnali
   shu manzilga tayanadi; usiz butun klinika bitta IP (`127.0.0.1`)
   sifatida ko'rinadi.

5. Tekshiring — ro'yxatdan o'tmasdan portal ochilmasligi kerak:
   ```bash
   curl -sI https://fayzcontrol.uz/doctor.html | head -1   # 302 -> /login.html
   curl -s  https://fayzcontrol.uz/api/patients            # 401
   curl -sI https://fayzcontrol.uz/db_config.json | head -1 # 403/404, hech qachon 200
   ```

---

## 🔗 5. Veb-Sayt Bilan Integratsiya

Rasmiy sayt (`fayzmedical.uz`) dagi yozilish formasi CRM ga ulanadi.

> **Nima o'zgardi.** Avval forma to'g'ridan-to'g'ri
> `/api/reception/appointment` ga yozardi. Butun `/api/*` avtorizatsiya
> talab qila boshlagach, o'sha endpoint **401** qaytaradigan bo'ldi va
> arizalar **jimgina yo'qola boshladi** — hech qayerda qayd etilmasdi va
> hech kimga xabar berilmasdi. Endi ular uchun alohida ochiq endpoint bor.

### Sayt shu manzilga yuboradi

```
POST https://fayzcontrol.uz/api/public/appointment-request
Content-Type: application/json

{
  "full_name":      "Aziza Rahimova",      // majburiy
  "phone":          "+998 90 111 22 33",   // majburiy
  "preferred_date": "2026-10-05",          // ixtiyoriy, o'tgan sana bo'lmasin
  "service_type":   "consultation",        // ixtiyoriy
  "note":           "Konsultatsiyaga yozilmoqchiman",  // ixtiyoriy
  "website":        ""                     // TUZOQ: ko'rinmas maydon, bo'sh qolsin
}
```

Javob **201** va `{"message": "...", "request_id": "REQ-..."}`.

Formaga `website` nomli **yashirin** maydon qo'ying (CSS bilan bekiting).
Odam uni ko'rmaydi va to'ldirmaydi; bot esa har bir maydonni to'ldiradi.
To'ldirilgan bo'lsa server **201 qaytaradi, lekin hech narsa saqlamaydi** —
bot buni bilib ololmaydi.

### Bu endpoint nima qiladi va nima qilmaydi

- Faqat `appointment_requests` jadvaliga yozadi. **Bemor kartasi ochilmaydi,
  navbat band qilinmaydi** — bu tekshirilmagan ma'lumot.
- Qabulxona "Saytdan So'rovlar" tabida ko'radi. **"Qabul qilish"** bosilgandagina
  bemor kartasi ochiladi va navbatga yoziladi. Spam bazani to'ldira olmaydi.
- Bir IP dan **soatiga 5 ta** ariza va **kuniga 20 ta** (urinishlar alohida
  hisoblanadi — telefon raqamini xato yozish arizani "yeb" qo'ymaydi).
- Tizimdagi **yagona** avtorizatsiyasiz yoziladigan yo'l. Qolgan barcha
  `/api/*` avvalgidek yopiq.

### CORS

Sayt boshqa domenda, shuning uchun **faqat shu endpoint** CORS javobini
beradi va **faqat ro'yxatdagi domenlar uchun**. Standart:
`https://fayzmedical.uz` va `https://www.fayzmedical.uz`. O'zgartirish:

```ini
Environment=FMH_PUBLIC_SITE_ORIGIN=https://fayzmedical.uz,https://www.fayzmedical.uz
```

(systemd servis faylida). Boshqa domendan kelgan so'rovga CORS sarlavhasi
berilmaydi va brauzer uni bloklaydi.

### Sozlamalar

| O'zgaruvchi | Ma'nosi | Standart |
| :--- | :--- | :--- |
| `FMH_PUBLIC_SITE_ORIGIN` | CORS ruxsat etilgan domenlar (vergul bilan) | `https://fayzmedical.uz,https://www.fayzmedical.uz` |
| `FMH_PUBLIC_ENQUIRY_PER_HOUR` | Bir IP dan soatiga saqlanadigan ariza | `5` |
| `FMH_PUBLIC_ENQUIRY_PER_DAY` | Bir IP dan kuniga | `20` |
| `FMH_PUBLIC_ENQUIRY_ATTEMPTS_PER_HOUR` | Bir IP dan soatiga urinish (xatolar ham) | `30` |

### Tekshirish

```bash
curl -i -X POST https://fayzcontrol.uz/api/public/appointment-request \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://fayzmedical.uz' \
  -d '{"full_name":"Test Bemor","phone":"+998901112233"}'
```

`201` va `Access-Control-Allow-Origin: https://fayzmedical.uz` bo'lishi kerak.
So'ng qabulxonada "Saytdan So'rovlar" tabini oching — ariza shu yerda turadi.
