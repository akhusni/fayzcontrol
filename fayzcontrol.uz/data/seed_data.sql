-- ============================================================================
-- FAYZ MEDICAL HOUSE — MASTER PRODUCTION SEED DATA (MySQL 8)
-- Contains: 12 Rooms, 14 Inpatient Beds, Medical Staff, Services Catalog,
--           Essential Pharmacy Formulary
--
-- Load AFTER data/schema.mysql.sql:
--     mysql -u <user> -p <database> < data/schema.mysql.sql
--     mysql -u <user> -p <database> < data/seed_data.sql
--
-- These statements said INSERT OR REPLACE INTO, which is SQLite. MySQL
-- rejects it outright with error 1064, so a fresh install following the
-- README ended up with no rooms, no beds and no staff -- and the whole
-- stationary side of the system has nothing to work with.
--
-- INSERT IGNORE, not REPLACE INTO: REPLACE deletes the existing row and
-- inserts a new one, which resets every column the seed does not name
-- (created_at among them) and briefly removes a row that beds and admissions
-- point at. IGNORE leaves anything already there alone, so this file stays
-- safe to re-run against a populated database.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. CLINIC ROOMS & WARDS
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO rooms (id, building_number, floor_number, room_number, room_name_uz, room_name_ru, room_name_en, room_type, total_capacity) VALUES
-- 1-Bino Xonalari
('ROOM-CONS-1', 1, 1, '1-KONS', '1-Konsultatsiya (Bosh shifokor)', 'Кабинет 1 (Главврач)', 'Consultation 1 (Chief Doctor)', 'consultation', 1),
('ROOM-CONS-2', 1, 1, '2-KONS', '2-Konsultatsiya (Diagnostika & Psixoterapiya)', 'Кабинет 2 (Диагностика)', 'Consultation 2 (Diagnostics)', 'consultation', 1),
('ROOM-REG-1', 1,  1, 'QABUL',  'Qabulxona va Kutish zali', 'Регистратура и Приемный покой', 'Reception & Lobby', 'reception', 4),
('ROOM-NURS-1', 1, 1, 'POST-1', '1-Qavat Hamshiralar posti', 'Пост медсестры 1-й этаж', '1st Floor Nurse Station', 'nurse_station', 1),
('ROOM-11', 1,     1, '11',     '11-Xona (Standart 2 o''rinli)', 'Палата 11 (Стандарт 2-местная)', 'Ward 11 (Standard 2-bed)', 'standard_ward', 2),
('ROOM-12', 1,     1, '12',     '12-Xona (Standart 2 o''rinli)', 'Палата 12 (Standart 2-местная)', 'Ward 12 (Standard 2-bed)', 'standard_ward', 2),

('ROOM-NURS-2', 1, 2, 'POST-2', '2-Qavat Markaziy Hamshiralar posti', 'Центральный пост 2-й этаж', '2nd Floor Nurse Station', 'nurse_station', 2),
('ROOM-21', 1,     2, '21',     '21-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 21 (2-местная / Люкс 1.1M)', 'Ward 21 (2-bed / Lux 1.1M)', 'standard_ward', 2),
('ROOM-22', 1,     2, '22',     '22-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 22 (2-местная / Lyuks 1.1M)', 'Ward 22 (2-bed / Lux 1.1M)', 'standard_ward', 2),
('ROOM-23', 1,     2, '23',     '23-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 23 (2-местная / Lyuks 1.1M)', 'Ward 23 (2-bed / Lux 1.1M)', 'standard_ward', 2),
('ROOM-24', 1,     2, '24',     '24-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 24 (2-местная / Lyuks 1.1M)', 'Ward 24 (2-bed / Lux 1.1M)', 'standard_ward', 2),
('ROOM-25', 1,     2, '25',     '25-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 25 (2-местная / Lyuks 1.1M)', 'Ward 25 (2-bed / Lux 1.1M)', 'standard_ward', 2),

