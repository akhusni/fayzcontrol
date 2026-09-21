# Fayz Control — O'zgarishlar Hisoboti

**Loyiha:** Fayz Medical House — Hospital Management & EMR Suite
**Holat:** 120 avtomatlashtirilgan test, barchasi muvaffaqiyatli o'tadi
**Sana:** 2026-yil sentabr

---

## 1. Tuzatilgan xatolar (backend)

Har biri qayta ishlab chiqarilgan (reproduced), tuzatilgan va test bilan
qoplangan.

| Xato | Oqibati |
| :--- | :------ |
| Karavot band qilishda sana tekshiruvi teskari bog'langan edi | **Bitta karavotga ikki bemor** joylashtirilishi mumkin edi. Qisman ustma-ust tushgan har qanday yotish qabul qilinardi. |
| Bir sekundda yaratilgan ikki qabul bir xil ID olardi | Ikkinchi qabul **sezilmasdan yo'qolardi** (`Duplicate entry`). |
| JSON fayllarga parallel yozish himoyalanmagan edi | Test paytida **8 foydalanuvchidan 2 tasi qoldi** — `superadmin` ham o'chib ketdi. |
| Xodim ID si `COUNT(*)` asosida yaratilardi | Parallel qo'shishda **mavjud xodim ustiga yozilardi**, tizim esa "saqlandi" deb javob berardi. 3 hamshiradan 1 tasi qolgan. |
| `pdf_generator.py` da sintaksis xatosi | **Barcha PDF eksport ishlamas holatda edi** — xato `except` bloki tomonidan yashiringan. |
| PDF chaqiruvi bayt massivini fayl yo'li deb qabul qilardi | PDF endpoint doim 404 qaytarardi. |
| Bemor/to'lov ID lari 9000 qiymatdan tasodifiy tanlanardi | ~112 bemordan keyin ID to'qnashuvi ehtimoli 50% — ro'yxatga olish xatolik bilan tugardi. |
| Qabulni o'chirishda hisob-kitob satrlari qolib ketardi | **Bemor boshqa bemorning yotishi uchun hisoblanardi.** 10 kunlik yotishga 17 kun yozilgan. |
| `beds.status` ga `'available'` yozilardi (4 joyda) | Karavotni xizmatga qaytarish **umuman ishlamasdi** — karavotlar `cleaning` holatida qolib, palata bo'shab qolardi. |
| Muvaffaqiyatsiz qabul bemor yozuvini qoldirardi | Har bir rad etilgan qabul "Yangi Bemor" nomli keraksiz yozuv qoldirardi. |
| `building_management.js` da cheksiz rekursiya | Haqiqiy bronlar mavjud bo'lganda sahifa stack overflow bilan ishlamay qolardi. |
| "Butun xona" qoidasi faqat brauzerda edi | Xona **1.1 mln/kun** ga yaxlit sotilgandan keyin ham ikkinchi o'ringa bemor qo'yish qabul qilinardi. Ya'ni bemor alohida xona uchun to'lab, yoniga begona odam joylashtirilishi mumkin edi. Ko'chirish (transfer) yo'li ham xuddi shunday ochiq edi. |
| Shifokorning kunlik ko'rigi **hech qachon saqlanmagan** | `POST /api/doctor/notes` mavjud bo'lmagan `vital_bp` ustuniga yozardi — har bir saqlash 500 xatolik qaytarardi. `doctor_daily_notes` jadvali ishlatilayotgan bazada **bo'm-bo'sh** edi: interfeys ishlayotgandek ko'rinardi va shifokor yozgan hamma narsani jimgina yo'qotardi. |
| Ko'rik to'ldirilmagan ko'rsatkichlarni **o'ylab topardi** | Bo'sh qoldirilsa avtomatik `120/80`, puls `72`, `36.6°`, SpO2 `98` yozilardi. Tibbiy yozuvda o'ylab topilgan ko'rsatkichni o'lchangandan ajratib bo'lmaydi — ular imzolanib, rasmiy hujjatga tushardi. |
| Ro'yxatga olishda jins va tug'ilgan sana so'ralmasdi | Server ularni o'zi to'ldirardi: **har bir bemor "erkak, 1990-yilda tug'ilgan"** deb yozilardi. Konsultatsiya saqlanganda esa bu qiymatlar **to'g'ri yozuvni ham ustidan yozardi**. |
| Konsultatsiya boshqa bemorga yozilishi mumkin edi | Bemorni qidirish `phone = ? OR full_name = ?` edi va telefon bo'sh bo'lsa ham solishtirardi. Ko'pchilik yozuvda telefon bo'sh — shuning uchun raqam qoldirmagan bemorning tashrifi **birinchi uchragan begona bemorga** yozilardi. |
| Hamshira ko'rsatkichlarini saqlay olmasdi | `daily_logs` faqat o'qish uchun ochiq edi — yozish yo'li umuman yo'q edi. |
| Sana chegarasi hisob-kitob bilan mos emasdi | Hisob-kitob `DATEDIFF(end, start)` — ketish kuni tunab qolinmaydi. Tekshiruv esa ikkala chetini ham band deb hisoblardi, shuning uchun **bemor chiqqan kuni yangi bemorni qabul qilib bo'lmasdi**: panel o'rinni bo'sh ko'rsatar, server esa rad etardi. |

