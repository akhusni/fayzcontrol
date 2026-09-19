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
INSERT IGNORE INTO rooms (id, floor_number, room_number, room_name_uz, room_name_ru, room_name_en, room_type, total_capacity) VALUES
('ROOM-CONS-1', 1, '1-KONS', '1-Konsultatsiya (Bosh shifokor)', 'Кабинет 1 (Главврач)', 'Consultation 1 (Chief Doctor)', 'consultation', 1),
('ROOM-CONS-2', 1, '2-KONS', '2-Konsultatsiya (Diagnostika & Psixoterapiya)', 'Кабинет 2 (Диагностика)', 'Consultation 2 (Diagnostics)', 'consultation', 1),
('ROOM-REG-1',  1, 'QABUL',  'Qabulxona va Kutish zali', 'Регистратура и Приемный покой', 'Reception & Lobby', 'reception', 4),
('ROOM-NURS-1', 1, 'POST-1', '1-Qavat Hamshiralar posti', 'Пост медсестры 1-й этаж', '1st Floor Nurse Station', 'nurse_station', 1),
('ROOM-11',     1, '11',     '11-Xona (Standart 2 o''rinli)', 'Палата 11 (Стандарт 2-местная)', 'Ward 11 (Standard 2-bed)', 'standard_ward', 2),
('ROOM-12',     1, '12',     '12-Xona (Standart 2 o''rinli)', 'Палата 12 (Standart 2-местная)', 'Ward 12 (Standard 2-bed)', 'standard_ward', 2),

('ROOM-NURS-2', 2, 'POST-2', '2-Qavat Markaziy Hamshiralar posti', 'Центральный пост 2-й этаж', '2nd Floor Nurse Station', 'nurse_station', 2),
('ROOM-21',     2, '21',     '21-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 21 (2-местная / Люкс 1.1M)', 'Ward 21 (2-bed / Lux 1.1M)', 'standard_ward', 2),
('ROOM-22',     2, '22',     '22-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 22 (2-местная / Lyuks 1.1M)', 'Ward 22 (2-bed / Lux 1.1M)', 'standard_ward', 2),
('ROOM-23',     2, '23',     '23-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 23 (2-местная / Lyuks 1.1M)', 'Ward 23 (2-bed / Lux 1.1M)', 'standard_ward', 2),
('ROOM-24',     2, '24',     '24-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 24 (2-местная / Lyuks 1.1M)', 'Ward 24 (2-bed / Lux 1.1M)', 'standard_ward', 2),
('ROOM-25',     2, '25',     '25-Xona (2 o''rinli / Lyuks 1.1M)', 'Палата 25 (2-местная / Lyuks 1.1M)', 'Ward 25 (2-bed / Lux 1.1M)', 'standard_ward', 2);

-- ----------------------------------------------------------------------------
-- 2. 14 INPATIENT BEDS (100% Bo'sh / Available)
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO beds (id, room_id, bed_code, bed_type, default_daily_rate, status) VALUES
('BED-1A',  'ROOM-11', '1A',  'standard', 720000.0, 'available'),
('BED-1B',  'ROOM-11', '1B',  'standard', 720000.0, 'available'),
('BED-2A',  'ROOM-12', '2A',  'standard', 720000.0, 'available'),
('BED-2B',  'ROOM-12', '2B',  'standard', 720000.0, 'available'),

('BED-21A', 'ROOM-21', '21A', 'standard', 720000.0, 'available'),
('BED-21B', 'ROOM-21', '21B', 'standard', 720000.0, 'available'),
('BED-22A', 'ROOM-22', '22A', 'standard', 720000.0, 'available'),
('BED-22B', 'ROOM-22', '22B', 'standard', 720000.0, 'available'),
('BED-23A', 'ROOM-23', '23A', 'standard', 720000.0, 'available'),
('BED-23B', 'ROOM-23', '23B', 'standard', 720000.0, 'available'),
('BED-24A', 'ROOM-24', '24A', 'standard', 720000.0, 'available'),
('BED-24B', 'ROOM-24', '24B', 'standard', 720000.0, 'available'),
('BED-25A', 'ROOM-25', '25A', 'standard', 720000.0, 'available'),
('BED-25B', 'ROOM-25', '25B', 'standard', 720000.0, 'available');

-- ----------------------------------------------------------------------------
-- 3. MEDICAL & CLINICAL STAFF
-- ----------------------------------------------------------------------------
INSERT IGNORE INTO staff (id, full_name, role, specialty, phone, salary_base, is_active) VALUES
('STF-DOC-01', 'Dr. Bobur Mirzayev',   'chief_doctor', 'Bosh Shifokor / Narkolog-Psixiatr', '+998901001122', 15000000.0, 1),
('STF-DOC-02', 'Dr. Jasur Aliyev',     'doctor',       'Shifokor-Narkolog',                 '+998902003344', 12000000.0, 1),
('STF-DOC-03', 'Dr. Dilnoza Rahimova', 'doctor',       'Psixoterapevt / Psixiatr',          '+998903005566', 10000000.0, 1),
('STF-NRS-01', 'Nilufar Karimova',    'nurse',        'Katta Hamshira',                    '+998904007788', 6000000.0,  1),
('STF-NRS-02', 'Shahnoza Qodirova',   'nurse',        'Post Hamshirasi',                   '+998905009900', 5000000.0,  1),
('STF-REC-01', 'Malika Usmonova',     'receptionist', 'Qabulxona Administratori',           '+998906001133', 4500000.0,  1);

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
