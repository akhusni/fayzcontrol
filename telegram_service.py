"""
Fayz Medical House — Telegram Bot Service
Integrates with Telegram Group topics:
- Hamshira (Topic ID: 2): Bemorlarning dorilari va ichish vaqtlari
- Doctor (Topic ID: 4): Statsionardagi bemorlar ro'yxati va holati
- Bugalteriya (Topic ID: 6): Kengaytirilgan kunlik moliya, kassa, qarzlar, dorixona va maosh fondi hisoboti (Xulosa, Ko'p varaqli Excel va Rasmiy PDF)
"""

import os
import sys
import io
import json
import datetime
import time
import threading
import urllib.request
import urllib.parse
from decimal import Decimal

# Add current dir to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import db
import nursery

# Telegram Configuration
# The bot token used to be hard-coded here and was pushed to a public GitHub
# repo, so anyone could post as the clinic bot. It now comes only from the
# environment; with no token the bot stays off, which also keeps local test
# runs from posting fake payments into the real staff group.
BOT_TOKEN = os.environ.get("FMH_TELEGRAM_BOT_TOKEN", "").strip()
ENABLED = bool(BOT_TOKEN)
CHAT_ID = int(os.environ.get("FMH_TELEGRAM_CHAT_ID", "-1004441223890"))

TOPIC_NURSES = 2        # "Hamshira"
TOPIC_DOCTORS = 4       # "Doctor"
TOPIC_ACCOUNTING = 6    # "Bugalteriya"

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_telegram_message(message_thread_id, text, parse_mode="HTML"):
    """Send text message to a specific topic in Telegram supergroup."""
    url = f"{API_BASE}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "message_thread_id": message_thread_id,
        "text": text,
        "parse_mode": parse_mode
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            return res_data
    except Exception as e:
        print(f"[ERROR] Failed to send message to topic {message_thread_id}: {e}")
        return None