---

## 2. Interfeys va foydalanish qulayligi

| Muammo | Yechim |
| :--- | :--- |
| Shifokor sahifasida retseptni o'chirish **hech narsa so'ramasdi** | Umumiy tasdiqlash oynasi barcha 8 sahifaga chiqarildi. |
| 14 ta brauzer `confirm()` va 11 ta `alert()` | Yagona uslubdagi dialog va bildirishnomalarga o'tkazildi (allergiya ogohlantirishlari ham). |
| Klaviatura fokusi ko'rinmasdi | `:focus-visible` qo'shildi — sichqoncha bilan ishlashda ko'rinish o'zgarmaydi. |
| Bildirishnomalar 1.8 soniyada yo'qolardi, o'qilmagani ustiga yozilardi | Muddat xatolik darajasiga qarab 3.2–9 soniya, yopish tugmasi, `aria-live`. |
| Sarlavhadagi tugmalar bir-birining ustiga chiqardi | **1081–1640px oralig'ida** (ya'ni ko'pchilik ekranlarda) tuzatildi. 8 sahifa × 8 o'lcham = 64 holat tekshirildi. |
| Statistika chiplari bir-biriga qo'shilib ketgandi | Har biri alohida ajratildi. |
| Bosma blankdagi logo tashqi (o'chgan) xizmatdan yuklanardi | Ichki SVG bilan almashtirildi. |

---

## 3. Xavfsizlik

Avval `/api/*` ning **barcha** endpointlari va portal sahifalari
avtorizatsiyasiz ochiq edi. Loyihaning o'z Nginx sxemasi bo'yicha bu
`fayzcontrol.uz` orqali **internetga ochiq** degani edi.

- **Avtorizatsiya:** server tomonida sessiyalar, `HttpOnly` + `SameSite=Strict`
  cookie, kirish sahifasi. Frontenddagi ~100 ta so'rovni o'zgartirish
  talab qilinmadi.
- **Parollar xeshlangan:** PBKDF2-SHA256, 240 000 iteratsiya. Eski ochiq
  matnli parollar server ishga tushganda avtomatik xeshlandi — xodimlar
  parolini almashtirishi shart bo'lmadi.
- **Rollar va ruxsatlar:** 11 ta rol, 53 endpoint va 12 sahifa
  ruxsatlar jadvaliga bog'landi. Ruxsat qoidasi yozilmagan endpoint
  **hamma uchun** taqiqlanadi (superadmin uchun ham).
- **Audit jurnali:** har bir o'zgartirish, kirish va rad etilgan urinish
  `audit_logs` ga yoziladi — kim, nima, qachon, qaysi IP.
- **Kirishni cheklash:** bir hisob uchun 8, bir IP uchun 50 urinish.
  IP chegarasi ataylab yuqori: Nginx ortida butun klinika bitta manzil
  sifatida ko'rinadi va bir xodimning xatosi hammani bloklab
  qo'ymasligi kerak.
- **Tarmoq:** server faqat `127.0.0.1` ni tinglaydi — loyihaning o'z
  Nginx konfiguratsiyasiga mos.
- **Ma'lumotlar bazasi paroli** `db.py` dan olib tashlandi (avval
  konfiguratsiya yo'qolsa ishlab chiqarish bazasiga ulanardi) va
  `database_report.html` dagi ochiq parol ham.

---

## 4. Yangi imkoniyatlar

### Hamshiralar posti (`nurse.html`)

Avval tizim retsept yozishni bilardi, lekin **dori berilganini qayd
qilish imkoniyati yo'q edi**.

- Kunlik dori berish jadvali retseptlardan **avtomatik hosil qilinadi** —
  shu sababli kelajakdagi kunni ham ko'rish mumkin.
- Kalendar: o'tgan kunlar (kim nima qabul qilgan) va kelajak (kim nima
  qabul qiladi).
