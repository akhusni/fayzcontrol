-- ============================================================================
-- FAYZ MEDICAL HOUSE / FAYZ CONTROL — ENTERPRISE REFACTORED SCHEMA v6
-- Target Engine: MySQL 8.0.45 Enterprise (InnoDB / UTF8MB4)
-- Architecture: Single-Responsibility Invariant Triggers, Signed Refund Payments,
--               Expanded Accounting PK (VARCHAR(128)), 100% Discount/Charity Guard,
--               BEFORE INSERT Invoice Balancing, Operational CAD Map (next_reserved_date),
--               Weighted Priority Window Ranking (Active Occupant > Chronological Reservation).
-- ============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- -----------------------------------------------------------------------------
-- 1. Facility & Bed Infrastructure (Physical Hardware States)
-- -----------------------------------------------------------------------------

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

CREATE TABLE IF NOT EXISTS beds (
    id VARCHAR(64) PRIMARY KEY,
    room_id VARCHAR(64) NOT NULL,
    bed_code VARCHAR(32) NOT NULL UNIQUE,
    bed_type VARCHAR(32) NOT NULL DEFAULT 'standard' CHECK(bed_type IN ('standard', 'vip')),
    default_daily_rate DECIMAL(14,2) NOT NULL DEFAULT 720000.00 CHECK(default_daily_rate >= 0),
    status VARCHAR(32) NOT NULL DEFAULT 'operational' CHECK(status IN (
        'operational', 'cleaning', 'maintenance', 'out_of_service'
    )),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms(id) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 2. Human Resources & Shift Rosters
-- -----------------------------------------------------------------------------

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

-- -----------------------------------------------------------------------------
-- 3. CRM, Patients & Hotline Queue
-- -----------------------------------------------------------------------------

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
    appointment_time TIME NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'confirmed' CHECK(status IN (
        'pending', 'confirmed', 'completed', 'cancelled', 'no_show'
    )),
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

-- -----------------------------------------------------------------------------
-- 4. Hospitalization & Vitals Tracking
-- -----------------------------------------------------------------------------

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
    CONSTRAINT chk_admissions_planned_dates CHECK(planned_end_date >= start_date),
    CONSTRAINT chk_admissions_actual_dates CHECK(actual_end_date IS NULL OR actual_end_date >= start_date),
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (bed_id) REFERENCES beds(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (attending_doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS daily_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    admission_id VARCHAR(64) NOT NULL,
    log_date DATE NOT NULL,
    attended TINYINT(1) NOT NULL DEFAULT 1 CHECK(attended IN (0, 1)),
    vital_bp_systolic INT CHECK(vital_bp_systolic IS NULL OR (vital_bp_systolic BETWEEN 50 AND 300)),
    vital_bp_diastolic INT CHECK(vital_bp_diastolic IS NULL OR (vital_bp_diastolic BETWEEN 30 AND 200)),
    vital_pulse INT CHECK(vital_pulse IS NULL OR (vital_pulse BETWEEN 30 AND 250)),
    vital_temp DECIMAL(4,1) CHECK(vital_temp IS NULL OR (vital_temp BETWEEN 30.0 AND 45.0)),
    vital_spo2 INT CHECK(vital_spo2 IS NULL OR (vital_spo2 BETWEEN 50 AND 100)),
    nurse_notes TEXT,
    recorded_by_staff_id VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_admission_log_date (admission_id, log_date),
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (recorded_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

-- -----------------------------------------------------------------------------
-- 5. Clinical EMR, Pharmacology & Progress Notes
-- -----------------------------------------------------------------------------

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

CREATE TABLE IF NOT EXISTS doctor_daily_notes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    admission_id VARCHAR(64),
    doctor_id VARCHAR(64),
    note_date DATE NOT NULL,
    patient_condition VARCHAR(32) NOT NULL DEFAULT 'moderate' CHECK(patient_condition IN (
        'satisfactory', 'moderate', 'severe', 'critical'
    )),
    vital_bp_systolic INT CHECK(vital_bp_systolic IS NULL OR (vital_bp_systolic BETWEEN 50 AND 300)),
    vital_bp_diastolic INT CHECK(vital_bp_diastolic IS NULL OR (vital_bp_diastolic BETWEEN 30 AND 200)),
    vital_pulse INT CHECK(vital_pulse IS NULL OR (vital_pulse BETWEEN 30 AND 250)),
    vital_temp DECIMAL(4,1) CHECK(vital_temp IS NULL OR (vital_temp BETWEEN 30.0 AND 45.0)),
    vital_spo2 INT CHECK(vital_spo2 IS NULL OR (vital_spo2 BETWEEN 50 AND 100)),
    dynamics_notes TEXT NOT NULL,
    treatment_adjustments TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (doctor_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

-- -----------------------------------------------------------------------------
-- 6. Billing, Invoicing & Double-Entry Accounting
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS services_catalog (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(64) NOT NULL CHECK(category IN ('inpatient', 'consultation', 'diagnostics', 'therapy', 'procedure', 'other')),
    unit_price DECIMAL(14,2) NOT NULL CHECK(unit_price >= 0),
    description TEXT,
    is_active TINYINT(1) NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS invoices (
    id VARCHAR(64) PRIMARY KEY,
    admission_id VARCHAR(64) NOT NULL UNIQUE,
    total_billed DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(total_billed >= 0),
    discount_amount DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(discount_amount >= 0),
    net_amount DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(net_amount >= 0),
    total_paid DECIMAL(14,2) NOT NULL DEFAULT 0.00 CHECK(total_paid >= 0),
    balance_due DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    payment_status VARCHAR(32) NOT NULL DEFAULT 'unpaid' CHECK(payment_status IN (
        'unpaid', 'partial', 'paid', 'refund_due', 'refunded'
    )),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (admission_id) REFERENCES admissions(id) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS invoice_items (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    invoice_id VARCHAR(64) NOT NULL,
    service_name VARCHAR(255) NOT NULL,
    quantity DECIMAL(10,2) NOT NULL DEFAULT 1.00 CHECK(quantity > 0),
    unit_price DECIMAL(14,2) NOT NULL CHECK(unit_price >= 0),
    total_amount DECIMAL(14,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    item_type VARCHAR(32) DEFAULT 'procedure' CHECK(item_type IN ('bed_stay', 'consultation', 'medication', 'lab_test', 'procedure', 'other')),
    service_start_date DATE,
    service_end_date DATE,
    bed_id VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_invoice_items_dates CHECK (
        service_end_date IS NULL 
        OR service_start_date IS NULL 
        OR service_end_date >= service_start_date
    ),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (bed_id) REFERENCES beds(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS payments (
    id VARCHAR(64) PRIMARY KEY,
    invoice_id VARCHAR(64) NOT NULL,
    amount DECIMAL(14,2) NOT NULL CHECK(amount <> 0), -- Signed: positive for payments, negative for refunds
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

CREATE TABLE IF NOT EXISTS accounting_transactions (
    id VARCHAR(128) PRIMARY KEY, -- Expanded to 128 to prevent prefix buffer overflow
    payment_id VARCHAR(64) UNIQUE,
    transaction_type VARCHAR(16) NOT NULL CHECK(transaction_type IN ('income', 'expense')),
    category VARCHAR(128) NOT NULL,
    amount DECIMAL(14,2) NOT NULL CHECK(amount > 0), -- Magnitude is always positive
    payment_method VARCHAR(32) NOT NULL DEFAULT 'cash' CHECK(payment_method IN (
        'cash', 'cash_register', 'terminal', 'card_transfer', 'payme_click', 'bank_wire'
    )),
    account_source VARCHAR(64) DEFAULT 'kassa',
    related_invoice_id VARCHAR(64),
    related_staff_id VARCHAR(64),
    description TEXT NOT NULL,
    transaction_date DATE NOT NULL,
    recorded_by_staff_id VARCHAR(64),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (payment_id) REFERENCES payments(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (related_invoice_id) REFERENCES invoices(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (related_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (recorded_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

-- -----------------------------------------------------------------------------
-- 7. High-Performance Indexing
-- -----------------------------------------------------------------------------

CREATE INDEX idx_patients_code ON patients(patient_code);
CREATE INDEX idx_patients_phone ON patients(phone);
CREATE INDEX idx_patients_status ON patients(status);

CREATE INDEX idx_admissions_patient ON admissions(patient_id);
CREATE INDEX idx_admissions_bed ON admissions(bed_id);
CREATE INDEX idx_admissions_status ON admissions(status, start_date, planned_end_date);

CREATE INDEX idx_daily_logs_admission ON daily_logs(admission_id, log_date);
CREATE INDEX idx_invoices_admission ON invoices(admission_id);
CREATE INDEX idx_invoice_items_segment ON invoice_items(invoice_id, bed_id, item_type);
CREATE INDEX idx_payments_invoice ON payments(invoice_id, payment_date);

CREATE INDEX idx_prescriptions_patient ON prescriptions(patient_id, status);
CREATE INDEX idx_prescriptions_admission ON prescriptions(admission_id, status);
CREATE INDEX idx_appointments_datetime ON appointments(appointment_date, appointment_time, status);
CREATE INDEX idx_call_logs_status ON call_logs(status, priority);
CREATE INDEX idx_accounting_txn_date ON accounting_transactions(transaction_date, transaction_type);

-- -----------------------------------------------------------------------------
-- 8. Single Responsibility Principle (SRP) Invariant Triggers
-- -----------------------------------------------------------------------------

DELIMITER $$

-- 8.1 Single Mathematical Authority on Invoices: Cascades Net Amount, Balance & Status (INSERT & UPDATE)
CREATE TRIGGER trg_invoices_before_insert
BEFORE INSERT ON invoices
FOR EACH ROW
BEGIN
    SET NEW.net_amount = GREATEST(0.00, NEW.total_billed - NEW.discount_amount);
    SET NEW.balance_due = NEW.net_amount - NEW.total_paid;

    -- Guard on total_billed > 0.00: allows 100% discount / VIP charity waivers to resolve to 'paid'
    -- Guard on total_billed = 0.00 with payment history resolves cancelled/fully refunded invoices to 'refunded'
    SET NEW.payment_status = CASE 
        WHEN NEW.total_paid > NEW.net_amount THEN 'refund_due'
        WHEN NEW.total_billed > 0.00 AND NEW.balance_due <= 0.00 THEN 'paid'
        WHEN NEW.total_billed = 0.00 AND (SELECT COUNT(*) FROM payments WHERE invoice_id = NEW.id) > 0 THEN 'refunded'
        WHEN NEW.total_paid > 0.00 THEN 'partial'
        ELSE 'unpaid'
    END;
END$$

CREATE TRIGGER trg_invoices_before_update
BEFORE UPDATE ON invoices
FOR EACH ROW
BEGIN
    SET NEW.net_amount = GREATEST(0.00, NEW.total_billed - NEW.discount_amount);
    SET NEW.balance_due = NEW.net_amount - NEW.total_paid;

    -- Guard on total_billed > 0.00: allows 100% discount / VIP charity waivers to resolve to 'paid'
    -- Guard on total_billed = 0.00 with payment history resolves cancelled/fully refunded invoices to 'refunded'
    SET NEW.payment_status = CASE 
        WHEN NEW.total_paid > NEW.net_amount THEN 'refund_due'
        WHEN NEW.total_billed > 0.00 AND NEW.balance_due <= 0.00 THEN 'paid'
        WHEN NEW.total_billed = 0.00 AND (SELECT COUNT(*) FROM payments WHERE invoice_id = NEW.id) > 0 THEN 'refunded'
        WHEN NEW.total_paid > 0.00 THEN 'partial'
        ELSE 'unpaid'
    END;
END$$

-- 8.2 Invoice Items: Sole Responsibility is Summing total_billed
CREATE TRIGGER trg_invoice_items_after_insert
AFTER INSERT ON invoice_items
FOR EACH ROW
BEGIN
    UPDATE invoices
    SET total_billed = (SELECT COALESCE(SUM(total_amount), 0.00) FROM invoice_items WHERE invoice_id = NEW.invoice_id),
        updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.invoice_id;
END$$

CREATE TRIGGER trg_invoice_items_after_update
AFTER UPDATE ON invoice_items
FOR EACH ROW
BEGIN
    UPDATE invoices
    SET total_billed = (SELECT COALESCE(SUM(total_amount), 0.00) FROM invoice_items WHERE invoice_id = NEW.invoice_id),
        updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.invoice_id;
END$$

CREATE TRIGGER trg_invoice_items_after_delete
AFTER DELETE ON invoice_items
FOR EACH ROW
BEGIN
    UPDATE invoices
    SET total_billed = (SELECT COALESCE(SUM(total_amount), 0.00) FROM invoice_items WHERE invoice_id = OLD.invoice_id),
        updated_at = CURRENT_TIMESTAMP
    WHERE id = OLD.invoice_id;
END$$

-- 8.3 Payments: Sole Responsibility is Summing total_paid & Routing Income/Expense Ledger
CREATE TRIGGER trg_after_payment_insert
AFTER INSERT ON payments
FOR EACH ROW
BEGIN
    DECLARE v_paid DECIMAL(14,2);
    SELECT COALESCE(SUM(amount), 0.00) INTO v_paid FROM payments WHERE invoice_id = NEW.invoice_id;

    UPDATE invoices SET total_paid = v_paid, updated_at = CURRENT_TIMESTAMP WHERE id = NEW.invoice_id;

    IF NEW.amount > 0 THEN
        INSERT INTO accounting_transactions (
            id, payment_id, transaction_type, category, amount, payment_method,
            account_source, related_invoice_id, related_staff_id,
            description, transaction_date, recorded_by_staff_id
        ) VALUES (
            CONCAT('TXN-', NEW.id), NEW.id, 'income', 'Bemor to\'lovi',
            NEW.amount, NEW.payment_method, NEW.account_destination,
            NEW.invoice_id, NEW.received_by_staff_id,
            CONCAT('Kassa kirim: To\'lov ', NEW.id, ' (Hisob: ', NEW.invoice_id, ')'),
            NEW.payment_date, NEW.received_by_staff_id
        );
    ELSE
        INSERT INTO accounting_transactions (
            id, payment_id, transaction_type, category, amount, payment_method,
            account_source, related_invoice_id, related_staff_id,
            description, transaction_date, recorded_by_staff_id
        ) VALUES (
            CONCAT('TXN-', NEW.id), NEW.id, 'expense', 'Bemorga qaytarish (Refund)',
            ABS(NEW.amount), NEW.payment_method, NEW.account_destination,
            NEW.invoice_id, NEW.received_by_staff_id,
            CONCAT('Kassa chiqim (Qaytarildi): To\'lov ', NEW.id, ' (Hisob: ', NEW.invoice_id, ')'),
            NEW.payment_date, NEW.received_by_staff_id
        );
    END IF;
END$$

CREATE TRIGGER trg_after_payment_update
AFTER UPDATE ON payments
FOR EACH ROW
BEGIN
    DECLARE v_paid DECIMAL(14,2);
    SELECT COALESCE(SUM(amount), 0.00) INTO v_paid FROM payments WHERE invoice_id = NEW.invoice_id;

    UPDATE invoices SET total_paid = v_paid, updated_at = CURRENT_TIMESTAMP WHERE id = NEW.invoice_id;

    IF NEW.amount > 0 THEN
        UPDATE accounting_transactions
        SET transaction_type = 'income',
            category = 'Bemor to\'lovi',
            amount = NEW.amount,
            payment_method = NEW.payment_method,
            account_source = NEW.account_destination,
            transaction_date = NEW.payment_date,
            recorded_by_staff_id = NEW.received_by_staff_id,
            description = CONCAT('Tahrirlangan to\'lov: ', NEW.id, ' (Hisob: ', NEW.invoice_id, ')')
        WHERE payment_id = NEW.id;
    ELSE
        UPDATE accounting_transactions
        SET transaction_type = 'expense',
            category = 'Bemorga qaytarish (Refund)',
            amount = ABS(NEW.amount),
            payment_method = NEW.payment_method,
            account_source = NEW.account_destination,
            transaction_date = NEW.payment_date,
            recorded_by_staff_id = NEW.received_by_staff_id,
            description = CONCAT('Tahrirlangan qaytarish (Refund): ', NEW.id, ' (Hisob: ', NEW.invoice_id, ')')
        WHERE payment_id = NEW.id;
    END IF;
END$$

CREATE TRIGGER trg_after_payment_delete
AFTER DELETE ON payments
FOR EACH ROW
BEGIN
    DECLARE v_paid DECIMAL(14,2);
    SELECT COALESCE(SUM(amount), 0.00) INTO v_paid FROM payments WHERE invoice_id = OLD.invoice_id;

    UPDATE invoices SET total_paid = v_paid, updated_at = CURRENT_TIMESTAMP WHERE id = OLD.invoice_id;
    DELETE FROM accounting_transactions WHERE payment_id = OLD.id;
END$$

DELIMITER ;

-- -----------------------------------------------------------------------------
-- 9. Analytical Views (Weighted Priority Window Ranking & CAD Projection)
-- -----------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_bed_live_status AS
WITH ranked_active_admissions AS (
    SELECT 
        a.id,
        a.bed_id,
        a.patient_id,
        a.program_type,
        a.start_date,
        a.planned_end_date,
        a.actual_end_date,
        p.patient_code,
        p.full_name AS patient_name,
        p.phone AS patient_phone,
        s.full_name AS doctor_name,
        ROW_NUMBER() OVER (
            PARTITION BY a.bed_id 
            ORDER BY 
                CASE 
                    WHEN CURDATE() BETWEEN a.start_date AND COALESCE(a.actual_end_date, a.planned_end_date) THEN 1
                    WHEN a.start_date > CURDATE() THEN 2
                    ELSE 3
                END ASC,
                a.start_date ASC,
                a.created_at DESC
        ) AS rn
    FROM admissions a
    JOIN patients p ON a.patient_id = p.id
    LEFT JOIN staff s ON a.attending_doctor_id = s.id
    WHERE a.status = 'active'
      AND (
          CURDATE() BETWEEN a.start_date AND COALESCE(a.actual_end_date, a.planned_end_date)
          OR a.start_date > CURDATE()
      )
)
SELECT 
    b.id AS bed_id,
    b.bed_code,
    b.bed_type,
    b.default_daily_rate,
    r.floor_number,
    r.room_number,
    r.room_name_uz,
    b.status AS physical_bed_status,
    CASE 
        WHEN b.status IN ('cleaning', 'maintenance', 'out_of_service') THEN b.status
        WHEN a.id IS NOT NULL AND CURDATE() BETWEEN a.start_date AND COALESCE(a.actual_end_date, a.planned_end_date) THEN 'occupied'
        WHEN a.id IS NOT NULL AND a.start_date > CURDATE() THEN 'reserved'
        ELSE 'available'
    END AS status,
    CASE 
        WHEN a.id IS NOT NULL AND b.status NOT IN ('cleaning', 'maintenance', 'out_of_service') 
        THEN a.id 
        ELSE NULL 
    END AS current_admission_id,
    CASE 
        WHEN a.id IS NOT NULL AND b.status NOT IN ('cleaning', 'maintenance', 'out_of_service') 
        THEN a.patient_code 
        ELSE NULL 
    END AS patient_code,
    CASE 
        WHEN a.id IS NOT NULL AND b.status NOT IN ('cleaning', 'maintenance', 'out_of_service') 
        THEN a.patient_name 
        ELSE NULL 
    END AS patient_name,
    CASE 
        WHEN a.id IS NOT NULL AND b.status NOT IN ('cleaning', 'maintenance', 'out_of_service') 
        THEN a.patient_phone 
        ELSE NULL 
    END AS patient_phone,
    CASE 
        WHEN a.id IS NOT NULL AND b.status NOT IN ('cleaning', 'maintenance', 'out_of_service') 
        THEN a.program_type 
        ELSE NULL 
    END AS program_type,
    CASE 
        WHEN a.id IS NOT NULL AND b.status NOT IN ('cleaning', 'maintenance', 'out_of_service') 
        THEN a.start_date 
        ELSE NULL 
    END AS check_in_date,
    CASE 
        WHEN a.id IS NOT NULL AND b.status NOT IN ('cleaning', 'maintenance', 'out_of_service') 
        THEN COALESCE(a.actual_end_date, a.planned_end_date) 
        ELSE NULL 
    END AS check_out_date,
    CASE 
        WHEN a.id IS NOT NULL AND b.status NOT IN ('cleaning', 'maintenance', 'out_of_service') 
        THEN a.doctor_name 
        ELSE NULL 
    END AS doctor_name,
    -- Operational Projection: Informs reception of upcoming reservation arrival
    (
        SELECT MIN(start_date) 
        FROM admissions 
        WHERE bed_id = b.id 
          AND status = 'active' 
          AND start_date > CURDATE()
    ) AS next_reserved_date
FROM beds b
JOIN rooms r ON b.room_id = r.id
LEFT JOIN ranked_active_admissions a ON b.id = a.bed_id AND a.rn = 1
ORDER BY r.floor_number, r.room_number, b.bed_code;

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
