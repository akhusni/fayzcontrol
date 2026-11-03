#!/usr/bin/env python3
"""
Fayz Medical House — Database & System Reset for Production Launch
Cleans all test patient records, admissions, medical histories, prescriptions,
billing, and dossiers while preserving clinics, rooms, beds, staff, catalog,
inventory stock, and system configurations.
"""

import os
import sys
import glob
import json
import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db import get_db


def create_backup(conn):
    """Creates a safety backup of all patient-related tables before deletion."""
    backup_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"patient_data_backup_{ts}.json")

    tables_to_dump = [
        "patients", "admissions", "appointments", "appointment_requests",
        "call_logs", "daily_logs", "bed_transfers", "medical_histories",
        "prescriptions", "doctor_daily_notes", "discharge_epicrises",
        "invoices", "invoice_items", "payments", "patient_referrals",
        "patient_dossiers", "inventory_dispensings", "inventory_dispensing_batches",
        "accounting_transactions"
    ]

    cur = conn.cursor()
    dump = {"created_at": datetime.datetime.now().isoformat(), "tables": {}}
    for t in tables_to_dump:
        try:
            cur.execute(f"SELECT * FROM {t}")
            rows = cur.fetchall()
            dump["tables"][t] = rows
        except Exception as e:
            dump["tables"][t] = f"Error: {e}"

    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2, default=str)

    print(f"[OK] Xavfsizlik zaxira nusxasi yaratildi: {backup_file}")
    return backup_file


