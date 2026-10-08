# Fayz Control — O'zgarishlar Hisoboti

**Loyiha:** Fayz Medical House — Hospital Management & EMR Suite
**Holat:** 182 avtomatlashtirilgan test, barchasi muvaffaqiyatli o'tadi
**Sana:** 2026-yil oktabr

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
| Dori buyurtmasi va chiqarish xulosasi bo'sh maydonlarni **o'ylab topardi** | Faqat dori nomi yuborilsa, buyurtma "infuzion flakon, 400 ml, tomchi, 5 kun" bo'lib, **STF-DOC-01** nomidan yozilardi — hamshira aynan shu buyurtmani bajarardi. Bo'sh chiqarish xulosasi tayyor tashxis (F10.2) va "sog'aydi" natijasi bilan saqlanardi. Endi dori, doza, yo'l, chastota va muddat majburiy; tashxis va natija ham. |
| Allergiya va surunkali kasallik standart holda "Yo'q" edi | Hech kim so'ramagan bemor "allergiyasi yo'q" deb yozilardi va shifokor sahifasidagi **allergiya ogohlantirishi o'chib qolardi**. Endi bo'sh qoladi. |
| Muallif noma'lum bo'lsa, yozuv haqiqiy xodim nomiga yozilardi | Buyurtma, karavot ko'chirish yoki kassa kvitansiyasi `STF-DOC-01`/`STF-REC-01` nomidan saqlanardi. Endi kirgan hisobdan olinadi yoki bo'sh qoladi. |
| Xatolar jimgina yutilardi (4 joyda) | Audit yozuvi yozilmasa, qabul sanasi o'qilmasa — hech kim bilmasdi. Endi server jurnaliga yoziladi. |
| Foydalanuvchilar fayli yo'qolsa, yangi hisob qo'shish **barcha hisoblarni o'chirardi** | Endi 503 bilan rad etiladi. |
| Ismsiz bemor "Yangi Bemor" deb ro'yxatga olinardi; shifokor tanlanmasa, ro'yxatdagi **birinchi shifokor** mas'ul qilinardi | Endi ism majburiy; shifokorsiz yotish shifokorsiz saqlanadi, shifokorsiz qabul (appointment) rad etiladi. Konsultatsiya saqlanganda qayd etilgan **allergiya o'chib ketardi** — endi saqlanib qoladi. |
| Yozuv ID lari (retsept, qabul, epikriz, bemor) 9000 qiymatdan tekshiruvsiz tanlanardi (14 joyda) | ~112 yozuvdan keyin saqlashlar tasodifan 500 xatolik bilan tugay boshlardi. Endi bo'sh ID tekshirib olinadi. |
| Shifokor sahifasi server **rad etgan retseptni** ham "muvaffaqiyatli qo'shildi" deb ko'rsatardi | Hamshira bu dorini hech qachon ko'rmasdi. Endi server javobi kutiladi va sababi ko'rsatiladi. |
| Shifokor sahifasi bo'sh maydonlarni **o'ylab topardi** | Bosim 120/80, puls 72, 36.6°, SpO2 98, jins "Erkak", allergiya "Yo'q", tashxis F10.2; chop etilgan kartada "tremor bor", "OIV/gepatit inkor qilinadi". Epikriz doim "sog'aydi" deb saqlanardi — endi **chiqish natijasi tanlanadi** (yangi maydon). |
| Rasmiy hujjatlar (epikriz, qabul varaqasi, muolaja varaqasi, kvitansiya, oylik varaqasi) bo'sh joyni to'ldirardi | Soxta tashxis va hamroh kasalliklar, "Dr. Bobur Mirzayev" imzosi, 20–27 avgust sanalari, 720 000 so'm to'lov, har oylikka 1,5 mln bonus. Endi "Qayd etilmagan", "—" yoki 0. |
| A4 blankdagi "Namuna" tugmasi haqiqiy bemor ismi yoniga **soxta qon guruhi** (A(II) Rh+), vazn, qand, tashxis va reja yozardi | Endi faqat bemor yozuvidagi haqiqiy ma'lumotlar qo'yiladi. |
| CRM'dagi bemor tahrirlari **umuman saqlanmasdi** | Serverda bunday yo'l yo'q edi, sahifa esa "saqlandi" derdi — CRM'da yozilgan allergiya shifokorga yetib bormasdi. Endi saqlanadi. |
| Turli odamlar **bitta bemor yozuvi**ga yozilardi | Faqat telefon yoki faqat ism bo'yicha moslashtirilardi; barcha anonim bemorlar bitta yozuvda edi. Endi telefon+ism yoki ism+tug'ilgan sana kerak; anonim tashrif har doim alohida. Har bir qabul ikkinchi (dublikat) bemor yozuvini ham yaratardi — tuzatildi. |
| Shifokor kabineti avvalgi foydalanuvchini "eslab qolardi" | Umumiy kompyuterda keyingi odam oldingi shifokor nomidan ishlardi; admin esa haqiqiy shifokor (Dr. Bobur Mirzayev) nomidan imzolardi. Endi kim kirganini server aytadi; chiqishda brauzerdagi bemor ma'lumotlari tozalanadi. |
| Ambulator, uyga chaqiruv va buxgalteriya qabullari xatoni yashirardi | Rad etilgan yoki internet uzilgan holatda ham "qayd etildi" derdi. Endi sababi ko'rsatiladi. |
| Oylik varaqasi tanlanmagan xodim uchun **birinchi xodimning** varaqasini chiqarardi | Endi xodim tanlanishi shart va hisob jadvaldagi formula bilan bir xil. |
| A4 blank "Namuna" tugmasi | Endi ro'yxatdan bemorni tanlash (ism va kod bo'yicha). |