def send_telegram_document(message_thread_id, file_path, caption=None, parse_mode="HTML"):
    """Send file/document to a specific topic using multipart/form-data."""
    url = f"{API_BASE}/sendDocument"
    boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
    
    file_name = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    body = io.BytesIO()
    
    # chat_id
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
    body.write(f"{CHAT_ID}\r\n".encode("utf-8"))

    # message_thread_id
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(b'Content-Disposition: form-data; name="message_thread_id"\r\n\r\n')
    body.write(f"{message_thread_id}\r\n".encode("utf-8"))

    # caption
    if caption:
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
        body.write(f"{caption}\r\n".encode("utf-8"))
        if parse_mode:
            body.write(f"--{boundary}\r\n".encode("utf-8"))
            body.write(b'Content-Disposition: form-data; name="parse_mode"\r\n\r\n')
            body.write(f"{parse_mode}\r\n".encode("utf-8"))

    # document file
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(f'Content-Disposition: form-data; name="document"; filename="{file_name}"\r\n'.encode("utf-8"))
    body.write(b"Content-Type: application/octet-stream\r\n\r\n")
    body.write(file_bytes)
    body.write(b"\r\n")

    body.write(f"--{boundary}--\r\n".encode("utf-8"))
    body_val = body.getvalue()

    req = urllib.request.Request(
        url,
        data=body_val,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            return res_data
    except Exception as e:
        print(f"[ERROR] Failed to send document to topic {message_thread_id}: {e}")
        return None


def format_currency(val):
    if val is None:
        return "0"
    try:
        return f"{int(round(float(val))):,}".replace(",", " ")
    except Exception:
        return str(val)


# -----------------------------------------------------------------------------
# 1. HAMSHIRALAR HISOBOTI (Topic: 2)
# -----------------------------------------------------------------------------
def generate_and_send_nurses_report(target_date=None):
    """
    Barcha bemorlarning dorilari va qachon ichish ro'yxati
    """
    if target_date is None:
        target_date = datetime.date.today()
    elif isinstance(target_date, str):
        target_date = datetime.date.fromisoformat(target_date)

    date_str = target_date.strftime("%d.%m.%Y")
    
    conn = db.get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.id AS admission_id, a.patient_id, a.start_date, a.planned_end_date,
               p.full_name AS patient_name, p.patient_code, p.medical_allergies,
               r.room_number, b.bed_code, s.full_name AS doctor_name
        FROM admissions a
        JOIN patients p ON a.patient_id = p.id
        JOIN beds b ON a.bed_id = b.id
        JOIN rooms r ON b.room_id = r.id
        LEFT JOIN staff s ON a.attending_doctor_id = s.id
        WHERE a.status = 'active'
        ORDER BY r.room_number, b.bed_code
    """)
    inpatients = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT rx.*, p.full_name AS patient_name, r.room_number, b.bed_code
        FROM prescriptions rx
        JOIN patients p ON rx.patient_id = p.id
        JOIN admissions a ON rx.admission_id = a.id
        JOIN beds b ON a.bed_id = b.id
        JOIN rooms r ON b.room_id = r.id
        WHERE rx.status = 'active' AND a.status = 'active'
        ORDER BY r.room_number, b.bed_code, rx.medication_name
    """)
    prescriptions = [dict(r) for r in cur.fetchall()]

    conn.close()

    lines = [
        "🏥 <b>FAYZ MEDICAL HOUSE — HAMSHIRALIK BO'LIMI</b>",
        f"📅 <b>Sana:</b> {date_str}",
        "📋 <b>BEMORLARNING DORILARI VA QABUL QILISH JADVALI</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    if not inpatients:
        lines.append("<i>Hozirgi vaqtda statsionarda yotgan faol bemorlar mavjud emas.</i>")
    else:
        rx_by_patient = {}
        for rx in prescriptions:
            rx_by_patient.setdefault(rx["patient_id"], []).append(rx)

        for idx, pt in enumerate(inpatients, start=1):
            lines.append(f"<b>{idx}. 👤 {pt['patient_name']}</b> (Palata: <b>{pt['room_number']}-{pt['bed_code']}</b>)")
            lines.append(f"   🆔 Kodi: <code>{pt['patient_code']}</code>")
            lines.append(f"   🩺 Shifokor: {pt['doctor_name'] or 'Belgilanmagan'}")
            if pt.get("medical_allergies"):
                lines.append(f"   ⚠️ Allergiya: {pt['medical_allergies']}")

            pt_rx = rx_by_patient.get(pt["patient_id"], [])
            if not pt_rx:
                lines.append("   💊 <i>Dorilar: Hozircha yangi dori yozilmagan yoki kutilmoqda.</i>")
            else:
                lines.append("   💊 <b>Buyurilgan dorilar va vaqtlari:</b>")
                for r_i, rx in enumerate(pt_rx, start=1):
                    med = rx["medication_name"]
                    dosage = rx.get("dosage", "")
                    timing = rx.get("timing") or rx.get("frequency") or "Ko'rsatilgan vaqtda"
                    route = rx.get("route", "")
                    instr = rx.get("instructions")
                    
                    route_str = f" ({route})" if route else ""
                    instr_str = f" [Izoh: {instr}]" if instr else ""
                    lines.append(f"      {r_i}) <b>{med}</b> — {dosage}{route_str}")
                    lines.append(f"         ⏰ <i>Qachon ichish:</i> <b>{timing}</b>{instr_str}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📊 Jami statsionar bemorlar: <b>{len(inpatients)} nafar</b>")
        lines.append("💉 <i>Eslatma: Har bir dori qabul qilingach, jurnaldan belgilab boring!</i>")

    msg_text = "\n".join(lines)
    return send_telegram_message(TOPIC_NURSES, msg_text)


# -----------------------------------------------------------------------------
# 2. DOKTORLAR HISOBOTI (Topic: 4)
# -----------------------------------------------------------------------------
def generate_and_send_doctors_report(target_date=None):
    """
    Statsionardagi va klinikadagi kasallar ro'yxati va ularning holati
    """
    if target_date is None:
        target_date = datetime.date.today()
    elif isinstance(target_date, str):
        target_date = datetime.date.fromisoformat(target_date)

    date_str = target_date.strftime("%d.%m.%Y")
    
    conn = db.get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.id AS admission_id, a.program_type, a.start_date, a.planned_end_date,
               a.daily_price, a.total_days, a.admission_notes,
               p.id AS patient_id, p.full_name AS patient_name, p.patient_code,
               p.gender, p.birth_date, p.birth_year, p.phone, p.medical_allergies,
               r.room_number, b.bed_code,
               s.full_name AS doctor_name, s.specialty AS doctor_specialty
        FROM admissions a
        JOIN patients p ON a.patient_id = p.id
        JOIN beds b ON a.bed_id = b.id
        JOIN rooms r ON b.room_id = r.id
        LEFT JOIN staff s ON a.attending_doctor_id = s.id
        WHERE a.status = 'active'
        ORDER BY r.floor_number, r.room_number, b.bed_code
    """)
    inpatients = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT mh.patient_id, mh.diagnosis_primary, mh.complaints, mh.icd10_code
        FROM medical_histories mh
        ORDER BY mh.updated_at DESC
    """)
    histories = {r["patient_id"]: dict(r) for r in cur.fetchall()}

    cur.execute("""
        SELECT dn.patient_id, dn.patient_condition, dn.dynamics_notes, dn.vital_bp_systolic,
               dn.vital_bp_diastolic, dn.vital_pulse, dn.vital_temp, dn.vital_spo2
        FROM doctor_daily_notes dn
        ORDER BY dn.note_date DESC, dn.id DESC
    """)
    latest_notes = {}
    for r in cur.fetchall():
        if r["patient_id"] not in latest_notes:
            latest_notes[r["patient_id"]] = dict(r)

    conn.close()

    lines = [
        "🏥 <b>FAYZ MEDICAL HOUSE — SHIFOKORLAR BO'LIMI</b>",
        f"📅 <b>Sana:</b> {date_str}",
        "📋 <b>STATSIONARDAGI BEMORLAR RO'YXATI</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    if not inpatients:
        lines.append("<i>Hozirgi vaqtda statsionarda davolanayotgan bemorlar mavjud emas.</i>")
    else:
        for idx, pt in enumerate(inpatients, start=1):
            pid = pt["patient_id"]
            hist = histories.get(pid, {})
            note = latest_notes.get(pid, {})

            age_str = ""
            if pt.get("birth_year"):
                age = target_date.year - int(pt["birth_year"])
                age_str = f" ({age} yosh)"
            elif pt.get("birth_date"):
                try:
                    b_yr = int(str(pt["birth_date"])[:4])
                    age_str = f" ({target_date.year - b_yr} yosh)"
                except Exception:
                    pass

            gender_uz = "Erkak" if pt.get("gender") == "male" else ("Ayol" if pt.get("gender") == "female" else "")
            gender_display = f", {gender_uz}" if gender_uz else ""

            lines.append(f"<b>{idx}. 👤 {pt['patient_name']}</b>{age_str}{gender_display}")
            lines.append(f"   🆔 ID: <code>{pt['patient_code']}</code> | 📞 {pt.get('phone') or 'Tel kiritilmagan'}")
            lines.append(f"   🛏 Palata: <b>{pt['room_number']}-xona (Krovat: {pt['bed_code']})</b>")
            lines.append(f"   🩺 Shifokor: <b>{pt['doctor_name'] or 'Belgilanmagan'}</b>")
            lines.append(f"   📅 Davolanish: {pt['start_date']} — {pt['planned_end_date']} ({pt.get('total_days', 1)} kun)")
            lines.append(f"   🏨 Dastur: <code>{pt['program_type']}</code>")

            diag = hist.get("diagnosis_primary")
            if diag:
                lines.append(f"   🩺 Tashxis: {diag}")

            condition = note.get("patient_condition")
            if condition:
                cond_uz = {
                    "satisfactory": "Qoniqarli",
                    "moderate": "O'rtacha",
                    "severe": "Og'ir",
                    "critical": "O'ta og'ir"
                }.get(condition, condition)
                lines.append(f"   ❤️ Holati: <b>{cond_uz}</b>")

            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📊 Jami statsionar bemorlar: <b>{len(inpatients)} nafar</b>")

    msg_text = "\n".join(lines)
    return send_telegram_message(TOPIC_DOCTORS, msg_text)


# -----------------------------------------------------------------------------
# 3. KUCHAYTIRILGAN BUXGALTERIYA HISOBOTLARI (Topic: 6)
# -----------------------------------------------------------------------------

def fetch_comprehensive_financial_data(target_date=None):
    """
    Klinikaning barcha moliyaviy ma'lumotlarini bazadan yig'ish:
    1. Tranzaksiyalar (Kirim / Chiqim)
    2. Bemorlar hisob-fakturalari (Invoices, Debtors, Net amount, Payments)
    3. Ko'rsatilgan xizmatlar va muolajalar (Invoice Items)
    4. Dorixona va ombor qoldig'i (Medications stock valuation)
    5. Xodimlar maosh fondi (Staff & Salaries)
    6. Umumiy KPI ko'rsatkichlari (v_daily_hospital_kpi)
    """
    if target_date is None:
        target_date = datetime.date.today()
    elif isinstance(target_date, str):
        target_date = datetime.date.fromisoformat(target_date)

    iso_date = target_date.isoformat()

    conn = db.get_db()
    cur = conn.cursor()

    # 1. Hospital KPI View
    cur.execute("SELECT * FROM v_daily_hospital_kpi")
    kpi_row = cur.fetchone() or {}
    kpi = dict(kpi_row)

    # 2. Accounting Transactions
    cur.execute("SELECT * FROM accounting_transactions ORDER BY transaction_date DESC, created_at DESC")
    all_transactions = [dict(r) for r in cur.fetchall()]
    today_transactions = [t for t in all_transactions if str(t.get("transaction_date")) == iso_date]

    # 3. Inpatient Financial Ledger (Invoices + Balances + Bed Info)
    cur.execute("SELECT * FROM v_financial_ledger ORDER BY created_at DESC")
    inpatient_ledger = [dict(r) for r in cur.fetchall()]

    # 4. Detailed Invoice Items
    cur.execute("""
        SELECT ii.*, inv.admission_id, p.full_name AS patient_name, p.patient_code
        FROM invoice_items ii
        JOIN invoices inv ON ii.invoice_id = inv.id
        JOIN admissions a ON inv.admission_id = a.id
        JOIN patients p ON a.patient_id = p.id
        ORDER BY ii.created_at DESC
    """)
    invoice_items = [dict(r) for r in cur.fetchall()]

    # 5. Medications Catalog (Pharmacy Valuation)
    cur.execute("""
        SELECT *, (stock_quantity * unit_price) AS total_value,
               (stock_quantity <= min_stock_level) AS is_low_stock
        FROM medications_catalog
        ORDER BY is_low_stock DESC, name ASC
    """)
    pharmacy_stock = [dict(r) for r in cur.fetchall()]

    # 6. Staff & Payroll
    cur.execute("SELECT * FROM staff ORDER BY role, full_name")
    staff_list = [dict(r) for r in cur.fetchall()]

    conn.close()

    # Calculate Cash Flow
    income_today = sum(float(t.get("amount") or 0) for t in today_transactions if t.get("transaction_type") == "income")
    expense_today = sum(float(t.get("amount") or 0) for t in today_transactions if t.get("transaction_type") == "expense")
    net_today = income_today - expense_today

    income_all = sum(float(t.get("amount") or 0) for t in all_transactions if t.get("transaction_type") == "income")
    expense_all = sum(float(t.get("amount") or 0) for t in all_transactions if t.get("transaction_type") == "expense")
    net_all = income_all - expense_all

    # Payment Methods Breakdown (All-time and today)
    methods_today = {}
    for t in today_transactions:
        m = t.get("payment_method") or "Boshqa"
        amt = float(t.get("amount") or 0)
        methods_today[m] = methods_today.get(m, 0.0) + amt

    methods_all = {}
    for t in all_transactions:
        m = t.get("payment_method") or "Boshqa"
        amt = float(t.get("amount") or 0)
        methods_all[m] = methods_all.get(m, 0.0) + amt

    # Debtors calculation
    total_billed = sum(float(inv.get("total_billed") or 0) for inv in inpatient_ledger)
    total_discounts = sum(float(inv.get("discount_amount") or 0) for inv in inpatient_ledger)
    total_net_invoiced = sum(float(inv.get("net_amount") or 0) for inv in inpatient_ledger)
    total_paid_invoices = sum(float(inv.get("total_paid") or 0) for inv in inpatient_ledger)
    total_debt = sum(float(inv.get("balance_due") or 0) for inv in inpatient_ledger)

    # Pharmacy Valuation
    pharmacy_total_value = sum(float(m.get("total_value") or 0) for m in pharmacy_stock)
    pharmacy_low_count = sum(1 for m in pharmacy_stock if m.get("is_low_stock"))

    # Payroll Total
    payroll_monthly_total = sum(float(s.get("salary_base") or 0) for s in staff_list)

    return {
        "target_date": target_date,
        "date_str": target_date.strftime("%d.%m.%Y"),
        "iso_date": iso_date,
        "kpi": kpi,
        "all_transactions": all_transactions,
        "today_transactions": today_transactions,
        "inpatient_ledger": inpatient_ledger,
        "invoice_items": invoice_items,
        "pharmacy_stock": pharmacy_stock,
        "staff_list": staff_list,
        "income_today": income_today,
        "expense_today": expense_today,
        "net_today": net_today,
        "income_all": income_all,
        "expense_all": expense_all,
        "net_all": net_all,
        "methods_today": methods_today,
        "methods_all": methods_all,
        "total_billed": total_billed,
        "total_discounts": total_discounts,
        "total_net_invoiced": total_net_invoiced,
        "total_paid_invoices": total_paid_invoices,
        "total_debt": total_debt,
        "pharmacy_total_value": pharmacy_total_value,
        "pharmacy_low_count": pharmacy_low_count,
        "payroll_monthly_total": payroll_monthly_total,
    }


def generate_comprehensive_excel(data, output_path):
    """
    Buxgalteriya uchun 5 varaqli professional Excel auditi:
    1. Moliyaviy_KPI — Barcha kassa, tushum, qarzlar, ombor va maosh xulosasi
    2. Kassa_Kirim_Chiqim — Barcha kassa operatsiyalari reyestri
    3. Bemorlar_Hisobi — Invoices, Bemorlar hisob-fakturalari va qarzlar
    4. Xizmatlar_Tafsiloti — Barcha ko'rsatilgan statsionar va tibbiy xizmatlar
    5. Dorixona_va_Ombor — Dori vositalari, qoldiq va zaxira qiymati
    6. Xodimlar_Maosh_Fondi — Shtat jadvali va oylik maosh fondi
    """
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    NAVY = "1E3A8A"
    BLUE = "2563EB"
    LIGHT_BLUE = "EFF6FF"
    GREEN = "059669"
    RED = "DC2626"
    GRAY_BG = "F3F4F6"
    CARD_BG = "F8FAFC"

    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    # =========================================================================
    # SHEET 1: MOLIYAVIY_KPI
    # =========================================================================
    ws1 = wb.active
    ws1.title = "Moliyaviy_KPI"

    ws1.merge_cells("A1:G1")
    t1 = ws1["A1"]
    t1.value = "FAYZ MEDICAL HOUSE — BOSH MOLIYAVIY AUDIT VA KPI HISOBOTI"
    t1.font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    t1.fill = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
    t1.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 36

    ws1.merge_cells("A2:G2")
    sub1 = ws1["A2"]
    sub1.value = f"Hisobot davri: {data['date_str']} | Yaratildi: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}"
    sub1.font = Font(name="Calibri", size=11, italic=True, color="FFFFFF")
    sub1.fill = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
    sub1.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[2].height = 22

    # KPI Summary Cards Block
    kpi_cards = [
        ("KASSA SOF QOLDIG'I (BUGUN)", f"{format_currency(data['net_today'])} UZS", "DBEAFE", "1D4ED8"),
        ("JAMI TUSHUM (KASSA)", f"{format_currency(data['income_all'])} UZS", "D1FAE5", "047857"),
        ("BEMORLARNING QARZDORLIGI", f"{format_currency(data['total_debt'])} UZS", "FEE2E2", "B91C1C"),
        ("HISOB-FAKTURALAR (NET)", f"{format_currency(data['total_net_invoiced'])} UZS", "FEF3C7", "B45309"),
        ("DORIXONA ZAXIRA QIYMATI", f"{format_currency(data['pharmacy_total_value'])} UZS", "E0E7FF", "3730A3"),
        ("OYLIK MAOSH FONDI", f"{format_currency(data['payroll_monthly_total'])} UZS", "EDE9FE", "6D28D9"),
    ]

    ws1.row_dimensions[4].height = 20
    ws1.row_dimensions[5].height = 26
    ws1.row_dimensions[7].height = 20
    ws1.row_dimensions[8].height = 26

    positions = [
        ("A", "B", 4, 5), ("C", "D", 4, 5), ("E", "G", 4, 5),
        ("A", "B", 7, 8), ("C", "D", 7, 8), ("E", "G", 7, 8),
    ]

    for (c_title, c_val, bg_col, text_col), (c_start, c_end, r_top, r_val) in zip(kpi_cards, positions):
        ws1.merge_cells(f"{c_start}{r_top}:{c_end}{r_top}")
        ws1.merge_cells(f"{c_start}{r_val}:{c_end}{r_val}")
        
        c1 = ws1[f"{c_start}{r_top}"]
        c1.value = c_title
        c1.font = Font(name="Calibri", size=9.5, bold=True, color=text_col)
        c1.alignment = Alignment(horizontal="center", vertical="center")
        c1.fill = PatternFill(start_color=bg_col, fill_type="solid")

        c2 = ws1[f"{c_start}{r_val}"]
        c2.value = c_val
        c2.font = Font(name="Calibri", size=13, bold=True, color=text_col)
        c2.alignment = Alignment(horizontal="center", vertical="center")
        c2.fill = PatternFill(start_color=bg_col, fill_type="solid")

    # Payment Methods Breakdown Table
    ws1.cell(row=10, column=1, value="TO'LOV KANALLARI BO'YICHA TAQSIMOT (KASSA TUSHUMI)").font = Font(name="Calibri", size=12, bold=True, color=NAVY)
    headers_pm = ["To'lov Usuli", "Bugungi Tushum (UZS)", "Umumiy Tushum (UZS)", "Ulush (%)"]
    ws1.row_dimensions[11].height = 24
    for idx, h in enumerate(headers_pm, start=1):
        cell = ws1.cell(row=11, column=idx, value=h)
        cell.font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=BLUE, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    pm_labels = {
        "terminal": "💳 Terminal (Bank kartalari)",
        "cash": "💵 Naqd pul (Kassa)",
        "card_transfer": "📲 Karta o'tkazma",
        "payme_click": "📱 Click / Payme",
        "bank_wire": "🏦 Bank hisob raqami"
    }

    r_pm = 12
    all_methods_keys = set(list(data["methods_today"].keys()) + list(data["methods_all"].keys()))
    if not all_methods_keys:
        all_methods_keys = ["terminal", "cash"]

    for m_k in all_methods_keys:
        m_today_val = data["methods_today"].get(m_k, 0.0)
        m_all_val = data["methods_all"].get(m_k, 0.0)
        share = (m_all_val / data["income_all"] * 100) if data["income_all"] > 0 else 0.0

        vals = [pm_labels.get(m_k, m_k.title()), m_today_val, m_all_val, f"{share:.1f}%"]
        for c_i, v in enumerate(vals, start=1):
            cell = ws1.cell(row=r_pm, column=c_i, value=v)
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            if c_i in (2, 3):
                cell.number_format = '#,##0'
                cell.alignment = Alignment(horizontal="right")
                cell.font = Font(name="Calibri", size=10, bold=True)
            elif c_i == 4:
                cell.alignment = Alignment(horizontal="center")
        ws1.row_dimensions[r_pm].height = 20
        r_pm += 1

    # Inpatient Stats
    r_pm += 1
    ws1.cell(row=r_pm, column=1, value="STATSIONAR VA O'RINLARNING MOLIYAVIY KO'RSATKICHLARI").font = Font(name="Calibri", size=12, bold=True, color=NAVY)
    r_pm += 1
    ws1.row_dimensions[r_pm].height = 24
    stat_heads = ["Ko'rsatkich", "Qiymat"]
    for c_i, h in enumerate(stat_heads, start=1):
        cell = ws1.cell(row=r_pm, column=c_i, value=h)
        cell.font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=BLUE, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    r_pm += 1
    kpi_stats = [
        ("Jami o'rinlar soni (Beds capacity)", f"{data['kpi'].get('total_beds', 14)} ta"),
        ("Faol hisob ochilgan bemorlar soni", f"{len(data['inpatient_ledger'])} nafar"),
        ("Bemorlarga hisoblangan xizmatlar (Brutto)", f"{format_currency(data['total_billed'])} UZS"),
        ("Taqdim etilgan chegirmalar summasi", f"{format_currency(data['total_discounts'])} UZS"),
        ("Bemorlardan qabul qilingan to'lovlar", f"{format_currency(data['total_paid_invoices'])} UZS"),
        ("Kutilayotgan debitor qarzdorlik", f"{format_currency(data['total_debt'])} UZS"),
    ]
    for s_label, s_val in kpi_stats:
        cell1 = ws1.cell(row=r_pm, column=1, value=s_label)
        cell2 = ws1.cell(row=r_pm, column=2, value=s_val)
        cell1.font = Font(name="Calibri", size=10)
        cell2.font = Font(name="Calibri", size=10, bold=True)
        cell1.border = thin_border
        cell2.border = thin_border
        ws1.row_dimensions[r_pm].height = 20
        r_pm += 1

    for col in ws1.columns:
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = 24
    ws1.column_dimensions['A'].width = 38
    ws1.column_dimensions['B'].width = 28

    # =========================================================================
    # SHEET 2: KASSA_KIRIM_CHIQIM
    # =========================================================================
    ws2 = wb.create_sheet("Kassa_Kirim_Chiqim")
    ws2.row_dimensions[1].height = 28
    ws2.merge_cells("A1:H1")
    t2 = ws2["A1"]
    t2.value = "KASSA VA HISOB-KITOB TRANZAKSIYALARI JURNALI"
    t2.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    t2.fill = PatternFill(start_color=BLUE, fill_type="solid")
    t2.alignment = Alignment(horizontal="center", vertical="center")

    headers_tx = ["№", "Tranzaksiya ID", "Sana", "Turi", "Kategoriya", "To'lov Usuli", "Summa (UZS)", "Tavsif"]
    ws2.row_dimensions[2].height = 24
    for c_i, h in enumerate(headers_tx, start=1):
        cell = ws2.cell(row=2, column=c_i, value=h)
        cell.font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=NAVY, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    r_tx = 3
    for idx, tx in enumerate(data["all_transactions"], start=1):
        ttype = "KIRIM" if tx.get("transaction_type") == "income" else "CHIQIM"
        amount = float(tx.get("amount") or 0)
        vals = [
            idx, tx.get("id"), str(tx.get("transaction_date")), ttype,
            tx.get("category"), tx.get("payment_method"), amount, tx.get("description")
        ]
        for c_i, val in enumerate(vals, start=1):
            cell = ws2.cell(row=r_tx, column=c_i, value=val)
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            if c_i == 1:
                cell.alignment = Alignment(horizontal="center")
            elif c_i == 4:
                cell.alignment = Alignment(horizontal="center")
                cell.font = Font(name="Calibri", size=10, bold=True, color="047857" if ttype == "KIRIM" else "DC2626")
            elif c_i == 7:
                cell.number_format = '#,##0'
                cell.alignment = Alignment(horizontal="right")
                cell.font = Font(name="Calibri", size=10, bold=True)
        ws2.row_dimensions[r_tx].height = 20
        r_tx += 1

    # Total row
    ws2.merge_cells(start_row=r_tx, start_column=1, end_row=r_tx, end_column=6)
    t_lbl = ws2.cell(row=r_tx, column=1, value="JAMI SOF QOLDIQ:")
    t_lbl.font = Font(name="Calibri", size=11, bold=True)
    t_lbl.alignment = Alignment(horizontal="right", vertical="center")
    t_lbl.fill = PatternFill(start_color=GRAY_BG, fill_type="solid")
    
    t_val = ws2.cell(row=r_tx, column=7, value=data["net_all"])
    t_val.font = Font(name="Calibri", size=11, bold=True, color=NAVY)
    t_val.number_format = '#,##0'
    t_val.alignment = Alignment(horizontal="right", vertical="center")
    t_val.fill = PatternFill(start_color=GRAY_BG, fill_type="solid")
    for col in range(1, 9):
        ws2.cell(row=r_tx, column=col).border = thin_border
    ws2.row_dimensions[r_tx].height = 24

    ws2.column_dimensions['A'].width = 6
    ws2.column_dimensions['B'].width = 24
    ws2.column_dimensions['C'].width = 14
    ws2.column_dimensions['D'].width = 12
    ws2.column_dimensions['E'].width = 22
    ws2.column_dimensions['F'].width = 18
    ws2.column_dimensions['G'].width = 20
    ws2.column_dimensions['H'].width = 40

    # =========================================================================
    # SHEET 3: BEMORLAR_HISOBI (INVOICES & DEBTORS)
    # =========================================================================
    ws3 = wb.create_sheet("Bemorlar_Hisobi")
    ws3.row_dimensions[1].height = 28
    ws3.merge_cells("A1:K1")
    t3 = ws3["A1"]
    t3.value = "BEMORLAR HISOB-FAKTURALARI VA QARZDORLIKLAR REYESTRI"
    t3.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    t3.fill = PatternFill(start_color=NAVY, fill_type="solid")
    t3.alignment = Alignment(horizontal="center", vertical="center")

    headers_inv = [
        "№", "Bemor Kodi", "F.I.Sh", "Palata-O'rin", "Dastur Turi",
        "Jami Billed", "Chegirma", "Sof Summa (Net)", "To'langan", "Qarzdorlik", "Holati"
    ]
    ws3.row_dimensions[2].height = 24
    for c_i, h in enumerate(headers_inv, start=1):
        cell = ws3.cell(row=2, column=c_i, value=h)
        cell.font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=BLUE, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    r_inv = 3
    for idx, inv in enumerate(data["inpatient_ledger"], start=1):
        st_uz = {
            "paid": "To'langan",
            "partial": "Qisman to'langan",
            "unpaid": "To'lanmagan",
            "refund_due": "Qaytarish kerak",
            "refunded": "Qaytarilgan"
        }.get(inv.get("payment_status"), inv.get("payment_status"))

        vals = [
            idx,
            inv.get("patient_code"),
            inv.get("patient_name"),
            f"{inv.get('room_number')}-{inv.get('bed_code')}",
            inv.get("program_type"),
            float(inv.get("total_billed") or 0),
            float(inv.get("discount_amount") or 0),
            float(inv.get("net_amount") or 0),
            float(inv.get("total_paid") or 0),
            float(inv.get("balance_due") or 0),
            st_uz
        ]
        for c_i, val in enumerate(vals, start=1):
            cell = ws3.cell(row=r_inv, column=c_i, value=val)
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            if c_i in (1, 2, 4, 11):
                cell.alignment = Alignment(horizontal="center")
            elif c_i in (6, 7, 8, 9, 10):
                cell.number_format = '#,##0'
                cell.alignment = Alignment(horizontal="right")
                if c_i == 10 and val > 0:
                    cell.font = Font(name="Calibri", size=10, bold=True, color="B91C1C")
                elif c_i == 9:
                    cell.font = Font(name="Calibri", size=10, bold=True, color="047857")
        ws3.row_dimensions[r_inv].height = 20
        r_inv += 1

    # Total row for invoices
    ws3.merge_cells(start_row=r_inv, start_column=1, end_row=r_inv, end_column=5)
    tot_lbl = ws3.cell(row=r_inv, column=1, value="JAMI REYESTR:")
    tot_lbl.font = Font(name="Calibri", size=11, bold=True)
    tot_lbl.alignment = Alignment(horizontal="right", vertical="center")
    tot_lbl.fill = PatternFill(start_color=GRAY_BG, fill_type="solid")

    tot_cols = [
        (6, data["total_billed"]),
        (7, data["total_discounts"]),
        (8, data["total_net_invoiced"]),
        (9, data["total_paid_invoices"]),
        (10, data["total_debt"])
    ]
    for c_idx, c_val in tot_cols:
        cell = ws3.cell(row=r_inv, column=c_idx, value=c_val)
        cell.font = Font(name="Calibri", size=11, bold=True, color=NAVY)
        cell.number_format = '#,##0'
        cell.alignment = Alignment(horizontal="right", vertical="center")
        cell.fill = PatternFill(start_color=GRAY_BG, fill_type="solid")

    for col in range(1, 12):
        ws3.cell(row=r_inv, column=col).border = thin_border
    ws3.row_dimensions[r_inv].height = 24

    ws3.column_dimensions['A'].width = 6
    ws3.column_dimensions['B'].width = 18
    ws3.column_dimensions['C'].width = 24
    ws3.column_dimensions['D'].width = 14
    ws3.column_dimensions['E'].width = 20
    ws3.column_dimensions['F'].width = 18
    ws3.column_dimensions['G'].width = 16
    ws3.column_dimensions['H'].width = 18
    ws3.column_dimensions['I'].width = 18
    ws3.column_dimensions['J'].width = 18
    ws3.column_dimensions['K'].width = 18

    # =========================================================================
    # SHEET 4: XIZMATLAR_TAFSILOTI
    # =========================================================================
    ws4 = wb.create_sheet("Xizmatlar_Tafsiloti")
    ws4.row_dimensions[1].height = 28
    ws4.merge_cells("A1:G1")
    t4 = ws4["A1"]
    t4.value = "BEMORLARGA KO'RSATILGAN XIZMATLAR VA SARFLOVLAR REYESTRI"
    t4.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    t4.fill = PatternFill(start_color=BLUE, fill_type="solid")
    t4.alignment = Alignment(horizontal="center", vertical="center")

    headers_items = ["№", "Bemor F.I.Sh", "Xizmat Nomi", "Kategoriya", "Miqdori", "Birlik Narxi (UZS)", "Jami Summa (UZS)"]
    ws4.row_dimensions[2].height = 24
    for c_i, h in enumerate(headers_items, start=1):
        cell = ws4.cell(row=2, column=c_i, value=h)
        cell.font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=NAVY, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    r_it = 3
    for idx, it in enumerate(data["invoice_items"], start=1):
        amt = float(it.get("quantity", 1) or 1) * float(it.get("unit_price", 0) or 0)
        vals = [
            idx,
            it.get("patient_name"),
            it.get("service_name"),
            it.get("item_type"),
            float(it.get("quantity") or 1),
            float(it.get("unit_price") or 0),
            amt
        ]
        for c_i, val in enumerate(vals, start=1):
            cell = ws4.cell(row=r_it, column=c_i, value=val)
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            if c_i == 1:
                cell.alignment = Alignment(horizontal="center")
            elif c_i in (5, 6, 7):
                cell.number_format = '#,##0'
                cell.alignment = Alignment(horizontal="right")
        ws4.row_dimensions[r_it].height = 20
        r_it += 1

    ws4.column_dimensions['A'].width = 6
    ws4.column_dimensions['B'].width = 24
    ws4.column_dimensions['C'].width = 36
    ws4.column_dimensions['D'].width = 16
    ws4.column_dimensions['E'].width = 12
    ws4.column_dimensions['F'].width = 18
    ws4.column_dimensions['G'].width = 20

    # =========================================================================
    # SHEET 5: DORIXONA_VA_OMBOR
    # =========================================================================
    ws5 = wb.create_sheet("Dorixona_va_Ombor")
    ws5.row_dimensions[1].height = 28
    ws5.merge_cells("A1:H1")
    t5 = ws5["A1"]
    t5.value = "DORIXONA VA OMBOR ZAXIRALARI BALANS QIYMATI"
    t5.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    t5.fill = PatternFill(start_color=NAVY, fill_type="solid")
    t5.alignment = Alignment(horizontal="center", vertical="center")

    headers_med = ["№", "Dori Nomi", "Kategoriya", "Formasi", "Qoldiq (Soni)", "Min Me'yor", "Birlik Narxi (UZS)", "Zaxira Qiymati (UZS)"]
    ws5.row_dimensions[2].height = 24
    for c_i, h in enumerate(headers_med, start=1):
        cell = ws5.cell(row=2, column=c_i, value=h)
        cell.font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=BLUE, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    r_med = 3
    for idx, med in enumerate(data["pharmacy_stock"], start=1):
        tot_val = float(med.get("total_value") or 0)
        vals = [
            idx, med.get("name"), med.get("category"), med.get("form"),
            med.get("stock_quantity"), med.get("min_stock_level"),
            float(med.get("unit_price") or 0), tot_val
        ]
        for c_i, val in enumerate(vals, start=1):
            cell = ws5.cell(row=r_med, column=c_i, value=val)
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            if c_i == 1:
                cell.alignment = Alignment(horizontal="center")
            elif c_i in (5, 6):
                cell.alignment = Alignment(horizontal="center")
                if c_i == 5 and med.get("is_low_stock"):
                    cell.font = Font(name="Calibri", size=10, bold=True, color="DC2626")
            elif c_i in (7, 8):
                cell.number_format = '#,##0'
                cell.alignment = Alignment(horizontal="right")
                if c_i == 8:
                    cell.font = Font(name="Calibri", size=10, bold=True)
        ws5.row_dimensions[r_med].height = 20
        r_med += 1

    # Total row
    ws5.merge_cells(start_row=r_med, start_column=1, end_row=r_med, end_column=7)
    med_tot = ws5.cell(row=r_med, column=1, value="JAMI OMBOR ZAXIRA QIYMATI:")
    med_tot.font = Font(name="Calibri", size=11, bold=True)
    med_tot.alignment = Alignment(horizontal="right", vertical="center")
    med_tot.fill = PatternFill(start_color=GRAY_BG, fill_type="solid")

    med_val_cell = ws5.cell(row=r_med, column=8, value=data["pharmacy_total_value"])
    med_val_cell.font = Font(name="Calibri", size=11, bold=True, color=NAVY)
    med_val_cell.number_format = '#,##0'
    med_val_cell.alignment = Alignment(horizontal="right", vertical="center")
    med_val_cell.fill = PatternFill(start_color=GRAY_BG, fill_type="solid")
    for col in range(1, 9):
        ws5.cell(row=r_med, column=col).border = thin_border
    ws5.row_dimensions[r_med].height = 24

    ws5.column_dimensions['A'].width = 6
    ws5.column_dimensions['B'].width = 30
    ws5.column_dimensions['C'].width = 20
    ws5.column_dimensions['D'].width = 18
    ws5.column_dimensions['E'].width = 14
    ws5.column_dimensions['F'].width = 14
    ws5.column_dimensions['G'].width = 18
    ws5.column_dimensions['H'].width = 22

    # =========================================================================
    # SHEET 6: XODIMLAR_MAOSH_FONDI
    # =========================================================================
    ws6 = wb.create_sheet("Xodimlar_Maosh_Fondi")
    ws6.row_dimensions[1].height = 28
    ws6.merge_cells("A1:F1")
    t6 = ws6["A1"]
    t6.value = "KLINIKA SHTAT JADVALI VA OYLIK MAOSH FONDI"
    t6.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    t6.fill = PatternFill(start_color=NAVY, fill_type="solid")
    t6.alignment = Alignment(horizontal="center", vertical="center")

    headers_stf = ["№", "Xodim ID", "F.I.Sh", "Lavozimi", "Mutaxassisligi", "Baza Oylik Maoshi (UZS)"]
    ws6.row_dimensions[2].height = 24
    for c_i, h in enumerate(headers_stf, start=1):
        cell = ws6.cell(row=2, column=c_i, value=h)
        cell.font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=BLUE, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    r_st = 3
    for idx, st in enumerate(data["staff_list"], start=1):
        vals = [
            idx, st.get("id"), st.get("full_name"), st.get("role"),
            st.get("specialty"), float(st.get("salary_base") or 0)
        ]
        for c_i, val in enumerate(vals, start=1):
            cell = ws6.cell(row=r_st, column=c_i, value=val)
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            if c_i in (1, 2, 4):
                cell.alignment = Alignment(horizontal="center")
            elif c_i == 6:
                cell.number_format = '#,##0'
                cell.alignment = Alignment(horizontal="right")
                cell.font = Font(name="Calibri", size=10, bold=True)
        ws6.row_dimensions[r_st].height = 20
        r_st += 1

    # Total row
    ws6.merge_cells(start_row=r_st, start_column=1, end_row=r_st, end_column=5)
    st_tot = ws6.cell(row=r_st, column=1, value="JAMI OYLIK MAOSH FONDI:")
    st_tot.font = Font(name="Calibri", size=11, bold=True)
    st_tot.alignment = Alignment(horizontal="right", vertical="center")
    st_tot.fill = PatternFill(start_color=GRAY_BG, fill_type="solid")

    st_val_cell = ws6.cell(row=r_st, column=6, value=data["payroll_monthly_total"])
    st_val_cell.font = Font(name="Calibri", size=11, bold=True, color=NAVY)
    st_val_cell.number_format = '#,##0'
    st_val_cell.alignment = Alignment(horizontal="right", vertical="center")
    st_val_cell.fill = PatternFill(start_color=GRAY_BG, fill_type="solid")
    for col in range(1, 7):
        ws6.cell(row=r_st, column=col).border = thin_border
    ws6.row_dimensions[r_st].height = 24

    ws6.column_dimensions['A'].width = 6
    ws6.column_dimensions['B'].width = 16
    ws6.column_dimensions['C'].width = 34
    ws6.column_dimensions['D'].width = 18
    ws6.column_dimensions['E'].width = 30
    ws6.column_dimensions['F'].width = 24

    wb.save(output_path)
    return output_path


def generate_comprehensive_pdf(data, output_path):
    """
    Kengaytirilgan rasmiy ko'p sahifali PDF moliyaviy audit hisoboti.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=26,
        leftMargin=26,
        topMargin=26,
        bottomMargin=26
    )

    PRIMARY = colors.HexColor('#1E3A8A')
    HEADER_BLUE = colors.HexColor('#2563EB')
    DARK = colors.HexColor('#0F172A')
    MUTED = colors.HexColor('#475569')
    LIGHT_BG = colors.HexColor('#F8FAFC')
    LINE_COLOR = colors.HexColor('#CBD5E1')

    styles = getSampleStyleSheet()
    clinic_style = ParagraphStyle('ClStyle', fontName='Helvetica-Bold', fontSize=15, leading=18, textColor=PRIMARY, alignment=1)
    sub_style = ParagraphStyle('SbStyle', fontName='Helvetica', fontSize=7.5, leading=10, textColor=MUTED, alignment=1)
    doc_title_style = ParagraphStyle('DocTStyle', fontName='Helvetica-Bold', fontSize=12.5, leading=15, textColor=PRIMARY, alignment=1)
    sec_title = ParagraphStyle('SecT', fontName='Helvetica-Bold', fontSize=9.5, leading=12, textColor=PRIMARY)
    
    kpi_title_p = ParagraphStyle('KPIT', fontName='Helvetica-Bold', fontSize=8, leading=10, alignment=1)
    kpi_val_p = ParagraphStyle('KPIV', fontName='Helvetica-Bold', fontSize=11, leading=13, alignment=1)

    th_style = ParagraphStyle('TH', fontName='Helvetica-Bold', fontSize=7.5, leading=9.5, textColor=colors.white, alignment=1)
    td_style = ParagraphStyle('TD', fontName='Helvetica', fontSize=7, leading=9, textColor=DARK)
    td_bold = ParagraphStyle('TDB', fontName='Helvetica-Bold', fontSize=7, leading=9, textColor=DARK)
    td_right = ParagraphStyle('TDR', fontName='Helvetica-Bold', fontSize=7, leading=9, textColor=DARK, alignment=2)

    story = []

    # ==================== PAGE 1 ====================
    # Header
    story.append(Paragraph("FAYZ MEDICAL HOUSE", clinic_style))
    story.append(Spacer(1, 2))
    story.append(Paragraph("Toshkent sh., Chilonzor tumani, Muqimiy ko'chasi 44-uy | Tel: +998 71 200-44-00", sub_style))
    story.append(Paragraph("Litsenziya: № 14285-L Toshkent Sh. SSV | INN: 309812456 | H/r: 20208000900123456001", sub_style))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceAfter=8))

    story.append(Paragraph("KENGAYTIRILGAN KUNLIK MOLIYAVIY AUDIT VA BUXGALTERIYA HISOBOTI", doc_title_style))
    story.append(Spacer(1, 2))
    story.append(Paragraph(f"Sana: <b>{data['date_str']}</b> | Shakllantirilgan vaqt: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}", sub_style))
    story.append(Spacer(1, 10))

    # 6 KPI Cards Table (2 rows x 3 cols)
    kpi_rows = [
        [
            Paragraph("<font color='#047857'>KASSA TUSHUMI (BUGUN)</font>", kpi_title_p),
            Paragraph("<font color='#B91C1C'>BEMORLAR QARZDORLIGI</font>", kpi_title_p),
            Paragraph("<font color='#1D4ED8'>SOF HISOB-FAKTURA (NET)</font>", kpi_title_p),
        ],
        [
            Paragraph(f"<font color='#047857'>+{format_currency(data['income_today'])} UZS</font>", kpi_val_p),
            Paragraph(f"<font color='#B91C1C'>{format_currency(data['total_debt'])} UZS</font>", kpi_val_p),
            Paragraph(f"<font color='#1D4ED8'>{format_currency(data['total_net_invoiced'])} UZS</font>", kpi_val_p),
        ],
        [
            Paragraph("<font color='#3730A3'>DORIXONA OMBOR ZAXIRASI</font>", kpi_title_p),
            Paragraph("<font color='#6D28D9'>OYLIK MAOSH FONDI</font>", kpi_title_p),
            Paragraph("<font color='#0F766E'>STATSIONAR O'RINLAR</font>", kpi_title_p),
        ],
        [
            Paragraph(f"<font color='#3730A3'>{format_currency(data['pharmacy_total_value'])} UZS</font>", kpi_val_p),
            Paragraph(f"<font color='#6D28D9'>{format_currency(data['payroll_monthly_total'])} UZS</font>", kpi_val_p),
            Paragraph(f"<font color='#0F766E'>{data['kpi'].get('total_beds', 14)} ta o'rin</font>", kpi_val_p),
        ]
    ]

    kpi_t = Table(kpi_rows, colWidths=[175, 180, 185])
    kpi_t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 1), colors.HexColor('#D1FAE5')),
        ('BACKGROUND', (1, 0), (1, 1), colors.HexColor('#FEE2E2')),
        ('BACKGROUND', (2, 0), (2, 1), colors.HexColor('#FEF3C7')),
        ('BACKGROUND', (0, 2), (0, 3), colors.HexColor('#E0E7FF')),
        ('BACKGROUND', (1, 2), (1, 3), colors.HexColor('#EDE9FE')),
        ('BACKGROUND', (2, 2), (2, 3), colors.HexColor('#CCFBF1')),
        ('BOX', (0, 0), (0, 1), 0.5, colors.HexColor('#10B981')),
        ('BOX', (1, 0), (1, 1), 0.5, colors.HexColor('#EF4444')),
        ('BOX', (2, 0), (2, 1), 0.5, colors.HexColor('#F59E0B')),
        ('BOX', (0, 2), (0, 3), 0.5, colors.HexColor('#6366F1')),
        ('BOX', (1, 2), (1, 3), 0.5, colors.HexColor('#8B5CF6')),
        ('BOX', (2, 2), (2, 3), 0.5, colors.HexColor('#14B8A6')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(kpi_t)
    story.append(Spacer(1, 12))

    # SECTION 1: INPATIENT BILLING & DEBTORS TABLE
    story.append(Paragraph("<b>1. BEMORLAR HISOB-FAKTURALARI VA QARZDORLIKLAR REYESTRI:</b>", sec_title))
    story.append(Spacer(1, 4))

    inv_heads = [
        Paragraph("№", th_style),
        Paragraph("Bemor F.I.Sh", th_style),
        Paragraph("Kodi", th_style),
        Paragraph("Xona", th_style),
        Paragraph("Brutto Summa", th_style),
        Paragraph("Chegirma", th_style),
        Paragraph("Sof (Net)", th_style),
        Paragraph("To'langan", th_style),
        Paragraph("Qarzdorlik", th_style),
        Paragraph("Holati", th_style)
    ]
    inv_data = [inv_heads]

    for idx, inv in enumerate(data["inpatient_ledger"], start=1):
        st_uz = {
            "paid": "To'langan", "partial": "Qisman", "unpaid": "To'lanmagan"
        }.get(inv.get("payment_status"), inv.get("payment_status"))
        
        inv_data.append([
            Paragraph(str(idx), td_style),
            Paragraph(str(inv.get("patient_name") or ""), td_bold),
            Paragraph(str(inv.get("patient_code") or ""), td_style),
            Paragraph(f"{inv.get('room_number')}-{inv.get('bed_code')}", td_style),
            Paragraph(format_currency(inv.get("total_billed")), td_right),
            Paragraph(format_currency(inv.get("discount_amount")), td_right),
            Paragraph(format_currency(inv.get("net_amount")), td_right),
            Paragraph(f"<font color='#047857'>{format_currency(inv.get('total_paid'))}</font>", td_right),
            Paragraph(f"<font color='#B91C1C'><b>{format_currency(inv.get('balance_due'))}</b></font>", td_right),
            Paragraph(st_uz, td_style),
        ])

    inv_table = Table(inv_data, colWidths=[18, 92, 58, 38, 55, 50, 55, 55, 60, 59])
    inv_t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BLUE),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, LINE_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for r_i in range(1, len(inv_data)):
        if r_i % 2 == 0:
            inv_t_style.append(('BACKGROUND', (0, r_i), (-1, r_i), LIGHT_BG))
    inv_table.setStyle(TableStyle(inv_t_style))
    story.append(inv_table)
    story.append(Spacer(1, 12))

    # SECTION 2: CASH FLOW TRANSACTIONS
    story.append(Paragraph("<b>2. KASSA TRANZAKSIYALARI (KIRIM VA CHIQIMLAR):</b>", sec_title))
    story.append(Spacer(1, 4))

    tx_heads = [
        Paragraph("№", th_style),
        Paragraph("ID", th_style),
        Paragraph("Sana", th_style),
        Paragraph("Turi", th_style),
        Paragraph("Kategoriya", th_style),
        Paragraph("To'lov Usuli", th_style),
        Paragraph("Summa (UZS)", th_style),
        Paragraph("Tavsif", th_style)
    ]
    tx_data = [tx_heads]

    tx_list = data["today_transactions"] if data["today_transactions"] else data["all_transactions"][:10]
    for idx, tx in enumerate(tx_list, start=1):
        ttype = "KIRIM" if tx.get("transaction_type") == "income" else "CHIQIM"
        type_col = "#047857" if ttype == "KIRIM" else "#DC2626"
        tx_data.append([
            Paragraph(str(idx), td_style),
            Paragraph(str(tx.get("id") or ""), td_style),
            Paragraph(str(tx.get("transaction_date") or ""), td_style),
            Paragraph(f"<font color='{type_col}'><b>{ttype}</b></font>", td_style),
            Paragraph(str(tx.get("category") or ""), td_style),
            Paragraph(str(tx.get("payment_method") or ""), td_style),
            Paragraph(format_currency(tx.get("amount")), td_right),
            Paragraph(str(tx.get("description") or ""), td_style),
        ])

    tx_table = Table(tx_data, colWidths=[18, 80, 52, 40, 75, 60, 75, 140])
    tx_t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, LINE_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for r_i in range(1, len(tx_data)):
        if r_i % 2 == 0:
            tx_t_style.append(('BACKGROUND', (0, r_i), (-1, r_i), LIGHT_BG))
    tx_table.setStyle(TableStyle(tx_t_style))
    story.append(tx_table)

    story.append(PageBreak())

    # ==================== PAGE 2 ====================
    story.append(Paragraph("FAYZ MEDICAL HOUSE — MOLIYAVIY AUDIT (DAVOMI)", clinic_style))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceAfter=8))

    # SECTION 3: PHARMACY STOCK VALUATION
    story.append(Paragraph(f"<b>3. DORIXONA VA OMBOR ZAXIRALARI (Jami balans qiymati: {format_currency(data['pharmacy_total_value'])} UZS):</b>", sec_title))
    story.append(Spacer(1, 4))

    med_heads = [
        Paragraph("№", th_style),
        Paragraph("Dori Nomi", th_style),
        Paragraph("Kategoriya", th_style),
        Paragraph("Formasi", th_style),
        Paragraph("Qoldiq", th_style),
        Paragraph("Min Me'yor", th_style),
        Paragraph("Birlik Narxi", th_style),
        Paragraph("Zaxira Qiymati (UZS)", th_style)
    ]
    med_data = [med_heads]

    for idx, med in enumerate(data["pharmacy_stock"], start=1):
        low_flag = "<font color='red'><b>!</b></font> " if med.get("is_low_stock") else ""
        med_data.append([
            Paragraph(str(idx), td_style),
            Paragraph(f"{low_flag}{med.get('name')}", td_bold),
            Paragraph(str(med.get("category") or ""), td_style),
            Paragraph(str(med.get("form") or ""), td_style),
            Paragraph(str(med.get("stock_quantity")), td_style),
            Paragraph(str(med.get("min_stock_level")), td_style),
            Paragraph(format_currency(med.get("unit_price")), td_right),
            Paragraph(format_currency(med.get("total_value")), td_right),
        ])

    med_table = Table(med_data, colWidths=[18, 120, 85, 75, 42, 50, 65, 85])
    med_t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BLUE),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, LINE_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for r_i in range(1, len(med_data)):
        if r_i % 2 == 0:
            med_t_style.append(('BACKGROUND', (0, r_i), (-1, r_i), LIGHT_BG))
    med_table.setStyle(TableStyle(med_t_style))
    story.append(med_table)
    story.append(Spacer(1, 14))

    # SECTION 4: STAFF PAYROLL SUMMARY
    story.append(Paragraph(f"<b>4. SHTAT JADVALI VA OYLIK MAOSH FONDI (Jami: {format_currency(data['payroll_monthly_total'])} UZS):</b>", sec_title))
    story.append(Spacer(1, 4))

    stf_heads = [
        Paragraph("№", th_style),
        Paragraph("Xodim F.I.Sh", th_style),
        Paragraph("Lavozimi / Roli", th_style),
        Paragraph("Mutaxassisligi", th_style),
        Paragraph("Oylik Baza Maoshi (UZS)", th_style)
    ]
    stf_data = [stf_heads]

    for idx, st in enumerate(data["staff_list"][:10], start=1):
        stf_data.append([
            Paragraph(str(idx), td_style),
            Paragraph(str(st.get("full_name") or ""), td_bold),
            Paragraph(str(st.get("role") or ""), td_style),
            Paragraph(str(st.get("specialty") or ""), td_style),
            Paragraph(format_currency(st.get("salary_base")), td_right),
        ])

    stf_table = Table(stf_data, colWidths=[20, 160, 100, 150, 110])
    stf_t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, LINE_COLOR),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for r_i in range(1, len(stf_data)):
        if r_i % 2 == 0:
            stf_t_style.append(('BACKGROUND', (0, r_i), (-1, r_i), LIGHT_BG))
    stf_table.setStyle(TableStyle(stf_t_style))
    story.append(stf_table)
    story.append(Spacer(1, 22))

    # Signatures
    sig_data = [
        [
            Paragraph("<b>Bosh hisobchi:</b> ___________________", td_style),
            Paragraph("<b>Kassa mas'uli:</b> ___________________", td_style),
            Paragraph("<b>Bosh shifokor:</b> ___________________", td_style)
        ],
        [
            Paragraph("<i>(F.I.Sh & Imzo)</i>", sub_style),
            Paragraph("<i>(F.I.Sh & Imzo)</i>", sub_style),
            Paragraph("<i>(F.I.Sh & Imzo)</i>", sub_style)
        ]
    ]
    sig_table = Table(sig_data, colWidths=[180, 180, 180])
    sig_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(sig_table)

    doc.build(story)
    return output_path


def generate_and_send_accounting_report(target_date=None):
    """
    To'liq qamrovli buxgalteriya hisoboti matni + Ko'p varaqli Excel + 2 sahifali PDF
    """
    data = fetch_comprehensive_financial_data(target_date)

    # Text summary formatted for Telegram
    lines = [
        "🏥 <b>FAYZ MEDICAL HOUSE — TO'LIQ KUNLIK MOLIYAVIY HISOBOT</b>",
        f"📅 <b>Sana:</b> {data['date_str']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💰 <b>1. KASSA VA TUSHUMLAR (CASH FLOW):</b>",
        f"🟢 <b>Bugungi kirim:</b> +{format_currency(data['income_today'])} UZS",
        f"🔴 <b>Bugungi chiqim:</b> -{format_currency(data['expense_today'])} UZS",
        f"📈 <b>Bugungi sof qoldiq:</b> <b>{format_currency(data['net_today'])} UZS</b>",
        f"💵 <i>Kassadagi jami yig'ilgan mablag': {format_currency(data['income_all'])} UZS</i>",
        "",
        "💳 <b>2. TO'LOV KANALLARI BO'YICHA:</b>"
    ]

    pm_uz = {
        "terminal": "💳 Terminal (Bank kartalari)",
        "cash": "💵 Naqd pul (Kassa)",
        "card_transfer": "📲 Karta o'tkazma",
        "payme_click": "📱 Click / Payme",
        "bank_wire": "🏦 Bank hisob raqami"
    }

    if data["methods_today"]:
        for m_k, m_v in data["methods_today"].items():
            lines.append(f"• {pm_uz.get(m_k, m_k.title())}: <b>{format_currency(m_v)} UZS</b>")
    else:
        for m_k, m_v in data["methods_all"].items():
            lines.append(f"• {pm_uz.get(m_k, m_k.title())}: {format_currency(m_v)} UZS")

    lines.extend([
        "",
        "🧾 <b>3. BEMORLAR HISOBI & QARZDORLIKLAR (INPATIENT BILLING):</b>",
        f"📋 <b>Hisoblangan umumiy summa:</b> {format_currency(data['total_billed'])} UZS",
        f"🏷 <b>Taqdim etilgan chegirmalar:</b> {format_currency(data['total_discounts'])} UZS",
        f"💼 <b>To'lanishi kerak sof summa (Net):</b> {format_currency(data['total_net_invoiced'])} UZS",
        f"✅ <b>Bemorlardan tushgan to'lovlar:</b> {format_currency(data['total_paid_invoices'])} UZS",
        f"⚠️ <b>Kutilayotgan qarzdorlik (Qarzlar):</b> <b>{format_currency(data['total_debt'])} UZS</b>",
        f"👥 Hisob ochilgan bemorlar soni: <b>{len(data['inpatient_ledger'])} nafar</b>",
        "",
        "💊 <b>4. DORIXONA & OMBOR ZAXIRASI:</b>",
        f"📦 Dori vositalari soni: <b>{len(data['pharmacy_stock'])} nomda</b>",
        f"💎 Ombordagi umumiy zaxira qiymati: <b>{format_currency(data['pharmacy_total_value'])} UZS</b>",
    ])

    if data["pharmacy_low_count"] > 0:
        lines.append(f"⚠️ <i>Diqqat: {data['pharmacy_low_count']} ta dorida zaxira kam qolgan!</i>")

    lines.extend([
        "",
        "👥 <b>5. XODIMLAR MAOSH FONDI:</b>",
        f"💼 Shtatdagi xodimlar: <b>{len(data['staff_list'])} nafar</b>",
        f"📊 Oylik rejaviy maosh fondi: <b>{format_currency(data['payroll_monthly_total'])} UZS</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📎 <b>ILOVADA TO'LIQ AUDIT HUJJATLARI:</b>",
        "1️⃣ <b>Excel (.xlsx):</b> 6 ta bo'limli to'liq tahliliy jadval (KPI, Kassa, Invoices, Xizmatlar, Dorixona, Maosh)",
        "2️⃣ <b>PDF (.pdf):</b> 2 sahifali rasmiy blankali moliyaviy audit hujjati (Muhr va imzo o'rinlari bilan)"
    ])

    msg_text = "\n".join(lines)
    send_telegram_message(TOPIC_ACCOUNTING, msg_text)

    # Reports output
    reports_dir = os.path.join(BASE_DIR, "data", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    excel_path = os.path.join(reports_dir, f"FMH_Moliya_Audit_{data['iso_date']}.xlsx")
    pdf_path = os.path.join(reports_dir, f"FMH_Moliya_Audit_{data['iso_date']}.pdf")

    # Generate documents
    generate_comprehensive_excel(data, excel_path)
    generate_comprehensive_pdf(data, pdf_path)

    # Send Excel Document
    send_telegram_document(
        TOPIC_ACCOUNTING,
        excel_path,
        caption=f"📊 <b>FMH Kengaytirilgan Moliyaviy Audit ({data['date_str']}) — Excel kitobi (6 ta varaq)</b>"
    )

    # Send PDF Document
    send_telegram_document(
        TOPIC_ACCOUNTING,
        pdf_path,
        caption=f"📑 <b>FMH Rasmiy Moliyaviy Audit Hujjati ({data['date_str']}) — A4 PDF formati</b>"
    )

    return True


def generate_and_send_daily_closing_report(target_date=None):
    """
    Soat 21:00 da kun yakuni bo'yicha to'liq kassa va moliyaviy hisobot:
    - Bugungi qabul qilingan tushum (Kirim)
    - Bugungi qilingan xarajatlar (Chiqim)
    - Klinikadagi jami qoldiq (Total clinic money)
    - Naqd pulda qancha (Cash)
    - P2P / Karta o'tkazmada qancha (P2P)
    - Bank hisob raqamida qancha (Bank account & Terminal)
    - Bemorlar qarzdorligi (Debtors)
    - Excel va PDF fayllari ilovasi
    """
    data = fetch_comprehensive_financial_data(target_date)
    conn = db.get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN transaction_type = 'income' AND transaction_date = CURDATE() THEN amount ELSE 0 END), 0) AS today_received,
            COALESCE(SUM(CASE WHEN transaction_type = 'expense' AND transaction_date = CURDATE() THEN amount ELSE 0 END), 0) AS today_spent,
            COALESCE(SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE -amount END), 0) AS total_clinic_money,
            
            -- Balance in Cash (Naqd)
            COALESCE(SUM(CASE 
                WHEN payment_method IN ('cash', 'cash_register') 
                THEN (CASE WHEN transaction_type = 'income' THEN amount ELSE -amount END) 
                ELSE 0 END), 0) AS balance_cash,

            -- Balance in P2P (Karta o'tkazma / Click / Payme)
            COALESCE(SUM(CASE 
                WHEN payment_method IN ('card_transfer', 'p2p', 'payme_click', 'click', 'payme') 
                THEN (CASE WHEN transaction_type = 'income' THEN amount ELSE -amount END) 
                ELSE 0 END), 0) AS balance_p2p,

            -- Balance in Bank Account & Terminal
            COALESCE(SUM(CASE 
                WHEN payment_method IN ('bank_wire', 'terminal', 'bank') 
                THEN (CASE WHEN transaction_type = 'income' THEN amount ELSE -amount END) 
                ELSE 0 END), 0) AS balance_bank,

            -- Today Received by Channel
            COALESCE(SUM(CASE 
                WHEN payment_method IN ('cash', 'cash_register') AND transaction_type = 'income' AND transaction_date = CURDATE() 
                THEN amount ELSE 0 END), 0) AS today_received_cash,

            COALESCE(SUM(CASE 
                WHEN payment_method IN ('card_transfer', 'p2p', 'payme_click', 'click', 'payme') AND transaction_type = 'income' AND transaction_date = CURDATE() 
                THEN amount ELSE 0 END), 0) AS today_received_p2p,

            COALESCE(SUM(CASE 
                WHEN payment_method IN ('bank_wire', 'terminal', 'bank') AND transaction_type = 'income' AND transaction_date = CURDATE() 
                THEN amount ELSE 0 END), 0) AS today_received_bank

        FROM accounting_transactions
    """)
    totals_row = cur.fetchone() or {}
    conn.close()

    today_received = float(totals_row.get('today_received', 0))
    today_spent = float(totals_row.get('today_spent', 0))
    today_net = today_received - today_spent
    total_clinic_money = float(totals_row.get('total_clinic_money', 0))
    balance_cash = float(totals_row.get('balance_cash', 0))
    balance_p2p = float(totals_row.get('balance_p2p', 0))
    balance_bank = float(totals_row.get('balance_bank', 0))
    today_received_cash = float(totals_row.get('today_received_cash', 0))
    today_received_p2p = float(totals_row.get('today_received_p2p', 0))
    today_received_bank = float(totals_row.get('today_received_bank', 0))

    lines = [
        "🌙 <b>FAYZ MEDICAL HOUSE — KUNLIK KASSA VA MOLIYA YAKUNI (21:00)</b>",
        f"📅 <b>Sana:</b> {data['date_str']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📊 <b>1. BUGUNGI KUN BO'YICHA HARAKAT:</b>",
        f"🟢 <b>Qabul qilingan jami tushum:</b> <b>+{format_currency(today_received)} UZS</b>",
        f"   • 💵 Naqd pulda: +{format_currency(today_received_cash)} UZS",
        f"   • 📲 P2P / Kartada: +{format_currency(today_received_p2p)} UZS",
        f"   • 🏦 Bank / Terminalda: +{format_currency(today_received_bank)} UZS",
        f"🔴 <b>Qilingan jami xarajatlar:</b> <b>-{format_currency(today_spent)} UZS</b>",
        f"📈 <b>Bugungi sof o'sish (Net):</b> <b>{format_currency(today_net)} UZS</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🏦 <b>2. KLINIKADAGI JAMI MABLAG' (MOLIYAVIY QOLDIQ):</b>",
        f"💎 <b>KLINIKANING UMUMIY BALANSI:</b> <b>{format_currency(total_clinic_money)} UZS</b>",
        "",
        "💰 <b>Qayerda qancha mablag' bor:</b>",
        f"💵 <b>Naqd pulda (Kassa):</b> <b>{format_currency(balance_cash)} UZS</b>",
        f"📲 <b>P2P / Karta o'tkazmada:</b> <b>{format_currency(balance_p2p)} UZS</b>",
        f"🏦 <b>Bank hisob raqamida (va Terminal):</b> <b>{format_currency(balance_bank)} UZS</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🧾 <b>3. QO'SHIMCHA AKTIVLAR VA QARZLAR:</b>",
        f"⚠️ <b>Bemorlar qarzdorligi (Kutilayotgan tushum):</b> {format_currency(data['total_debt'])} UZS",
        f"📦 <b>Ombordagi dori zaxirasi qiymati:</b> {format_currency(data['pharmacy_total_value'])} UZS",
        f"👥 <b>Statsionardagi faol bemorlar:</b> {len(data['inpatient_ledger'])} nafar",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📎 <b>ILOVADA KUN YAKUNI BO'YICHA AUDIT HUJJATLARI:</b>",
        "1️⃣ <b>Excel (.xlsx):</b> 6 ta bo'limli to'liq kassa va hisob-kitob auditi",
        "2️⃣ <b>PDF (.pdf):</b> Imzolar va rasmiy blankaga ega kunlik Z-hisobot hujjati"
    ]

    msg_text = "\n".join(lines)
    send_telegram_message(TOPIC_ACCOUNTING, msg_text)

    # Generate documents
    reports_dir = os.path.join(BASE_DIR, "data", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    excel_path = os.path.join(reports_dir, f"FMH_Kunlik_Yakun_{data['iso_date']}.xlsx")
    pdf_path = os.path.join(reports_dir, f"FMH_Kunlik_Yakun_{data['iso_date']}.pdf")

    generate_comprehensive_excel(data, excel_path)
    generate_comprehensive_pdf(data, pdf_path)

    send_telegram_document(
        TOPIC_ACCOUNTING,
        excel_path,
        caption=f"📊 <b>FMH Kunlik Kassa Yakuni ({data['date_str']}) — Excel Auditi</b>"
    )

    send_telegram_document(
        TOPIC_ACCOUNTING,
        pdf_path,
        caption=f"📑 <b>FMH Rasmiy Kunlik Z-Hisobot ({data['date_str']}) — A4 PDF</b>"
    )

    return True


# Global scheduler state. The last closing date is kept on disk: held only in
# memory, every restart after 21:00 (a deploy, a crash) posted the day's
# closing report again.
_STATE_FILE = os.path.join(BASE_DIR, 'data', 'telegram_state.json')


def _load_last_closing_date():
    try:
        with open(_STATE_FILE, encoding='utf-8') as f:
            return json.load(f).get('last_closing_date')
    except Exception:
        return None


def _save_last_closing_date(day_iso):
    tmp = _STATE_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'last_closing_date': day_iso}, f)
        os.replace(tmp, _STATE_FILE)
    except Exception as e:
        print(f"[Daily Closing Scheduler] holat saqlanmadi: {e}")


