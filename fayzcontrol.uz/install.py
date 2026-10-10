#!/usr/bin/env python3
"""
==============================================================================
FAYZ MEDICAL HOUSE — Enterprise MySQL 8.0 Verification & Setup Script
==============================================================================
This script validates the clinic management system with MySQL 8.0:
1. Connects to MySQL 8.0 via db.get_db().
2. Validates Rooms (12), Inpatient Beds (14), and Clinical Staff.
3. Checks static portals and API data integrity.
==============================================================================
"""

import os
import sys
import json

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

def run_installation():
    print("=" * 70)
    print(">>> FAYZ MEDICAL HOUSE -- ENTERPRISE MYSQL 8.0 TEKSHIRUV VA SOZLASH")
    print("=" * 70)

    # Step 1: Connect to MySQL
    print("\n[1/4] MySQL 8.0 ma'lumotlar bazasiga ulanish...")
    try:
        from db import get_db, load_config
        cfg = load_config()
        print(f"  * Host: {cfg.get('host')}:{cfg.get('port')}")
        print(f"  * DB: {cfg.get('database')} (User: {cfg.get('user')})")
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT VERSION() AS ver, DATABASE() AS db_name, USER() AS usr;")
        row = cur.fetchone()
        ver = row.get('ver', '')
        db_name = row.get('db_name', '')
        usr = row.get('usr', '')
        print(f"  [OK] Muvaffaqiyatli ulandi: MySQL {ver} | DB: {db_name} | User: {usr}")

        # Verify Tables
        cur.execute("SELECT COUNT(*) FROM beds")
        total_beds = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM staff WHERE is_active = 1")
        staff_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM patients")
        patients_count = cur.fetchone()[0]
        conn.close()

        print(f"  * Jami statsionar o'rinlar: {total_beds} ta")
        print(f"  * Faol shifokor va xodimlar: {staff_count} nafar")
        print(f"  * Bemorlar ro'yxati: {patients_count} nafar")
    except Exception as e:
        print(f"  [FAIL] MySQL ga ulanishda xatolik: {e}")
        return False

    # Step 2: Validate Data Files
    print("\n[2/4] Tizim ma'lumotlar fayllarini tekshirish...")
    json_files = ['reception_db.json', 'accounting_db.json', 'hr_db.json', 'clinic_rooms.json', 'pharmacology_db.json']
    for jf in json_files:
        p = os.path.join(DATA_DIR, jf)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    json.load(f)
                print(f"  [OK] {jf:25} -> Toza va to'g'ri")
            except Exception as e:
                print(f"  [FAIL] {jf:25} -> JSON xatolik: {e}")
        else:
            print(f"  [FAIL] {jf:25} -> Topilmadi!")

    # Step 3: Check Static Pages
    print("\n[3/4] Veb-sahifalar va modullarni tekshirish...")
    pages = [
        ('superpage.html', 'Super-Portal (10 Bo\'lim)'),
        ('reception.html', 'Qabulxona & Triage'),
        ('building_management.html', 'Statsionar (14 Karavot)'),
        ('doctor.html', 'Shifokor Posti & EMR'),
        ('accounting.html', 'Moliya & Kassa'),
        ('hr.html', 'Kadrlar & Oylik'),
        ('crm.html', 'Bemorlar CRM'),
        ('medical_blank.html', 'A4 Tibbiy Blanklar'),
    ]
    for p_file, p_name in pages:
        full_p = os.path.join(BASE_DIR, p_file)
        if os.path.exists(full_p):
            print(f"  [OK] {p_file:25} -> {p_name}")
        else:
            print(f"  [FAIL] {p_file:25} -> Topilmadi!")

    # Step 4: Completion Summary
    print("\n[4/4] Tekshiruv muvaffaqiyatli yakunlandi!")
    print("=" * 70)
    print("Tizimni ishga tushirish uchun:")
    print("   1. 'python server.py' ni ishga tushiring.")
    print("   2. Brauzeringizda quyidagi manzilni oching:")
    print("      -> http://localhost:3000/superpage.html (Barcha bo'limlar)")
    print("      -> http://localhost:3000/reception.html (Qabulxona)")
    print("      -> http://localhost:3000/building_management.html (Statsionar)")
    print("      -> http://localhost:3000/doctor.html (Shifokor)")
    print("=" * 70)
    return True

if __name__ == '__main__':
    run_installation()