-- Yangi 2-Bino Xonalari (5 ta xona)
('ROOM-B2-04', 2, 1, '4', '2-Bino 4-Xona (2 o''rinli)', '2-Корпус 4-Палата (2-местная)', 'Building 2 Room 4 (2-bed)', 'standard_ward', 2),
('ROOM-B2-05', 2, 1, '5', '2-Bino 5-Xona (3 o''rinli)', '2-Корпус 5-Палата (3-местная)', 'Building 2 Room 5 (3-bed)', 'standard_ward', 3),
('ROOM-B2-01', 2, 2, '1', '2-Bino 1-Xona (VIP 1 o''rinli)', '2-Корпус 1-Палата (VIP 1-местная)', 'Building 2 Room 1 (VIP Single)', 'vip_ward', 1),
('ROOM-B2-02', 2, 2, '2', '2-Bino 2-Xona (2 o''rinli)', '2-Корпус 2-Палата (2-местная)', 'Building 2 Room 2 (2-bed)', 'standard_ward', 2),
('ROOM-B2-03', 2, 2, '3', '2-Bino 3-Xona (2 o''rinli)', '2-Корпус 3-Палата (2-местная)', 'Building 2 Room 3 (2-bed)', 'standard_ward', 2);

-- ----------------------------------------------------------------------------
-- 2. 14 INPATIENT BEDS
--
-- beds.status is the PHYSICAL state of the bed and accepts only
-- operational / cleaning / maintenance / out_of_service. 'available',
-- 'occupied' and 'reserved' are DERIVED for a given date by the
-- v_bed_live_status view; writing one of them violates beds_chk_3.
--
-- These fourteen rows said 'available'. INSERT IGNORE swallowed the
-- constraint violation without a word, so a fresh install produced twelve
-- rooms and ZERO beds, and the whole stationary side had nothing to work
-- with. It only appears on an empty database -- which is exactly what a new
-- clinic starts with.
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO beds (id, room_id, bed_code, bed_type, default_daily_rate, status) VALUES
('BED-1A',  'ROOM-11', '1A',  'standard', 720000.0, 'operational'),
('BED-1B',  'ROOM-11', '1B',  'standard', 720000.0, 'operational'),
('BED-2A',  'ROOM-12', '2A',  'standard', 720000.0, 'operational'),
('BED-2B',  'ROOM-12', '2B',  'standard', 720000.0, 'operational'),

('BED-21A', 'ROOM-21', '21A', 'standard', 720000.0, 'operational'),
('BED-21B', 'ROOM-21', '21B', 'standard', 720000.0, 'operational'),
('BED-22A', 'ROOM-22', '22A', 'standard', 720000.0, 'operational'),
('BED-22B', 'ROOM-22', '22B', 'standard', 720000.0, 'operational'),
('BED-23A', 'ROOM-23', '23A', 'standard', 720000.0, 'operational'),
('BED-23B', 'ROOM-23', '23B', 'standard', 720000.0, 'operational'),
('BED-24A', 'ROOM-24', '24A', 'standard', 720000.0, 'operational'),
('BED-24B', 'ROOM-24', '24B', 'standard', 720000.0, 'operational'),
('BED-25A', 'ROOM-25', '25A', 'standard', 720000.0, 'operational'),
('BED-25B', 'ROOM-25', '25B', 'standard', 720000.0, 'operational'),

-- Yangi 2-Bino Karavotlari (10 ta karavot)
('BED-B2-4A', 'ROOM-B2-04', 'B2-4A', 'standard', 720000.0, 'operational'),
('BED-B2-4B', 'ROOM-B2-04', 'B2-4B', 'standard', 720000.0, 'operational'),
('BED-B2-5A', 'ROOM-B2-05', 'B2-5A', 'standard', 800000.0, 'operational'),
('BED-B2-5B', 'ROOM-B2-05', 'B2-5B', 'standard', 800000.0, 'operational'),
('BED-B2-5C', 'ROOM-B2-05', 'B2-5C', 'standard', 800000.0, 'operational'),
('BED-B2-1',  'ROOM-B2-01', 'B2-1',  'vip',     1000000.0, 'operational'),
('BED-B2-2A', 'ROOM-B2-02', 'B2-2A', 'standard', 720000.0, 'operational'),
('BED-B2-2B', 'ROOM-B2-02', 'B2-2B', 'standard', 720000.0, 'operational'),
('BED-B2-3A', 'ROOM-B2-03', 'B2-3A', 'standard', 800000.0, 'operational'),
('BED-B2-3B', 'ROOM-B2-03', 'B2-3B', 'standard', 800000.0, 'operational');