_last_closing_date = _load_last_closing_date()
_scheduler_started = False
_scheduler_lock = threading.Lock()

def start_daily_closing_scheduler():
    """
    Har kuni soat 21:00 da avtomatik ravishda kun yakuni hisobotini
    Bugalteriya topigiga yuboruvchi daemon scheduler.
    """
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def _loop():
        global _last_closing_date
        print("[*] 21:00 Kunlik kassa yakuni scheduleri ishga tushirildi...")
        while True:
            try:
                now = datetime.datetime.now()
                today_iso = now.date().isoformat()
                if now.hour >= 21 and _last_closing_date != today_iso:
                    print(f"[*] Soat 21:00! Kunlik moliya yakuni hisoboti yuborilmoqda: {today_iso}")
                    _last_closing_date = today_iso
                    _save_last_closing_date(today_iso)
                    generate_and_send_daily_closing_report()
            except Exception as e:
                print(f"[Daily Closing Scheduler Error] {e}")
            import time
            time.sleep(30)

    t = threading.Thread(target=_loop, daemon=True, name="FMH-DailyClosingScheduler")
    t.start()
    return t
def send_all_reports(target_date=None):
    """Barcha 3 ta guruh mavzusiga (topic) barcha hisobotlarni bir vaqtda yuborish."""
    print("[1/3] Hamshiralar hisoboti yuborilmoqda...")
    res_nurses = generate_and_send_nurses_report(target_date)

    print("[2/3] Shifokorlar hisoboti yuborilmoqda...")
    res_doctors = generate_and_send_doctors_report(target_date)

    print("[3/3] Kengaytirilgan Buxgalteriya hisoboti (Xulosa + Ko'p varaqli Excel + PDF) yuborilmoqda...")
    res_acc = generate_and_send_accounting_report(target_date)

    print("Barcha hisobotlar muvaffaqiyatli jo'natildi!")
    return {
        "nurses": res_nurses is not None,
        "doctors": res_doctors is not None,
        "accounting": res_acc is not None
    }


