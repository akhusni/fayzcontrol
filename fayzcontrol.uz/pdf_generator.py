"""
Fayz Medical House — Backend PDF Generator Engine
Queries Enterprise MySQL 8.0 directly and compiles official PDF documents using ReportLab.
"""

import io
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
from db import get_db

def generate_patient_pdf(*args, **kwargs):
    doc_type = kwargs.get('doc_type', 'prescriptions')
    if len(args) == 1:
        patient_id = args[0]
    elif len(args) >= 2:
        patient_id = args[1]
        if len(args) >= 3:
            doc_type = args[2]
    else:
        patient_id = kwargs.get('patient_id')

    conn = get_db()
    cur = conn.cursor()

    # 1. Fetch Patient
    cur.execute("SELECT * FROM patients WHERE id = ? OR patient_code = ?", (patient_id, patient_id))
    pt_row = cur.fetchone()
    if not pt_row:
        conn.close()
        return None
    pt = dict(pt_row)
    actual_id = pt['id']

    # 2. Fetch Active Admission & Doctor
    cur.execute("""
        SELECT a.*, r.room_number, b.bed_code, s.full_name AS doctor_name, s.specialty AS doctor_title
        FROM admissions a
        JOIN beds b ON a.bed_id = b.id
        JOIN rooms r ON b.room_id = r.id
        LEFT JOIN staff s ON a.attending_doctor_id = s.id
        WHERE a.patient_id = ?
        ORDER BY a.start_date DESC LIMIT 1
    """, (actual_id,))
    adm_row = cur.fetchone()
    adm = dict(adm_row) if adm_row else {}

    # 3. Fetch Medical History
    cur.execute("SELECT * FROM medical_histories WHERE patient_id = ? ORDER BY updated_at DESC LIMIT 1", (actual_id,))
    anam_row = cur.fetchone()
    anam = dict(anam_row) if anam_row else {}

    # 4. Fetch Prescriptions
    cur.execute("SELECT * FROM prescriptions WHERE patient_id = ? ORDER BY created_at DESC", (actual_id,))
    prescriptions = [dict(r) for r in cur.fetchall()]

    # 5. Fetch Daily Notes
    cur.execute("SELECT * FROM doctor_daily_notes WHERE patient_id = ? ORDER BY note_date DESC, id DESC", (actual_id,))
    daily_notes = [dict(r) for r in cur.fetchall()]

    # 6. Fetch Discharge Epicrisis
    cur.execute("SELECT * FROM discharge_epicrises WHERE patient_id = ? ORDER BY updated_at DESC LIMIT 1", (actual_id,))
    epicrisis_row = cur.fetchone()
    epicrisis = dict(epicrisis_row) if epicrisis_row else {}

    conn.close()

    # --- REPORTLAB PDF GENERATION ---
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom Color Palette
    PRIMARY = colors.HexColor('#0284c7')
    DARK_TEXT = colors.HexColor('#0f172a')
    MUTED_TEXT = colors.HexColor('#64748b')
    BG_LIGHT = colors.HexColor('#f8fafc')
    BORDER_COLOR = colors.HexColor('#cbd5e1')

    # Typography Styles
    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=15, leading=19, textColor=DARK_TEXT, alignment=1)
    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11, textColor=MUTED_TEXT, alignment=1)
    clinic_name_style = ParagraphStyle('ClinicName', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=13, leading=15, textColor=DARK_TEXT)
    clinic_sub_style = ParagraphStyle('ClinicSub', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7.5, leading=9, textColor=PRIMARY)
    meta_style = ParagraphStyle('MetaStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=7.5, leading=10, textColor=MUTED_TEXT, alignment=2)
    section_heading = ParagraphStyle('SecHeading', parent=styles['Heading3'], fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=PRIMARY)
    body_style = ParagraphStyle('BodyTextCustom', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11, textColor=DARK_TEXT)
    bold_style = ParagraphStyle('BoldCustom', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=DARK_TEXT)

    story = []

    # --- CLINIC HEADER LETTERHEAD ---
    header_left = [
        Paragraph("FAYZ MEDICAL HOUSE", clinic_name_style),
        Paragraph("XUSUSIY NARKOLOGIYA VA PSIXIATRIYA KLINIKASI", clinic_sub_style)
    ]
    header_right = [
        Paragraph("<b>O'zR SSV Litsenziyasi:</b> № 4082-00", meta_style),
        Paragraph("<b>Manzil:</b> Toshkent sh., Yunusobod t., Bodomzor str. 42", meta_style),
        Paragraph("<b>Ishonch Telefoni:</b> +998 (71) 200-03-03", meta_style),
        Paragraph("<b>Veb-sayt:</b> www.fayzmedicalhouse.uz", meta_style)
    ]

    header_table = Table([[header_left, header_right]], colWidths=[280, 240])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceBefore=4, spaceAfter=10))

    # --- DOCUMENT TITLE ---
    title_text = "RASMIY MUOLAJA VARAQASI (LIST NAZNACHENIY)"
    sub_text = "Klinik dori-darmonlar va tibbiy muolajalar tayinlovi"

    if doc_type == 'anamnesis':
        title_text = "KASALLIK TARIXI VA ANAMNEZI (EMR)"
        sub_text = "Statsionar / Ambulator bemorning birlamchi tibbiy ko'rik hujjati"
    elif doc_type == 'epicrisis':
        title_text = "STATSIONARDAN CHIQARISH EPIKRIZI"
        sub_text = "Rasmiy tibbiy xulosa va uyda davolanish tavsiyalari"
    elif doc_type == 'full_dossier':
        title_text = "TO'LIQ BEMOR KLINIK EMR DOSSYESI"
        sub_text = "Yagona kompleks tibbiy hujjat (Anamnez, Retseptlar, Ko'riklar & Epikriz)"

    story.append(Paragraph(title_text, title_style))
    story.append(Paragraph(sub_text, subtitle_style))
    story.append(Spacer(1, 10))

    # --- PATIENT IDENTITY GRID ---
    age_str = f"{2026 - pt['birth_year']} yosh" if pt.get('birth_year') else "N/A"
    gender_str = "Ayol" if pt.get('gender') == 'female' else "Erkak"
    room_str = f"{adm.get('room_number', 'N/A')}-xona ({adm.get('bed_code', '')})" if adm else "Ambulator"
    primary_diag = anam.get('diagnosis_primary') or "Surunkali alkogolizm 2-bosqich. Abstinensiya sindromi."
    icd10 = anam.get('icd10_code') or "F10.2"
    allergies = pt.get('medical_allergies') or "Qayd etilmagan (Yo'q)"
    # Computed outside the f-string below: an escaped quote inside an f-string
    # expression is a syntax error before Python 3.12, which made this whole
    # module fail to import and silently disabled every PDF export.
    allergy_color = '#f43f5e' if allergies.lower() != "yo'q" else '#10b981'

    pt_grid_data = [
        [Paragraph(f"<b>Bemor F.I.SH.:</b> {pt.get('full_name', '')}", body_style), Paragraph(f"<b>Bemor Kodi:</b> {pt.get('patient_code', '')}", body_style)],
        [Paragraph(f"<b>Yoshi / Jinsi:</b> {age_str} ({gender_str})", body_style), Paragraph(f"<b>Joylashuvi:</b> {room_str}", body_style)],
        [Paragraph(f"<b>Asosiy Klinik Tashxis:</b> {primary_diag}", body_style), Paragraph(f"<b>XKT-10 Kodi:</b> {icd10}", body_style)],
        [Paragraph(f"<b>Dori Allergiyalari Statusi:</b> <font color='{allergy_color}'><b>{allergies}</b></font>", body_style), Paragraph(f"<b>Mas'ul Shifokor:</b> {adm.get('doctor_name', 'Dr. Rustam Ziyayev')}", body_style)]
    ]

    pt_grid_table = Table(pt_grid_data, colWidths=[260, 260])
    pt_grid_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BG_LIGHT),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('PADDING', (0, 0), (-1, -1), 5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(pt_grid_table)
    story.append(Spacer(1, 10))

    # --- SECTION 1: ANAMNESIS (IF APPLICABLE) ---
    if doc_type in ['anamnesis', 'full_dossier']:
        story.append(Paragraph("<b>BEMOR SHIKOYATLARI & ANAMNEZI</b>", section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        
        complaints_text = anam.get('complaints') or "Patsiyent intoksikatsiya, uyqusizlik, tremor va bezovtalikdan shikoyat qiladi."
        morbi_text = anam.get('anamnesis_morbi') or "Surunkali alkogolli intoksikatsiya holati. Zapoy staji 5 kun."
        somatic_text = anam.get('somatic_status') or "Teri qoplamalari rangpar, tremori bor, arterial bosim 120/80 mm Hg, puls 74 ur/min."
        psych_text = anam.get('psychiatric_status') or "Ongi saqlangan, zamon va makonda orientatsiyasi bor. Affektiv fon bezovta."

        anam_data = [
            [Paragraph("<b>Shikoyat va Anamnez:</b>", bold_style), Paragraph(complaints_text, body_style)],
            [Paragraph("<b>Anamnesis Morbi:</b>", bold_style), Paragraph(morbi_text, body_style)],
            [Paragraph("<b>Somatik & Nevrologik:</b>", bold_style), Paragraph(somatic_text, body_style)],
            [Paragraph("<b>Psixik Status:</b>", bold_style), Paragraph(psych_text, body_style)]
        ]

        anam_table = Table(anam_data, colWidths=[130, 390])
        anam_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(anam_table)
        story.append(Spacer(1, 10))

    # --- SECTION 2: PRESCRIPTIONS TABLE (IF APPLICABLE) ---
    if doc_type in ['prescriptions', 'anamnesis', 'full_dossier']:
        story.append(Paragraph("<b>DORI-DARMON VA MUOLAJA TAYINLOVLARI (LIST NAZNACHENIY)</b>", section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))

        rx_headers = ["№", "Dori vositasi & Shakli", "Doza", "Yuborish Yo'li", "Vaqti / Davriyligi", "Davomiyligi", "Holati"]
        rx_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in rx_headers]]

        if prescriptions:
            for idx, r in enumerate(prescriptions, 1):
                status_color = "#10b981" if r.get('status') == 'completed' else ("#f43f5e" if r.get('status') == 'cancelled' else "#0284c7")
                status_lbl = "Bajarildi" if r.get('status') == 'completed' else ("Bekor" if r.get('status') == 'cancelled' else "Faol")
                rx_rows.append([
                    Paragraph(str(idx), body_style),
                    Paragraph(f"<b>{r.get('medication_name', '')}</b><br/><font color='#64748b' size='7'>{r.get('form', '')}</font>", body_style),
                    Paragraph(f"<b>{r.get('dosage', '')}</b>", body_style),
                    Paragraph(r.get('route', ''), body_style),
                    Paragraph(f"{r.get('frequency', '')}<br/><font color='#64748b' size='7'>{r.get('timing', '')}</font>", body_style),
                    Paragraph(f"{r.get('duration_days', 5)} kun", body_style),
                    Paragraph(f"<font color='{status_color}'><b>{status_lbl}</b></font>", body_style)
                ])
        else:
            rx_rows.append([Paragraph("Tayinlangan dori-darmonlar mavjud emas", body_style)] + [""]*6)

        rx_table = Table(rx_rows, colWidths=[18, 142, 55, 110, 105, 45, 45])
        rx_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(rx_table)
        story.append(Spacer(1, 10))

    # --- SECTION 3: DAILY PROGRESS NOTES (IF APPLICABLE) ---
    if doc_type in ['full_dossier'] and daily_notes:
        story.append(Paragraph("<b>SHIFOKOR KUNDALIK KO'RIGI QAYDLARI (DNEVNIK OBXODA)</b>", section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))

        dn_headers = ["Sana", "Gemodinamika", "Holat Dinamikasi", "Korreksiya"]
        dn_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in dn_headers]]

        for dn in daily_notes:
            vitals = f"BP: {dn.get('vital_bp', '120/80')}<br/>P: {dn.get('vital_pulse', 72)}<br/>T: {dn.get('vital_temp', 36.6)}°C"
            dn_rows.append([
                Paragraph(f"<b>{dn.get('note_date', '')}</b>", body_style),
                Paragraph(vitals, body_style),
                Paragraph(dn.get('dynamics_notes', ''), body_style),
                Paragraph(dn.get('treatment_adjustments', 'O\'zgarishsiz'), body_style)
            ])

        dn_table = Table(dn_rows, colWidths=[65, 85, 240, 130])
        dn_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('PADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(dn_table)
        story.append(Spacer(1, 10))

    # --- SECTION 4: DISCHARGE EPICRISIS (IF APPLICABLE) ---
    if doc_type in ['epicrisis', 'full_dossier']:
        story.append(Paragraph("<b>CHIQARISH EPIKRIZI VA TAVSIYALAR</b>", section_heading))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))

        summary_text = epicrisis.get('treatment_summary') or "Bemor klinikada detoksikatsiya va statsionar reabilitatsiya kursini muvaffaqiyatli o'tdi. Holati barqarorlashgan holda chiqarildi."
        home_rx_text = epicrisis.get('home_prescriptions') or "1. Meksidol 125mg tabletka — kuniga 2 mahal, 1 oy.\n2. Neyromultivit — kuniga 1 tabletka, 20 kun."
        psycho_text = epicrisis.get('psycho_recommendations') or "Psixoterapevt qabuliga haftada 1 marta qatnashish, 12 qadam dasturi mashg'ulotlari."

        epi_data = [
            [Paragraph("<b>Klinik Xulosa:</b>", bold_style), Paragraph(summary_text, body_style)],
            [Paragraph("<b>Uyda Davolanish:</b>", bold_style), Paragraph(home_rx_text.replace('\n', '<br/>'), body_style)],
            [Paragraph("<b>Psixologik Tavsiya:</b>", bold_style), Paragraph(psycho_text.replace('\n', '<br/>'), body_style)]
        ]

        epi_table = Table(epi_data, colWidths=[120, 400])
        epi_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(epi_table)
        story.append(Spacer(1, 10))

    # --- OFFICIAL FOOTER STAMP & SIGNATURE BLOCK ---
    doc_name = adm.get('doctor_name') or "Klinik Shifokor"
    doc_title = adm.get('doctor_title') or "Narkolog-Psixiatr"

    sig_col1 = [
        Paragraph("<b>Mas'ul Shifokor:</b>", body_style),
        Paragraph(f"<b>{doc_name}</b>", ParagraphStyle('DocN', parent=body_style, fontName='Helvetica-Bold', textColor=PRIMARY)),
        Paragraph(f"<font size='7' color='#64748b'>{doc_title}</font>", body_style),
        Spacer(1, 12),
        Paragraph("_______________________<br/><font size='7' color='#64748b'>(Shifokor Imzosi)</font>", body_style)
    ]

    sig_col2 = [
        Paragraph("<font size='7.5' color='#94a3b8'><b>FAYZ MEDICAL HOUSE</b><br/>KLINIKA MUHR O'RNI<br/>(OFFICIAL STAMP)</font>", ParagraphStyle('Stp', parent=body_style, alignment=1))
    ]

    sig_col3 = [
        Paragraph("<b>Hujjat Verifikatsiyasi:</b>", body_style),
        Paragraph(f"<font size='7' color='#64748b'>Sertifikat kodi: EMR-{pt.get('patient_code', '')}-SQL</font>", body_style),
        Paragraph(f"<font size='7' color='#64748b'>Generatsiya vaqti: 2026-08-18</font>", body_style),
        Spacer(1, 6),
        Paragraph("<font size='6.5' color='#94a3b8'>Ushbu PDF fayli MySQL 8.0 ma'lumotlar bazasidan avtomatik shakllantirilgan.</font>", body_style)
    ]

    sig_table = Table([[sig_col1, sig_col2, sig_col3]], colWidths=[180, 160, 180])
    sig_table.setStyle(TableStyle([
        ('BOX', (1, 0), (1, 0), 1, colors.HexColor('#94a3b8')),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('PADDING', (0, 0), (-1, -1), 4),
    ]))

    story.append(KeepTogether([
        HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=8, spaceAfter=8),
        sig_table
    ]))

    try:
        conn.close()
    except Exception:
        pass

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# =============================================================================
# NURSE STATION — DAILY MEDICATION ROUND
# =============================================================================
#
# The round could be printed from the browser but not downloaded: there was no
# PDF of it, only the page's own print stylesheet. A printed sheet is signed
# and filed, so it needs to exist as a file the ward can keep and re-send, not
# only as whatever the browser happened to render that afternoon.