def clean_patient_database(dry_run=False):
    conn = get_db()
    if not conn:
        print("[!] Ma'lumotlar bazasiga ulanib bo'lmadi!")
        return False

    print("\n" + "=" * 60)
    print("FAYZ CONTROL — ISHLATISHGA TAYYORLASH (TOZALASH AMALIYOTI)")
    print("=" * 60)

    try:
        if not dry_run:
            create_backup(conn)

        cur = conn.cursor()

        # Check existing row counts before deletion
        cur.execute("SELECT COUNT(*) FROM patients")
        p_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM admissions")
        adm_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM invoices")
        inv_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM payments")
        pay_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM staff")
        st_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM rooms")
        rm_cnt = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM beds")
        bd_cnt = cur.fetchone()[0]

        print(f"\nHozirgi holat:")
        print(f"  - Bemorlar soni: {p_cnt}")
        print(f"  - Statsionar yotqizishlar: {adm_cnt}")
        print(f"  - Hisob-fakturalar (invoices): {inv_cnt}")
        print(f"  - To'lovlar: {pay_cnt}")
        print(f"  - Xodimlar (saqlanadi): {st_cnt}")
        print(f"  - Xonalar/Palatalar (saqlanadi): {rm_cnt}")
        print(f"  - Koykalar (saqlanadi): {bd_cnt}")

        if dry_run:
            print("\n[DRY RUN] Hech qanday ma'lumot o'chirilmadi.")
            return True

        # Disable foreign key checks for atomic wipe
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")

        # 1. Restore dispensed inventory items back to inventory_batches
        try:
            cur.execute("""
                SELECT item_id, batch_id, ABS(qty_delta) as dispensed_qty 
                FROM inventory_transactions 
                WHERE txn_type = 'dispense'
            """)
            dispenses = cur.fetchall()
            for d in dispenses:
                b_id = d.get('batch_id') if isinstance(d, dict) else d[1]
                qty = d.get('dispensed_qty') if isinstance(d, dict) else d[2]
                if b_id and qty:
                    cur.execute("""
                        UPDATE inventory_batches 
                        SET remaining_qty = remaining_qty + ? 
                        WHERE id = ?
                    """, (qty, b_id))
            print(f"[OK] {len(dispenses)} ta ombor tarqatmasi qaytarildi (qoldiq tiklandi).")
        except Exception as e:
            print(f"[!] Ombor tarqatmasini tiklashda ogohlantirish: {e}")

        # Delete patient inventory dispensing & transactions
        cur.execute("DELETE FROM inventory_dispensing_batches")
        cur.execute("DELETE FROM inventory_dispensings")
        cur.execute("DELETE FROM inventory_transactions WHERE txn_type = 'dispense' OR patient_id IS NOT NULL")
        print("[OK] Ombor tarqatmalar tarixi tozalandi.")

        # 2. Patient dossiers and referrals
        cur.execute("DELETE FROM patient_dossiers")
        cur.execute("DELETE FROM patient_referrals")
        print("[OK] Bemor hujjatlari va yo'llanmalar tozalandi.")

        # 3. Medical records: prescriptions, notes, epicrises, daily logs, histories
        cur.execute("DELETE FROM medication_administrations")
        cur.execute("DELETE FROM prescriptions")
        cur.execute("DELETE FROM doctor_daily_notes")
        cur.execute("DELETE FROM discharge_epicrises")
        cur.execute("DELETE FROM daily_logs")
        cur.execute("DELETE FROM bed_transfers")
        cur.execute("DELETE FROM medical_histories")
        try: cur.execute("DELETE FROM treatment_plans")
        except Exception: pass
        try: cur.execute("DELETE FROM consultations")
        except Exception: pass
        print("[OK] Barcha tibbiy yozuvlar, retseptlar va epikrizlar tozalandi.")

        # 4. Invoices, items, payments, and patient accounting transactions
        cur.execute("DELETE FROM payments")
        cur.execute("DELETE FROM invoice_items")
        cur.execute("DELETE FROM invoices")
        cur.execute("""
            DELETE FROM accounting_transactions 
            WHERE payment_id IS NOT NULL 
               OR related_invoice_id IS NOT NULL 
               OR category LIKE '%Bemor%' 
               OR category = 'patient_payment'
        """)
        print("[OK] Bemorlarga oid barcha hisoblar, to'lovlar va kassa tushumlari tozalandi.")

        # 5. Appointments, requests, call logs, and admissions
        cur.execute("DELETE FROM appointments")
        cur.execute("DELETE FROM appointment_requests")
        cur.execute("DELETE FROM call_logs")
        cur.execute("DELETE FROM admissions")
        print("[OK] Statsionar qabullar va qabulxona yozuvlari tozalandi.")

        # 6. Delete master patients table
        cur.execute("DELETE FROM patients")
        print("[OK] Bemorlar asosiy ro'yxati (patients) tozalandi.")

        # 7. Reset all beds to operational status
        cur.execute("UPDATE beds SET status = 'operational'")
        print("[OK] Barcha koykalar 'operational' (bo'sh va tayyor) holatiga o'tkazildi.")

        # 8. Clear audit logs (test entries) and user sessions
        cur.execute("TRUNCATE TABLE audit_logs")
        cur.execute("TRUNCATE TABLE user_sessions")
        print("[OK] Audit loglari va eski sessiyalar tozalandi.")

        # Re-enable foreign key checks
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()

        # 9. Clean physical patient dossier PDF files
        dossier_dir = os.path.join(BASE_DIR, "data", "patient_dossiers")
        if os.path.exists(dossier_dir):
            files = glob.glob(os.path.join(dossier_dir, "*.pdf"))
            for f in files:
                try:
                    os.remove(f)
                except Exception:
                    pass
            print(f"[OK] {len(files)} ta bemor PDF hujjati data/patient_dossiers papkasidan o'chirildi.")

        # 10. Clean test reports
        report_dir = os.path.join(BASE_DIR, "data", "reports")
        if os.path.exists(report_dir):
            files = glob.glob(os.path.join(report_dir, "*.*"))
            for f in files:
                try:
                    os.remove(f)
                except Exception:
                    pass
            print(f"[OK] {len(files)} ta eski test hisobot data/reports papkasidan o'chirildi.")

        # Final Verification
        cur.execute("SELECT COUNT(*) FROM patients")
        p_after = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM staff")
        st_after = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM rooms")
        rm_after = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM beds")
        bd_after = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM medications_catalog")
        med_after = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM services_catalog")
        srv_after = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM referral_doctors")
        ref_after = cur.fetchone()[0]

        print("\n" + "=" * 60)
        print("YAKUNIY TEKSHIRUV:")
        print(f"  - Bemorlar: {p_after} (TOZA)")
        print(f"  - Xodimlar: {st_after} (SAQLANDI)")
        print(f"  - Xonalar: {rm_after} (SAQLANDI)")
        print(f"  - Koykalar: {bd_after} (SAQLANDI, BARCHASI BO'SH)")
        print(f"  - Dorilar katalogi: {med_after} (SAQLANDI)")
        print(f"  - Xizmatlar katalogi: {srv_after} (SAQLANDI)")
        print(f"  - Hamkor shifokorlar: {ref_after} (SAQLANDI)")
        print("=" * 60)
        print("\n[MUVAFFAQITYAT] Tizim yangi ish boshlashga 100% tayyor!")

    except Exception as e:
        conn.rollback()
        print(f"\n[XATOLIK] Tozalash jarayonida xatolik yuz berdi: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return True


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    clean_patient_database(dry_run=dry_run)