-- ----------------------------------------------------------------------------
-- 3. MEDICAL & CLINICAL STAFF
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO staff (id, full_name, role, specialty, phone, salary_base, is_active) VALUES
('STF-DOC-01', 'Umarov Xusan Payziboyevich',         'chief_doctor', 'Bosh Shifokor / Narkolog-Psixiatr', '+998 90 000-01-01', 15000000.0, 1),
('STF-DOC-02', 'Shermuxamedova Farida Miraxatovna',  'doctor',       'Davolovchi Shifokor-Narkolog',     '+998 90 000-01-02', 12000000.0, 1),
('STF-DOC-03', 'Vasina Yuliya Aleksandrovna',        'doctor',       'Davolovchi Shifokor-Psixiatr',     '+998 90 000-01-03', 12000000.0, 1),
('STF-NRS-01', 'Abdukarimova Ra\'no Xudayberganovna','nurse',        'Hamshiralik ishi',                 '+998 90 000-02-01', 6000000.0,  1),
('STF-NRS-02', 'Atametova Tursunoy Xudayberganovna', 'nurse',        'Hamshiralik ishi',                 '+998 90 000-02-02', 6000000.0,  1),
('STF-NRS-03', 'G\'aniyeva Saygul Shodmon qizi',     'nurse',        'Hamshiralik ishi',                 '+998 90 000-02-03', 6000000.0,  1),
('STF-NRS-04', 'Safarova Shaxnoza Abdumannapovna',   'nurse',        'Hamshiralik ishi',                 '+998 90 000-02-04', 6000000.0,  1),
('STF-NRS-05', 'Saydaminova Ziyeda Umar qizi',       'nurse',        'Hamshiralik ishi',                 '+998 90 000-02-05', 6000000.0,  1),
('STF-NRS-06', 'Xoltoyeva Shaxlo Sobitjonovna',      'nurse',        'Hamshiralik ishi',                 '+998 90 000-02-06', 6000000.0,  1),
('STF-SPC-01', 'Ibragimova Nodira Batirovna',        'support',      'Tibbiy massaj / Fizioterapiya',    '+998 90 000-03-01', 5000000.0,  1),
('STF-SAN-01', 'Donoboyeva Laylo Donoboyevna',       'sanitar',      'Sanitariya & Gigiyena',            '+998 90 000-04-01', 3800000.0,  1),
('STF-SAN-02', 'Egamqulova Xilola Xoshimqulovna',    'sanitar',      'Sanitariya & Gigiyena',            '+998 90 000-04-02', 3800000.0,  1),
('STF-SAN-03', 'Karabaeva Muxayyo Toshpo\'latovna',  'sanitar',      'Sanitariya & Gigiyena',            '+998 90 000-04-03', 3800000.0,  1),
('STF-SAN-04', 'Karakulova Xurshida Mirzakim qizi',  'sanitar',      'Sanitariya & Gigiyena',            '+998 90 000-04-04', 3800000.0,  1),
('STF-SAN-05', 'Maxkamova Umida Muminovna',          'sanitar',      'Sanitariya & Gigiyena',            '+998 90 000-04-05', 3800000.0,  1),
('STF-SAN-06', 'Musaxanova Fotima Danabayevna',      'sanitar',      'Sanitariya & Gigiyena',            '+998 90 000-04-06', 3800000.0,  1);

