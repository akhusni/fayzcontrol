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
- `api.php`
- `.htaccess`
- `robots.txt`
- `data/` (fayz_clinic.db va JSON bazalar)
- `css/`
- `js/`
- `assets/`

---

## ⚙️ 4. Serverda Ishga Tushirishning 2 Ta Usuli

### Usul 1 (Eng Oson — PHP & Apache orqali):
Sayt papkasiga yuklangan `.htaccess` va `api.php` tayyor sozlangan:
- Foydalanuvchi `https://fayzcontrol.uz` ga kirganda, `.htaccess` avtomatik tarzda `superpage.html` ni ochadi.
- API so'rovlari (`/api/*`) kelganda, `api.php` avtomatik tarzda `server.py` ni orqa fonda uyg'otadi va so'rovlarni unga yo'naltiradi. Hech qanday murakkab sozlash shart emas!

### Usul 2 (Professional — Linux Systemd Service & Nginx Proxy):
Server terminalida (SSH):
1. Servis faylini yarating:
   ```bash
   sudo nano /etc/systemd/system/fayzcontrol.service
   ```
2. Quyidagi matnni qo'ying:
   ```ini
   [Unit]
   Description=Fayz Control CRM Service
   After=network.target

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/var/www/fayzcontrol/data/www/fayzcontrol.uz
   ExecStart=/usr/bin/python3 server.py
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   ```
3. Servisni yoqing va ishga tushiring:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now fayzcontrol.service
   ```

4. FastPanel'da sayt sozlamalari -> **Nginx** bo'limiga quyidagini qo'shing:
   ```nginx
   location / {
       proxy_pass http://127.0.0.1:3000;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

---

## 🔗 5. Veb-Sayt Bilan Integratsiya

Rasmiy saytingiz (`website-main`) foydalanuvchisi qabulga yozilganda, arizalar avtomatik ravishda `https://fayzcontrol.uz/api/reception/appointment` manziliga kelib tushadi va CRM da darhol aks etadi.