_ROUND_STATE_UZ = {
    'given':        'Berildi',
    'missed':       "O'tkazib yuborildi",
    'refused':      'Bemor rad etdi',
    'held':         "To'xtatildi",
    'pending':      'Kutilmoqda',
    'scheduled':    'Rejalashtirilgan',
    'not_recorded': 'Qayd etilmagan',
}


def _clinic_letterhead(styles, PRIMARY, DARK_TEXT, MUTED_TEXT):
    """The masthead both documents share, so they cannot drift apart."""
    clinic_name_style = ParagraphStyle(
        'ClinicNameR', parent=styles['Heading2'], fontName='Helvetica-Bold',
        fontSize=13, leading=15, textColor=DARK_TEXT)
    clinic_sub_style = ParagraphStyle(
        'ClinicSubR', parent=styles['Normal'], fontName='Helvetica-Bold',
        fontSize=7.5, leading=9, textColor=PRIMARY)
    meta_style = ParagraphStyle(
        'MetaStyleR', parent=styles['Normal'], fontName='Helvetica',
        fontSize=7.5, leading=10, textColor=MUTED_TEXT, alignment=2)

    header = Table([[
        [Paragraph("FAYZ MEDICAL HOUSE", clinic_name_style),
         Paragraph("XUSUSIY NARKOLOGIYA VA PSIXIATRIYA KLINIKASI", clinic_sub_style)],
        [Paragraph("<b>O'zR SSV Litsenziyasi:</b> № 4082-00", meta_style),
         Paragraph("<b>Manzil:</b> Toshkent sh., Yunusobod t., Bodomzor str. 42", meta_style),
         Paragraph("<b>Ishonch Telefoni:</b> +998 (71) 200-03-03", meta_style)],
    ]], colWidths=[280, 240])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return header