-- ----------------------------------------------------------------------------
-- 4. MASTER SERVICES PRICING CATALOG
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO services_catalog (id, name, category, unit_price, description) VALUES
('SRV-DETOX-5',   'Standart Detoksikatsiya dasturi (5 kun)', 'inpatient',     3600000.0, '5 kunlik to''liq statsionar detoks, dori-darmonlar va nazorat'),
('SRV-DETOX-10',  'Intensiv Reabilitatsiya dasturi (10 kun)','inpatient',     7200000.0, '10 kunlik to''liq kompleks reabilitatsiya va psixoterapiya'),
('SRV-CONS-DOC',  'Shifokor Narkolog/Psixiatr konsultatsiyasi','consultation', 250000.0,  'Birlamchi chuqurlashtirilgan ko''rik va davolash rejasi'),
('SRV-PSYCHO-1',  'Individual Psixoterapiya seansi',          'therapy',      300000.0,  '1 soatlik individual psixoterapevtik seans'),
('SRV-ECG-01',    'EKG Elektrokardiogramma tekshiruvi',       'diagnostics',  80000.0,   'Yurak faoliyati elektrokardiografik monitoringi'),
('SRV-LAB-GEN',   'Klinik qon va siydik laboratoriya tahlili', 'diagnostics',  120000.0,  'Umumiy klinik laboratoriya ekspress tahlillari'),
('SRV-IV-DRIP',   'Intensiv infuzion terapiya (1 kapelnitsa)', 'procedure',    150000.0,  'Statsionar yoki ambulator infuzion dori yuborish');

-- ----------------------------------------------------------------------------
-- 5. MASTER MEDICATIONS & PHARMACOLOGY CATALOG
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO medications_catalog (id, name, category, form, standard_dosage, unit_price, stock_quantity, min_stock_level) VALUES
('MED-001', 'Reamberin 1.5% 400ml',      'Detoksikatsiya',  'Infuzion flakon', '400 ml', 45000.0,  50, 15),
('MED-002', 'Heptral 500mg (Ademetionin)','Gepatoprotektor', 'Ampula/Flakon',   '500 mg', 120000.0, 30, 10),
('MED-003', 'Mexidol 5% 2ml',            'Antioksidant',    'Ampula',          '2 ml',   25000.0,  60, 20),
('MED-004', 'Glutathione 600mg',         'Detoksikatsiya',  'Flakon',          '600 mg', 180000.0, 25, 10),
('MED-005', 'Vitamin B-Complex 2ml',     'Vitamin',         'Ampula',          '2 ml',   15000.0,  80, 20),
('MED-006', 'Diazepam 0.5% 2ml',         'Sedativ',         'Ampula',          '2 ml',   35000.0,  40, 15),
('MED-007', 'Magniy Sulfat 25% 10ml',    'Sedativ',         'Ampula',          '10 ml',  8000.0,   75, 25),
('MED-008', 'Natriy Xlorid 0.9% 500ml',  'Eritma',          'Infuzion flakon', '500 ml', 12000.0,  100, 30);