- `Kuniga 1-2 mahal` — shifokor tanloviga qoldirilgan oraliq: pastki
  chegara rejalashtiriladi, ruxsat etilgan maksimum ko'rsatiladi.
- `Zarurat tug'ilganda` — jadvalga **qo'yilmaydi**, aks holda har kuni
  "o'tkazib yuborilgan" deb hisoblanardi.
- `har 8 soatda` — kuniga 3 marta (8 marta emas).
- A4 bosma varaqa: klinika blankasi, imzo ustuni, holat rangsiz
  printerda ham o'qiladi.

### Shifokor konsultatsiyasi (`consultation.html`)

Narkologiya/psixiatriya uchun **6 bo'limli, 41 maydonli** anketa.

- Bemor ma'lumotlari, davolash asosi (o'z xohishi / oila / sud qarori),
  asosiy muammo, moddalar tarixi, psixiatrik va tibbiy anamnez, oila va
  ijtimoiy muhit, klinik baholash va xavf darajasi.
- **Davolash rejasi alohida saqlanadi va alohida chop etiladi.** Anketa —
  bir suhbatdagi holatning o'zgarmas qaydi; reja esa qayta ko'rib
  chiqiladigan ko'rsatma. Yangi faol reja avvalgisini almashtiradi.
- Sud qarori raqamisiz sud qarori bilan davolash saqlanmaydi;
  protokolsiz detoks rejasi saqlanmaydi.
- Qabulxonadan yo'naltirilgan bemorlar navbati — resepshn olgan
  ma'lumotlar avtomatik to'ldiriladi.

### Qabulxona: xonalar holati paneli (`reception.html`)

Qabulxonaning kunlik birinchi savoli — **qaysi xona bo'sh va qachongacha**.
Avval bunga javob yo'q edi: qabul shaklidagi karavot tanlash faqat o'sha
shakl so'ragan sanalarni va 14 ta alohida o'rinni ko'rsatardi, klinika esa
xonani yaxlit sotadi.

- Yangi **"Xonalar Holati"** tabi: qavatlar bo'yicha xonalar, har birida
  o'rinlar, kim yotgani va qaysi sanagacha. Sana oralig'ini tanlash
  (Bugun / 1 hafta / 10 kun / 1 oy).
- **Butun xona** band bo'lganda ikkinchi o'rin `bo'sh` ham, `band` ham emas —
  *"butun xona (bo'sh turadi)"* deb ko'rsatiladi: u pullangan va ataylab
  bo'sh qoldirilgan.

### Statsionar kunlik ko'rigi (`ward.html`)

Avval ko'rik faqat bitta bemor ichida, EMR sahifasida bor edi — **ro'yxat
yo'q edi**. Shifokor kim yotganini oldindan bilishi va har bir kartani
alohida ochishi kerak edi; kim ko'rikdan o'tgani, kim kutayotgani hech
qayerda ko'rinmasdi.

- Tanlangan kunda karavotda yotgan barcha bemorlar — palata tartibida:
  o'rin, xona, ism, **nechanchi kun / jami**, mas'ul shifokor, allergiya.
- Hamshira o'sha kuni yozgan ko'rsatkichlar **kontekst sifatida**
  ko'rsatiladi (tahrirlanmaydi — bu boshqa xodimning alohida yozuvi).
- Har bir kartada ko'rikning o'zi: umumiy holat, ko'rsatkichlar, dinamika
  va davolashga o'zgartirish. Ko'rikdan o'tgan bemor **yashil** bo'ladi,
  sarlavhada esa "ko'rikdan o'tgan / kutilmoqda" soni turadi.
- Kun bo'yicha bitta ko'rik: tuzatish **almashtiradi**, ikkinchi qarama-qarshi
  yozuv qo'shmaydi.

### Hamshira: ko'rsatkichlar va PDF

- **Ko'rsatkichlar yoziladi.** Har bir bemor kartasida AB, puls, harorat,
  SpO2 va izoh. Kun bo'yicha bitta yozuv — tuzatish almashtiradi. Tuzatish
  **faqat o'zi nomlagan maydonni** o'zgartiradi: kunduzgi puls ertalabki
  bosimni o'chirib yubormaydi.
- **PDF yuklab olish.** Avval faqat brauzer orqali chop etish bor edi.
  Imzolangan varaqa tikiladi — demak u fayl sifatida mavjud bo'lishi kerak.

### Ro'yxatga olishda tug'ilgan sana va jins

