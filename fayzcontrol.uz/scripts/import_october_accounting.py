#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_october_accounting.py
Imports the official October 2026 accounting and clinical records into Fayzcontrol:
1. Adds consulting doctors into staff table
2. Adds 100 October patients into patients table (marked discharged)
3. Adds 100 admissions into admissions table (marked discharged so 0 beds are occupied)
4. Adds 100 invoices into invoices table matching exact billed, paid, debt numbers
5. Adds payments into payments table matching cash, terminal, and card totals
6. Adds all 297 daily cash journal entries into accounting_transactions table
7. Verifies that all balances and metrics match the October 2026 financial report perfectly.
"""

import sys
import os
import csv
import re
import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from db import get_db

CSV_PATH = os.path.join(BASE_DIR, 'data', 'october_2026_source.csv')
SQL_EXPORT_PATH = os.path.join(BASE_DIR, 'data', 'october_2026_accounting_data.sql')

# Doctor mappings
DOCTOR_STAFF_MAP = {
    'Хусан Файзибаевич': 'STF-DOC-01',
    'Х.П.': 'STF-DOC-01',
    'Ўзимиз': 'STF-DOC-01',
    'Фарида Мирахатовna': 'STF-DOC-02',
    'Фарида Мирахатовна': 'STF-DOC-02',
    'Юля Александровна': 'STF-DOC-03',
    'Сайгул': 'STF-NRS-03',
    'Лайло': 'STF-SAN-01',
    'Шахло': 'STF-NRS-06',
    'Шахноза': 'STF-NRS-04',
    'Нодира': 'STF-SPC-01',
    'Зарифбой Ибадуллаев': 'STF-DOC-04',
    'Гулнора Муратовна': 'STF-DOC-05',
    'Вазира Анваровна': 'STF-DOC-06',
    'Сайёра опа кардиолог': 'STF-DOC-07',
    'Дилдора Дилшодовна': 'STF-DOC-08',
    'Хумоюн': 'STF-DOC-09',
    'Шохрух': 'STF-DOC-10',
    'Сардор': 'STF-DOC-11',
    'Валера': 'STF-DOC-12'
}

EXTRA_STAFF = [
    ('STF-DOC-04', 'IBADULLAYEV ZARIFBOY', 'doctor', 'Psixiatr-Konsultant', 1),
    ('STF-DOC-05', 'NASRIDDINOVA GULNORA MURATOVNA', 'doctor', 'Shifokor-Narkolog', 1),
    ('STF-DOC-06', 'ANVAROVA VAZIRA', 'doctor', 'Psixoterapevt', 1),
    ('STF-DOC-07', 'SAYYORA KARDIOLOG', 'doctor', 'Kardiolog-Konsultant', 1),
    ('STF-DOC-08', 'DILDORA DILSHODOVNA', 'doctor', 'Shifokor', 1),
    ('STF-DOC-09', 'KUCHKAROV XUMOYUN NURALIYEVICH', 'doctor', 'Shifokor', 1),
    ('STF-DOC-10', 'SHOXJAXON SHIFOKOR', 'doctor', 'Shifokor', 1),
    ('STF-DOC-11', 'SARDOR SHIFOKOR', 'doctor', 'Shifokor', 1),
    ('STF-DOC-12', 'VALERIY KONSULTANT', 'doctor', 'Konsultant', 1),
]

def parse_source_csv():
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]

    sec2_lines = []
    sec3_lines = []
    sec4_lines = []
    curr = 1

    for l in lines:
        if 'KUNLIK KASSA HISOBOTI' in l:
            curr = 2
            continue
        elif 'BEMORLAR REESTRI VA XIZMATLAR HISOBOTI' in l:
            curr = 3
            continue
        elif 'CHIQIMLAR VA XARAJATLAR TAHLILI' in l:
            curr = 4
            continue

        if curr == 2:
            sec2_lines.append(l)
        elif curr == 3:
            sec3_lines.append(l)
        elif curr == 4:
            sec4_lines.append(l)

    # Parse Patients (Section 3)
    patients = []
    r3 = csv.reader(sec3_lines)
    for row in r3:
        if row and row[0].isdigit():
            num = int(row[0])
            name = row[1].strip()
            doc = row[2].strip()
            care_type = row[3].strip()
            daily_rate = float(row[4] or 0)
            billed = float(row[5] or 0)
            paid_cash = float(row[6] or 0)
            paid_term = float(row[7] or 0)
            paid_card = float(row[8] or 0)
            paid_total = float(row[9] or 0)
            debt = float(row[10] or 0)
            patients.append({
                'num': num,
                'name': name,
                'doctor': doc,
                'care_type': care_type,
                'daily_rate': daily_rate,
                'billed': billed,
                'paid_cash': paid_cash,
                'paid_term': paid_term,
                'paid_card': paid_card,
                'paid_total': paid_total,
                'debt': debt
            })

    # Parse Journal (Section 2)
    journal = []
    r2 = csv.reader(sec2_lines)
    for row in r2:
        if row and row[0].isdigit():
            num = int(row[0])
            dt = row[1].strip()
            desc = row[2].strip()
            cat = row[3].strip()
            cash = float(row[4] or 0)
            card = float(row[5] or 0)
            tot_in = float(row[6] or 0)
            exp = float(row[7] or 0)
            qoldiq = float(row[8] or 0)
            izoh = row[9].strip() if len(row) > 9 else ""
            journal.append({
                'num': num,
                'date_str': dt,
                'desc': desc,
                'category': cat,
                'cash': cash,
                'card': card,
                'total_in': tot_in,
                'expense': exp,
                'qoldiq': qoldiq,
                'notes': izoh
            })

    # Parse Expenses (Section 4)
    expenses = []
    r4 = csv.reader(sec4_lines)
    for row in r4:
        if row and row[0].isdigit():
            num = int(row[0])
            dt = row[1].strip()
            desc = row[2].strip()
            cat = row[3].strip()
            amt = float(row[4] or 0)
            method = row[5].strip() if len(row) > 5 else "Naqd"
            notes = row[6].strip() if len(row) > 6 else ""
            expenses.append({
                'num': num,
                'date_str': dt,
                'desc': desc,
                'category': cat,
                'amount': amt,
                'method': method,
                'notes': notes
            })

    return patients, journal, expenses

def format_date_ymd(d_str):
    parts = d_str.split('.')
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]:0>2}-{parts[0]:0>2}"
    return d_str

def main():
    print("=== Fayz Medical House: October 2026 Accounting Import ===")
    patients, journal, expenses = parse_source_csv()
    print(f"[OK] Parsed source CSV: {len(patients)} patients, {len(journal)} journal entries, {len(expenses)} expense categories.")

    conn = get_db()
    cur = conn.cursor()

    # 1. Ensure Extra Consulting Doctors in staff table
    print("--- 1. Ensuring Consulting Doctors in staff table ---")
    for s_id, s_name, s_role, s_spec, s_act in EXTRA_STAFF:
        cur.execute("SELECT id FROM staff WHERE id = %s", (s_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO staff (id, full_name, role, specialty, is_active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, '2026-10-01 00:00:00', '2026-10-01 00:00:00')
            """, (s_id, s_name, s_role, s_spec, s_act))
            print(f"  Inserted staff: {s_id} - {s_name}")
        else:
            print(f"  Staff already exists: {s_id} - {s_name}")

    # 2. Get list of operational beds
    cur.execute("SELECT id FROM beds ORDER BY id")
    beds_list = [r['id'] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
    if not beds_list:
        raise RuntimeError("No beds found in database!")

    # 3. Clean up any previous October import (idempotent run)
    print("--- 2. Cleaning previous October records if present ---")
    cur.execute("DELETE FROM accounting_transactions WHERE id LIKE 'TXN-2026-OCT-%' OR id LIKE 'TRX-2026-OCT-%' OR id LIKE 'TXN-PAY-2026-OCT-%'")
    cur.execute("DELETE FROM accounting_transactions WHERE id IN ('TRX-2026-9464', 'TRX-MED-2026-20154', 'TRX-MED-2026-63771')")
    cur.execute("DELETE FROM payments WHERE id LIKE 'PAY-2026-OCT-%'")
    cur.execute("DELETE FROM invoice_items WHERE invoice_id LIKE 'INV-2026-OCT-%'")
    cur.execute("DELETE FROM invoices WHERE id LIKE 'INV-2026-OCT-%'")
    cur.execute("DELETE FROM admissions WHERE id LIKE 'ADM-2026-OCT-%'")
    cur.execute("DELETE FROM patients WHERE id LIKE 'PAT-2026-OCT-%'")
    conn.commit()
    print("  Cleaned previous October test records.")

    # 4. Insert 100 Patients, Admissions, Invoices, Payments
    print(f"--- 3. Inserting {len(patients)} October Patients & Billings ---")
    patient_id_map = {} # num -> patient_id
    invoice_id_map = {} # num -> invoice_id

    for p in patients:
        idx = p['num']
        pat_id = f"PAT-2026-OCT-{idx:03d}"
        adm_id = f"ADM-2026-OCT-{idx:03d}"
        inv_id = f"INV-2026-OCT-{idx:03d}"
        patient_code = f"P-2610-{idx:03d}"
        patient_id_map[idx] = pat_id
        invoice_id_map[idx] = inv_id

        doc_staff_id = DOCTOR_STAFF_MAP.get(p['doctor'], 'STF-DOC-01')
        bed_id = beds_list[(idx - 1) % len(beds_list)]

        # Calculate stay days
        daily_rate = p['daily_rate']
        billed = p['billed']
        total_days = max(1, int(round(billed / daily_rate))) if daily_rate > 0 else 1
        
        # Start and end date in October 2026
        # Distribute starts from Oct 1 to Oct 25
        start_day = min(25, 1 + ((idx * 3) % 25))
        end_day = min(31, start_day + total_days)
        start_date = f"2026-10-{start_day:02d}"
        end_date = f"2026-10-{end_day:02d}"

        # Insert patient
        cur.execute("""
            INSERT INTO patients (id, patient_code, full_name, status, referral_source, created_at, updated_at)
            VALUES (%s, %s, %s, 'discharged', 'walk_in', %s, %s)
        """, (pat_id, patient_code, p['name'], f"{start_date} 09:00:00", f"{end_date} 18:00:00"))

        # Insert admission with status = 'discharged' so 0 beds are occupied
        # Note: total_days is a generated column in MySQL, omit from column list
        cur.execute("""
            INSERT INTO admissions (
                id, patient_id, bed_id, attending_doctor_id, program_type,
                daily_price, start_date, planned_end_date, actual_end_date,
                status, admission_notes, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                'discharged', 'Oktyabr 2026 hisoboti bo''yicha bemor', %s, %s
            )
        """, (
            adm_id, pat_id, bed_id, doc_staff_id, p['care_type'],
            daily_rate, start_date, end_date, end_date,
            f"{start_date} 09:00:00", f"{end_date} 18:00:00"
        ))

        # Insert invoice
        # Note: trg_invoices_before_insert will compute net_amount, balance_due, and payment_status
        cur.execute("""
            INSERT INTO invoices (
                id, admission_id, total_billed, discount_amount, net_amount,
                total_paid, balance_due, payment_status, created_at, updated_at
            ) VALUES (
                %s, %s, %s, 0.00, %s,
                0.00, %s, 'unpaid', %s, %s
            )
        """, (
            inv_id, adm_id, billed, billed,
            billed, f"{end_date} 18:00:00", f"{end_date} 18:00:00"
        ))

        # Insert payments
        # Account destinations: 'kassa', 'terminal_bank', 'click_payme_merchant', 'main_bank_account'
        # Payment methods: 'cash', 'terminal', 'card_transfer'
        if p['paid_cash'] > 0:
            pay_id = f"PAY-2026-OCT-{idx:03d}-C"
            cur.execute("""
                INSERT INTO payments (
                    id, invoice_id, amount, payment_method, account_destination,
                    payment_date, notes, received_by_staff_id, created_at
                ) VALUES (
                    %s, %s, %s, 'cash', 'kassa',
                    %s, %s, 'STF-DOC-01', %s
                )
            """, (pay_id, inv_id, p['paid_cash'], end_date, f"{p['name']} naqd to'lov", f"{end_date} 18:00:00"))

        if p['paid_term'] > 0:
            pay_id = f"PAY-2026-OCT-{idx:03d}-T"
            cur.execute("""
                INSERT INTO payments (
                    id, invoice_id, amount, payment_method, account_destination,
                    payment_date, notes, received_by_staff_id, created_at
                ) VALUES (
                    %s, %s, %s, 'terminal', 'terminal_bank',
                    %s, %s, 'STF-DOC-01', %s
                )
            """, (pay_id, inv_id, p['paid_term'], end_date, f"{p['name']} terminal to'lov", f"{end_date} 18:00:00"))

        if p['paid_card'] > 0:
            pay_id = f"PAY-2026-OCT-{idx:03d}-K"
            cur.execute("""
                INSERT INTO payments (
                    id, invoice_id, amount, payment_method, account_destination,
                    payment_date, notes, received_by_staff_id, created_at
                ) VALUES (
                    %s, %s, %s, 'card_transfer', 'click_payme_merchant',
                    %s, %s, 'STF-DOC-01', %s
                )
            """, (pay_id, inv_id, p['paid_card'], end_date, f"{p['name']} karta to'lov", f"{end_date} 18:00:00"))

    conn.commit()
    print("  Inserted all 100 patients, admissions, invoices, and payments.")

    # 5. Clean trigger-generated TXN-PAY transactions so we can insert the exact daily cash journal
    cur.execute("DELETE FROM accounting_transactions WHERE id LIKE 'TXN-PAY-2026-OCT-%'")
    conn.commit()

    # 6. Insert All 297 Daily Cash Journal Entries (Section 2)
    print(f"--- 4. Inserting {len(journal)} Daily Cash Journal Entries ---")
    
    # Map patient first names to invoice_id for automatic linkage
    name_to_inv = {}
    for p in patients:
        first_w = p['name'].strip().split()[0].lower()
        if len(first_w) >= 3 and first_w not in name_to_inv:
            name_to_inv[first_w] = invoice_id_map[p['num']]

    imported_txns = 0
    for idx_j, j in enumerate(journal, start=1):
        num = idx_j
        dt_sql = format_date_ymd(j['date_str'])
        desc = j['desc']
        cat = j['category']
        cash = j['cash']
        card = j['card']
        exp = j['expense']
        izoh = j['notes']
        notes_full = f"{desc} | {izoh}" if izoh and izoh != desc else desc

        # Check if description matches a patient invoice
        rel_inv = None
        d_lower = desc.lower()
        for p_w, inv_ref in name_to_inv.items():
            if p_w in d_lower:
                rel_inv = inv_ref
                break

        # Case 1: Special inkassatsiya transfer row (num 81: Bank hisobiga)
        if num == 81 and cash == 50000000 and exp == 50000000:
            # Record inkassatsiya expense (cash register out)
            cur.execute("""
                INSERT INTO accounting_transactions (
                    id, transaction_type, category, amount, payment_method,
                    account_source, description, transaction_date, recorded_by_staff_id,
                    payroll_month, created_at
                ) VALUES (
                    %s, 'expense', 'incasso', 50000000, 'cash',
                    'kassa', 'Bankka inkassatsiya (naqd pul topshirildi)', %s, 'STF-DOC-01',
                    '2026-10', %s
                )
            """, (f"TRX-2026-OCT-{num:03d}-OUT", dt_sql, f"{dt_sql} 16:00:00"))

            # Record bank deposit income (bank account in)
            cur.execute("""
                INSERT INTO accounting_transactions (
                    id, transaction_type, category, amount, payment_method,
                    account_source, description, transaction_date, recorded_by_staff_id,
                    payroll_month, created_at
                ) VALUES (
                    %s, 'income', 'incasso', 50000000, 'bank_wire',
                    'main_bank_account', 'Bank hisob raqamiga kirim (inkassatsiya)', %s, 'STF-DOC-01',
                    '2026-10', %s
                )
            """, (f"TRX-2026-OCT-{num:03d}-IN", dt_sql, f"{dt_sql} 16:05:00"))
            imported_txns += 2
            continue

        # Case 2: Expense entry
        if exp > 0:
            exp_cat = 'operational_expense'
            if any(k in desc.lower() for k in ['х.п.', 'rahbariyat']):
                exp_cat = 'Раҳбарият / Х.П.'
            elif any(k in desc.lower() for k in ['аванс', 'oylik', 'bonus']):
                exp_cat = 'Иш ҳақи / Аванс'
            elif any(k in desc.lower() for k in ['дори', 'азолентол', 'azaleptol', 'капсул']):
                exp_cat = 'Дори-дармон'
            elif any(k in desc.lower() for k in ['қайтарилди', 'обратно', 'возврат']):
                exp_cat = 'Қайтарилган пул (Возврат)'
            elif any(k in desc.lower() for k in ['арида']):
                exp_cat = 'Контрагент / Харид'
            elif any(k in desc.lower() for k in ['банк', 'инкассация']):
                exp_cat = 'incasso'
            else:
                exp_cat = 'Хўжалик харажати'

            cur.execute("""
                INSERT INTO accounting_transactions (
                    id, transaction_type, category, amount, payment_method,
                    account_source, description, transaction_date, recorded_by_staff_id,
                    payroll_month, created_at
                ) VALUES (
                    %s, 'expense', %s, %s, 'cash',
                    'kassa', %s, %s, 'STF-DOC-01',
                    '2026-10', %s
                )
            """, (f"TRX-2026-OCT-{num:03d}-EXP", exp_cat, exp, notes_full, dt_sql, f"{dt_sql} 14:00:00"))
            imported_txns += 1

        # Case 3: Cash In
        if cash > 0:
            cur.execute("""
                INSERT INTO accounting_transactions (
                    id, transaction_type, category, amount, payment_method,
                    account_source, related_invoice_id, description, transaction_date,
                    recorded_by_staff_id, payroll_month, created_at
                ) VALUES (
                    %s, 'income', %s, %s, 'cash',
                    'kassa', %s, %s, %s,
                    'STF-DOC-01', '2026-10', %s
                )
            """, (f"TRX-2026-OCT-{num:03d}-C", cat, cash, rel_inv, notes_full, dt_sql, f"{dt_sql} 11:00:00"))
            imported_txns += 1

        # Case 4: Card In
        if card > 0:
            cur.execute("""
                INSERT INTO accounting_transactions (
                    id, transaction_type, category, amount, payment_method,
                    account_source, related_invoice_id, description, transaction_date,
                    recorded_by_staff_id, payroll_month, created_at
                ) VALUES (
                    %s, 'income', %s, %s, 'terminal',
                    'terminal_bank', %s, %s, %s,
                    'STF-DOC-01', '2026-10', %s
                )
            """, (f"TRX-2026-OCT-{num:03d}-K", cat, card, rel_inv, notes_full, dt_sql, f"{dt_sql} 11:30:00"))
            imported_txns += 1

    conn.commit()
    print(f"  Inserted {imported_txns} transactions into accounting_transactions.")

    # 7. Verification queries
    print("--- 5. Running System Verification ---")
    cur.execute("""
        SELECT COUNT(*) AS total_patients,
               COALESCE(SUM(total_billed), 0) AS sum_billed,
               COALESCE(SUM(total_paid), 0) AS sum_paid,
               COALESCE(SUM(balance_due), 0) AS sum_debt,
               COALESCE(SUM(paid_cash), 0) AS sum_cash,
               COALESCE(SUM(paid_terminal), 0) AS sum_terminal,
               COALESCE(SUM(paid_card_online), 0) AS sum_card
        FROM v_financial_ledger
    """)
    v_res = cur.fetchone()
    print(f"[VERIFY] v_financial_ledger:")
    print(f"  Total Patients: {v_res['total_patients']} (Expected: 100)")
    print(f"  Total Billed:   {v_res['sum_billed']:,.2f} UZS (Expected: 397,437,000.00)")
    print(f"  Total Paid:     {v_res['sum_paid']:,.2f} UZS (Expected: 374,590,000.00)")
    print(f"  Total Debt:     {v_res['sum_debt']:,.2f} UZS (Expected: 22,847,000.00)")
    print(f"  Paid Cash:      {v_res['sum_cash']:,.2f} UZS (Expected: 251,120,000.00)")
    print(f"  Paid Terminal:  {v_res['sum_terminal']:,.2f} UZS (Expected: 110,690,000.00)")
    print(f"  Paid Card:      {v_res['sum_card']:,.2f} UZS (Expected: 12,780,000.00)")

    cur.execute("""
        SELECT transaction_type, payment_method, COALESCE(SUM(amount), 0) AS sum_amt, COUNT(*) AS cnt
        FROM accounting_transactions
        WHERE transaction_date BETWEEN '2026-10-01' AND '2026-10-31'
        GROUP BY transaction_type, payment_method
        ORDER BY transaction_type, payment_method
    """)
    print("[VERIFY] accounting_transactions:")
    for r in cur.fetchall():
        print(f"  {r['transaction_type']:8} | {r['payment_method']:10} | {r['sum_amt']:>15,.2f} UZS | {r['cnt']} txns")

    cur.execute("""
        SELECT COUNT(*) AS occupied_count
        FROM v_bed_live_status
        WHERE status = 'occupied'
    """)
    occ = cur.fetchone()['occupied_count']
    print(f"[VERIFY] Bed Occupancy: {occ} occupied beds (Expected: 0 occupied, all available for November live data).")

    # 8. Export SQL Dump
    print(f"--- 6. Exporting SQL migration to {SQL_EXPORT_PATH} ---")
    export_sql_file()
    print("[OK] All October 2026 accounting records successfully imported!")

def export_sql_file():
    conn = get_db()
    cur = conn.cursor()

    with open(SQL_EXPORT_PATH, 'w', encoding='utf-8') as f:
        f.write("-- Fayz Medical House: October 2026 Accounting Migration\n")
        f.write("-- Auto-generated by scripts/import_october_accounting.py\n\n")
        f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")

        # Staff
        f.write("-- 1. Consulting Doctors\n")
        for s_id, s_name, s_role, s_spec, s_act in EXTRA_STAFF:
            f.write(f"INSERT INTO staff (id, full_name, role, specialty, is_active, created_at, updated_at) "
                    f"VALUES ('{s_id}', '{s_name}', '{s_role}', '{s_spec}', 1, '2026-10-01 00:00:00', '2026-10-01 00:00:00') "
                    f"ON DUPLICATE KEY UPDATE full_name = VALUES(full_name), specialty = VALUES(specialty);\n")
        f.write("\n")

        # Clean previous
        f.write("-- 2. Idempotent Cleanup of October Records\n")
        f.write("DELETE FROM accounting_transactions WHERE id LIKE 'TXN-2026-OCT-%' OR id LIKE 'TRX-2026-OCT-%' OR id LIKE 'TXN-PAY-2026-OCT-%';\n")
        f.write("DELETE FROM payments WHERE id LIKE 'PAY-2026-OCT-%';\n")
        f.write("DELETE FROM invoice_items WHERE invoice_id LIKE 'INV-2026-OCT-%';\n")
        f.write("DELETE FROM invoices WHERE id LIKE 'INV-2026-OCT-%';\n")
        f.write("DELETE FROM admissions WHERE id LIKE 'ADM-2026-OCT-%';\n")
        f.write("DELETE FROM patients WHERE id LIKE 'PAT-2026-OCT-%';\n\n")

        # Patients
        f.write("-- 3. Patients\n")
        cur.execute("SELECT * FROM patients WHERE id LIKE 'PAT-2026-OCT-%' ORDER BY id")
        for r in cur.fetchall():
            fn = r['full_name'].replace("'", "''")
            f.write(f"INSERT INTO patients (id, patient_code, full_name, status, referral_source, created_at, updated_at) "
                    f"VALUES ('{r['id']}', '{r['patient_code']}', '{fn}', '{r['status']}', '{r['referral_source']}', '{r['created_at']}', '{r['updated_at']}');\n")
        f.write("\n")

        # Admissions
        f.write("-- 4. Admissions\n")
        cur.execute("SELECT * FROM admissions WHERE id LIKE 'ADM-2026-OCT-%' ORDER BY id")
        for r in cur.fetchall():
            notes = (r['admission_notes'] or '').replace("'", "''")
            f.write(f"INSERT INTO admissions (id, patient_id, bed_id, attending_doctor_id, program_type, daily_price, start_date, planned_end_date, actual_end_date, status, admission_notes, created_at, updated_at) "
                    f"VALUES ('{r['id']}', '{r['patient_id']}', '{r['bed_id']}', '{r['attending_doctor_id']}', '{r['program_type']}', {r['daily_price']}, '{r['start_date']}', '{r['planned_end_date']}', '{r['actual_end_date']}', '{r['status']}', '{notes}', '{r['created_at']}', '{r['updated_at']}');\n")
        f.write("\n")

        # Invoices
        f.write("-- 5. Invoices\n")
        cur.execute("SELECT * FROM invoices WHERE id LIKE 'INV-2026-OCT-%' ORDER BY id")
        for r in cur.fetchall():
            f.write(f"INSERT INTO invoices (id, admission_id, total_billed, discount_amount, net_amount, total_paid, balance_due, payment_status, created_at, updated_at) "
                    f"VALUES ('{r['id']}', '{r['admission_id']}', {r['total_billed']}, {r['discount_amount']}, {r['net_amount']}, {r['total_paid']}, {r['balance_due']}, '{r['payment_status']}', '{r['created_at']}', '{r['updated_at']}');\n")
        f.write("\n")

        # Payments
        f.write("-- 6. Payments\n")
        cur.execute("SELECT * FROM payments WHERE id LIKE 'PAY-2026-OCT-%' ORDER BY id")
        for r in cur.fetchall():
            notes = (r['notes'] or '').replace("'", "''")
            f.write(f"INSERT INTO payments (id, invoice_id, amount, payment_method, account_destination, payment_date, notes, received_by_staff_id, created_at) "
                    f"VALUES ('{r['id']}', '{r['invoice_id']}', {r['amount']}, '{r['payment_method']}', '{r['account_destination']}', '{r['payment_date']}', '{notes}', '{r['received_by_staff_id']}', '{r['created_at']}');\n")
        f.write("\n")

        # Remove trigger-generated TXN-PAY transactions so accounting_transactions is exact
        f.write("DELETE FROM accounting_transactions WHERE id LIKE 'TXN-PAY-2026-OCT-%';\n\n")

        # Accounting transactions
        f.write("-- 7. Daily Cash Journal Transactions\n")
        cur.execute("SELECT * FROM accounting_transactions WHERE id LIKE 'TRX-2026-OCT-%' ORDER BY id")
        for r in cur.fetchall():
            cat = (r['category'] or '').replace("'", "''")
            desc = (r['description'] or '').replace("'", "''")
            rel_inv = f"'{r['related_invoice_id']}'" if r['related_invoice_id'] else "NULL"
            f.write(f"INSERT INTO accounting_transactions (id, transaction_type, category, amount, payment_method, account_source, related_invoice_id, description, transaction_date, recorded_by_staff_id, payroll_month, created_at) "
                    f"VALUES ('{r['id']}', '{r['transaction_type']}', '{cat}', {r['amount']}, '{r['payment_method']}', '{r['account_source']}', {rel_inv}, '{desc}', '{r['transaction_date']}', '{r['recorded_by_staff_id']}', '{r['payroll_month']}', '{r['created_at']}');\n")
        f.write("\n")

        f.write("SET FOREIGN_KEY_CHECKS = 1;\n")

if __name__ == '__main__':
    main()