---

### 2026-oktabr: GitHub'dan olingan yangi qism tekshiruvi

Navbatchilik jadvali, Telegram va dori xaridi qo'shilgan versiya qatorma-qator
tekshirildi. Topilgan xatolar:

| Joy | Xato | Tuzatildi |
|---|---|---|
| Buxgalteriya | Click/Payme va bank o'tkazmalari kassa qoldiqlarida hisoblanmasdi | Endi hisoblanadi |
| Navbatchilik | Smena almashtirilganda hamshira va shifokorlar ro'yxati o'chib ketardi | Faqat smenalar yangilanadi |
| Navbatchilik | Fayl bo'lmasa sahifa ishlamasdi va soxta shifokorlar yozilardi | Bo'sh jadval, hech narsa o'ylab topilmaydi |
| Navbatchilik | Server rad etsa ham "saqlandi" deb chiqardi | Haqiqiy xato ko'rsatiladi |
| Shifokor | Anamnez saqlanganda hech kim baholamagan "o'z joniga qasd xavfi: yo'q" yozilgan konsultatsiya yaratilardi | Olib tashlandi |
| Dori xaridi | 2,5 quti puldan 2,5, omborga 2 deb yozilardi | Faqat butun son qabul qilinadi |
| Telegram | 21:00 hisoboti server qayta ishga tushganda ikki marta ketardi | Bir marta |
| Server | Port band bo'lsa cheksiz qayta urinardi | To'xtaydi va sababini yozadi |

### 2026-10-08: 1-bosqich — jiddiy xatolar tuzatildi

Tizim xaritasi (`FMH_System_Overview_2026-10-08.md`) bo'yicha topilgan eng
xavfli xatolar. Ko'rinish o'zgarmadi; faqat quyidagi "o'ylab topilgan"
ma'lumotlar olib tashlandi.

| Joy | Xato | Tuzatildi |
|---|---|---|
| Statsionar (karavotlar) | Kartadagi "Chiqarish" tugmasi oxirgi ochilgan bemorni chiqarardi | Aynan shu kartadagi bemor chiqariladi |
| Statsionar | "O'chirish" bir xil ismli barcha bemorlarni va ularning yozuvlarini o'chirardi | Faqat shu qabul o'chiriladi; server endi ism bo'yicha o'chirmaydi |
| Statsionar | Chiqarish rad etilsa ham "chiqarildi" deb ko'rsatardi | Server xatosi ko'rsatiladi |
| Shifokor | Kunlik ko'rik yozuvi hech qachon saqlanmasdi | Saqlanadi va to'g'ri ko'rinadi |
| Shifokor | Dori xavfsizligi / allergiya kartasi ishlamasdi | Ishlaydi |
| Shifokor | Epikrizdagi tavsiyalar keyingi bemorga o'tib qolardi; uyga dorilar o'chib ketardi | Har bemorning o'z saqlangan epikrizi ko'rsatiladi |
| Shifokor | "Avtomatik epikriz" hammaga bir xil dorilar (Meksidol va h.k.) yozardi | Faqat bemorning o'z tayinlovlari ko'chiriladi |
| Shifokor | "Me'yoriy ko'rsatkichlar" tugmasi (120/80, 74, 36.6, 99%) | Olib tashlandi — o'lchanmagan ko'rsatkich yozilmaydi |
| Shifokor | Ro'yxatda ko'rsatkichi yo'q bemorga 120/80, 72, 99% chiqardi | "—" chiqadi |
| Shifokor | PDF har doim retsept varag'ini berardi; "Kasallik tarixi"/"Dossye" chop etilsa epikriz chiqardi | Tanlangan hujjat chiqadi |
| PDF | Bo'sh joylarga F10.2 tashxis, shikoyat, 120/80, "muvaffaqiyatli" xulosa va shifokor ismi yozilardi | "Qayd etilmagan" yoziladi |
| Qabulxona | Qabuldagi avans to'lovi jimgina yo'qolardi (qabulxona huquqi yetmasdi) | Avans qabul bilan birga saqlanadi; boshqa to'lovlarga ruxsat berilmadi |
| Qabulxona | Band vaqtlar ko'rinmasdi — bitta vaqtga ikki bemor yozilardi | Band vaqt ko'rinadi, server ham ikkinchi yozuvni rad etadi |
| Qabulxona | Eski bazada konsultatsiyaga yozish 500 xato berardi | Server ishga tushganda baza avtomatik tuzatiladi |
| Navbatchilik | Smena almashtirish boshqa oylarni o'chirib yuborishi mumkin edi | Faqat ikki kun yangilanadi; server sanalar bo'yicha birlashtiradi; "Kim bilan" tekshiriladi |
| Buxgalteriya | Daromad grafigi bemor to'lovlarini ikki marta hisoblardi | Bir marta |
| CRM | Tug'ilgan yil 1990, jins "Ayol" deb o'zi to'ldirilardi | Bo'sh qoladi |
| CRM | Epikriz bo'limi har bemorga bir xil soxta tashxis, davolash va imzo ko'rsatardi | Shifokor saqlagan haqiqiy epikriz yoki "hali yozilmagan" |
| CRM | To'lov bo'lmasa soxta "CHK-2026-01" cheki ko'rinardi; tarixda soxta karavot va shifokor | "Qayd etilmagan" |
| CRM, Qabulxona, Shifokor | Bemorni o'chirish rad etilsa ham "o'chirildi" deb chiqardi | Haqiqiy xato ko'rsatiladi |