# -----------------------------------------------------------------------------
# 4.1 REAL-TIME INCOME & EXPENSE NOTIFICATIONS (TOPIC 6: BUGALTERIYA)
# -----------------------------------------------------------------------------
import threading

_notified_transaction_ids = set()
_notified_lock = threading.Lock()

def _mark_as_notified(txn_id):
    with _notified_lock:
        _notified_transaction_ids.add(str(txn_id))

def _is_already_notified(txn_id):
    with _notified_lock:
        return str(txn_id) in _notified_transaction_ids


def _claim(txn_id):
    """Atomically take the right to announce txn_id; False if already taken.

    The ids used to be marked only after the message went out, so the 5-second
    watchdog could pick up a payment the request thread was still sending and
    post it a second time.
    """
    with _notified_lock:
        key = str(txn_id)
        if key in _notified_transaction_ids:
            return False
        _notified_transaction_ids.add(key)
        return True


def notify_payment_entered_sync(pay_data):
    """
    Kassa/Bemor to'lovi (yoki qaytarish) tizimga kiritilganda darhol Telegramga xabar berish.
    """
    pay_id = pay_data.get('id')
    if pay_id and _is_already_notified(f"TXN-{pay_id}"):
        return
    if pay_id and not _claim(pay_id):
        return

    amount = float(pay_data.get('amount') or 0)
    is_refund = amount < 0
    inv_id = pay_data.get('invoice_id')
    method = pay_data.get('payment_method', 'cash')
    acc = pay_data.get('account_destination', 'kassa')
    notes = pay_data.get('notes', '')
    staff_id = pay_data.get('staff_id') or pay_data.get('received_by_staff_id')

    method_labels = {
        'terminal': '💳 Terminal (Bank kartalari)',
        'cash': '💵 Naqd pul (Kassa)',
        'cash_register': '💵 Naqd pul (Kassa apparati)',
        'card_transfer': '📲 Karta o\'tkazma (P2P)',
        'payme_click': '📱 Click / Payme (Online)',
        'bank_wire': '🏦 Bank hisob raqami'
    }

    acc_labels = {
        'kassa': '💵 Asosiy kassa (Naqd)',
        'terminal_bank': '🏦 Bank terminal hisobi',
        'click_payme_merchant': '📱 Click / Payme hisobi',
        'main_bank_account': '🏦 Asosiy bank hisob raqami'
    }

    patient_name = "Noma'lum"
    patient_code = "-"
    room_bed = "-"
    balance_due = None
    staff_name = None

    try:
        conn = db.get_db()
        cur = conn.cursor()

        if inv_id:
            cur.execute("""
                SELECT inv.balance_due, inv.net_amount,
                       p.full_name AS patient_name, p.patient_code,
                       r.room_number, b.bed_code
                FROM invoices inv
                LEFT JOIN admissions a ON inv.admission_id = a.id
                LEFT JOIN patients p ON a.patient_id = p.id
                LEFT JOIN beds b ON a.bed_id = b.id
                LEFT JOIN rooms r ON b.room_id = r.id
                WHERE inv.id = ?
            """, (inv_id,))
            row = cur.fetchone()
            if row:
                patient_name = row.get('patient_name') or patient_name
                patient_code = row.get('patient_code') or patient_code
                if row.get('room_number') and row.get('bed_code'):
                    room_bed = f"{row.get('room_number')}-{row.get('bed_code')}"
                balance_due = row.get('balance_due')

        if staff_id:
            cur.execute("SELECT full_name FROM staff WHERE id = ?", (staff_id,))
            st_row = cur.fetchone()
            if st_row:
                staff_name = st_row.get('full_name')

        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END), 0) AS today_income,
                COALESCE(SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END), 0) AS today_expense
            FROM accounting_transactions
            WHERE transaction_date = CURDATE()
        """)
        totals = cur.fetchone() or {}
        today_income = float(totals.get('today_income', 0))
        today_expense = float(totals.get('today_expense', 0))
        today_net = today_income - today_expense

        conn.close()
    except Exception as e:
        print(f"[Telegram Notify DB Error] {e}")
        today_income = 0
        today_expense = 0
        today_net = 0

    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    if not is_refund:
        title = "🟢 <b>YANGI TUSHUM (KIRIM) QAYD ETILDI</b>"
        sign = "+"
        amt_str = f"<font color='#047857'><b>+{format_currency(amount)} UZS</b></font>"
    else:
        title = "🔴 <b>BEMORGA QAYTARISH (REFUND) QAYD ETILDI</b>"
        sign = "-"
        amt_str = f"<font color='#DC2626'><b>-{format_currency(abs(amount))} UZS</b></font>"

    lines = [
        title,
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>Summa:</b> {sign}{format_currency(abs(amount))} UZS",
        f"💳 <b>To'lov usuli:</b> {method_labels.get(method, method.title())}",
        f"📥 <b>Kassa yo'nalishi:</b> {acc_labels.get(acc, acc.title())}",
        f"📂 <b>Kategoriya:</b> Bemor to'lovi (Davolanish)",
        "",
        f"👤 <b>Bemor:</b> <b>{patient_name}</b> (<code>{patient_code}</code>)",
        f"🛏 <b>Palata-O'rin:</b> <b>{room_bed}</b>",
        f"🧾 <b>Hisob-faktura:</b> <code>{inv_id}</code>",
    ]

    if balance_due is not None:
        lines.append(f"📊 <b>Qolgan qarzdorlik:</b> {format_currency(balance_due)} UZS")

    if notes:
        lines.append(f"📝 <b>Izoh:</b> <i>{notes}</i>")

    if staff_name:
        lines.append(f"👨‍💼 <b>Qabul qildi:</b> {staff_name}")

    lines.append(f"⏰ <b>Vaqt:</b> {now_str}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📈 <i>Bugungi jami kirim: {format_currency(today_income)} UZS | Sof kassa: {format_currency(today_net)} UZS</i>")

    msg_text = "\n".join(lines)
    send_telegram_message(TOPIC_ACCOUNTING, msg_text)
    
    if pay_id:
        _mark_as_notified(pay_id)
        _mark_as_notified(f"TXN-{pay_id}")


def notify_payment_entered_async(pay_data):
    """Non-blocking background thread to send payment notification immediately."""
    threading.Thread(target=notify_payment_entered_sync, args=(pay_data,), daemon=True).start()


def notify_accounting_transaction_entered_sync(txn_data):
    """
    Operatsion xarajat (chiqim), kirim yoki inkassatsiya kiritilganda darhol Telegramga xabar berish.
    """
    trx_id = txn_data.get('id')
    if trx_id and not _claim(trx_id):
        return

    txn_type = txn_data.get('transaction_type') or txn_data.get('type') or 'expense'
    category = txn_data.get('category', 'operational_expense')
    amount = float(txn_data.get('amount') or 0)
    method = txn_data.get('payment_method', 'cash')
    desc = txn_data.get('description') or txn_data.get('title') or "Kassa amaliyoti"
    staff_id = txn_data.get('recorded_by_staff_id')

    method_labels = {
        'terminal': '💳 Terminal (Bank)',
        'cash': '💵 Naqd pul (Kassa)',
        'cash_register': '💵 Kassa apparati',
        'card_transfer': '📲 Karta o\'tkazma',
        'payme_click': '📱 Click / Payme',
        'bank_wire': '🏦 Bank hisob raqami'
    }

    category_labels = {
        'medication_purchase': '💊 Dori-darmon xaridi (Ombor)',
        'salary': '💼 Xodimlar & Shifokorlar maoshi',
        'utilities': '💡 Kommunal to\'lovlar & Internet',
        'rent': '🏢 Bino ijarasi',
        'food_catering': '🍲 Bemorlar oziq-ovqati (Katering)',
        'equipment': '🩺 Tibbiy jihozlar & Sarflov',
        'operational_expense': '📦 Xo\'jalik xarajatlari',
        'incasso': '🏦 Kassa inkassatsiyasi (Bankka)',
        'patient_payment': '👤 Bemor to\'lovi',
        'consultation': '🩺 Konsultatsiya tushumi'
    }

    staff_name = None
    try:
        conn = db.get_db()
        cur = conn.cursor()

        if staff_id:
            cur.execute("SELECT full_name FROM staff WHERE id = ?", (staff_id,))
            st_row = cur.fetchone()
            if st_row:
                staff_name = st_row.get('full_name')

        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END), 0) AS today_income,
                COALESCE(SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END), 0) AS today_expense
            FROM accounting_transactions
            WHERE transaction_date = CURDATE()
        """)
        totals = cur.fetchone() or {}
        today_income = float(totals.get('today_income', 0))
        today_expense = float(totals.get('today_expense', 0))
        today_net = today_income - today_expense

        conn.close()
    except Exception as e:
        print(f"[Telegram Notify DB Error] {e}")
        today_income = 0
        today_expense = 0
        today_net = 0

    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    if txn_type == 'income':
        title = "🟢 <b>YANGI TUSHUM (KIRIM) QAYD ETILDI</b>"
        sign = "+"
    else:
        title = "🔴 <b>YANGI XARAJAT (CHIQIM) QAYD ETILDI</b>"
        sign = "-"

    lines = [
        title,
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 <b>Summa:</b> {sign}{format_currency(amount)} UZS",
        f"💳 <b>To'lov usuli:</b> {method_labels.get(method, method.title())}",
        f"📂 <b>Kategoriya:</b> <b>{category_labels.get(category, category)}</b>",
        f"📝 <b>Tavsif / Maqsad:</b> {desc}",
        f"🆔 <b>Tranzaksiya ID:</b> <code>{trx_id}</code>",
    ]

    if staff_name:
        lines.append(f"👨‍💼 <b>Mas'ul xodim:</b> {staff_name}")

    lines.append(f"⏰ <b>Vaqt:</b> {now_str}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"📊 <i>Bugungi kirim: {format_currency(today_income)} UZS | Chiqim: {format_currency(today_expense)} UZS | Sof: {format_currency(today_net)} UZS</i>"
    )

    msg_text = "\n".join(lines)
    send_telegram_message(TOPIC_ACCOUNTING, msg_text)

    if trx_id:
        _mark_as_notified(trx_id)