INSERT IGNORE INTO medications_catalog (id, name, category, form, standard_dosage, unit_price, stock_quantity, min_stock_level) VALUES
('FMH-001', 'Natriy oksibutirat (Sodium oxybutyrate) 5.0 ml', 'Narkologiya va Detoksikatsiya', 'Ampula', '5.0 ml (1 ampula)', 45000.0, 120.0, 10),
('FMH-002', 'Verzepam 0.5% - 2.0 ml (Diazepam)', 'Trankvilizatorlar va Uxlatuvchilar', 'Ampula', '2.0 ml (10 mg)', 38000.0, 250.0, 10),
('FMH-003', 'Sibazon 5 mg (Diazepam)', 'Trankvilizatorlar va Uxlatuvchilar', 'Tabletkalar', '1 tabletka (5 mg)', 28000.0, 300.0, 10),
('FMH-004', 'Siklodol 2 mg (Trihexyphenidyl)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (2 mg)', 22000.0, 180.0, 10),
('FMH-005', 'Galopril 0.5% - 1.0 ml (Haloperidol)', 'Neyroleptiklar va Antipsixotiklar', 'Ampula', '1.0 ml (5 mg)', 32000.0, 200.0, 10),
('FMH-006', 'Galopril 5 mg (Haloperidol)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (5 mg)', 26000.0, 240.0, 10),
('FMH-007', 'Galopril 1.5 mg (Haloperidol)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (1.5 mg)', 24000.0, 190.0, 10),
('FMH-008', 'Triftazin 0.2% - 1.0 ml (Trifluoperazine)', 'Neyroleptiklar va Antipsixotiklar', 'Ampula', '1.0 ml (2 mg)', 30000.0, 150.0, 10),
('FMH-009', 'Triftazin 5 mg (Trifluoperazine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (5 mg)', 25000.0, 180.0, 10),
('FMH-010', 'Klofelin 0.15 mg (Clonidine)', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '0.5 - 1 tabletka (0.075 - 0.15 mg)', 18000.0, 140.0, 10),
('FMH-011', 'Amitriptilin 1% - 2.0 ml (Amitriptyline)', 'Antidepressantlar', 'Ampula', '2.0 ml (20 mg)', 28000.0, 210.0, 10),
('FMH-012', 'Amitriptilin 25 mg (Amitriptyline)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (25 mg)', 22000.0, 350.0, 10),
('FMH-013', 'Amitriptilin 10 mg (Amitriptyline)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (10 mg)', 19000.0, 200.0, 10),
('FMH-014', 'Azaleptol 100 mg (Clozapine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '0.5 - 1 tabletka (50-100 mg)', 42000.0, 160.0, 10),
('FMH-015', 'Azaleptol 25 mg (Clozapine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (25 mg)', 34000.0, 190.0, 10),
('FMH-016', 'Alprazolam 1 mg', 'Trankvilizatorlar va Uxlatuvchilar', 'Tabletkalar', '0.5 - 1 tabletka (0.5 - 1 mg)', 52000.0, 170.0, 10),
('FMH-017', 'Fenazepam 1 mg', 'Trankvilizatorlar va Uxlatuvchilar', 'Tabletkalar', '1 tabletka (1 mg)', 36000.0, 260.0, 10),
('FMH-018', 'Olfreks 10 mg (Olanzapine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (10 mg)', 85000.0, 140.0, 10),
('FMH-019', 'Natriy xlorid 0.9% - 250 ml (Saline)', 'Infuzion va Detoks Eritmalar', 'Infuzion flakon', '250 ml', 9000.0, 500.0, 10),
('FMH-020', 'Glyukoza 5% - 250 ml (Glucose)', 'Infuzion va Detoks Eritmalar', 'Infuzion flakon', '250 ml', 9500.0, 420.0, 10),
('FMH-021', 'Reosorbilakt 200 ml (Rheosorbilact)', 'Infuzion va Detoks Eritmalar', 'Infuzion flakon', '200 ml', 32000.0, 310.0, 10),
('FMH-022', 'Modeten Depo 2.5% - 1.0 ml (Fluphenazine decanoate)', 'Neyroleptiklar va Antipsixotiklar', 'Ampula', '1.0 ml (25 mg)', 95000.0, 80.0, 10),
('FMH-023', 'Natriy xlorid 0.9% - 100 ml (Saline)', 'Infuzion va Detoks Eritmalar', 'Infuzion flakon', '100 ml', 7500.0, 480.0, 10),
('FMH-024', 'Analgin 50% - 2.0 ml (Metamizole)', 'Og''riqsizlantiruvchilar va NYAQV', 'Ampula', '2.0 ml', 12000.0, 400.0, 10),
('FMH-025', 'Konvuleks 150 mg (Valproic acid)', 'Normotimiklar va Tutqanoqqa Qarshi', 'Kapsulalar', '1-2 kapsula (150-300 mg)', 68000.0, 160.0, 10),
('FMH-026', 'Karbamazepin 200 mg (Carbamazepine)', 'Normotimiklar va Tutqanoqqa Qarshi', 'Tabletkalar', '1 tabletka (200 mg)', 24000.0, 290.0, 10),
('FMH-027', 'Sedareks 2 mg (Risperidone)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (2 mg)', 58000.0, 130.0, 10),
('FMH-028', 'Tolanz 10 mg (Olanzapine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (10 mg)', 78000.0, 120.0, 10),
('FMH-029', 'Sedalit 300 mg (Lithium carbonate)', 'Normotimiklar va Tutqanoqqa Qarshi', 'Tabletkalar', '1 tabletka (300 mg)', 48000.0, 110.0, 10),
('FMH-030', 'Misol 50 mg (Sertraline)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (50 mg)', 62000.0, 220.0, 10),
('FMH-031', 'Dimedrol 1% - 1.0 ml (Diphenhydramine)', 'Trankvilizatorlar va Uxlatuvchilar', 'Ampula', '1.0 ml (10 mg)', 14000.0, 380.0, 10),
('FMH-032', 'Fenibut 250 mg (Phenibut)', 'Nootropiklar va Neyroprotektorlar', 'Tabletkalar', '1 tabletka (250 mg)', 38000.0, 250.0, 10),
('FMH-033', 'No-Spa 2% - 2.0 ml (Drotaverine)', 'Og''riqsizlantiruvchilar va NYAQV', 'Ampula', '2.0 ml (40 mg)', 26000.0, 320.0, 10),
('FMH-034', 'Kaltsiy glyukonat 10% - 10.0 ml', 'Infuzion va Detoks Eritmalar', 'Ampula', '10.0 ml', 16000.0, 250.0, 10),
('FMH-035', 'Magniy sulfat 25% - 5.0 ml', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '5.0 ml', 11000.0, 350.0, 10),
('FMH-036', 'Riboksin 2% - 10.0 ml (Inosine)', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '10.0 ml', 18000.0, 260.0, 10),
('FMH-037', 'Natriy tiosulfat 30% - 10.0 ml', 'Narkologiya va Detoksikatsiya', 'Ampula', '10.0 ml', 19000.0, 240.0, 10),
('FMH-038', 'Novokain 0.5% - 5.0 ml (Procaine)', 'Og''riqsizlantiruvchilar va NYAQV', 'Ampula', '5.0 ml', 9000.0, 420.0, 10),
('FMH-039', 'Metoklopramid 0.5% - 2.0 ml (Cerucal)', 'Gepatoprotektorlar va Oshqozon-Ichak', 'Ampula', '2.0 ml (10 mg)', 17000.0, 310.0, 10),
('FMH-040', 'Deksametazon 0.4% - 1.0 ml (4 mg)', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '1.0-2.0 ml (4-8 mg)', 21000.0, 360.0, 10),
('FMH-041', 'Strofantin G 0.025% - 1.0 ml', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '0.5 - 1.0 ml (0.125 - 0.25 mg)', 28000.0, 90.0, 10),
('FMH-042', 'Kofein-natriy benzoat 20% - 1.0 ml', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '1.0 ml', 12000.0, 210.0, 10),
('FMH-043', 'Kordiamin 25% - 2.0 ml (Nikethamide)', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '2.0 ml', 14000.0, 220.0, 10),
('FMH-044', 'Kokarboksilaza 50 mg (Cocarboxylase)', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '50 mg', 28000.0, 190.0, 10),
('FMH-045', 'Kaliy xlorid 4% - 10.0 ml (Potassium chloride)', 'Infuzion va Detoks Eritmalar', 'Ampula', '10.0 ml', 10000.0, 310.0, 10),
('FMH-046', 'Fanigan (Paracetamol + Diclofenac)', 'Og''riqsizlantiruvchilar va NYAQV', 'Tabletkalar', '1 tabletka', 31000.0, 350.0, 10),
('FMH-047', 'Normatim (Lithium ascorbate + vitamins)', 'Normotimiklar va Tutqanoqqa Qarshi', 'Tabletkalar', '1 tabletka', 92000.0, 180.0, 10),
('FMH-048', 'Diakarb 250 mg (Acetazolamide)', 'Nootropiklar va Neyroprotektorlar', 'Tabletkalar', '1 tabletka (250 mg)', 42000.0, 210.0, 10),
('FMH-049', 'Citapra 10 mg (Escitalopram)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (10 mg)', 72000.0, 170.0, 10),
('FMH-050', 'Espa-Deprex 20 mg (Escitalopram)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (20 mg)', 84000.0, 130.0, 10),
('FMH-051', 'Fevarin 100 mg (Fluvoxamine)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (100 mg)', 115000.0, 140.0, 10),
('FMH-052', 'Trittiko 150 mg (Trazodone)', 'Antidepressantlar', 'Tabletkalar', '1/3 - 1 tabletka (50-150 mg)', 105000.0, 160.0, 10),
('FMH-053', 'No-Spa 40 mg tabletka (Drotaverine)', 'Og''riqsizlantiruvchilar va NYAQV', 'Tabletkalar', '1-2 tabletka (40-80 mg)', 24000.0, 400.0, 10),
('FMH-054', 'Sonapaks 25 mg (Thioridazine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (25 mg)', 35000.0, 210.0, 10),
('FMH-055', 'Sonapaks 10 mg (Thioridazine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (10 mg)', 29000.0, 190.0, 10),
('FMH-056', 'Prosulpin 200 mg (Sulpiride)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (200 mg)', 54000.0, 160.0, 10),
('FMH-057', 'Grandaksin 50 mg (Tofisopam)', 'Trankvilizatorlar va Uxlatuvchilar', 'Tabletkalar', '1 tabletka (50 mg)', 48000.0, 320.0, 10),
('FMH-058', 'Reksetin 30 mg (Paroxetine)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (30 mg)', 98000.0, 150.0, 10),
('FMH-059', 'Teralidjen 5 mg (Alimemazine)', 'Trankvilizatorlar va Uxlatuvchilar', 'Tabletkalar', '1-2 tabletka (5-10 mg)', 86000.0, 280.0, 10),
('FMH-060', 'Valdoksan 25 mg (Agomelatine)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (25 mg)', 145000.0, 110.0, 10),
('FMH-061', 'Telsartan 80 mg (Telmisartan)', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '1 tabletka (80 mg)', 75000.0, 180.0, 10),
('FMH-062', 'Ketilept 200 mg (Quetiapine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (200 mg)', 110000.0, 150.0, 10),
('FMH-063', 'Tiaprosan 100 mg (Tiapride)', 'Narkologiya va Detoksikatsiya', 'Tabletkalar', '1 tabletka (100 mg)', 78000.0, 170.0, 10),
('FMH-064', 'Korvalol (Corvalol) tomchilari', 'Kardiologiya va Shoshilinch Yordam', 'Tomchi / Flakon', '25-30 tomchi', 9000.0, 350.0, 10),
('FMH-065', 'Piratsetam 20% - 10.0 ml (Piracetam)', 'Nootropiklar va Neyroprotektorlar', 'Ampula', '10.0 ml (2.0 g)', 22000.0, 320.0, 10),
('FMH-066', 'Mildronat 10% - 5.0 ml (Meldonium)', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '5.0 ml (500 mg)', 46000.0, 280.0, 10),
('FMH-067', 'L-lizin essinat 5.0 ml (L-lysine aescinat)', 'Nootropiklar va Neyroprotektorlar', 'Ampula', '5.0 ml', 82000.0, 200.0, 10),
('FMH-068', 'Mirtel 30 mg (Mirtazapine)', 'Antidepressantlar', 'Tabletkalar', '0.5 - 1 tabletka (15-30 mg)', 88000.0, 130.0, 10),
('FMH-069', 'Bisoprolol 5 mg', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '1 tabletka (5 mg)', 18000.0, 310.0, 10),
('FMH-070', 'Bisakodil 10 mg shamcha (Bisacodyl)', 'Gepatoprotektorlar va Oshqozon-Ichak', 'Kapsulalar', '1 shamcha (10 mg)', 16000.0, 220.0, 10),
('FMH-071', 'Senadeksin (Senna glycosides)', 'Gepatoprotektorlar va Oshqozon-Ichak', 'Tabletkalar', '1-2 tabletka', 6000.0, 380.0, 10),
('FMH-072', 'Loperamid 2 mg (Loperamide)', 'Gepatoprotektorlar va Oshqozon-Ichak', 'Kapsulalar', '1-2 kapsula (2-4 mg)', 8000.0, 300.0, 10),
('FMH-073', 'Diklofenak natriy 2.5% - 3.0 ml (75 mg)', 'Og''riqsizlantiruvchilar va NYAQV', 'Ampula', '3.0 ml (75 mg)', 15000.0, 340.0, 10),
('FMH-074', 'Adrenalin 0.18% - 1.0 ml (Epinephrine)', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '0.5 - 1.0 ml', 14000.0, 150.0, 10),
('FMH-075', 'Melbek 1% - 1.5 ml (Meloxicam 15 mg)', 'Og''riqsizlantiruvchilar va NYAQV', 'Ampula', '1.5 ml (15 mg)', 42000.0, 190.0, 10),
('FMH-076', 'Furosemid 1% - 2.0 ml (Furosemide 20 mg)', 'Kardiologiya va Shoshilinch Yordam', 'Ampula', '2.0 ml (20 mg)', 11000.0, 350.0, 10),
('FMH-077', 'Furosemid 40 mg (Furosemide)', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '1 tabletka (40 mg)', 12000.0, 310.0, 10),
('FMH-078', 'Kaptopril 25 mg (Captopril)', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '1 tabletka (25 mg)', 14000.0, 380.0, 10),
('FMH-079', 'Enalapril 5 mg', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '1 tabletka (5 mg)', 14000.0, 320.0, 10),
('FMH-080', 'Validol 60 mg tabletka (sublingual)', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '1 tabletka', 6000.0, 450.0, 10),
('FMH-081', 'Farmadipin tomchilari (Nifedipine)', 'Kardiologiya va Shoshilinch Yordam', 'Tomchi / Flakon', '3-5 tomchi', 28000.0, 160.0, 10),
('FMH-082', 'Enam 10 mg (Enalapril)', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '1 tabletka (10 mg)', 22000.0, 250.0, 10),
('FMH-083', 'Volodip 10/160 mg (Amlodipine + Valsartan)', 'Kardiologiya va Shoshilinch Yordam', 'Tabletkalar', '1 tabletka', 95000.0, 140.0, 10),
('FMH-084', 'Avtoriya 25 mg (Hydroxyzine)', 'Trankvilizatorlar va Uxlatuvchilar', 'Tabletkalar', '1 tabletka (25 mg)', 54000.0, 200.0, 10),
('FMH-085', 'Ketap 200 mg (Quetiapine)', 'Neyroleptiklar va Antipsixotiklar', 'Tabletkalar', '1 tabletka (200 mg)', 96000.0, 140.0, 10),
('FMH-086', 'Velaksin 37.5 mg (Venlafaxine)', 'Antidepressantlar', 'Tabletkalar', '1 tabletka (37.5 mg)', 92000.0, 130.0, 10),
('FMH-087', 'Vinpotsetin 2.0 ml (Vinpocetine / Cavinton)', 'Nootropiklar va Neyroprotektorlar', 'Ampula', '2.0 ml (10 mg)', 28000.0, 250.0, 10),
('FMH-088', 'Vitamin B kompleks 2.0 ml (B1, B6, B12)', 'Nootropiklar va Neyroprotektorlar', 'Ampula', '2.0 ml', 34000.0, 380.0, 10),
('MED-PARACETAMOL-500', 'Paratsetamol 500 mg tabletka (Paracetamol)', 'Og''riqsizlantiruvchi va Isitma tushiruvchi', 'Tabletkalar', '500 mg (1 tabletka)', 1500.0, 0, 10);