8 ta yangi test qo'shildi, jami 190 ta test o'tadi.

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
- **Bosh sahifa roli serverdan olinadi.** `superpage` rolni brauzerdan
  (`localStorage`) o'qirdi: hech kim kirmagan brauzer superadmin panelini
  ochardi. Ma'lumot baribir server tomonidan himoyalangan edi, lekin endi
  ism va rol faqat `/api/auth/session` dan olinadi, rolni almashtirish esa
  soxta ism ("Dr. Rahim Karimov") qo'ymaydi.

---

## 4. Yangi imkoniyatlar

### Klinika egasi uchun pul oqimi (`owner.html`) — telefon uchun

Yangi rol: **Klinika egasi**. Faqat ko'radi, hech narsani o'zgartira olmaydi.
Kirgandan keyin to'g'ridan-to'g'ri shu sahifa ochiladi.

- Davr: bugun, 7 kun, shu oy, o'tgan oy, yil yoki istalgan sana oralig'i.
- Qancha pul tushdi, qancha sarflandi, qancha qoldi (yoki zarar) va oldingi
  shunday davrga nisbatan o'zgarish.
- "Har 100 so'm tushumdan": har bir xarajat turi va foydaga qancha to'g'ri keladi.
- **Pul qayerdan keldi**: bemor to'lovlari hisob-fakturadagi xizmatlar
  bo'yicha bo'linadi (statsionar kunlari, konsultatsiya, dori, tahlil,
  muolaja). Qatorni bossangiz — har bir to'lov va bemor nomi.
- **Pul nimaga ketdi**: maosh, dori xaridi, ovqat, ijara, kommunal va h.k.
  Kassadan bankka inkassatsiya xarajat hisoblanmaydi.
- To'lov turi bo'yicha (naqd, karta, Click/Payme, bank), kunma-kun grafik,
  kelgan bemorlarning to'lanmagan qoldig'i va berilgan dorilar tannarxi.
- Kunduzgi va tungi rejim.

Hisob yaratish: Super-Portal → foydalanuvchi qo'shish → rol
"Klinika egasi (Pul oqimi)".

### Dori ombori: berilgan doza ombordan ayiriladi

- Hamshira dozani "berildi" deb belgilasa, ombordan **1 birlik** (ampula,
  flakon yoki tabletka) ayiriladi. Xato tuzatilsa (berildi → berilmadi)
  birlik qaytariladi.
- Shifokor yozgan nom ombordagi nomga mos kelmasa, buxgalteriyadagi
  **"Dori sarfi"** bo'limida "bog'lanmagan" bo'lib chiqadi. Buxgalter uni
  bir marta ombordagi dori bilan bog'laydi — avval berilgan dozalar ham,
  keyingilari ham ayiriladi.
- Muhim: ombordagi miqdorni **dona/ampula** bilan yuriting, quti bilan emas —
  har bir doza 1 birlik deb hisoblanadi.

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

