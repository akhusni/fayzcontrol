-- ============================================================================
-- FAYZ MEDICAL HOUSE — CLEAN TEST PATIENT DATA FOR PRODUCTION LAUNCH
--
-- This script removes all test patient records, admissions, prescriptions,
-- medical histories, dossiers, appointments, invoices, and payments,
-- while 100% PRESERVING clinics, rooms, beds, staff, services catalog,
-- medications catalog, suppliers, and system configuration.
-- ============================================================================

SET FOREIGN_KEY_CHECKS = 0;

-- 1. Restore inventory batch quantities for dispensed items
UPDATE inventory_batches ib
JOIN (
    SELECT batch_id, SUM(ABS(qty_delta)) AS total_dispensed
    FROM inventory_transactions
    WHERE txn_type = 'dispense' AND batch_id IS NOT NULL
    GROUP BY batch_id
) d ON ib.id = d.batch_id
SET ib.remaining_qty = ib.remaining_qty + d.total_dispensed;

-- Delete inventory dispensings & dispense transactions
DELETE FROM inventory_dispensing_batches;
DELETE FROM inventory_dispensings;
DELETE FROM inventory_transactions WHERE txn_type = 'dispense' OR patient_id IS NOT NULL;

-- 2. Patient dossiers and referrals
DELETE FROM patient_dossiers;
DELETE FROM patient_referrals;

-- 3. Medical records: prescriptions, notes, epicrises, daily logs, histories
DELETE FROM medication_administrations;
DELETE FROM prescriptions;
DELETE FROM doctor_daily_notes;
DELETE FROM discharge_epicrises;
DELETE FROM daily_logs;
DELETE FROM bed_transfers;
DELETE FROM medical_histories;
DELETE FROM treatment_plans;
DELETE FROM consultations;

-- 4. Billing: payments, invoices, items, and patient transactions
DELETE FROM payments;
DELETE FROM invoice_items;
DELETE FROM invoices;
DELETE FROM accounting_transactions 
WHERE payment_id IS NOT NULL 
   OR related_invoice_id IS NOT NULL 
   OR category LIKE '%Bemor%'
   OR category = 'patient_payment';

-- 5. Appointments, requests, and admissions
DELETE FROM appointments;
DELETE FROM appointment_requests;
DELETE FROM call_logs;
DELETE FROM admissions;

-- 6. Master patients table
DELETE FROM patients;

-- 7. Reset all beds to operational status (all beds empty and ready)
UPDATE beds SET status = 'operational';

-- 8. Reset audit logs and sessions
TRUNCATE TABLE audit_logs;
TRUNCATE TABLE user_sessions;

SET FOREIGN_KEY_CHECKS = 1;

-- Verification queries
SELECT 'Patients remaining' AS metric, COUNT(*) AS count FROM patients
UNION ALL
SELECT 'Active admissions', COUNT(*) FROM admissions
UNION ALL
SELECT 'Staff preserved', COUNT(*) FROM staff
UNION ALL
SELECT 'Rooms preserved', COUNT(*) FROM rooms
UNION ALL
SELECT 'Beds ready', COUNT(*) FROM beds WHERE status = 'operational'
UNION ALL
SELECT 'Medications catalog', COUNT(*) FROM medications_catalog
UNION ALL
SELECT 'Services catalog', COUNT(*) FROM services_catalog
UNION ALL
SELECT 'Referral doctors', COUNT(*) FROM referral_doctors;