Qabulxona endi **tug'ilgan sanani** (yilni emas) va **jinsni** so'raydi;
ikkalasi shifokor anketasiga avtomatik o'tadi. To'ldirilmasa — bo'sh
qoladi, o'ylab topilmaydi.

### Karavot bandligi endi serverdan olinadi

Avval bandlik brauzerda hisoblanardi. Buning o'rniga
`GET /api/facility/availability` qo'shildi. Nima almashtirildi:

| Avval | Muammo |
| :--- | :--- |
| `data/clinic_rooms.json` + `reception.js` ichidagi nusxasi | Ikkalasi ham `rooms`/`beds` jadvallaridan farq qilib ketgandi. |
| `localStorage` dagi bronlar | Faqat bitta kompyuterda mavjud edi: bitta xodimning brauzeridagi bron **haqiqiy o'rinni bloklardi**, boshqalarga va serverga esa ko'rinmasdi. Qabulxona har bir qabulni o'sha joyga yozardi, lekin **hech narsa uni o'chirmasdi** — bemor chiqarilgandan keyin ham o'rin bloklangan qolaverardi. |
| Qo'lda yozilgan "qaysi o'rin qaysi bilan juft" jadvali | Butun xona qoidasi endi serverda; palatalar o'zgarsa ham mos qoladi. |
| KPI uchun alohida, ikkinchi bandlik hisobi | O'z nusxasidagi qoidalar bilan. Endi bitta manbadan. |

Yo'l-yo'lakay tuzatildi: ta'mirdagi yoki xizmatdan chiqarilgan o'rin
**yashil (bo'sh) ko'rsatilardi**; tablar orasidagi sinxronizatsiya esa ikki
versiya eskirgan kalitni kuzatardi va hech qachon ishlamasdi.

---

## 5. Sinov va infratuzilma

- **120 avtomatlashtirilgan test**, faqat standart kutubxona.
  `python3 tests/test_clinic.py`
- Git repozitoriysi, har bir o'zgarish sababi bilan izohlangan.
- MySQL 8+ sxemasi yangilandi; yangi jadvallar server ishga tushganda
  avtomatik yaratiladi.

---

## 6. Hal qilinishi kerak bo'lgan masalalar

**Darhol (PO/administrator qaroriga muhtoj):**

1. **Standart parollarni almashtirish.** `superadmin` va boshqa hisoblar
   dastlabki parollarda — ular tarqatilgan arxivda bo'lgan. Tizim
   birinchi kirishda parolni almashtirishni talab qiladi, lekin
   parollar almashtirilishi kerak.

**Keyingi ish (tavsiya etilgan tartibda):**

2. **Farmatsevt va oshxona sahifalari.**
3. `building_management.html` hali ham bronlarni `localStorage` da
   saqlaydi. Qabulxona endi unga bog'liq emas, lekin o'sha sahifaning
   o'zi ham bazaga o'tkazilishi kerak.
4. Sessiyalar hozircha xotirada — server qayta ishga tushganda barcha
   xodimlar qaytadan kirishi kerak.
5. Ro'yxatlarda sahifalash (pagination) yo'q — hozirgi hajmda muammo
   emas, yillar o'tib sekinlashadi.
6. `audit_logs` uchun ko'rish interfeysi (ma'lumot yoziladi, lekin
   ko'rish uchun SQL kerak).

---

**Klinika tomonidan tasdiqlangan qarorlar:**

- **Butun xona faqat bitta dastur orqali sotiladi** —
  `statsionar_full_room`. Boshqa lyuks/VIP nomlari yo'q, shuning uchun
  `db.py` dagi `FULL_ROOM_PROGRAMS` ro'yxati shundayligicha qoladi.
- **Ketish kuni o'rin darhol yangi bemorga beriladi.** Dezinfeksiya
  uchun alohida bir kunlik oraliq kerak emas — tozalash tez bajariladi.
  Haqiqiy chiqarishda o'rin baribir `cleaning` holatiga o'tadi va
  tozalash yakunlanmaguncha qabul qilinmaydi.

---

## 7. Ishga tushirish

```bash
python3 -m pip install PyMySQL reportlab
cp db_config.example.json db_config.json   # o'z parolingizni kiriting
python3 server.py 3000
```

Brauzer: `http://localhost:3000` → kirish sahifasi.

Batafsil: `README.md`.

> **Diqqat:** `db_config.json` bu arxivga **qo'shilmagan** — u parol
> saqlaydi. `db_config.example.json` dan nusxa oling.
