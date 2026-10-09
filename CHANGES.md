# Fayz Control — O'zgarishlar Hisoboti

**Loyiha:** Fayz Medical House — Hospital Management & EMR Suite
**Holat:** 245 avtomatlashtirilgan test, barchasi muvaffaqiyatli o'tadi
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

### 2026-10-08: 2-bosqich — tekshiruv natijalari, kirish, menyu, narxlar

1-bosqich o'zgarishlari qayta tekshirildi (har bir topilma ikki marta
alohida tasdiqlandi), so'ng qolgan jiddiy xatolar tuzatildi.

| Joy | Xato | Tuzatildi |
|---|---|---|
| Kirish | `?next=` havolasi orqali kirgandan keyin boshqa saytga yuborish mumkin edi | Faqat shu saytdagi va xodimga ruxsat berilgan sahifa ochiladi |
| Kirish | Har kim Super-Portalga tushardi (`/`, `index.html` ham) | Har bir lavozim o'z bosh sahifasiga tushadi (hamshira → Hamshira posti va h.k.) |
| Kirish | Bosh sahifasi ruxsatsiz bo'lgan hisob cheksiz yo'naltirishga tushib qolardi | Har doim ochish mumkin bo'lgan sahifa beriladi |
| Barcha sahifalar | Parolni o'zgartirish uchun havola yo'q edi | Yuqoridagi ism yonida kalit belgisi; sahifada "Ortga qaytish" |
| Barcha sahifalar | Logotip ba'zi lavozimlarda yo'qolib qolardi | Logotip xodimning bosh sahifasiga olib boradi |
| Barcha sahifalar | Har sahifada boshqacha menyu (3–11 tugma, nomlari har xil) | Bitta menyu: bir xil nom va tartib, bo'limlar bo'yicha, lavozimga qarab |
| Shifokor | Ko'rik yozuvidagi matn sahifada kod sifatida ishlashi mumkin edi (xavfsizlik) | Oddiy matn sifatida ko'rsatiladi |
| Shifokor | Epikrizda yozilgan, lekin saqlanmagan tavsiya anamnez saqlanganda o'chib ketardi | Saqlanib qoladi |
| Shifokor | Qayta yotqizilgan bemorda oldingi yotishning epikrizi to'ldirilib turardi | Faqat joriy yotishniki ko'rsatiladi |
| Shifokor | "Avto epikriz" hech qachon ishlamasdi; tugagan/to'xtatilgan dorilarni ham ko'chirardi | Bo'sh maydonga faqat faol tayinlovlar ko'chiriladi |
| Shifokor | Hujjat oynasida "Chop Etish" har doim retsept varag'ini chiqarardi | Tanlangan hujjat chiqadi |
| Shifokor | Ambulator bemorga bir kunda bir nechta ko'rik yozuvi to'planardi | Kuniga bitta, tuzatish shu yozuvni yangilaydi |
| Shifokor | Bir kunda qayta saqlangan epikrizdan eskisi ochilishi mumkin edi | Eng oxirgisi ochiladi (PDF ham) |
| PDF | Matnda `<` belgisi bo'lsa PDF umuman chiqmasdi | Chiqadi |
| PDF | Shifokor yozilmagan bo'lsa ham "Klinik Shifokor, Narkolog-Psixiatr" imzosi | "Qayd etilmagan" |
| Qabulxona | Bekor qilingan yozuv faqat ekrandan o'chardi; bo'shagan vaqtni qayta band qilib bo'lmasdi | Serverda bekor qilinadi (tasdiqlash so'raladi), vaqt bo'shaydi |
| Qabulxona | Click/Payme avansi bank hisobiga yozilardi | Click/Payme hisobiga (buxgalteriya bilan bir xil) |
| Qabulxona | Avans saqlanmasa, qabul bo'lgan bo'lsa ham xato chiqardi va qayta yuborilardi | Qabul saqlanadi; avansni buxgalteriyada kiritish so'raladi |
| Buxgalteriya | Shifokor oyligi 0 so'm bo'lib yozilardi va "to'landi" deyilardi | Haqiqiy summa yuboriladi; rad etilsa xato ko'rsatiladi |
| Buxgalteriya | Kassa operatsiyalari (kirim/chiqim, inkassatsiya) rad etilsa ham saqlandi deyilardi | Server javobi tekshiriladi |
| Buxgalteriya | Hisobga qo'shilgan xizmat/dori 4 soniyada yo'qolardi | Serverda saqlanadi, narxni server narxlar ro'yxati yoki ombordan oladi, dori ombordan ayiriladi |
| Navbatchilik | 2026-13-45 kabi mavjud bo'lmagan sana saqlanardi | Rad etiladi |
| CRM | Tez boshqa bemorga o'tilganda oldingi bemorning epikriz xatosi ko'rinardi | Faqat ochiq bemorniki ko'rsatiladi |
| Bemorni o'chirish | Kunlik qaydlar va karavot ko'chishlari bazada qolib ketardi | Ular ham o'chiriladi |
| Texnik hisobotlar | Ikki texnik sahifa ishlab turgan server manzili va baza ma'lumotlarini ko'rsatardi | Saytdan olindi (`docs/` papkasida hujjat sifatida qoldi), Super-Portaldagi havolalar olib tashlandi |
| Buxgalteriya | Maosh to'langani 4 soniyadan keyin "Hisoblangan"ga qaytardi, bir kishiga ikki marta to'lash mumkin edi | To'lov xodimga bog'lanadi; shu oy to'langan bo'lsa qayta to'lanmaydi |
| Statsionar | Qabul / tahrirlash / karavot almashtirish oynasi hech narsani saqlamasdi | Qabul faqat Qabulxonada; karta oynasi faqat ko'rish uchun |
| Statsionar | Karavot almashtirish yo'q edi | "Karavotni almashtirish" serverda saqlanadi (tasdiqlash so'raladi) |
| Statsionar | Ko'chirilgan bemor qolgan kunlar uchun 720 000 dan qayta hisoblanardi (butun xona / chegirma yo'qolardi) | Kelishilgan narx saqlanadi (rahbar tasdiqlashi kerak, pastda) |
| Statsionar | Ta'mirdagi karavot bo'sh ko'rinardi | "TA'MIRDA" kartasi, "Ta'mirga yuborish" / "Ta'mirlandi" tugmalari |
| Statsionar | Server javob bermasa barcha karavotlar bo'sh ko'rinib qolardi | Oxirgi ma'lumot qoladi, ogohlantirish chiqadi |
| Statsionar | "Chiqarish" tugmasi xato bilan to'xtardi | Ishlaydi |
| Statsionar | Bemor ismi sahifada kod sifatida ishlashi mumkin edi (xavfsizlik) | Oddiy matn |
| Narxlar | Har sahifada o'z narxlari yozilgan edi (720 000 / 1 100 000 / 630 000 ...) | Qabulxona, Buxgalteriya, Shifokor, Super-Portal va Statsionar bitta narxlar ro'yxatidan o'qiydi |
| Narxlar | Konsultatsiya narxi Qabulxonada statsionar dastur bo'lib chiqardi | Chiqmaydi; konsultatsiya narxi tahrirlanadi |
| Narxlar | Narx saqlashda hech narsa tekshirilmasdi; tarmoq xatosida "saqlandi" deyilardi | Har narx tekshiriladi; saqlanmasa aniq aytiladi |
| Narxlar | Narxsiz qabul 720 000 dan hisoblanardi | Dastur narxi olinadi |