def generate_round_pdf(day):
    """
    One day's medication round as a PDF, in ward order.

    `day` is a datetime.date. Built from nursery.build_round, so the sheet is
    the same reading of the same orders the nurse station shows -- a future
    date is answerable because the round is derived from the standing orders
    rather than from what has been recorded.

    Returns PDF bytes, or None when the day has no patients on it.
    """
    import nursery

    conn = get_db()
    try:
        round_data = nursery.build_round(conn, day)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not round_data['patients']:
        return None

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30,
                            topMargin=30, bottomMargin=30,
                            title=f"Dori berish varaqasi {round_data['date']}")

    styles = getSampleStyleSheet()
    PRIMARY = colors.HexColor('#0284c7')
    DARK_TEXT = colors.HexColor('#0f172a')
    MUTED_TEXT = colors.HexColor('#64748b')
    BG_LIGHT = colors.HexColor('#f1f5f9')
    BORDER_COLOR = colors.HexColor('#cbd5e1')

    title_style = ParagraphStyle('RTitle', parent=styles['Heading1'],
                                 fontName='Helvetica-Bold', fontSize=14,
                                 leading=17, textColor=DARK_TEXT, alignment=1)
    subtitle_style = ParagraphStyle('RSub', parent=styles['Normal'],
                                    fontName='Helvetica', fontSize=8.5,
                                    leading=11, textColor=MUTED_TEXT, alignment=1)
    body = ParagraphStyle('RBody', parent=styles['Normal'], fontName='Helvetica',
                          fontSize=8, leading=10, textColor=DARK_TEXT)
    bold = ParagraphStyle('RBold', parent=styles['Normal'],
                          fontName='Helvetica-Bold', fontSize=9, leading=11,
                          textColor=DARK_TEXT)
    small = ParagraphStyle('RSmall', parent=styles['Normal'], fontName='Helvetica',
                           fontSize=7, leading=9, textColor=MUTED_TEXT)

    story = [_clinic_letterhead(styles, PRIMARY, DARK_TEXT, MUTED_TEXT),
             HRFlowable(width="100%", thickness=2, color=PRIMARY,
                        spaceBefore=4, spaceAfter=10),
             Paragraph("KUNLIK DORI BERISH VARAQASI (LIST NAZNACHENIY)", title_style)]

    when = round_data['date']
    if round_data['is_future']:
        when += " — rejalashtirilgan kun"
    elif round_data['is_past']:
        when += " — o'tgan kun"
    story.append(Paragraph(when, subtitle_style))

    t = round_data['totals']
    story.append(Paragraph(
        f"Rejada: {t['planned']} &nbsp;·&nbsp; Berilgan: {t['given']} &nbsp;·&nbsp; "
        f"Zaruratga ko'ra: {t['as_needed_orders']} &nbsp;·&nbsp; "
        f"Bemorlar: {len(round_data['patients'])}", subtitle_style))
    story.append(Spacer(1, 10))

    for p in round_data['patients']:
        block = [Paragraph(
            f"{p['bed_code']} &nbsp; ({p['room_number']}-xona) &nbsp;&nbsp; "
            f"<b>{p['patient_name']}</b> &nbsp; <font size='7' color='#64748b'>"
            f"{p['patient_code']}</font>", bold)]

        allergy = (p.get('medical_allergies') or '').strip()
        if allergy and allergy.lower() not in ("yo'q", "yoq", "-"):
            block.append(Paragraph(
                f"<font color='#b91c1c'><b>ALLERGIYA:</b> {allergy}</font>", body))

        rows = [[Paragraph("<b>Vaqt</b>", body), Paragraph("<b>Dori</b>", body),
                 Paragraph("<b>Doza / yo'l</b>", body), Paragraph("<b>Holat</b>", body),
                 Paragraph("<b>Imzo</b>", body)]]
        for d in p['doses']:
            rows.append([
                Paragraph(d['slot_label'] or '—', body),
                Paragraph(d['medication_name'] or '—', body),
                Paragraph(f"{d.get('dosage') or ''} {d.get('route') or ''}".strip() or '—', body),
                Paragraph(_ROUND_STATE_UZ.get(d['state'], d['state']), body),
                Paragraph('', body),
            ])
        for o in p.get('as_needed', []):
            rows.append([
                Paragraph("<i>zarurat</i>", body),
                Paragraph(o.get('medication_name') or '—', body),
                Paragraph(f"{o.get('dosage') or ''} {o.get('route') or ''}".strip() or '—', body),
                Paragraph("Zaruratga ko'ra", body),
                Paragraph('', body),
            ])

        table = Table(rows, colWidths=[70, 150, 110, 105, 100], repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.4, BORDER_COLOR),
            ('BACKGROUND', (0, 0), (-1, 0), BG_LIGHT),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ]))
        block.append(table)

        # The morning's observation, on the same sheet as the doses.
        v = p.get('vitals') or {}
        def _v(key, unit=''):
            val = v.get(key)
            return f"{val}{unit}" if val is not None else '____'
        block.append(Paragraph(
            f"Ko'rsatkichlar: AB {_v('vital_bp_systolic')}/{_v('vital_bp_diastolic')} mm &nbsp;·&nbsp; "
            f"Puls {_v('vital_pulse')} &nbsp;·&nbsp; Harorat {_v('vital_temp', '°C')} &nbsp;·&nbsp; "
            f"SpO2 {_v('vital_spo2', '%')}"
            + (f" &nbsp;·&nbsp; {v['nurse_notes']}" if v.get('nurse_notes') else ''),
            small))
        block.append(Spacer(1, 9))
        story.append(KeepTogether(block))

    story.append(HRFlowable(width="100%", thickness=1.2, color=PRIMARY,
                            spaceBefore=6, spaceAfter=6))
    story.append(Table([[
        Paragraph("Navbatchi hamshira: ______________________", body),
        Paragraph("Bosh hamshira: ______________________", body),
        Paragraph("Sana: ______________", body),
    ]], colWidths=[200, 200, 120]))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