def notify_accounting_transaction_entered_async(txn_data):
    """Non-blocking background thread to send expense/transaction notification immediately."""
    threading.Thread(target=notify_accounting_transaction_entered_sync, args=(txn_data,), daemon=True).start()


def start_transaction_watchdog():
    """
    Background watchdog daemon thread:
    Polls the database every 5 seconds for any new transactions added in MySQL directly
    or via any script that bypassed the server HTTP routes, ensuring 100% of transactions
    are reported in real-time.
    """
    def _watchdog_loop():
        # Pre-seed existing transaction IDs so old historical ones aren't blasted
        try:
            conn = db.get_db()
            cur = conn.cursor()
            cur.execute("SELECT id FROM accounting_transactions ORDER BY created_at DESC LIMIT 500")
            for r in cur.fetchall():
                _mark_as_notified(r['id'])
            conn.close()
        except Exception as e:
            print(f"[Watchdog Init Error] {e}")

        while True:
            try:
                import time
                time.sleep(5)
                conn = db.get_db()
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, payment_id, transaction_type, category, amount, payment_method,
                           account_source, related_invoice_id, related_staff_id, description,
                           transaction_date, recorded_by_staff_id, created_at
                    FROM accounting_transactions
                    WHERE created_at >= NOW() - INTERVAL 1 HOUR
                    ORDER BY created_at ASC
                """)
                rows = cur.fetchall()
                conn.close()

                for row in rows:
                    t_id = row['id']
                    if not _is_already_notified(t_id):
                        if row.get('payment_id'):
                            # The payment id is what the request thread claims;
                            # remember the row too so it is checked only once.
                            _mark_as_notified(t_id)
                        # Trigger notification
                        if row.get('payment_id'):
                            # It's a payment-linked transaction
                            notify_payment_entered_sync({
                                'id': row['payment_id'],
                                'invoice_id': row.get('related_invoice_id'),
                                'amount': float(row['amount']) if row['transaction_type'] == 'income' else -float(row['amount']),
                                'payment_method': row.get('payment_method'),
                                'account_destination': row.get('account_source'),
                                'notes': row.get('description'),
                                'staff_id': row.get('recorded_by_staff_id')
                            })
                        else:
                            # Direct accounting transaction
                            notify_accounting_transaction_entered_sync({
                                'id': t_id,
                                'transaction_type': row['transaction_type'],
                                'category': row['category'],
                                'amount': float(row['amount']),
                                'payment_method': row.get('payment_method'),
                                'description': row.get('description'),
                                'recorded_by_staff_id': row.get('recorded_by_staff_id')
                            })
            except Exception as e:
                import time
                time.sleep(5)

    t = threading.Thread(target=_watchdog_loop, daemon=True, name="FMH-TransactionWatchdog")
    t.start()
    return t


# -----------------------------------------------------------------------------
# 5. INTERACTIVE BOT LISTENER (POLLING)
# -----------------------------------------------------------------------------
def run_polling():
    """
    Botni doimiy tinglash rejimida ishga tushirish.
    Xodimlar guruh topiklarida buyruq yozganda avtomatik javob beradi:
      - /dorilar, /hamshira -> Hamshiralar topigiga dorilar jadvali
      - /kasallar, /bemorlar, /doctor -> Doktorlar topigiga kasallar ro'yxati
      - /hisobot, /moliya, /bugalteriya -> Buxgalteriyaga kengaytirilgan hisobot + Excel + PDF
      - /all -> Barcha topiklar hisobotlarini yangilash
    """
    # Start transaction watchdog and 21:00 closing scheduler alongside bot listener
    start_transaction_watchdog()
    start_daily_closing_scheduler()
    print(f"[*] FayzControl bot, Kassa Watchdog va 21:00 Scheduleri faollashtirildi (Chat ID: {CHAT_ID}). Xabarlar kutilmoqda...")
    offset = None
    
    while True:
        try:
            url = f"{API_BASE}/getUpdates?timeout=30"
            if offset:
                url += f"&offset={offset}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=40) as res:
                data = json.loads(res.read().decode("utf-8"))
            
            if not data.get("ok"):
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                if chat_id != CHAT_ID:
                    continue

                text = (msg.get("text") or "").strip().lower()
                thread_id = msg.get("message_thread_id")

                if text.startswith("/dorilar") or text.startswith("/hamshira"):
                    send_telegram_message(thread_id or TOPIC_NURSES, "⏳ Hamshiralar uchun dori qabul qilish jadvali tayyorlanmoqda...")
                    generate_and_send_nurses_report()

                elif text.startswith("/kasallar") or text.startswith("/bemorlar") or text.startswith("/doctor"):
                    send_telegram_message(thread_id or TOPIC_DOCTORS, "⏳ Statsionardagi bemorlar ro'yxati tayyorlanmoqda...")
                    generate_and_send_doctors_report()

                elif text.startswith("/yakun") or text.startswith("/21:00") or text.startswith("/closing") or text.startswith("/balans"):
                    send_telegram_message(thread_id or TOPIC_ACCOUNTING, "⏳ Kun yakuni kassa hisoboti (21:00), naqd, p2p, bank va jami qoldiqlar hisoblanmoqda...")
                    generate_and_send_daily_closing_report()

                elif text.startswith("/hisobot") or text.startswith("/moliya") or text.startswith("/bugalteriya"):
                    send_telegram_message(thread_id or TOPIC_ACCOUNTING, "⏳ Buxgalteriya kengaytirilgan hisoboti, 6 varaqli Excel va PDF hujjatlari shakllantirilmoqda...")
                    generate_and_send_accounting_report()

                elif text.startswith("/all") or text.startswith("/yangilash"):
                    send_telegram_message(thread_id or TOPIC_ACCOUNTING, "⏳ Barcha topiklar bo'yicha hisobotlar yangilanmoqda...")
                    send_all_reports()

                elif text.startswith("/start") or text.startswith("/help"):
                    help_text = (
                        "🤖 <b>FayzControl Bot buyruqlari:</b>\n\n"
                        "💊 <code>/dorilar</code> — Hamshiralar uchun dori qabul qilish jadvali\n"
                        "🩺 <code>/kasallar</code> — Shifokorlar uchun statsionar bemorlar ro'yxati\n"
                        "📊 <code>/hisobot</code> — Buxgalteriya uchun to'liq moliya auditi (Excel + PDF)\n"
                        "🌙 <code>/yakun</code> (yoki <code>/21:00</code>) — Kun yakuni kassa holati (Naqd, P2P, Bank, Jami)\n"
                        "🔄 <code>/all</code> — Barcha bo'limlar hisobotini yangilash"
                    )
                    send_telegram_message(thread_id or TOPIC_DOCTORS, help_text)

        except Exception as e:
            import time
            time.sleep(3)


if __name__ == "__main__":
    if not ENABLED:
        print("[!] FMH_TELEGRAM_BOT_TOKEN o'rnatilmagan - Telegram bot o'chiq.")
        sys.exit(1)
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("--nurses", "-n", "nurses"):
            generate_and_send_nurses_report()
        elif arg in ("--doctors", "-d", "doctors"):
            generate_and_send_doctors_report()
        elif arg in ("--accounting", "-a", "accounting"):
            generate_and_send_accounting_report()
        elif arg in ("--closing", "-c", "closing", "yakun", "21:00"):
            generate_and_send_daily_closing_report()
        elif arg in ("--listen", "--poll", "-p"):
            run_polling()
        else:
            send_all_reports()
    else:
        generate_and_send_daily_closing_report()