**PO qarorlari (2026-10-08):** (1) Ko'chirilganda kelishilgan narx qoladi, lekin
"Yangi kunlik narx (ixtiyoriy)" maydonida yangi narx yozish mumkin — u ko'chirish
sanasidan qo'llanadi. (2) Server ro'yxatdan farq qiladigan narxni rad etmaydi.
(3) Uyga chaqiruv hozircha yo'q: yozuv turidan olib tashlandi, o'ylab topilgan
850 000 narx o'chirildi (eski yozuvlar o'zgarmaydi).

Bu ikki masala 3-bosqichda hal qilindi (pastda).

29 ta yangi test qo'shildi, jami 219 ta test o'tadi.


### 2026-10-09: 3-bosqich — Qabulxona narxi, navbatchilik narxlari va maosh serverda

| Joy | Xato | Tuzatildi |
|---|---|---|
| Qabulxona | Kunlik statsionarda karavot tanlanganda narx 630 000 dan karavot narxi 720 000 ga almashardi | Faqat "Statsionar (2 kishilik xonada 1 karavot)" karavot narxini oladi; boshqa dasturlar o'z narxida qoladi |
| Narxlar | Navbatchilik smena narxlari (shifokor 350 000, hamshira 400 000, sanitarka 300 000) har sahifada alohida yozilgan edi | Bitta narxlar ro'yxatida; Super-Portal → Narxlar bo'limida tahrirlanadi |
| HR | Navbatchilik jadvali har safar sahifa ochilganda qaytadan tuzilardi — qo'lda kiritilgan o'zgarishlar yo'qolardi | HR va Navbatchilik sahifasi bitta jadvalni (serverda) ko'radi va o'zgartiradi |
| HR | Maosh brauzerda o'ylab topilgan jadvaldan hisoblanardi; har bir shifokorga 2 600 000 "statsionar bonusi" va 6 ta detoks bonusi qo'shilardi | Maosh serverda: oklad + saqlangan smenalar × narxlar ro'yxatidagi tarif. Hech kim kiritmagan bonuslar olib tashlandi |
| HR | Pay slip har doim "Avgust 2026", "15.08.2026" va "TO'LANGAN ✓" deb chiqardi | Tanlangan oy, bugungi sana, holat "Hisoblangan" |
| Navbatchilik | Sanitarkalar xodimlar ro'yxatida yo'q edi (maosh hisoblab bo'lmasdi) | "Sanitar" lavozimi qo'shildi; jadvaldagi 6 sanitarka xodim sifatida qo'shildi (faqat ism, telefon va oklad kiritilmagan) |
| Navbatchilik | Saqlanmagan oy uchun sahifaga yozilgan ismlar bilan o'ylab topilgan jadval ko'rsatilardi | Xodimlar ro'yxatidan taklif tuziladi va "saqlanmagan" deb belgilanadi; "Jadvalni saqlash" bosilmaguncha maosh hisoblanmaydi |
| Navbatchilik | Saqlangan jadvalda hamshira va shifokor ko'rinmasdi ("Hamshira smenada", "Dr. Umarov Xusan" o'ylab topilgan) | Jadvaldagi haqiqiy xodim ko'rsatiladi; bo'sh bo'lsa "—" |
| Navbatchilik | Zaxira (2-post) sanitarka kuni ham 300 000 deb hisoblanardi | Faqat asosiy post to'lanadi |
| Navbatchilik | Sanitarka jadvalni saqlay olardi — endi bu maosh degani (o'ziga smena yozishi mumkin edi) | Sanitarka jadvalni faqat ko'radi; saqlash va almashtirishni HR / administrator qiladi |
| HR | Yangi xodim qo'shilganda ID xodimlar sonidan tuzilardi va shu ID dagi boshqa xodimning yozuvi ustidan yozilardi | ID ni server bo'sh raqamdan beradi |
| HR | Oklad bo'sh qoldirilsa 10 000 000 deb saqlanardi; noto'g'ri e-pochta o'ylab topilardi | Bo'sh oklad = 0, e-pochta bo'sh qoladi; noto'g'ri summa rad etiladi |
| HR | Server rad etgan xodim ham ro'yxatga qo'shilib "qo'shildi" deyilardi | Xato ko'rsatiladi, hech narsa qo'shilmaydi |
| HR | Xodim ismi tuzatilsa, saqlangan smenalari to'lanmay qolardi | Jadvaldagi shu xodim kunlari ham yangi ismga o'tkaziladi (boshqa odam yozilgan kunlar o'zgarmaydi) |
| HR | "Yangi Smena Qo'shish" tugmasi ishlamasdi | Smenalar bo'limini ochadi va kalendarda qanday qo'shishni ko'rsatadi |

**Rahbar qarorlari (2026-10-09):** (1) Maosh Navbatchilik sahifasidagi (serverdagi)
jadval bo'yicha hisoblanadi. (2) Sanitarkalar xodim sifatida qo'shiladi.
(3) Rejalashtirilmagan oy — taklif sifatida ko'rsatiladi, saqlanmaguncha to'lanmaydi.

**Diqqat:** jadvaldagi ism shu ID dagi xodim ismiga mos kelmasa (masalan, jadvalda
`STF-DOC-01` = "Umarov Xusan", xodimlar ro'yxatida `STF-DOC-01` = boshqa shifokor),
bu smena **to'lanmaydi** va HR → Maosh bo'limida ogohlantirish chiqadi. HR jadvalda
o'sha kunlarni to'g'ri xodim bilan qayta belgilashi kerak.

Daromad solig'i 12% va INPS 0,1% avvalgidek qoldi.

9 ta yangi test qo'shildi, jami 228 ta test o'tadi.

### 2026-10-09: 4-bosqich (A) — kichik tuzatishlar

| Joy | Xato | Tuzatildi |
|---|---|---|
| Barcha sahifalar | Xato xabarlari ("error") yashil, "muvaffaqiyatli" ko'rinishida chiqib, tez yo'qolardi | Xato xabari qizil chiqadi va uzoqroq turadi |
| Qabulxona | Qo'ng'iroq qayd etilganda server javobi tekshirilmasdi — rad etilgan qo'ng'iroq ham "qayd etildi" deyilardi | Faqat server saqlaganda ro'yxatga qo'shiladi; aks holda sababi ko'rsatiladi |
| Qabulxona | "Saytdan So'rovlar" soni faqat bo'lim ochilganda yangilanardi | Soni har daqiqada avtomatik yangilanadi |
| Qabulxona | Saytdan kelgan so'rov qabul qilinganda bemor shifokorsiz, soat 10:00 ga yozilardi | Qabul qilishda shifokor, sana va vaqt so'raladi; server ularsiz yoki band vaqtga yozmaydi |
| Qabulxona | Saytda xizmat turi erkin matn bo'lsa, so'rovni qabul qilish 500 xato berardi | Noma'lum xizmat turi "Ambulator" sifatida yoziladi |
| Telegram | Saytdan yangi so'rov kelganda hech kim xabar olmasdi | Xodimlar guruhiga xabar boradi (faqat ism, telefon, istalgan sana va izoh). Bot tokeni bo'lmasa — hech narsa yuborilmaydi; sayt so'rovini sekinlashtirmaydi |
| Hamshira posti, Statsionar ko'rigi | Shifokor saqlagan davolash rejasi bu sahifalarda ko'rinmasdi | Har bir bemor kartasida "Davolash rejasi" tugmasi — amaldagi rejani faqat o'qish uchun ochadi |
| Buxgalteriya | To'lov server tomonidan rad etilsa oyna xabarsiz yopilardi | Oyna ochiq qoladi, sababi ko'rsatiladi |
| Buxgalteriya | Yangi hisob ochilganda avans to'lovi rad etilsa ham "to'landi" deb hisoblanardi | Hisob ochiladi, avans saqlanmagani haqida ogohlantirish chiqadi |
| Buxgalteriya | "Shu Oy (Avgust)" tugmasi har doim Avgust deb yozardi | Joriy oy nomi ko'rsatiladi |
| Buxgalteriya | Inkassatsiyada o'ylab topilgan "Xusnitdinov Azamat", kvitansiya va Z-hisobotda "Dilnoza R." / "Dilnoza Rahimova" chiqardi | Ism maydoni bo'sh (majburiy), hujjatlarda bo'sh imzo chizig'i |
| Buxgalteriya | Shifokor biriktirilmagan hisobda o'ylab topilgan "Dr. Rustam Ziyayev", manzil har doim "Toshkent" | Bo'sh yoki "—" |
| Shifokor posti | Protokol tugmasi barcha dorilar saqlanmasa ham "tayinlandi" derdi | Nechta dori haqiqatan saqlangani aytiladi |
| Shifokor posti | Retsept holatini o'zgartirish yoki o'chirish rad etilsa umumiy xabar chiqardi | Serverning aniq sababi ko'rsatiladi |
| Shifokor posti | Bemor yoshi 2026 − tug'ilgan yil deb hisoblanardi | Joriy yildan hisoblanadi |
| Shifokor posti, Navbatchilik | Sahifa yuklanguncha boshqa shifokor/sanitarka ismi ko'rinib turardi | Yuklanguncha "—" |
| A4 blanklar | Imzo qatorida o'ylab topilgan "Dr. Xusnitdinov A." | Bo'sh — shifokor o'zi yozadi |
| Muolaja varaqasi (chop etish) | "Katta Hamshira" imzosida o'ylab topilgan "Nilufar Karimova" | "—" |
| HR | Xodimni o'chirish rad etilsa ham "o'chirildi" deyilardi | Faqat server o'chirganda ro'yxatdan olinadi |
| HR | Davomat sanasi har doim 15.08.2026 | Bugungi sana |
| Super-Portal | Xona/karavot/xodim/foydalanuvchi amallari rad etilsa umumiy xabar | Serverning aniq sababi ko'rsatiladi |
| Bemorlar kartotekasi (CRM) | "Yangi To'lov Qabul Qilish" summani faqat ekranda o'zgartirardi — hech narsa saqlanmasdi | To'lov bu yerda saqlanmasligi va Buxgalteriyada qabul qilinishi aytiladi |
| Hujjatlar | README dagi fayllar tuzilmasi eski (`crm-suite/`), testlar soni eskirgan | Haqiqiy tuzilma va joriy testlar soni |

**Diqqat:** Telegram xabari uchun serverda `FMH_TELEGRAM_BOT_TOKEN` bo'lishi kerak.
Xabar guruhning asosiy chatiga boradi; alohida mavzu (topic) kerak bo'lsa
`FMH_TELEGRAM_ENQUIRY_TOPIC` ga uning raqamini yozing.

6 ta yangi test qo'shildi, jami 234 ta test o'tadi.

### 2026-10-09: 4-bosqich (B) — HR: davomat, oylar, xodim ma'lumotlari

| Joy | Xato | Tuzatildi |
|---|---|---|
| HR — Davomat | Davomat faqat shu brauzerda saqlanardi; boshqa kompyuterda yoki keshi tozalangach yo'qolardi, bazaga yetib bormasdi | Davomat serverda saqlanadi (`POST /api/hr/attendance`): bir xodim uchun bir kunda bitta yozuv, qayta saqlash uni tuzatadi. Rad etilsa sababi qizil xabarda ko'rsatiladi |
| HR — Davomat | Hech kim qayd etmagan xodim ham "Keldi, 08:00, 8 soat, Standart ish kuni" deb ko'rinardi | "Qayd etilmagan" deb ko'rinadi; vaqt va soat "—" |
| HR — Davomat | Faqat bugungi kun; "Tungi smenaga rejalashtirilgan" holati bazada yo'q edi | Jadval ustida "Sana" tanlanadi (kelajak kun mumkin emas). Holatlar: Keldi, Kechikdi, Kelmadi, Ta'tilda, Kasal; alohida "Smena" (kunduzgi / tungi / 24 soat) |
| HR — Davomat | "Ishlangan soat" qo'lda yozilardi va vaqtlarga zid bo'lishi mumkin edi | Kelgan/ketgan vaqtdan avtomatik hisoblanadi; tungi smena ertasi tongda tugashi hisobga olinadi |
| HR — Davomat | "Bugun ishda" soni barcha kunlardagi yozuvlarni sanardi | Faqat bugungi "Keldi/Kechikdi" yozuvlari |
| HR — Navbatchilik va Maosh | Faqat joriy oy ko'rinardi | Oy almashtirish tugmalari (‹ ›) va "Bugun"; jadval va maosh tanlangan oy bo'yicha serverdan qayta yuklanadi |
| HR — Xodim formasi | Ishga qabul sanasi, staj, toifa, lavozim nomi, bo'lim, qavat, Telegram, protsedura haqi faqat brauzerda edi va qayta yuklashda yo'qolardi | Serverda saqlanadi (bazaga yangi ustunlar avtomatik qo'shiladi). Bo'sh qoldirilgan maydon bo'sh qoladi |
| HR — Xodim formasi | Bo'sh maydonlar o'rniga taxmin yozilardi: "Oliy toifa", 5 yil staj, bugungi sana, "Narkologiya", "Mutaxassis" | Taxmin yozilmaydi; bo'sh bo'lsa "—" |
| HR — Xodim formasi | Okladi 0 bo'lgan xodim (masalan, faqat navbatchilik oladigan sanitarka) tahrirlansa forma 10 000 000 ko'rsatardi va saqlasa shu yozilardi | Haqiqiy oklad (0 ham) ko'rsatiladi |
| HR — Xodim formasi | Farmatsevt, kadrlar bo'limi, statsionar menejeri, oshxona xodimi tahrirlansa "admin" bo'lib qolardi | O'z lavozimi saqlanadi |
| HR — Xodimni o'chirish | Tugma "butunlay o'chirish" derdi, lekin server faqat faolsizlantirardi; xodim ro'yxatdan jim yo'qolib, qayta yuklashda qaytib chiqardi | Tugma va savol "Faolsizlantirish" deydi; xodim xira, "Faolsizlantirilgan" belgisi bilan qoladi va "Faollashtirish" tugmasi bilan qaytariladi. Yozuvlari saqlanadi |
| Server | — | `POST /api/staff/<id>/reactivate` — faqat faollikni qaytaradi, boshqa ma'lumotlarga tegmaydi. Davomat va qayta faollashtirish faqat HR (va admin) uchun; qabulxona 403 oladi |
| Xavfsizlik | Har qanday xodim barcha maoshlar va davomatni ko'ra olardi (`/api/hr/data`, `/api/staff`) | Faqat HR, kassir (buxgalteriya yozish huquqi) va klinika egasi ko'radi |

**Eslatma:** pasport/JShShIR maydoni hali ham saqlanmaydi (shaxsiy ma'lumot —
saqlash kerakmi, PO hal qiladi). "KPI reyting" ham hech qayerda kiritilmaydi.

11 ta yangi test qo'shildi, jami 246 ta test o'tadi.

### 2026-10-09: 4-bosqich (C) — administrator paneli

| Joy | Xato | Tuzatildi |
|---|---|---|
| Super-Portal — Foydalanuvchilar | Yangi hisob formasida 13 ta roldan faqat 6 tasi bor edi (sanitarka, farmatsevt, HR, statsionar menejeri, oshxona, bosh shifokor, admin yo'q) | Rollar ro'yxati serverdan olinadi (`GET /api/users/roles`, `permissions.ROLES`) — barcha 13 rol, nomi bilan |
| Super-Portal — Foydalanuvchilar | Hisobni faqat yaratish va o'chirish mumkin edi | "Tahrirlash" oynasi: F.I.Sh, telefon, rol, xodim bilan bog'lash, holat (Faol / Bloklangan). Bloklangan xodim darhol tizimdan chiqariladi va kira olmaydi |
| Super-Portal — Foydalanuvchilar | Parolini unutgan xodimni qaytarish yo'li yo'q edi | "Parolni tiklash" tugmasi: yangi bir martalik parol bir marta oynada ko'rsatiladi ("Nusxa" tugmasi bilan), hech qayerda saqlanmaydi; xodim kirgach uni almashtirishi shart, eski sessiyalari yopiladi |
| Super-Portal — Foydalanuvchilar | Parol majburiy edi | Ixtiyoriy: bo'sh qoldirilsa server bir martalik parol beradi va bir marta ko'rsatadi. Yozilgan parol kamida 8 belgi |
| Server — `/api/users` | Har qanday rol nomi qabul qilinardi (noma'lum rol bilan kirgan xodim hech narsani ko'rmasdi); login, F.I.Sh tekshirilmasdi | Rol `permissions.ROLES` dan bo'lishi, login 3-40 lotin belgi, F.I.Sh bo'sh emas, xodim ID mavjud bo'lishi shart; xato maydon nomi bilan qaytadi (400) |
| Server — `/api/users` | Hisob ID foydalanuvchilar sonidan yasalardi va o'chirishdan keyin takrorlanardi; o'chirish shu ID li barcha hisoblarni o'chirardi; yo'q hisob uchun ham "o'chirildi" derdi | ID bo'sh raqam qidirib beriladi; faqat bitta hisob o'chiriladi; yo'q hisob — 404 |
| Server — `/api/users` | Superadmin hisobini va o'z hisobini o'chirish, bloklash, rolini tushirish mumkin edi | Taqiqlangan (403): `superadmin` hisobi, o'z hisobi va oxirgi faol bosh administrator. Ro'yxatda "Himoyalangan" deb ko'rinadi |
| Server — `/api/users` | Tahrirlashda parolni to'g'ridan-to'g'ri yozib qo'yish mumkin edi (almashtirish talabisiz) | Parol faqat "Parolni tiklash" orqali o'zgaradi |
| Xavfsizlik — Audit | Yangi hisob yaratilganda yozilgan parol audit jurnaliga ochiq matnda tushardi (lokal bazada 2 414 ta yozuv) | Parollar jurnalga yozilmaydi (`[yashirilgan]`); eski yozuvlardagi parollar server ishga tushganda avtomatik yashiriladi (kim, nima, qachon o'zgarmaydi) |
| Xavfsizlik | Rol yoki holat o'zgarsa, xodimning ochiq sessiyasi eski huquqlar bilan 12 soatgacha ishlayverardi | Rol, holat, ruxsatlar yoki xodim bog'lanishi o'zgarsa, sessiyalari yopiladi |
| Super-Portal — Audit jurnali (yangi) | Audit jurnali yozilardi, lekin uni faqat MySQL orqali o'qish mumkin edi | 5-yorliq "Audit jurnali": sana oralig'i, foydalanuvchi, bo'lim, amal, matn bo'yicha qidiruv, sahifalash (50/100/200). Faqat o'qish uchun (`GET /api/audit`, faqat admin) |
| Super-Portal — Kadrlar | Ishga qabul formasi maoshni `salary` deb yuborardi — server uni o'qimasdi; maydonda 10 000 000 turardi; smena ham o'qilmasdi (doim "kunduzgi") | `base_salary` va `shift_type` yuboriladi; maydon bo'sh (bo'sh = 0). Ro'yxatdagi "Oylik" ustuni haqiqiy okladni ko'rsatadi |
| Super-Portal | Ismlar tekshirilmasdan sahifaga qo'yilardi (maxsus belgilar sahifani buzishi mumkin edi) | Foydalanuvchilar, xodimlar va audit jadvallarida barcha qiymatlar xavfsiz ko'rsatiladi |

13 ta yangi test qo'shildi, jami 259 ta test o'tadi.

### 2026-10-09: 4-bosqich (D) — buxgalteriya va hisoblar

| Joy | Xato | Tuzatildi |
|---|---|---|
| Buxgalteriya — Maosh | "Shifokorlar oyligi" sahifaning o'zida o'ylab topilgan raqamlardan hisoblanardi: oklad 8 500 000 (bosh shifokorga 12 000 000), bemorlar to'lovidan 8–10 % "gonorar" (hech kim belgilamagan), shifokorlar ismida "dr" borligiga qarab tanlanardi. Maosh shu summada to'lanardi — HR hisobidan boshqa ikkinchi formula | Maosh bo'limi serverdagi yagona hisobni ko'rsatadi (`GET /api/hr/payroll`, HR sahifasidagi bilan bir xil): oklad + saqlangan navbatchilik smenalari, minus daromad solig'i va pensiya. Barcha xodimlar ko'rinadi, "gonorar" yo'q |
| Buxgalteriya — Maosh to'lash | To'lov summasi o'ylab topilgan "oklad + gonorar" edi; kassir nomi sifatida to'qima ism yozilardi | Qo'lga beriladigan (sof) summa to'lanadi — HR varaqasidagi "Sof to'lanadigan" bilan bir xil. Soliq va pensiya davlatga alohida xarajat sifatida o'tkaziladi, shuning uchun bu yerda ikki marta yozilmaydi. Jurnal yozuvida oy, brutto va ushlab qolingan summa ko'rinadi. "Shu oy to'langan" himoyasi (xodim + oy) saqlandi |
| Ruxsatlar | Buxgalter maosh hisobini o'qiy olmasdi (faqat HR), shuning uchun sahifa o'zi hisoblardi | Maosh hisobini HR, buxgalteriyada yozish huquqi borlar va klinika egasi o'qiydi. Qabulxona (faqat o'qish) — yo'q (403). Boshqa HR ma'lumotlari ochilmadi |
| Server — `/api/accounting/data` | Javobda yashirin "shifokorlar maoshi" bor edi: oklad + bemorlar to'lovining 10 %; bu har bir shifokor okladini qabulxona va bosh shifokorga ham yuborardi | Olib tashlandi (hech bir sahifa ishlatmasdi) |
| Buxgalteriya — Hisoblar | Karavoti yoki muddati yo'q hisob "BED-1A" karavoti, soxta telefon "+998 (90) --- -- --", bugungi sana va 10 kun bilan ko'rsatilar va chekka chiqarilardi | Yo'q qiymat "—" bo'lib qoladi; chekda yotoq-kun qatori faqat statsionar uchun |
| Buxgalteriya — Yangi hisob | Kunlar soni bo'sh qolsa 10 kun hisoblanardi; maydon oldindan 10 bilan to'ldirilgan edi | Maydon bo'sh ochiladi, kunlar kiritilmasa hisob ochilmaydi |
| Buxgalteriya | Ishlatilmaydigan eski kod brauzer xotirasidagi bronlardan 10 kunlik va "BED-1A" li hisob yasay olardi | Olib tashlandi |
| Qabulxona — Konsultatsiya | Kvitansiyada 250 000 so'm konsultatsiya narxi chiqardi, lekin hech qayerda hisobga yozilmasdi — pul bepul berilardi | Konsultatsiya qayd etilganda hisob ochiladi: 1 qator, qabulxonada yozilgan narx (yozilmasa — narxlar ro'yxatidagi). Narx 0 yoki noto'g'ri bo'lsa rad etiladi |
| Qabulxona — Ambulator | Kunlik to'lov (310 000) oldindan ko'rishda ko'rinardi, lekin hisobga yozilmasdi; kurs kunlari maydoni ko'rinmasdi; 2 mahallik kurs tanlansa ham 1 mahallik narx qolardi | "Kurs davomiyligi (kun)" maydoni qo'shildi (majburiy). Hisob: kunlar × kunlik narx, bitta qator. Tanlangan tarifning narxi qo'yiladi |
| Qabulxona — Statsionar | Kunlar soni bo'sh qolsa 7 kun deb olinardi | Kunlar kiritilmasa qabul qilinmaydi |
| Server — Tashrif hisobi | Hisob faqat statsionarga (karavotga) bog'lanardi, shuning uchun tashrifni hisoblab bo'lmasdi | Hisob tashrifga (qabulga) ham bog'lanadi; bitta tashrif — bitta hisob. Qayta yuborilgan so'rov (ikki marta bosish) ikkinchi hisob ochmaydi. To'lov olinmagan tashrif bekor qilinsa hisobi ham o'chadi; to'lov olingan bo'lsa hisob qoladi (qaytarish — buxgalteriyada) |
| Hisobotlar | — | Tashrif hisoblari buxgalteriya jadvali, bemor kartasi (CRM), egasi hisoboti va Telegram hisobotida ko'rinadi ("Ambulator", karavotsiz). Bo'limlar diagrammasiga "Shifokor konsultatsiyalari" qo'shildi |
| Buxgalteriya — Bemor hisoblari (yangi) | Bemorning hisoblarini faqat bittadan ko'rish mumkin edi | Har bir qatorda "Hisoblar" tugmasi: bemorning barcha hisoblari — qatorlari, to'lovlari, chegirma va qoldig'i bilan. Faqat o'qish uchun (`GET /api/accounting/patient-invoices`) |

Qabulxona to'lovni o'zi olmaydi: tashrif hisobi buxgalteriyada "To'lanmagan" bo'lib chiqadi va kassada to'lanadi.

10 ta yangi test qo'shildi, jami 269 ta test o'tadi.

### 2026-10-09: 4-bosqich (E) — server qayta ishga tushganda kirish saqlanadi

| Joy | Xato | Tuzatildi |
|---|---|---|
| Kirish (sessiyalar) | Sessiyalar faqat server xotirasida edi: har bir yangilash yoki qayta ishga tushirishda barcha xodimlar smena o'rtasida tizimdan chiqib ketardi, to'ldirilayotgan shakllar yo'qolardi | Sessiyalar MySQL'dagi yangi `user_sessions` jadvalida saqlanadi. Server qayta ishga tushgandan keyin xodim qaytadan kirmasdan ishlashda davom etadi. 12 soatlik harakatsizlik muddati o'zgarmadi |
| Xavfsizlik | — | Bazada cookie tokenining o'zi emas, faqat SHA-256 xeshi saqlanadi: jadval nusxasi (zaxira, dump) bilan hech kim tizimga kira olmaydi. IP manzil va brauzer nomi ham yoziladi |
| Xavfsizlik | — | Sessiya tiklanganda xodim ma'lumoti `users.json` dan qayta o'qiladi: o'chirilgan yoki bloklangan xodim qaytib kira olmaydi, rol o'zgarsa yangisi amal qiladi |
| Chiqish va "hamma joydan chiqarish" | — | "Chiqish", parolni almashtirish, administrator parolni tiklashi, rol/holat o'zgarishi va xodimni o'chirish bazadagi sessiyalarni ham o'chiradi — qayta ishga tushirish ularni qaytarmaydi |
| Server unumdorligi | — | Oxirgi faollik vaqti bazaga har so'rovda emas, daqiqasiga ko'pi bilan bir marta yoziladi. Muddati o'tgan sessiyalar har kirishda va server ishga tushganda o'chiriladi |
| MySQL ishlamay qolsa | — | `/api/auth/session` 500 bermaydi: xotiradagi sessiyalar ishlashda davom etadi, notanish sessiya "kirilmagan" deb hisoblanadi (kirish uchun baribir MySQL kerak, avvalgidek) |

Serverdagi MySQL foydalanuvchisiga `user_sessions` jadvali uchun `CREATE` (birinchi ishga tushishda bir marta), `SELECT`, `INSERT`, `UPDATE`, `DELETE` huquqlari kerak. Hammani darhol tizimdan chiqarish: `DELETE FROM user_sessions;` va serverni qayta ishga tushirish.

9 ta yangi test qo'shildi, jami 278 ta test o'tadi.

### 2026-10-09: 4-bosqich — tekshiruv tuzatishlari

4-bosqich (A–E) kodini qayta tekshirishda topilgan xatolar.

| Joy | Xato | Tuzatildi |
|---|---|---|
| Super-Portal, HR, Buxgalteriya — tugmalar | Xodim, xona, hisob yoki tashrif ID'sida qo'shtirnoq (') bo'lsa, tugma bosilganda shu matn skript sifatida ishlardi (Super-Portalda — bosh administrator huquqi bilan) | Tugmalarga ID xavfsiz shaklda uzatiladi. Server ham sahifa o'zi tanlagan ID'ni faqat lotin harflari, raqam, `-` va `_` (64 belgigacha) bo'lsa qabul qiladi (xodim, tashrif, to'lov, bemor, qo'ng'iroq, anamnez, retsept, epikriz) |
| Buxgalteriya — Hisoblar jadvali | Hisob raqami, bemor ismi, karavot, shifokor va jurnal yozuvlari tozalanmasdan chiqarilardi | Hammasi xavfsiz ko'rsatiladi |
| Foydalanuvchilar (admin) | "admin" (yozish) ruxsati bor xodim o'zini yoki boshqani bosh administrator qila olardi, `*` ruxsatini bera olardi, boshqa bosh administratorning parolini tiklab, uning nomidan kira olardi | Bosh administrator rolini, `*` va "admin" yozish ruxsatini faqat bosh administrator beradi; bosh administrator (va foydalanuvchilarni boshqaradigan) hisobni faqat bosh administrator o'zgartiradi yoki parolini tiklaydi (aks holda 403) |
| Buxgalteriya — Maosh | "Shu oy to'langan" tekshiruvi faqat brauzerda edi: ikkinchi oyna yoki takroriy bosish bir xodimga ikki marta maosh to'lardi | Server bir xodimga bir oy uchun ikkinchi maoshni rad etadi (409, sababi bilan) |
| Buxgalteriya — Maosh oyi | Maoshni faqat joriy kalendar oy uchun to'lash mumkin edi; oy almashgach o'tgan oyning maoshini to'lab bo'lmasdi, tekshiruv yozilgan sanaga qarardi | Maosh bo'limida **"Maosh oyi"** tanlagichi bor (joriy oy — standart). Tanlangan oy hisobi yuklanadi va to'lov shu oy uchun yoziladi (`payroll_month` ustuni, avtomatik qo'shiladi). Eski yozuvlar sanasiga qarab hisoblanadi |
| Qabulxona — Tashrifni bekor qilish | To'lanmagan tashrif bekor qilinsa, hisobdagi **hamma** qatorlar o'chardi — buxgalteriyada qo'shilgan dorilar ham (ombordan ayirilgan dori hisobdan yo'qolardi) | Faqat tashrif haqi qatori o'chadi. Boshqa qatorlar bo'lsa hisob qoladi va xabarda aytiladi |
| Server — xodimlar ro'yxati | `/api/doctors` har bir xodimga shifokorlar okladini yuborardi; `/api/staff` protsedura haqini yashirmasdi | Oklad va protsedura haqi faqat HR, buxgalteriya (yozish) va klinika egasiga yuboriladi |
| HR | Lavozim nomi, ism, telefon, Telegram tozalanmasdan kartochkalarga chiqarilardi | Xavfsiz ko'rsatiladi; server lavozim va Telegram maydonlarida `< > "` belgilarini rad etadi |
| Audit jurnali | Mavjud bo'lmagan login bilan kirish urinishi yozilganda yozilgan matn (ko'pincha login maydoniga yozib yuborilgan parol) jurnalda ko'rinardi | Bunday urinish `[noma'lum login]` deb yoziladi; eski yozuvlar server ishga tushganda yashiriladi (mavjud xodimlar logini qoladi) |
| Hamshira / Palata — Davolash rejasi | Sekin javob boshqa bemor uchun ochilgan oynaga tushishi mumkin edi (boshqa bemorning dorilari) | Kech kelgan javob tashlab yuboriladi |
| Super-Portal — Foydalanuvchini tahrirlash | Faolsizlantirilgan xodimga bog'langan foydalanuvchi oynasida "Bog'lanmagan" chiqardi va saqlashda bog'lanish o'chib ketardi | Joriy bog'lanish "(faol emas)" belgisi bilan saqlanadi; ro'yxat yuklanib bo'lgach oyna to'ldiriladi |
| HR — Xodimni tahrirlash | Faolsizlantirilgan xodimni tahrirlash (masalan, telefonni tuzatish) uni jimgina qayta faollashtirardi (jadval va maoshga qaytardi) | Tahrir holatni o'zgartirmaydi; qayta faollashtirish faqat "Qayta faollashtirish" tugmasi bilan |
| Server ishga tushishi | Barcha avtomatik yangilanishlar bitta blokda edi: bittasi xato bersa, qolganlari jimgina bajarilmasdi | Har bir qadam alohida, xatosi logga yoziladi. Parollarni yashirish faqat hali yashirilmagan yozuvlarni o'qiydi (har safar 2 600+ yozuvni emas) |
| Kirish (sessiyalar) | Faollik vaqti bir xil soniyaga yozilsa sessiya "bekor qilingan" deb tushunilib, xodim tizimdan chiqarilardi | Tuzatildi |
| Kirish (sessiyalar) | "Chiqish" yoki "hamma joydan chiqarish" paytida baza vaqtincha ishlamasa, sessiya keyinroq qayta tiklanishi mumkin edi | Bekor qilingan sessiyalar xotirada ham eslab qolinadi va qaytarilmaydi; bazadan o'chirish qayta urinib ko'riladi |
| Kirish (sessiyalar) | `users.json` vaqtincha yo'qolsa (iCloud nomini o'zgartirgan holat), barcha sessiyalar bazadan o'chirilardi | Sessiya o'chirilmaydi, so'rov rad etiladi; fayl qaytgach ishlash davom etadi |
| Saytdan kelgan ariza — qabul qilish | Shifokor o'rniga istalgan xodim tanlanardi; o'tgan sana qabul qilinardi; "uyga chiqish" bron qilinardi; bemor faqat telefon bo'yicha topilardi (bir oiladagi boshqa odamning kartasiga tushardi) | Faqat faol shifokor; o'tgan sana rad etiladi; "uyga chiqish" ambulator tashrif sifatida yoziladi (PO: hozircha uyga chiqish yo'q); bemor telefon **va** ism bo'yicha topiladi |
| Buxgalteriya | Kassir sifatida to'qima ism yozilardi; inkassatsiyada majburiy "topshiruvchi" ismi hech qayerda saqlanmasdi | To'qima ism olib tashlandi; topshiruvchi ismi va izoh jurnal yozuviga qo'shiladi |
| Telegram | Muhit o'zgaruvchisida xato (masalan, topic raqami o'rniga matn) barcha Telegram xabarlarini jimgina o'chirib qo'yardi | Noto'g'ri qiymat e'tiborsiz qoldiriladi va logga bir qator yoziladi |
| HR — Davomat | Server UTC vaqtda ishlasa, Toshkentda 00:00–05:00 orasida bugungi davomat "kelajak kun" deb rad etilardi | Bir kunlik farqqa ruxsat berildi |
| Qabulxona — Takroriy konsultatsiya | Shu kuni shu shifokorga to'langan konsultatsiyadan keyin ikkinchi haqiqiy konsultatsiya "qayta yuborish" deb hisoblanib, hisobga yozilmasdi | Faqat oxirgi 10 daqiqada ochilgan va to'lanmagan tashrif qayta yuborish deb hisoblanadi (sahifa so'rov ID'sini yubormaydi, qayta yuborish soniyalar ichida bo'ladi) |

Ko'rinadigan o'zgarishlar: Buxgalteriya → Maosh bo'limida "Maosh oyi" tanlagichi; bir oy uchun takroriy maosh endi server xabari bilan rad etiladi; faolsizlantirilgan xodimni tahrirlash uni faollashtirmaydi; "admin" huquqli (bosh administrator bo'lmagan) xodim bosh administrator huquqlarini bera olmaydi.

17 ta yangi test qo'shildi, jami 295 ta test o'tadi.

### 2026-10-10: Ombor (W1a) — zaxira va harakat daftari

Tibbiy ombor serveri (`inventory.py`, yo'llar `warehouse_api.py`, `/api/warehouse/*`). Loyiha: `docs/WAREHOUSE_DESIGN.md`. Sahifa (interfeys) va eski kodlarni (hamshira dozasi, hisob qatori, dori xaridi) yangi xizmatga o'tkazish keyingi qadam; hozircha ular eski usulda ishlayveradi.

| Joy | Xato | Tuzatildi |
|---|---|---|
| Ombor — qoldiq | Qoldiq oddiy son edi: u qayerdan kelgani va qayerga ketgani hech qayerda yozilmasdi; hisob buzilsa, sababini topib bo'lmasdi | Har bir o'zgarish o'zgarmas **harakat daftariga** (`inventory_transactions`) yoziladi, shu bilan bir tranzaksiyada. Bazaning o'zi daftardagi yozuvni o'zgartirish va o'chirishni rad etadi (tuzatish — teskari yozuv bilan). Qoldiq, partiyalar va daftar `GET /api/warehouse/reconciliation` bilan solishtiriladi |
| Ombor — partiyalar | Yaroqlilik muddati va partiya hisobi yo'q edi | Har bir kirim partiya (`inventory_batches`) ochadi. Dori beriladigan paytda eng erta muddatli partiya birinchi olinadi (FEFO); muddati o'tgan partiyadan berib bo'lmaydi; muddati tugayotgan va o'tgan partiyalar ogohlantirishga tushadi |
| Ombor — narxlar | Dori xaridi bemorga sotiladigan narxni (`unit_price`) xarid narxi bilan **ustiga yozib yuborardi** | Uch narx ajratildi: **xarid narxi**, **o'rtacha tannarx** (har kirimda o'rtacha hisoblanadi) va **bemor narxi** (xarid unga tegmaydi). Ombor qiymati = qoldiq × o'rtacha tannarx; jami / muddati o'tgan / yaroqli qismlarga bo'linadi |
| Ombor — o'lchov | Qoldiq faqat butun son; qadoq (quti) va dona farqi yo'q edi | Hamma miqdor eng kichik birlikda (tabletka, ml, dona…), kasr bo'lishi mumkin (faqat ruxsat berilgan mahsulotlarda). 3 quti × 30 tabletka = 90 tabletka, narxi qutining 1/30 qismi |
| Ombor — kirim hujjati | Xarid darhol qoldiqqa qo'shilardi; xato bo'lsa faqat o'chirish mumkin edi | Qoralama (qoldiqqa tegmaydi) → tasdiqlash → (bekor qilish yoki qaytarish). Tasdiqlash bitta tranzaksiyada: partiyalar, daftar, o'rtacha tannarx, buxgalteriya xarajati (`medication_purchase`) va ogohlantirishlar. Ikkinchi marta tasdiqlab bo'lmaydi. Qaytarilganda xarajat bekor qilinadi, daftardagi yozuvlar qoladi; mahsulotning bir qismi ishlatilgan bo'lsa qaytarib bo'lmaydi |
| Ombor — dori berish | Retsept yozilishi yoki doza berilishi qoldiqni tekshirmasdi va nima haqiqatda berilgani saqlanmasdi | Retsept qoldiqni o'zgartirmaydi. Dori faqat faol retsept bo'yicha beriladi (bekor qilingan, yakunlangan, to'xtatilgan retsept rad etiladi), qoldiqdan ko'p berib bo'lmaydi, retseptda yozilgan miqdordan ortiq ham. Qisman berish mumkin. Bemor tarixi (`GET /dispensings?patient_id=`) **haqiqatda berilgan** miqdor, partiya, doza va shifokorni saqlaydi. Berish bekor qilinsa, qoldiq qaytadi, tarix qoladi |
| Ombor — takroriy bosish | Ikki marta bosish yoki qayta yuborish ikki marta ayirardi | `client_request_id` — bir xil so'rov bir marta bajariladi, ikkinchisi birinchi natijani qaytaradi |
| Ombor — bir vaqtda ishlash | Ikki kishi oxirgi donani bir vaqtda olsa, qoldiq manfiy bo'lishi mumkin edi | Mahsulot va partiya qatorlari qulflanadi; oxirgi birliklarga parallel so'rovlar qoldiqni manfiy qilmaydi (sinovdan o'tgan). Xato bo'lsa, qoldiq, daftar va tarixning hech biri o'zgarmaydi |
| Ombor — kam qoldiq | "Kam" deb qoldiq **teng** bo'lganda ham aytilardi (`<=`) | Faqat qoldiq minimaldan **qat'iy kam** bo'lsa (`<`). "Tugagan" (qoldiq 0) alohida holat. Minimal qoldiq oldindan 10 (sozlamadan olinadi, kodga yozilmagan), buxgalter har bir mahsulot uchun o'zgartiradi. `v_pharmacy_low_stock` va egasi hisobotidagi "kam" belgisi ham shunga moslandi |
| Ombor — ruxsatlar | Ombor uchun alohida huquq yo'q edi | Yangi `warehouse` moduli: farmatsevt va buxgalter — o'qish va yozish; bosh shifokor, statsionar menejeri, klinika egasi — faqat o'qish. Shifokor va hamshira faqat "bor-yo'qligini" so'raydi (`/availability`, narxsiz). **Narxlar va qiymat** (xarid narxi, tannarx, jami qiymat, kirim summalari) faqat buxgalter, egasi va bosh administratorga ko'rinadi; kirim hujjati, minimal qoldiq va bemor narxini faqat buxgalter o'zgartiradi (farmatsevt 403 oladi) |
| Ombor — hisobotlar | — | `GET /reports/<nom>`: qoldiq, kam qoldiq, tugagan, muddat, qiymat (jami va kategoriya bo'yicha), kirimlar, berilganlar, tuzatishlar, harakat (mahsulot bo'yicha), solishtirish. `?format=csv` — Excel uchun fayl (formula bo'lib ketadigan matn zararsizlantiriladi) |
| Dori retsepti | Retseptda ombor mahsuloti va buyurilgan miqdor saqlanmasdi | `POST /api/doctor/prescriptions` ixtiyoriy `medication_id`, `quantity_prescribed`, `quantity_unit` qabul qiladi (bo'sh bo'lsa bo'sh qoladi, hech narsa o'ylab topilmaydi) |
| Baza | `stock_quantity` va `min_stock_level` butun son edi | `DECIMAL(14,3)`; mavjud qoldiq uchun "OCHILISH" partiyasi va daftarga "opening" yozuvi qo'shildi (tannarx 0 — haqiqiysi noma'lum, o'ylab topilmadi). Migratsiya takroran ishga tushsa ham xavfsiz; hamma o'zgarish `data/schema.mysql.sql` ga ko'chirildi |

Ko'rinadigan o'zgarishlar: yangi `/api/warehouse/*` yo'llari va `warehouse` huquqi; Super-Portal va boshqa sahifalar hozircha o'zgarmadi; bemorga sotiladigan narx endi xarid bilan o'zgarmaydi (faqat yangi `POST /api/warehouse/receipts` orqali; eski `/api/accounting/medication-purchases` hali eski usulda ishlaydi).

**Administrator uchun (bir marta):** daftarni "o'zgarmas" qiluvchi ikkita trigger (`trg_inv_txn_no_update`, `trg_inv_txn_no_delete`) uchun MySQL foydalanuvchisiga `TRIGGER` huquqi va `log_bin_trust_function_creators=1` (yoki SUPER) kerak. Dastur foydalanuvchisida bu huquq bo'lmasa, server ishga tushganda logga "trigger ... failed" yozadi va ishlashda davom etadi; shunda `data/schema.mysql.sql` ichidagi ikkita `CREATE TRIGGER` buyrug'ini administrator bir marta qo'lda bajaradi (shundan keyingina daftar bazaning o'zi tomonidan himoyalanadi).

**Hali qilinmagan (keyingi qadam):** (1) `warehouse.html` sahifasi va menyu; (2) hamshira dozasi, hisob qatori (invoice-items), eski dori xaridi va bemorni o'chirish yangi xizmatga ulanadi — shu paytgacha ular qoldiqni eski usulda o'zgartiradi va `GET /reconciliation` o'sha mahsulotlarni "mos kelmaydi" deb ko'rsatadi; (3) hamshira hisobotida (`medicine_usage`) kasr qoldiq butun songa qirqiladi.

Boshqa tuzatma: `SessionsSurviveRestart.test_last_seen_is_not_written_on_every_request` sinovi kasr soniya sababli uch martadan birida xato berardi — butun soniyaga keltirildi (dastur kodi o'zgarmadi).

53 ta yangi test qo'shildi, jami 348 ta test o'tadi.

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

- **245 avtomatlashtirilgan test**, faqat standart kutubxona.
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
8. Ro'yxatlarda sahifalash (pagination) yo'q — hozirgi hajmda muammo
   emas, yillar o'tib sekinlashadi.
9. `audit_logs` uchun ko'rish interfeysi (ma'lumot yoziladi, lekin
   ko'rish uchun SQL kerak).

**PO qarori kerak:**

11. **Shifokorlarga gonorar (bemorlar to'lovidan ulush) beriladimi?**
   Buxgalteriya sahifasi 8–10 % ulushni o'zi to'qib qo'shardi — bu olib
   tashlandi, chunki hech qayerda belgilangan stavka yo'q. Agar gonorar
   kerak bo'lsa: kimga, necha foiz, nimadan (hisoblangan summa yoki
   to'langan pul), qaysi oy uchun — shuni aytsangiz, u server maosh
   hisobiga (HR bilan bir joyda) qo'shiladi.
12. **Tashrif to'lovi qabulxonada olinadimi?** Hozir konsultatsiya va
   ambulator hisobi ochiladi, pulni kassa (buxgalteriya) qabul qiladi.
   Qabulxona ham pul olishi kerak bo'lsa, buni alohida yoqish mumkin.
13. **Kursni qisman bekor qilish.** Ambulator yoki statsionar kurs
   o'rtasida bekor qilinsa, o'tgan kunlar va berilgan dorilar qanday
   hisobdan chiqariladi (to'liq to'lanadimi, qolgan kunlar qaytariladimi)?
   Hozir faqat to'lanmagan tashrifning tashrif haqi qatori o'chiriladi.
14. **Ushlab qolingan soliq va pensiya uchun xarajat turi.** Maoshda sof
   summa to'lanadi; daromad solig'i va pensiyani davlatga o'tkazish uchun
   alohida xarajat turi (kategoriya) kerakmi va qanday nomlansin?
15. **Oy o'rtasida ishdan ketgan xodimning okladi.** Oklad ishlagan
   kunlarga bo'lib (pro-rata) hisoblanadimi yoki to'liq oy uchunmi?
   Hozir to'liq oklad ko'rsatiladi.

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
