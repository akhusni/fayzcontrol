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

## 🔗 5. Veb-Sayt Bilan Integratsiya — **HOZIRDA ISHLAMAYDI**

Avval rasmiy sayt (`fayzmedical.uz`) qabulga yozilish arizasini
`https://fayzcontrol.uz/api/reception/appointment` ga yuborardi va u
to'g'ridan-to'g'ri CRM ga tushardi.

**Bu endi ishlamaydi va buni bilib turish kerak.** Butun `/api/*`
avtorizatsiya talab qiladi, `/api/reception/appointment` esa ochiq
endpointlar ro'yxatida emas (`auth.py` → `PUBLIC_API_PATHS`). Sayt
formasi endi **401** oladi va ariza **hech qayerga tushmaydi** —
jimgina yo'qoladi.

Uchta variant bor, qaysi birini tanlashni klinika hal qiladi:

1. **Hozircha shunday qoldirish** va saytdagi formani telefon raqamiga
   almashtirish. Eng xavfsiz, lekin onlayn yozilish yo'qoladi.
2. **Alohida ochiq endpoint** qo'shish (masalan
   `/api/public/appointment-request`): faqat yozish, faqat "yangi
   ariza" holatida saqlaydi, IP bo'yicha cheklangan va
   qabulxona tasdiqlamaguncha bemor kartasi yaratilmaydi. Spam va
   bazani to'ldirish xavfi bor, shuning uchun cheklov majburiy.
3. **Sayt uchun alohida xizmat hisobi** va API kaliti — sayt backend'i
   (brauzer emas) shu kalit bilan murojaat qiladi.

Tavsiya: **2-variant**, lekin bu alohida ish va deploydan oldin
qilinishi shart emas. Muhimi — hozir forma ishlamasligini bilish.
