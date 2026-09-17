-- ============================================================================
-- FAYZ MEDICAL HOUSE / FAYZ CONTROL — ENTERPRISE MYSQL 8.0 DATABASE SCHEMA
-- Target Engine: MySQL 8.0+ / MariaDB 10.5+ (InnoDB Engine / UTF8MB4)
-- Architecture: 6 Clinical Domains, Triggers, Financial Constraints & KPI Views
-- ============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================================================
-- DOMAIN 1: FACILITY & INPATIENT INFRASTRUCTURE
-- ============================================================================

-- 1.1 Rooms and Specialized Wards
CREATE TABLE IF NOT EXISTS rooms (
    id VARCHAR(64) PRIMARY KEY,
    floor_number INT NOT NULL CHECK(floor_number IN (1, 2)),
    room_number VARCHAR(32) NOT NULL,
    room_name_uz VARCHAR(255) NOT NULL,
    room_name_ru VARCHAR(255),
    room_name_en VARCHAR(255),
    room_type VARCHAR(64) NOT NULL CHECK(room_type IN (
        'standard_ward', 'vip_ward', 'consultation', 
        'nurse_station', 'reception', 'utility'
    )),
    total_capacity INT NOT NULL DEFAULT 1 CHECK(total_capacity >= 0),
    is_active TINYINT(1) NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 1.2 Inpatient Beds (14 Dedicated Treatment Beds)
CREATE TABLE IF NOT EXISTS beds (
    id VARCHAR(64) PRIMARY KEY,
    room_id VARCHAR(64) NOT NULL,
    bed_code VARCHAR(32) NOT NULL UNIQUE,
    bed_type VARCHAR(32) NOT NULL DEFAULT 'standard' CHECK(bed_type IN ('standard', 'vip')),
    default_daily_rate DECIMAL(14,2) NOT NULL DEFAULT 720000.00 CHECK(default_daily_rate >= 0),
    status VARCHAR(32) NOT NULL DEFAULT 'available' CHECK(status IN (
        'available', 'occupied', 'reserved', 'cleaning', 'maintenance'
    )),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- DOMAIN 2: HUMAN RESOURCES & ACCESS CONTROL
-- ============================================================================

-- 2.1 Staff & Medical Specialists
CREATE TABLE IF NOT EXISTS staff (
    id VARCHAR(64) PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(64) NOT NULL CHECK(role IN (
        'admin', 'chief_doctor', 'doctor', 'nurse', 'receptionist', 'accountant'
    )),
    specialty VARCHAR(255),
    phone VARCHAR(64),
    email VARCHAR(255),
    salary_base DECIMAL(14,2) DEFAULT 0.00 CHECK(salary_base >= 0),
    shift_type VARCHAR(32) DEFAULT 'day' CHECK(shift_type IN ('day', 'night', '24h', 'rotating')),
    is_active TINYINT(1) NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2.2 Staff Duty Shifts & Attendance Logs
CREATE TABLE IF NOT EXISTS staff_attendance (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    staff_id VARCHAR(64) NOT NULL,
    work_date DATE NOT NULL,
    shift_type VARCHAR(32) NOT NULL DEFAULT 'day' CHECK(shift_type IN ('day', 'night', '24h')),
    check_in DATETIME,
    check_out DATETIME,
    status VARCHAR(32) NOT NULL DEFAULT 'present' CHECK(status IN ('present', 'absent', 'late', 'on_leave', 'sick')),
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_staff_work_date (staff_id, work_date),
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- DOMAIN 3: CRM, RECEPTION & PATIENT REGISTRY
-- ============================================================================

-- 3.1 Patient Master Record (Anonymity & Confidentiality Guaranteed)
CREATE TABLE IF NOT EXISTS patients (
    id VARCHAR(64) PRIMARY KEY,
    patient_code VARCHAR(32) NOT NULL UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(64),
    emergency_contact VARCHAR(255),
    gender VARCHAR(16) DEFAULT 'male' CHECK(gender IN ('male', 'female', 'other')),
    birth_year INT,
    address TEXT,
    referral_source VARCHAR(64) DEFAULT 'walk_in',
    is_anonymous TINYINT(1) NOT NULL DEFAULT 0 CHECK(is_anonymous IN (0, 1)),
    medical_allergies TEXT,
    chronic_conditions TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'discharged', 'archived')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3.2 Reception Appointments & Consultations Booking
CREATE TABLE IF NOT EXISTS appointments (
    id VARCHAR(64) PRIMARY KEY,
    patient_id VARCHAR(64),
    patient_name VARCHAR(255) NOT NULL,
    patient_phone VARCHAR(64) NOT NULL,
    doctor_id VARCHAR(64),
    service_type VARCHAR(64) NOT NULL DEFAULT 'outpatient' CHECK(service_type IN (
        'outpatient', 'inpatient_consult', 'psychotherapy', 'home_visit', 'diagnostics'
    )),
    appointment_date DATE NOT NULL,
    appointment_time VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'confirmed' CHECK(status IN (
        'pending', 'confirmed', 'completed', 'cancelled', 'no_show'
    )),
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3.3 Inbound Hotline & CRM Call Logs
CREATE TABLE IF NOT EXISTS call_logs (
    id VARCHAR(64) PRIMARY KEY,
    caller_name VARCHAR(255),
    caller_phone VARCHAR(64) NOT NULL,
    call_direction VARCHAR(16) NOT NULL DEFAULT 'inbound' CHECK(call_direction IN ('inbound', 'outbound')),
    source VARCHAR(32) NOT NULL DEFAULT 'hotline' CHECK(source IN ('hotline', 'telegram', 'instagram', 'website', 'referral')),
    category VARCHAR(128) DEFAULT 'Konsultatsiya',
    priority VARCHAR(16) NOT NULL DEFAULT 'medium' CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
    status VARCHAR(32) NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'in_progress', 'converted', 'closed')),
    call_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    handled_by_staff_id VARCHAR(64),
    FOREIGN KEY (handled_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- DOMAIN 4: HOSPITALIZATION, ADMISSIONS & BED MANAGEMENT
-- ============================================================================

-- 4.1 Inpatient Admissions (Davolanish & Yotish Dasturlari)
CREATE TABLE IF NOT EXISTS admissions (
    id VARCHAR(64) PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    bed_id VARCHAR(64) NOT NULL,
    attending_doctor_id VARCHAR(64),
    program_type VARCHAR(64) NOT NULL DEFAULT 'detox',
    start_date DATE NOT NULL,
    planned_end_date DATE NOT NULL,
    actual_end_date DATE,
    daily_price DECIMAL(14,2) NOT NULL CHECK(daily_price >= 0),
    total_days INT GENERATED ALWAYS AS (
        GREATEST(1, DATEDIFF(COALESCE(actual_end_date, planned_end_date), start_date))
    ) STORED,
    status VARCHAR(32) NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'discharged', 'transferred', 'cancelled')),
    admission_notes TEXT,
    discharge_summary TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (bed_id) REFERENCES beds(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (attending_doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4.2 Daily Nursing & Vital Signs Tracking
CREATE TABLE IF NOT EXISTS daily_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    admission_id VARCHAR(64) NOT NULL,
    log_date DATE NOT NULL,
    attended TINYINT(1) NOT NULL DEFAULT 1 CHECK(attended IN (0, 1)),
    vital_bp_systolic INT,
    vital_bp_diastolic INT,
    vital_pulse INT,
    vital_temp DECIMAL(4,1),
    vital_spo2 INT,
    nurse_notes TEXT,
    recorded_by_staff_id VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_admission_log_date (admission_id, log_date),
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (recorded_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4.3 Bed Transfer History (O'rin Almashtirish Tarixi)
CREATE TABLE IF NOT EXISTS bed_transfers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    admission_id VARCHAR(64) NOT NULL,
    from_bed_id VARCHAR(64) NOT NULL,
    to_bed_id VARCHAR(64) NOT NULL,
    transfer_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    transfer_reason TEXT,
    performed_by_staff_id VARCHAR(64),
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (from_bed_id) REFERENCES beds(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (to_bed_id) REFERENCES beds(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (performed_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- DOMAIN 5: CLINICAL EMR, PHARMACOTHERAPY & MEDICAL RECORDS
-- ============================================================================

-- 5.1 Comprehensive Medical Histories & Anamnesis (Kasallik Tarixi)
CREATE TABLE IF NOT EXISTS medical_histories (
    id VARCHAR(64) PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    admission_id VARCHAR(64),
    doctor_id VARCHAR(64),
    complaints TEXT,
    anamnesis_morbi TEXT,
    anamnesis_vitae TEXT,
    allergic_status TEXT,
    somatic_status TEXT,
    psychiatric_status TEXT,
    diagnosis_primary TEXT,
    diagnosis_secondary TEXT,
    icd10_code VARCHAR(32),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5.2 Formulary & Medications Inventory Catalog
CREATE TABLE IF NOT EXISTS medications_catalog (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(128) NOT NULL,
    form VARCHAR(64) NOT NULL,
    standard_dosage VARCHAR(128),
    unit_price DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(unit_price >= 0),
    stock_quantity INT NOT NULL DEFAULT 0 CHECK(stock_quantity >= 0),
    min_stock_level INT NOT NULL DEFAULT 10,
    is_active TINYINT(1) NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5.3 Clinical Prescriptions (List Naznacheniy / Dori Tayinlash)
CREATE TABLE IF NOT EXISTS prescriptions (
    id VARCHAR(64) PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    admission_id VARCHAR(64),
    doctor_id VARCHAR(64),
    medication_id VARCHAR(64),
    medication_name VARCHAR(255) NOT NULL,
    form VARCHAR(64),
    dosage VARCHAR(128) NOT NULL,
    route VARCHAR(64) NOT NULL,
    frequency VARCHAR(64) NOT NULL,
    duration_days INT NOT NULL DEFAULT 5 CHECK(duration_days > 0),
    timing VARCHAR(128),
    instructions TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'cancelled', 'held')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (medication_id) REFERENCES medications_catalog(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5.4 Doctor's Daily Progress Notes & Ward Rounds (Dnevnik Obxoda)
CREATE TABLE IF NOT EXISTS doctor_daily_notes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    admission_id VARCHAR(64),
    doctor_id VARCHAR(64),
    note_date DATE NOT NULL,
    patient_condition VARCHAR(32) NOT NULL DEFAULT 'moderate' CHECK(patient_condition IN (
        'satisfactory', 'moderate', 'severe', 'critical'
    )),
    vital_bp VARCHAR(32),
    vital_pulse INT,
    vital_temp DECIMAL(4,1),
    vital_spo2 INT,
    dynamics_notes TEXT NOT NULL,
    treatment_adjustments TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5.5 Discharge Epicrisis & Treatment Summaries (Chiqarish Epikrizi)
CREATE TABLE IF NOT EXISTS discharge_epicrises (
    id VARCHAR(64) PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    admission_id VARCHAR(64),
    doctor_id VARCHAR(64),
    epicrisis_date DATE NOT NULL,
    diagnosis_final TEXT NOT NULL,
    icd10_code VARCHAR(32),
    treatment_summary TEXT,
    home_prescriptions TEXT,
    psycho_recommendations TEXT,
    discharge_status VARCHAR(64) NOT NULL DEFAULT 'recovered' CHECK(discharge_status IN (
        'recovered', 'improved', 'unchanged', 'transferred', 'against_medical_advice'
    )),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- DOMAIN 6: BILLING, REVENUE, ACCOUNTING & AUDIT TRAIL
-- ============================================================================

-- 6.1 Medical Services Catalog (Narxlar Ro'yxati)
CREATE TABLE IF NOT EXISTS services_catalog (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(64) NOT NULL CHECK(category IN ('inpatient', 'consultation', 'diagnostics', 'therapy', 'procedure', 'other')),
    unit_price DECIMAL(14,2) NOT NULL CHECK(unit_price >= 0),
    description TEXT,
    is_active TINYINT(1) NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6.2 Patient Invoices (Hisob-Fakturalar)
CREATE TABLE IF NOT EXISTS invoices (
    id VARCHAR(64) PRIMARY KEY,
    admission_id VARCHAR(64) NOT NULL UNIQUE,
    total_billed DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(total_billed >= 0),
    discount_amount DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(discount_amount >= 0),
    net_amount DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(net_amount >= 0),
    total_paid DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(total_paid >= 0),
    balance_due DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    payment_status VARCHAR(32) NOT NULL DEFAULT 'unpaid' CHECK(payment_status IN (
        'unpaid', 'partial', 'paid', 'refunded'
    )),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6.3 Invoice Line Items (Xizmatlar & Dori-darmon tafsilotlari)
CREATE TABLE IF NOT EXISTS invoice_items (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    invoice_id VARCHAR(64) NOT NULL,
    service_name VARCHAR(255) NOT NULL,
    quantity DECIMAL(10,2) NOT NULL DEFAULT 1.00 CHECK(quantity > 0),
    unit_price DECIMAL(14,2) NOT NULL CHECK(unit_price >= 0),
    total_amount DECIMAL(14,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    item_type VARCHAR(32) DEFAULT 'procedure' CHECK(item_type IN ('bed_stay', 'consultation', 'medication', 'lab_test', 'procedure', 'other')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6.4 Patient Payments (Kassa, Terminal, Karta/Payme/Click)
CREATE TABLE IF NOT EXISTS payments (
    id VARCHAR(64) PRIMARY KEY,
    invoice_id VARCHAR(64) NOT NULL,
    amount DECIMAL(14,2) NOT NULL CHECK(amount > 0),
    payment_method VARCHAR(32) NOT NULL CHECK(payment_method IN (
        'cash', 'cash_register', 'terminal', 'card_transfer', 'payme_click', 'bank_wire'
    )),
    account_destination VARCHAR(64) NOT NULL DEFAULT 'kassa' CHECK(account_destination IN (
        'kassa', 'terminal_bank', 'click_payme_merchant', 'main_bank_account'
    )),
    transaction_ref VARCHAR(128),
    payment_date DATE NOT NULL,
    notes TEXT,
    received_by_staff_id VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (received_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6.5 Clinic Operational Accounting Journal (Xarajatlar, Maoshlar va Kirimlar)
CREATE TABLE IF NOT EXISTS accounting_transactions (
    id VARCHAR(64) PRIMARY KEY,
    transaction_type VARCHAR(16) NOT NULL CHECK(transaction_type IN ('income', 'expense')),
    category VARCHAR(128) NOT NULL,
    amount DECIMAL(14,2) NOT NULL CHECK(amount > 0),
    payment_method VARCHAR(32) NOT NULL DEFAULT 'cash' CHECK(payment_method IN ('cash', 'terminal', 'bank_wire', 'card_transfer')),
    account_source VARCHAR(64) DEFAULT 'kassa',
    related_invoice_id VARCHAR(64),
    related_staff_id VARCHAR(64),
    description TEXT NOT NULL,
    transaction_date DATE NOT NULL,
    recorded_by_staff_id VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (related_invoice_id) REFERENCES invoices(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (related_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (recorded_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6.6 System Audit Logs (Xavfsizlik va Amallar Jurnali)
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    entity_name VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    action_type VARCHAR(32) NOT NULL CHECK(action_type IN (
        'CREATE', 'UPDATE', 'DELETE', 'CHECK_IN', 'CHECK_OUT', 'TRANSFER', 'PAYMENT_RECEIVED'
    )),
    old_data_json JSON,
    new_data_json JSON,
    performed_by_staff_id VARCHAR(64),
    ip_address VARCHAR(64),
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (performed_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- PERFORMANCE & HIGH-SPEED SEARCH INDEXES
-- ============================================================================

CREATE INDEX idx_patients_code ON patients(patient_code);
CREATE INDEX idx_patients_phone ON patients(phone);
CREATE INDEX idx_patients_status ON patients(status);

CREATE INDEX idx_admissions_patient ON admissions(patient_id);
CREATE INDEX idx_admissions_bed ON admissions(bed_id);
CREATE INDEX idx_admissions_status ON admissions(status, start_date, planned_end_date);

CREATE INDEX idx_daily_logs_admission ON daily_logs(admission_id, log_date);
CREATE INDEX idx_invoices_admission ON invoices(admission_id);
CREATE INDEX idx_payments_invoice ON payments(invoice_id, payment_date);

CREATE INDEX idx_prescriptions_patient ON prescriptions(patient_id, status);
CREATE INDEX idx_prescriptions_admission ON prescriptions(admission_id, status);
CREATE INDEX idx_appointments_date ON appointments(appointment_date, status);
CREATE INDEX idx_call_logs_status ON call_logs(status, priority);

-- ============================================================================
-- AUTOMATED FINANCIAL, BED-OCCUPANCY & INTEGRITY TRIGGERS
-- ============================================================================

DELIMITER $$

-- Trigger 1: Auto-occupy bed & auto-generate invoice upon active admission
CREATE TRIGGER trg_admission_occupy_bed
AFTER INSERT ON admissions
FOR EACH ROW
BEGIN
    IF NEW.status = 'active' THEN
        UPDATE beds SET status = 'occupied', updated_at = CURRENT_TIMESTAMP WHERE id = NEW.bed_id;
        UPDATE patients SET status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = NEW.patient_id;
        
        INSERT IGNORE INTO invoices (id, admission_id, total_billed, discount_amount, net_amount, total_paid, balance_due, payment_status)
        VALUES (
            CONCAT('INV-', NEW.id),
            NEW.id,
            NEW.daily_price * GREATEST(1, DATEDIFF(COALESCE(NEW.actual_end_date, NEW.planned_end_date), NEW.start_date)),
            0.00,
            NEW.daily_price * GREATEST(1, DATEDIFF(COALESCE(NEW.actual_end_date, NEW.planned_end_date), NEW.start_date)),
            0.00,
            NEW.daily_price * GREATEST(1, DATEDIFF(COALESCE(NEW.actual_end_date, NEW.planned_end_date), NEW.start_date)),
            'unpaid'
        );
    END IF;
END$$

-- Trigger 2: Auto-release bed when admission is discharged or cancelled
CREATE TRIGGER trg_admission_release_bed
AFTER UPDATE ON admissions
FOR EACH ROW
BEGIN
    IF NEW.status IN ('discharged', 'cancelled') AND OLD.status = 'active' THEN
        UPDATE beds SET status = 'available', updated_at = CURRENT_TIMESTAMP WHERE id = NEW.bed_id;
    END IF;
END$$

-- Trigger 3: Bed Transfer synchronization
CREATE TRIGGER trg_after_bed_transfer
AFTER INSERT ON bed_transfers
FOR EACH ROW
BEGIN
    UPDATE beds SET status = 'available', updated_at = CURRENT_TIMESTAMP WHERE id = NEW.from_bed_id;
    UPDATE beds SET status = 'occupied', updated_at = CURRENT_TIMESTAMP WHERE id = NEW.to_bed_id;
    UPDATE admissions SET bed_id = NEW.to_bed_id, updated_at = CURRENT_TIMESTAMP WHERE id = NEW.admission_id;
END$$

-- Trigger 4: Recalculate invoice after payment insert
CREATE TRIGGER trg_after_payment_insert
AFTER INSERT ON payments
FOR EACH ROW
BEGIN
    DECLARE v_paid DECIMAL(14,2);
    SELECT COALESCE(SUM(amount), 0.00) INTO v_paid FROM payments WHERE invoice_id = NEW.invoice_id;
    
    UPDATE invoices
    SET total_paid = v_paid,
        balance_due = net_amount - v_paid,
        payment_status = CASE
            WHEN (net_amount - v_paid) <= 0.00 THEN 'paid'
            WHEN v_paid > 0.00 THEN 'partial'
            ELSE 'unpaid'
        END,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.invoice_id;
END$$

-- Trigger 5: Recalculate invoice after payment update
CREATE TRIGGER trg_after_payment_update
AFTER UPDATE ON payments
FOR EACH ROW
BEGIN
    DECLARE v_paid DECIMAL(14,2);
    SELECT COALESCE(SUM(amount), 0.00) INTO v_paid FROM payments WHERE invoice_id = NEW.invoice_id;
    
    UPDATE invoices
    SET total_paid = v_paid,
        balance_due = net_amount - v_paid,
        payment_status = CASE
            WHEN (net_amount - v_paid) <= 0.00 THEN 'paid'
            WHEN v_paid > 0.00 THEN 'partial'
            ELSE 'unpaid'
        END,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.invoice_id;
END$$

-- Trigger 6: Recalculate invoice after payment delete
CREATE TRIGGER trg_after_payment_delete
AFTER DELETE ON payments
FOR EACH ROW
BEGIN
    DECLARE v_paid DECIMAL(14,2);
    SELECT COALESCE(SUM(amount), 0.00) INTO v_paid FROM payments WHERE invoice_id = OLD.invoice_id;
    
    UPDATE invoices
    SET total_paid = v_paid,
        balance_due = net_amount - v_paid,
        payment_status = CASE
            WHEN (net_amount - v_paid) <= 0.00 THEN 'paid'
            WHEN v_paid > 0.00 THEN 'partial'
            ELSE 'unpaid'
        END,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = OLD.invoice_id;
END$$

DELIMITER ;

-- ============================================================================
-- ANALYTICAL & REPORTING VIEWS
-- ============================================================================

-- View 1: Real-time Facility & Bed Occupancy
CREATE OR REPLACE VIEW v_bed_live_status AS
SELECT 
    b.id AS bed_id,
    b.bed_code,
    b.bed_type,
    b.default_daily_rate,
    r.floor_number,
    r.room_number,
    r.room_name_uz,
    b.status AS system_bed_status,
    CASE 
        WHEN a.id IS NOT NULL THEN 'occupied' 
        ELSE 'available' 
    END AS status,
    a.id AS current_admission_id,
    p.patient_code,
    p.full_name AS patient_name,
    p.phone AS patient_phone,
    a.program_type,
    a.start_date AS check_in_date,
    COALESCE(a.actual_end_date, a.planned_end_date) AS check_out_date,
    s.full_name AS doctor_name
FROM beds b
JOIN rooms r ON b.room_id = r.id
LEFT JOIN admissions a ON b.id = a.bed_id 
    AND a.status = 'active' 
    AND CURDATE() >= a.start_date 
    AND CURDATE() <= COALESCE(a.actual_end_date, a.planned_end_date)
LEFT JOIN patients p ON a.patient_id = p.id
LEFT JOIN staff s ON a.attending_doctor_id = s.id
ORDER BY r.floor_number, r.room_number, b.bed_code;

-- View 2: Complete Patient Financial Balance Sheet & Payment Split
CREATE OR REPLACE VIEW v_financial_ledger AS
SELECT 
    inv.id AS invoice_id,
    a.id AS admission_id,
    p.id AS patient_id,
    p.patient_code,
    p.full_name AS patient_name,
    p.phone AS patient_phone,
    p.referral_source,
    b.id AS bed_id,
    b.bed_code,
    r.room_number,
    r.floor_number,
    s.full_name AS doctor_name,
    a.program_type,
    a.daily_price,
    a.start_date,
    COALESCE(a.actual_end_date, a.planned_end_date) AS end_date,
    a.total_days,
    inv.total_billed,
    inv.discount_amount,
    inv.net_amount,
    inv.total_paid,
    inv.balance_due,
    inv.payment_status,
    COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id = inv.id AND payment_method IN ('cash', 'cash_register')), 0.00) AS paid_cash,
    COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id = inv.id AND payment_method = 'terminal'), 0.00) AS paid_terminal,
    COALESCE((SELECT SUM(amount) FROM payments WHERE invoice_id = inv.id AND payment_method IN ('card_transfer', 'payme_click')), 0.00) AS paid_card_online,
    inv.created_at
FROM invoices inv
JOIN admissions a ON inv.admission_id = a.id
JOIN patients p ON a.patient_id = p.id
JOIN beds b ON a.bed_id = b.id
JOIN rooms r ON b.room_id = r.id
LEFT JOIN staff s ON a.attending_doctor_id = s.id
ORDER BY inv.created_at DESC;

-- View 3: 360° Comprehensive Patient Active Profile
CREATE OR REPLACE VIEW v_patient_full_profile AS
SELECT 
    p.id AS patient_id,
    p.patient_code,
    p.full_name,
    p.phone,
    p.emergency_contact,
    p.gender,
    p.birth_year,
    p.referral_source,
    p.is_anonymous,
    p.medical_allergies,
    p.chronic_conditions,
    p.status AS patient_status,
    a.id AS active_admission_id,
    a.program_type,
    a.start_date AS admission_date,
    a.planned_end_date,
    b.bed_code,
    r.room_number,
    s.full_name AS attending_doctor,
    COALESCE(inv.net_amount, 0.00) AS current_net_billed,
    COALESCE(inv.total_paid, 0.00) AS current_paid,
    COALESCE(inv.balance_due, 0.00) AS current_balance_due,
    (SELECT COUNT(*) FROM prescriptions rx WHERE rx.patient_id = p.id AND rx.status = 'active') AS active_prescriptions_count,
    (SELECT COUNT(*) FROM daily_logs dl WHERE dl.admission_id = a.id) AS days_logged_count
FROM patients p
LEFT JOIN admissions a ON p.id = a.patient_id AND a.status = 'active'
LEFT JOIN beds b ON a.bed_id = b.id
LEFT JOIN rooms r ON b.room_id = r.id
LEFT JOIN staff s ON a.attending_doctor_id = s.id
LEFT JOIN invoices inv ON a.id = inv.admission_id;

-- View 4: Live Executive Clinic KPIs & Census
CREATE OR REPLACE VIEW v_daily_hospital_kpi AS
SELECT
    (SELECT COUNT(*) FROM beds) AS total_beds,
    (SELECT COUNT(DISTINCT bed_id) FROM admissions WHERE status = 'active' AND CURDATE() >= start_date AND CURDATE() <= COALESCE(actual_end_date, planned_end_date)) AS occupied_beds,
    (SELECT COUNT(*) FROM beds) - (SELECT COUNT(DISTINCT bed_id) FROM admissions WHERE status = 'active' AND CURDATE() >= start_date AND CURDATE() <= COALESCE(actual_end_date, planned_end_date)) AS available_beds,
    ROUND((SELECT COUNT(DISTINCT bed_id) FROM admissions WHERE status = 'active' AND CURDATE() >= start_date AND CURDATE() <= COALESCE(actual_end_date, planned_end_date)) / GREATEST(1, (SELECT COUNT(*) FROM beds)) * 100, 1) AS occupancy_rate_percent,
    (SELECT COUNT(*) FROM admissions WHERE status = 'active' AND CURDATE() >= start_date AND CURDATE() <= COALESCE(actual_end_date, planned_end_date)) AS active_inpatient_count,
    (SELECT COUNT(*) FROM patients WHERE status = 'active') AS active_patient_count,
    (SELECT COALESCE(SUM(total_billed), 0.00) FROM invoices) AS total_revenue_billed,
    (SELECT COALESCE(SUM(total_paid), 0.00) FROM invoices) AS total_revenue_collected,
    (SELECT COALESCE(SUM(balance_due), 0.00) FROM invoices) AS total_outstanding_debt,
    (SELECT COUNT(*) FROM appointments WHERE appointment_date = CURDATE() AND status != 'cancelled') AS today_appointments_count,
    (SELECT COUNT(*) FROM prescriptions WHERE status = 'active') AS active_prescriptions_count;

-- View 5: Pharmacy Low Stock Alerts
CREATE OR REPLACE VIEW v_pharmacy_low_stock AS
SELECT
    id AS medication_id,
    name AS medication_name,
    category,
    form,
    stock_quantity,
    min_stock_level,
    (min_stock_level - stock_quantity) AS deficit_quantity,
    unit_price
FROM medications_catalog
WHERE stock_quantity <= min_stock_level AND is_active = 1
ORDER BY (stock_quantity - min_stock_level) ASC;

SET FOREIGN_KEY_CHECKS = 1;