### Saytdan kelgan arizalar (`/api/public/appointment-request`)

Rasmiy saytdagi yozilish formasi CRM ga **ariza yubora olmay qolgandi**:
u `/api/reception/appointment` ga yozardi, avtorizatsiya joriy etilgach esa
o'sha endpoint 401 qaytaradigan bo'ldi. Arizalar **jimgina yo'qolardi** —
hech qayerda qayd etilmasdi va hech kimga xabar berilmasdi.

- Sayt uchun **alohida ochiq endpoint**. Tizimdagi yagona avtorizatsiyasiz
  yoziladigan yo'l, shuning uchun ataylab tor qilingan: faqat
  `appointment_requests` jadvaliga yozadi, **bemor kartasi ochmaydi va
  navbat band qilmaydi**.
- Qabulxonada **"Saytdan So'rovlar"** tabi. Bemor kartasi faqat xodim
  **"Qabul qilish"** bosganda ochiladi — spam bazani to'ldira olmaydi.
- IP bo'yicha cheklov: soatiga 5 ariza, kuniga 20. Urinishlar alohida
  hisoblanadi, ya'ni telefon raqamini xato yozish arizani "yeb" qo'ymaydi.
- Ko'rinmas "tuzoq" maydon: bot to'ldirsa, server 201 qaytaradi-yu **hech
  narsa saqlamaydi**.
- CORS **faqat shu endpoint** uchun va **faqat klinika sayti** domeniga
  ochiladi.

### Zaxira nusxa (backup)

Avval umuman yo'q edi. Endi `scripts/backup.sh` va
`scripts/restore-test.sh`:

- Parol **buyruq satrida ko'rinmaydi** — vaqtinchalik `0600` faylga
  yoziladi va skript tugashi bilan o'chiriladi.
- `restore-test.sh` arxivni **alohida vaqtinchalik bazaga** tiklaydi,
  jonli baza bilan jadval-ma-jadval solishtiradi va nusxani o'chiradi.
  Sinovdan o'tkazildi: 24 jadval, 5 view, farq yo'q.
- Yo'l-yo'lakay topildi: `mysqldump` ga `--set-gtid-purged=OFF` bermasa,
  arxiv **24-qatorda tiklanmay to'xtaydi** ("GTID_PURGED cannot be
  changed"). Bu faqat haqiqiy tiklashni sinab ko'rganda ma'lum bo'ladi.

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

- **190 avtomatlashtirilgan test**, faqat standart kutubxona.
  `python3 tests/test_clinic.py`
- Git repozitoriysi, har bir o'zgarish sababi bilan izohlangan.
- MySQL 8+ sxemasi yangilandi; yangi jadvallar server ishga tushganda
  avtomatik yaratiladi.

---

## 6. Hal qilinishi kerak bo'lgan masalalar

**Serverda bajarilishi kerak (kod emas, amal):**

1. **Zaxira cron'ini o'rnatish.** Skriptlar tayyor va sinovdan o'tgan
   (`scripts/backup.sh`, `scripts/restore-test.sh`), lekin ular
   **o'z-o'zidan ishlamaydi** — `/etc/cron.d/` ga qo'yilishi kerak.
   `README.md` → "Zaxira Nusxa" bo'limi.
2. **Parollarni tarqatish.** Barcha 16 hisobga yangi bir martalik parol
   berilgan va har biri birinchi kirishda o'z parolini o'rnatishga
   majbur. Excel faylini xodimlarga bergach **o'chiring**.

3. **Telegram bot tokenini yangilash.** Eski token ochiq GitHub
   repozitoriysiga tushib qolgan. @BotFather → `/revoke`, keyin yangi
   tokenni serverda `FMH_TELEGRAM_BOT_TOKEN` muhit o'zgaruvchisiga
   yozing (kodga emas). Token bo'lmasa bot o'chiq turadi.
4. **GitHub repozitoriysini yopiq (private) qilish.**
5. **Klinika egasi uchun hisob yaratish** (yuqoriga qarang).

**Keyingi ish (tavsiya etilgan tartibda):**

6. **Farmatsevt va oshxona sahifalari.**
7. `building_management.html` hali ham bronlarni `localStorage` da
   saqlaydi. Qabulxona endi unga bog'liq emas, lekin o'sha sahifaning
   o'zi ham bazaga o'tkazilishi kerak.
8. Sessiyalar hozircha xotirada — server qayta ishga tushganda barcha
   xodimlar qaytadan kirishi kerak.
9. Ro'yxatlarda sahifalash (pagination) yo'q — hozirgi hajmda muammo
   emas, yillar o'tib sekinlashadi.
10. `audit_logs` uchun ko'rish interfeysi (ma'lumot yoziladi, lekin
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
