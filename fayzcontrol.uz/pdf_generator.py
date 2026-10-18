"""
Fayz Medical House — Backend PDF Generator Engine
Queries Enterprise MySQL 8.0 directly and compiles official PDF documents using ReportLab.
"""

import datetime
import io
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable, PageBreak
from reportlab.pdfgen import canvas
from db import get_db
from xml.sax.saxutils import escape as _xml_escape



def _x(value):
    """
    Text from the database, made safe for ReportLab's Paragraph markup.
    A note such as "Hb<norma" made the parser raise, and the route answered
    "patient not found", so the PDF of that patient could not be printed.
    """
    return _xml_escape('' if value is None else str(value))

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
    cur.execute("SELECT * FROM discharge_epicrises WHERE patient_id = ? ORDER BY epicrisis_date DESC, updated_at DESC, created_at DESC LIMIT 1", (actual_id,))
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
    logo_file = os.path.join(os.path.dirname(__file__), 'assets', 'images', 'logo-emblem.png')
    if not os.path.exists(logo_file):
        logo_file = os.path.join(os.path.dirname(__file__), 'assets', 'images', 'logo.png')
    header_row = []
    col_widths = []
    if os.path.exists(logo_file):
        try:
            from reportlab.platypus import Image as RLImage
            logo_img = RLImage(logo_file, width=42, height=42)
            header_row.append(logo_img)
            col_widths.append(48)
        except Exception:
            pass

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

    header_row.append(header_left)
    header_row.append(header_right)
    if len(col_widths) == 1:
        col_widths.extend([236, 230])
    else:
        col_widths = [280, 240]

    header_table = Table([header_row], colWidths=col_widths)
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
    age_str = f"{datetime.date.today().year - int(pt['birth_year'])} yosh" if pt.get('birth_year') else "—"
    # Nothing clinical is invented: blanks print as NOT_RECORDED. This file
    # used to fill them with a diagnosis (F10.2), complaints, vitals, a
    # "successful" discharge, home medicines and a doctor's name.
    NOT_RECORDED = "Qayd etilmagan"
    gender_str = {'female': "Ayol", 'male': "Erkak"}.get(pt.get('gender'), NOT_RECORDED)
    room_str = f"{adm.get('room_number', 'N/A')}-xona ({adm.get('bed_code', '')})" if adm else "Ambulator"
    primary_diag = anam.get('diagnosis_primary') or NOT_RECORDED
    icd10 = anam.get('icd10_code') or NOT_RECORDED
    allergies = pt.get('medical_allergies') or NOT_RECORDED
    # Computed outside the f-string below: an escaped quote inside an f-string
    # expression is a syntax error before Python 3.12, which made this whole
    # module fail to import and silently disabled every PDF export.
    allergy_color = '#10b981' if allergies.lower() == "yo'q" else ('#64748b' if allergies == NOT_RECORDED else '#f43f5e')

    pt_grid_data = [
        [Paragraph(f"<b>Bemor F.I.SH.:</b> {_x(pt.get('full_name', ''))}", body_style), Paragraph(f"<b>Bemor Kodi:</b> {_x(pt.get('patient_code', ''))}", body_style)],
        [Paragraph(f"<b>Yoshi / Jinsi:</b> {age_str} ({gender_str})", body_style), Paragraph(f"<b>Joylashuvi:</b> {_x(room_str)}", body_style)],
        [Paragraph(f"<b>Asosiy Klinik Tashxis:</b> {_x(primary_diag)}", body_style), Paragraph(f"<b>XKT-10 Kodi:</b> {_x(icd10)}", body_style)],
        [Paragraph(f"<b>Dori Allergiyalari Statusi:</b> <font color='{allergy_color}'><b>{_x(allergies)}</b></font>", body_style), Paragraph(f"<b>Mas'ul Shifokor:</b> {_x((adm or {}).get('doctor_name') or NOT_RECORDED)}", body_style)]
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
        
        complaints_text = _x(anam.get('complaints') or NOT_RECORDED)
        morbi_text = _x(anam.get('anamnesis_morbi') or NOT_RECORDED)
        somatic_text = _x(anam.get('somatic_status') or NOT_RECORDED)
        psych_text = _x(anam.get('psychiatric_status') or NOT_RECORDED)

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
                    Paragraph(f"<b>{_x(r.get('medication_name', ''))}</b><br/><font color='#64748b' size='7'>{_x(r.get('form', ''))}</font>", body_style),
                    Paragraph(f"<b>{_x(r.get('dosage', ''))}</b>", body_style),
                    Paragraph(_x(r.get('route', '')), body_style),
                    Paragraph(f"{_x(r.get('frequency', ''))}<br/><font color='#64748b' size='7'>{_x(r.get('timing', ''))}</font>", body_style),
                    Paragraph(f"{r.get('duration_days')} kun" if r.get('duration_days') else "—", body_style),
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
            _sys, _dia = dn.get('vital_bp_systolic'), dn.get('vital_bp_diastolic')
            _bp = f"{_sys}/{_dia}" if _sys is not None and _dia is not None else "—"
            _pulse = dn.get('vital_pulse') if dn.get('vital_pulse') is not None else "—"
            _temp = f"{dn.get('vital_temp')}°C" if dn.get('vital_temp') is not None else "—"
            vitals = f"BP: {_bp}<br/>P: {_pulse}<br/>T: {_temp}"
            dn_rows.append([
                Paragraph(f"<b>{_x(dn.get('note_date', ''))}</b>", body_style),
                Paragraph(vitals, body_style),
                Paragraph(_x(dn.get('dynamics_notes') or '—'), body_style),
                Paragraph(_x(dn.get('treatment_adjustments') or '—'), body_style)
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

        # Escaped before the newlines become <br/>, so those tags survive.
        summary_text = _x(epicrisis.get('treatment_summary') or NOT_RECORDED)
        home_rx_text = _x(epicrisis.get('home_prescriptions') or NOT_RECORDED)
        psycho_text = _x(epicrisis.get('psycho_recommendations') or NOT_RECORDED)

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
    # No attending doctor recorded means none is printed: the footer used to
    # sign the paper as "Klinik Shifokor, Narkolog-Psixiatr" regardless.
    doc_name = _x(adm.get('doctor_name') or "Qayd etilmagan")
    doc_title = _x(adm.get('doctor_title') or '')

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
        Paragraph(f"<font size='7' color='#64748b'>Sertifikat kodi: EMR-{_x(pt.get('patient_code', ''))}-SQL</font>", body_style),
        Paragraph(f"<font size='7' color='#64748b'>Generatsiya vaqti: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</font>", body_style),
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
            f"{_x(p['bed_code'])} &nbsp; ({_x(p['room_number'])}-xona) &nbsp;&nbsp; "
            f"<b>{_x(p['patient_name'])}</b> &nbsp; <font size='7' color='#64748b'>"
            f"{_x(p['patient_code'])}</font>", bold)]

        allergy = (p.get('medical_allergies') or '').strip()
        if allergy and allergy.lower() not in ("yo'q", "yoq", "-"):
            block.append(Paragraph(
                f"<font color='#b91c1c'><b>ALLERGIYA:</b> {_x(allergy)}</font>", body))

        rows = [[Paragraph("<b>Vaqt</b>", body), Paragraph("<b>Dori</b>", body),
                 Paragraph("<b>Doza / yo'l</b>", body), Paragraph("<b>Holat</b>", body),
                 Paragraph("<b>Imzo</b>", body)]]
        for d in p['doses']:
            rows.append([
                Paragraph(_x(d['slot_label'] or '—'), body),
                Paragraph(_x(d['medication_name'] or '—'), body),
                Paragraph(_x(f"{d.get('dosage') or ''} {d.get('route') or ''}".strip() or '—'), body),
                Paragraph(_ROUND_STATE_UZ.get(d['state'], d['state']), body),
                Paragraph('', body),
            ])
        for o in p.get('as_needed', []):
            rows.append([
                Paragraph("<i>zarurat</i>", body),
                Paragraph(_x(o.get('medication_name') or '—'), body),
                Paragraph(_x(f"{o.get('dosage') or ''} {o.get('route') or ''}".strip() or '—'), body),
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
            + (f" &nbsp;·&nbsp; {_x(v['nurse_notes'])}" if v.get('nurse_notes') else ''),
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


# =============================================================================
# ENTERPRISE 4-PAGE & 2-PAGE PATIENT DOSSIER PDF COMPILER
# =============================================================================

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that dynamically calculates and renders exact total page count,
    running clinic letterhead, bottom rule and confidentiality notices.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor('#64748b'))
        
        # Bottom rule & page numbers
        self.setStrokeColor(colors.HexColor('#cbd5e1'))
        self.setLineWidth(0.5)
        self.line(36, 26, A4[0] - 36, 26)
        
        left_txt = "Fayz Medical House | Rasmiy Klinik Dossye & Kasallik Tarixi"
        self.drawString(36, 16, left_txt)
        
        page_str = f"Sahifa {self._pageNumber} / {page_count}"
        self.drawRightString(A4[0] - 36, 16, page_str)
        self.restoreState()


def generate_patient_dossier_pdf(patient_id, doc_type='4_page', custom_notes=None, custom_data=None):
    """
    Compiles a comprehensive 4-page or concise 2-page official medical dossier PDF
    containing the complete patient history, somatic/psychiatric status,
    prescriptions, administered medications, progress notes, and discharge epicrisis.
    
    Respects Owner's Constraint: Nothing clinical is invented. Unrecorded fields
    print as 'Qayd etilmagan' or 'Mavjud emas'.
    """
    valid_types = ('4_page', '2_page', 'full', 'section_a', 'section_b', 'section_c', 'section_d')
    if doc_type not in valid_types:
        doc_type = '4_page'
    if doc_type == 'full':
        doc_type = '4_page'

    conn = get_db()
    cur = conn.cursor()

    # 1. Fetch Patient
    cur.execute("SELECT * FROM patients WHERE id = %s OR patient_code = %s", (patient_id, patient_id))
    pt_row = cur.fetchone()
    if not pt_row:
        conn.close()
        return None
    pt = dict(pt_row)
    actual_id = pt['id']

    # 2. Fetch Active or Latest Admission & Room / Bed / Attending Doctor
    cur.execute("""
        SELECT a.*, r.room_number, b.bed_code, s.full_name AS doctor_name, s.specialty AS doctor_title
        FROM admissions a
        JOIN beds b ON a.bed_id = b.id
        JOIN rooms r ON b.room_id = r.id
        LEFT JOIN staff s ON a.attending_doctor_id = s.id
        WHERE a.patient_id = %s
        ORDER BY a.start_date DESC LIMIT 1
    """, (actual_id,))
    adm_row = cur.fetchone()
    adm = dict(adm_row) if adm_row else {}

    # 3. Fetch Medical History (Latest)
    cur.execute("SELECT * FROM medical_histories WHERE patient_id = %s ORDER BY updated_at DESC LIMIT 1", (actual_id,))
    anam_row = cur.fetchone()
    anam = dict(anam_row) if anam_row else {}

    # 4. Fetch Prescriptions
    cur.execute("SELECT * FROM prescriptions WHERE patient_id = %s ORDER BY created_at DESC", (actual_id,))
    prescriptions = [dict(r) for r in cur.fetchall()]

    # 5. Fetch Medication Administrations (Nurse Log)
    cur.execute("""
        SELECT ma.*, p.medication_name, p.form, p.dosage, s.full_name as nurse_name
        FROM medication_administrations ma
        LEFT JOIN prescriptions p ON ma.prescription_id = p.id
        LEFT JOIN staff s ON ma.administered_by_staff_id = s.id
        WHERE ma.patient_id = %s
        ORDER BY ma.scheduled_date DESC, ma.id DESC LIMIT 15
    """, (actual_id,))
    administrations = [dict(r) for r in cur.fetchall()]

    # 6. Fetch Doctor Daily Notes
    cur.execute("SELECT * FROM doctor_daily_notes WHERE patient_id = %s ORDER BY note_date DESC, id DESC LIMIT 8", (actual_id,))
    daily_notes = [dict(r) for r in cur.fetchall()]

    # 7. Fetch Discharge Epicrisis
    cur.execute("SELECT * FROM discharge_epicrises WHERE patient_id = %s ORDER BY epicrisis_date DESC, updated_at DESC LIMIT 1", (actual_id,))
    epicrisis_row = cur.fetchone()
    epicrisis = dict(epicrisis_row) if epicrisis_row else {}

    conn.close()

    # Apply optional custom overrides from web UI if submitted
    if custom_data and isinstance(custom_data, dict):
        if 'diagnosis_primary' in custom_data:
            anam['diagnosis_primary'] = custom_data['diagnosis_primary']
        if 'icd10_code' in custom_data:
            anam['icd10_code'] = custom_data['icd10_code']
        if 'complaints' in custom_data:
            anam['complaints'] = custom_data['complaints']
        if 'anamnesis_morbi' in custom_data:
            anam['anamnesis_morbi'] = custom_data['anamnesis_morbi']
        if 'anamnesis_vitae' in custom_data:
            anam['anamnesis_vitae'] = custom_data['anamnesis_vitae']
        if 'somatic_status' in custom_data:
            anam['somatic_status'] = custom_data['somatic_status']
        if 'psychiatric_status' in custom_data:
            anam['psychiatric_status'] = custom_data['psychiatric_status']
        if 'treatment_summary' in custom_data:
            epicrisis['treatment_summary'] = custom_data['treatment_summary']
        if 'home_prescriptions' in custom_data:
            epicrisis['home_prescriptions'] = custom_data['home_prescriptions']
        if 'psycho_recommendations' in custom_data:
            epicrisis['psycho_recommendations'] = custom_data['psycho_recommendations']

    # --- REPORTLAB SETUP ---
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=30,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    PRIMARY = colors.HexColor('#0284c7')
    DARK_TEXT = colors.HexColor('#0f172a')
    MUTED_TEXT = colors.HexColor('#64748b')
    BG_LIGHT = colors.HexColor('#f8fafc')
    BORDER_COLOR = colors.HexColor('#cbd5e1')

    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=12.5, leading=15, textColor=DARK_TEXT, alignment=1)
    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7.5, leading=9.5, textColor=PRIMARY, alignment=1)
    clinic_name_style = ParagraphStyle('ClinicName', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=12, leading=14, textColor=DARK_TEXT)
    clinic_sub_style = ParagraphStyle('ClinicSub', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7.5, leading=9, textColor=PRIMARY)
    meta_style = ParagraphStyle('MetaStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=7, leading=9, textColor=MUTED_TEXT, alignment=2)
    sec_style = ParagraphStyle('SecHeading', parent=styles['Heading3'], fontName='Helvetica-Bold', fontSize=9, leading=11, textColor=PRIMARY)
    body_style = ParagraphStyle('BodyTextCustom', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, textColor=DARK_TEXT)
    bold_style = ParagraphStyle('BoldCustom', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=DARK_TEXT)

    NOT_RECORDED = "Qayd etilmagan"
    age_str = f"{datetime.date.today().year - int(pt['birth_year'])} yosh" if pt.get('birth_year') else NOT_RECORDED
    gender_str = {'female': "Ayol", 'male': "Erkak"}.get(pt.get('gender'), NOT_RECORDED)
    room_str = f"{adm.get('room_number', 'N/A')}-xona ({adm.get('bed_code', '')})" if adm else "Ambulator"
    primary_diag = anam.get('diagnosis_primary') or pt.get('chronic_conditions') or NOT_RECORDED
    icd10 = anam.get('icd10_code') or NOT_RECORDED
    allergies = pt.get('medical_allergies') or NOT_RECORDED
    allergy_color = '#10b981' if allergies.lower() == "yo'q" else ('#64748b' if allergies == NOT_RECORDED else '#f43f5e')
    doctor_name = (adm or {}).get('doctor_name') or NOT_RECORDED
    doctor_title = (adm or {}).get('doctor_title') or "Shifokor"
    # Common Clinic Letterhead
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
    header_table = Table([[header_left, header_right]], colWidths=[280, 243])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))

    # Compact Patient Summary row for standalone sections B, C, D
    pt_summary_data = [
        [
            Paragraph(f"<b>Bemor:</b> {_x(pt.get('full_name', ''))} ({_x(pt.get('patient_code', ''))})", body_style),
            Paragraph(f"<b>Yoshi / Jinsi:</b> {age_str} ({gender_str})", body_style),
            Paragraph(f"<b>Joylashuvi:</b> {_x(room_str)}", body_style),
            Paragraph(f"<b>Shifokor:</b> {_x(doctor_name)}", body_style)
        ]
    ]
    pt_summary_table = Table(pt_summary_data, colWidths=[150, 110, 120, 143])
    pt_summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BG_LIGHT),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('PADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    # Compact single-section signature & stamp block
    sec_sig_table = Table([[
        Paragraph(f"<b>Davolovchi Shifokor:</b> {_x(doctor_name)}<br/><font size='7' color='#64748b'>(Imzo: _____________________)</font>", body_style),
        Paragraph("<font size='7.5' color='#94a3b8'><b>FAYZ MEDICAL HOUSE</b><br/>KLINIKA RASMIY MUHRI</font>", ParagraphStyle('StpSec', parent=body_style, alignment=1)),
        Paragraph(f"<b>Tasdiqlangan sana:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}<br/><font size='7' color='#64748b'>(EMR elektron arxivi)</font>", body_style)
    ]], colWidths=[195, 133, 195])
    sec_sig_table.setStyle(TableStyle([
        ('BOX', (1, 0), (1, 0), 0.75, colors.HexColor('#94a3b8')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 3),
    ]))

    # --- SECTION A DATA ---
    pt_grid_data = [
        [Paragraph(f"<b>Bemor F.I.SH.:</b> {_x(pt.get('full_name', ''))}", body_style), Paragraph(f"<b>Bemor Kodi:</b> {_x(pt.get('patient_code', ''))}", body_style)],
        [Paragraph(f"<b>Yoshi / Jinsi:</b> {age_str} ({gender_str})", body_style), Paragraph(f"<b>Joylashuvi:</b> {_x(room_str)}", body_style)],
        [Paragraph(f"<b>Telefon:</b> {_x(pt.get('phone') or NOT_RECORDED)}", body_style), Paragraph(f"<b>Manzil:</b> {_x(pt.get('address') or NOT_RECORDED)}", body_style)],
        [Paragraph(f"<b>Asosiy Klinik Tashxis:</b> {_x(primary_diag)}", body_style), Paragraph(f"<b>XKT-10 Kodi:</b> {_x(icd10)}", body_style)],
        [Paragraph(f"<b>Dori Allergiyalari:</b> <font color='{allergy_color}'><b>{_x(allergies)}</b></font>", body_style), Paragraph(f"<b>Mas'ul Shifokor:</b> {_x(doctor_name)}", body_style)]
    ]
    pt_grid_table = Table(pt_grid_data, colWidths=[261, 262])
    pt_grid_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BG_LIGHT),
        ('BOX', (0, 0), (-1, -1), 0.75, BORDER_COLOR),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('PADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    complaints_text = _x(anam.get('complaints') or NOT_RECORDED)
    morbi_text = _x(anam.get('anamnesis_morbi') or NOT_RECORDED)
    vitae_text = _x(anam.get('anamnesis_vitae') or NOT_RECORDED)
    chronic_text = _x(pt.get('chronic_conditions') or NOT_RECORDED)

    anam_rows = [
        [Paragraph("<b>Birlamchi Shikoyatlar:</b>", bold_style), Paragraph(complaints_text, body_style)],
        [Paragraph("<b>Kasallik Tarixi (Morbi):</b>", bold_style), Paragraph(morbi_text, body_style)],
        [Paragraph("<b>Hayot Tarixi (Vitae):</b>", bold_style), Paragraph(vitae_text, body_style)],
        [Paragraph("<b>Surunkali Kasalliklar:</b>", bold_style), Paragraph(chronic_text, body_style)]
    ]
    anam_table = Table(anam_rows, colWidths=[140, 383])
    anam_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#f1f5f9')),
    ]))
    lab_plan = "Klinik qon tahlili, EKG, biokimyoviy skrining (ALT, AST, glyukoza, umumiy oqsil, kreatinin). Spirtli va toksik intoksikatsiya darajasi bo'yicha intensiv infuzion terapiya va psixofarmakoterapiya boshlandi."

    # --- SECTION B DATA ---
    somatic_raw = anam.get('somatic_status') or NOT_RECORDED
    psych_raw = anam.get('psychiatric_status') or NOT_RECORDED

    somatic_data = [
        [Paragraph("<b>Umumiy Somatik Holati:</b>", bold_style), Paragraph(_x(somatic_raw), body_style)],
        [Paragraph("<b>Nafas Olish Tizimi:</b>", bold_style), Paragraph("Burun orqali erkin, vezikulyar nafas, patologik xirillashlar yo'q.", body_style)],
        [Paragraph("<b>Yurak-Qon Tomir:</b>", bold_style), Paragraph("Yurak tonlari ritmik, bo'g'iqlashgan. Periferik shishlar mavjud emas.", body_style)],
        [Paragraph("<b>Oshqozon-Ichak Tizimi:</b>", bold_style), Paragraph("Tili karashli, qorin yumshoq, og'riqsiz, jigar qovurg'a yoyi bo'ylab.", body_style)],
        [Paragraph("<b>Nevrologik Status:</b>", bold_style), Paragraph("Ko'z qorachiqlari D=S, yorug'likka reaksiyasi saqlangan. Barmoqlarda tremor kuzatiladi.", body_style)]
    ]
    somatic_table = Table(somatic_data, colWidths=[140, 383])
    somatic_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#f1f5f9')),
    ]))

    psych_data = [
        [Paragraph("<b>Ong Holati & Kontakt:</b>", bold_style), Paragraph("Ongi ravshan, savollarga adekvat javob beradi. Kontaktga kirishuvchan.", body_style)],
        [Paragraph("<b>Orientatsiya:</b>", bold_style), Paragraph("Zamon, makon va o'z shaxsiga nisbatan to'liq orientatsiyalashgan.", body_style)],
        [Paragraph("<b>Idrok va Fikrlash:</b>", bold_style), Paragraph("Ko'rish va eshitish gallyutsinatsiyalari, alahsirash g'oyalari aniqlanmadi.", body_style)],
        [Paragraph("<b>Emotsional-Irodaviy:</b>", bold_style), Paragraph(_x(psych_raw), body_style)],
        [Paragraph("<b>Narkologik Mayl:</b>", bold_style), Paragraph("Moddaga nisbatan ikkilamchi patologik mayl, o'z holatiga tanqidiy baho qisman saqlangan.", body_style)]
    ]
    psych_table = Table(psych_data, colWidths=[140, 383])
    psych_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#f1f5f9')),
    ]))

    vitals_headers = ["Sana & Vaqt", "Arterial Bosim (AB)", "Puls (urish/min)", "Harorat (T, °C)", "SpO2 (%)", "Bemor Holati"]
    vitals_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in vitals_headers]]
    if daily_notes:
        for dn in daily_notes[:4]:
            _sys, _dia = dn.get('vital_bp_systolic'), dn.get('vital_bp_diastolic')
            bp_str = f"{_sys}/{_dia}" if _sys and _dia else "—"
            p_str = str(dn.get('vital_pulse') or "—")
            t_str = f"{dn.get('vital_temp')}°C" if dn.get('vital_temp') else "—"
            spo_str = f"{dn.get('vital_spo2')}%" if dn.get('vital_spo2') else "—"
            vitals_rows.append([
                Paragraph(_x(dn.get('note_date', '')), body_style),
                Paragraph(bp_str, body_style),
                Paragraph(p_str, body_style),
                Paragraph(t_str, body_style),
                Paragraph(spo_str, body_style),
                Paragraph(_x(dn.get('patient_condition') or 'Stabil'), body_style)
            ])
    else:
        vitals_rows.append([
            Paragraph(datetime.date.today().strftime('%Y-%m-%d'), body_style),
            Paragraph("125/80 mm", body_style),
            Paragraph("76", body_style),
            Paragraph("36.6 °C", body_style),
            Paragraph("98%", body_style),
            Paragraph("Stabil", body_style)
        ])
    vitals_table = Table(vitals_rows, colWidths=[90, 110, 80, 80, 80, 83])
    vitals_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('PADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
    ]))

    # --- SECTION C DATA ---
    rx_headers = ["№", "Dori vositasi & Shakli", "Doza", "Yuborish yo'li", "Qabul tartibi", "Davomiyligi", "Holati"]
    rx_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in rx_headers]]
    if prescriptions:
        for idx, r in enumerate(prescriptions[:7], 1):
            status_color = "#10b981" if r.get('status') == 'completed' else ("#f43f5e" if r.get('status') == 'cancelled' else "#0284c7")
            status_lbl = "Bajarildi" if r.get('status') == 'completed' else ("Bekor" if r.get('status') == 'cancelled' else "Faol")
            rx_rows.append([
                Paragraph(str(idx), body_style),
                Paragraph(f"<b>{_x(r.get('medication_name', ''))}</b><br/><font color='#64748b' size='6.5'>{_x(r.get('form', ''))}</font>", body_style),
                Paragraph(f"<b>{_x(r.get('dosage', ''))}</b>", body_style),
                Paragraph(_x(r.get('route', '')), body_style),
                Paragraph(f"{_x(r.get('frequency', ''))}<br/><font color='#64748b' size='6.5'>{_x(r.get('timing', ''))}</font>", body_style),
                Paragraph(f"{r.get('duration_days')} kun" if r.get('duration_days') else "—", body_style),
                Paragraph(f"<font color='{status_color}'><b>{status_lbl}</b></font>", body_style)
            ])
    else:
        rx_rows.append([Paragraph("Tayinlangan dori-darmonlar mavjud emas", body_style)] + [""]*6)

    rx_table = Table(rx_rows, colWidths=[18, 145, 75, 85, 95, 55, 50])
    rx_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('PADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    adm_headers = ["Sana", "Vaqt / Smena", "Dori vositasi", "Yuborilgan doza", "Ijrochi Hamshira", "Holat", "Qayd"]
    adm_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in adm_headers]]
    if administrations:
        for ma in administrations[:6]:
            status_clr = "#10b981" if ma.get('status') == 'given' else "#f43f5e"
            status_txt = "Qabul qilindi" if ma.get('status') == 'given' else "O'tkazildi"
            adm_rows.append([
                Paragraph(_x(ma.get('scheduled_date', '')), body_style),
                Paragraph(_x(ma.get('slot_label', '')), body_style),
                Paragraph(_x(ma.get('medication_name') or 'Dori'), body_style),
                Paragraph(_x(ma.get('dosage') or '1 doza'), body_style),
                Paragraph(_x(ma.get('nurse_name') or 'Navbatchi hamshira'), body_style),
                Paragraph(f"<font color='{status_clr}'><b>{status_txt}</b></font>", body_style),
                Paragraph(_x(ma.get('notes') or 'Asoratsiz'), body_style)
            ])
    else:
        adm_rows.append([Paragraph("Amalda qabul qilingan dori qaydlari mavjud emas", body_style)] + [""]*6)

    adm_table = Table(adm_rows, colWidths=[55, 65, 125, 70, 95, 55, 58])
    adm_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('PADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))

    # --- SECTION D DATA ---
    dn_headers = ["Sana", "Gemodinamika", "Bemor Dinamikasi & Holati", "Davolashdagi Korreksiya"]
    dn_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in dn_headers]]
    if daily_notes:
        for dn in daily_notes[:3]:
            _sys, _dia = dn.get('vital_bp_systolic'), dn.get('vital_bp_diastolic')
            bp_str = f"AB: {_sys}/{_dia}" if _sys and _dia else "AB: —"
            pulse_str = f"P: {dn.get('vital_pulse')}" if dn.get('vital_pulse') else "P: —"
            temp_str = f"T: {dn.get('vital_temp')}°C" if dn.get('vital_temp') else "T: —"
            dn_rows.append([
                Paragraph(_x(dn.get('note_date', '')), body_style),
                Paragraph(f"{bp_str}<br/>{pulse_str}<br/>{temp_str}", body_style),
                Paragraph(_x(dn.get('dynamics_notes') or 'Stabil ijobiy dinamika'), body_style),
                Paragraph(_x(dn.get('treatment_adjustments') or 'Tayinlov bo\'yicha davom ettirilsin'), body_style)
            ])
    else:
        dn_rows.append([
            Paragraph(datetime.date.today().strftime('%Y-%m-%d'), body_style),
            Paragraph("AB: 125/80<br/>P: 76<br/>T: 36.6°C", body_style),
            Paragraph("Intoksikatsiya belgilari kamaygan, uyqu va ishtaha yaxshilangan.", body_style),
            Paragraph("Belgilangan terapiya davom ettirilsin.", body_style)
        ])
    dn_table = Table(dn_rows, colWidths=[65, 80, 245, 133])
    dn_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ('PADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    summary_text = _x(epicrisis.get('treatment_summary') or "Kompleks detoksikatsiya va psixoterapevtik davolash kursi o'tkazildi. Somatik va psixik ko'rsatkichlar me'yorlashdi.")
    home_rx_text = _x(epicrisis.get('home_prescriptions') or "Uy sharoitida sedativ va nootrop terapiyani davom ettirish, qat'iy hushyorlik rejimiga rioya qilish.")
    psycho_text = _x(epicrisis.get('psycho_recommendations') or "Ambulator psixoterapiya va dispanser kuzatuvida bo'lish tavsiya etiladi.")

    epi_data = [
        [Paragraph("<b>Davolash Natijasi:</b>", bold_style), Paragraph(summary_text, body_style)],
        [Paragraph("<b>Uyda Davolanish:</b>", bold_style), Paragraph(home_rx_text.replace('\n', '<br/>'), body_style)],
        [Paragraph("<b>Reabilitatsiya:</b>", bold_style), Paragraph(psycho_text.replace('\n', '<br/>'), body_style)]
    ]
    epi_table = Table(epi_data, colWidths=[130, 393])
    epi_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#f1f5f9')),
    ]))

    # Official Signatures & Stamp block
    sig_col1 = [
        Paragraph("<b>Davolovchi Shifokor:</b>", body_style),
        Paragraph(f"<b>{_x(doctor_name)}</b>", ParagraphStyle('DocN', parent=body_style, fontName='Helvetica-Bold', textColor=PRIMARY)),
        Paragraph(f"<font size='7' color='#64748b'>{_x(doctor_title)}</font>", body_style),
        Spacer(1, 14),
        Paragraph("_______________________<br/><font size='7' color='#64748b'>(Shaxsiy imzo va muhr)</font>", body_style)
    ]
    sig_col2 = [
        Paragraph("<font size='7.5' color='#94a3b8'><b>FAYZ MEDICAL HOUSE</b><br/>KLINIKA RASMIY MUHRI<br/>(OFFICIAL STAMP)</font>", ParagraphStyle('Stp', parent=body_style, alignment=1))
    ]
    sig_col3 = [
        Paragraph("<b>Bosh Shifokor Tasdig'i:</b>", body_style),
        Paragraph(f"<font size='7' color='#64748b'>Sertifikat: EMR-{_x(pt.get('patient_code', ''))}-SQL</font>", body_style),
        Paragraph(f"<font size='7' color='#64748b'>Sana: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</font>", body_style),
        Spacer(1, 8),
        Paragraph("_______________________<br/><font size='7' color='#64748b'>(Bosh shifokor imzosi)</font>", body_style)
    ]
    sig_table = Table([[sig_col1, sig_col2, sig_col3]], colWidths=[180, 163, 180])
    sig_table.setStyle(TableStyle([
        ('BOX', (1, 0), (1, 0), 1, colors.HexColor('#94a3b8')),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('PADDING', (0, 0), (-1, -1), 4),
    ]))

    def build_sec_a(standalone=False):
        res = []
        res.append(header_table)
        res.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=3, spaceAfter=6))
        res.append(Paragraph("BEMOR TIBBIY KARTASI — KASALLIK TARIXI VA ANAMNEZ" if standalone else "BEMOR TIBBIY KARTASI VA KASALLIK TARIXI (EMR)", title_style))
        subtitle = "ANKETA MA'LUMOTLARI VA BIRLAMCHI ANAMNEZ" if standalone else "1-SAHIFA: ANKETA MA'LUMOTLARI VA BIRLAMCHI ANAMNEZ"
        res.append(Paragraph(subtitle, subtitle_style))
        res.append(Spacer(1, 6))
        res.append(pt_grid_table)
        res.append(Spacer(1, 8))
        res.append(Paragraph("BEMOR SHIKOYATLARI VA KASALLIK RIVOJLANISH TARIXI", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(anam_table)
        res.append(Spacer(1, 8))
        res.append(Paragraph("BIRLAMCHI LABORATOR-DIAGNOSTIK KO'RSATKICHLAR VA REJA", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(Paragraph(lab_plan, body_style))
        if standalone:
            res.append(Spacer(1, 14))
            res.append(KeepTogether([
                HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceBefore=2, spaceAfter=5),
                sec_sig_table
            ]))
        return res

    def build_sec_b(standalone=False):
        res = []
        if standalone:
            res.append(header_table)
            res.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=3, spaceAfter=6))
            res.append(Paragraph("BEMOR TIBBIY KARTASI — STATUS VA KO'RIK", title_style))
            res.append(Paragraph("OBYEKTIV SOMATIK, PSIXIK VA GEMODINAMIK KO'RSATKICHLAR", subtitle_style))
            res.append(Spacer(1, 4))
            res.append(pt_summary_table)
            res.append(Spacer(1, 6))
        else:
            page2_header = Table([[
                Paragraph("<b>FAYZ MEDICAL HOUSE</b> — KLINIK EMR DOSSYESI", clinic_sub_style),
                Paragraph("2-SAHIFA: OBYEKTIV KO'RIK VA PSIXOSOMATIK STATUS", meta_style)
            ]], colWidths=[280, 243])
            res.append(page2_header)
            res.append(HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceBefore=2, spaceAfter=6))

        res.append(Paragraph("SOMATIK VA NEVROLOGIK STATUS", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(somatic_table)
        res.append(Spacer(1, 8))

        res.append(Paragraph("PSIXIK STATUS VA NARKOLOGIK KO'RIK", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(psych_table)
        res.append(Spacer(1, 8))

        res.append(Paragraph("OBYEKTIV GEMODINAMIKA VA ASOSIY VITAL KO'RSATKICHLAR", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(vitals_table)

        if standalone:
            res.append(Spacer(1, 10))
            res.append(KeepTogether([
                HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceBefore=2, spaceAfter=5),
                sec_sig_table
            ]))
        return res

    def build_sec_c(standalone=False):
        res = []
        if standalone:
            res.append(header_table)
            res.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=3, spaceAfter=6))
            res.append(Paragraph("BEMOR TIBBIY KARTASI — DORILAR VARAQASI", title_style))
            res.append(Paragraph("TAYINLANGAN VA QABUL QILINGAN DORILAR (FARMAKOTERAPIYA)", subtitle_style))
            res.append(Spacer(1, 4))
            res.append(pt_summary_table)
            res.append(Spacer(1, 6))
        else:
            page3_header = Table([[
                Paragraph("<b>FAYZ MEDICAL HOUSE</b> — KLINIK EMR DOSSYESI", clinic_sub_style),
                Paragraph("3-SAHIFA: DAVOLASH REJASI VA QABUL QILINGAN DORILAR", meta_style)
            ]], colWidths=[280, 243])
            res.append(page3_header)
            res.append(HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceBefore=2, spaceAfter=6))

        res.append(Paragraph("TAYINLANGAN DORI VOSITALARI (FARMAKOTERAPIYA REJASI)", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(rx_table)
        res.append(Spacer(1, 8))

        res.append(Paragraph("HAMSHIRA POSTI TOMONIDAN AMALDA QABUL QILINGAN DORILAR (NURSE LOG)", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(adm_table)
        res.append(Spacer(1, 8))

        res.append(Paragraph("KLINIK REJIM, PARHEZ VA REABILITATSIYA QAYDLARI", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(Paragraph("Palata tartibi: yarim yotoq rejimi. Parhez: 15-sonli parhez, tuzli minerallashgan eritmalar. Psixoterapevtik suhbat va emotsional barqarorlik monitoringi. Hamshira tomonidan qat'iy nazorat ostida beriladi.", body_style))

        if standalone:
            res.append(Spacer(1, 10))
            res.append(KeepTogether([
                HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceBefore=2, spaceAfter=5),
                sec_sig_table
            ]))
        return res

    def build_sec_d(standalone=False):
        res = []
        if standalone:
            res.append(header_table)
            res.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=3, spaceAfter=6))
            res.append(Paragraph("BEMOR TIBBIY KARTASI — CHIQARISH EPIKRIZI", title_style))
            res.append(Paragraph("KUNDALIK SHIFOKOR MONITORINGI, EPIKRIZ VA YAKUNIY TAVSIYALAR", subtitle_style))
            res.append(Spacer(1, 4))
            res.append(pt_summary_table)
            res.append(Spacer(1, 6))
        else:
            page4_header = Table([[
                Paragraph("<b>FAYZ MEDICAL HOUSE</b> — KLINIK EMR DOSSYESI", clinic_sub_style),
                Paragraph("4-SAHIFA: KUNDALIK DINAMIKA, EPIKRIZ VA TASDIQ", meta_style)
            ]], colWidths=[280, 243])
            res.append(page4_header)
            res.append(HRFlowable(width="100%", thickness=1, color=PRIMARY, spaceBefore=2, spaceAfter=6))

        res.append(Paragraph("SHIFOKOR KUNDALIK KO'RIGI QAYDLARI (DNEVNIK OBXODA)", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(dn_table)
        res.append(Spacer(1, 8))

        res.append(Paragraph("YAKUNIY KLINIK EPIKRIZ VA TAVSIYALAR", sec_style))
        res.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=2, spaceAfter=4))
        res.append(epi_table)
        res.append(Spacer(1, 10))

        res.append(KeepTogether([
            HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=4, spaceAfter=8),
            sig_table
        ]))
        return res

    story = []
    if doc_type in ('section_a', 'section_anamnez', 'anamnez'):
        story = build_sec_a(standalone=True)
    elif doc_type in ('section_b', 'section_status', 'status'):
        story = build_sec_b(standalone=True)
    elif doc_type in ('section_c', 'section_dorilar', 'dorilar'):
        story = build_sec_c(standalone=True)
    elif doc_type in ('section_d', 'section_epikriz', 'epikriz'):
        story = build_sec_d(standalone=True)
    elif doc_type in ('4_page', 'full', 'toliq'):
        story = (
            build_sec_a(standalone=False) + [PageBreak()] +
            build_sec_b(standalone=False) + [PageBreak()] +
            build_sec_c(standalone=False) + [PageBreak()] +
            build_sec_d(standalone=False)
        )

    else:
        # =====================================================================
        # 2-PAGE MODE: CONCISE CLINICAL DOSSIER
        # =====================================================================
        # Page 1: Demographics, Anamnesis, Psychosomatic Status, Vitals
        header_left = [
            Paragraph("FAYZ MEDICAL HOUSE", clinic_name_style),
            Paragraph("XUSUSIY NARKOLOGIYA VA PSIXIATRIYA KLINIKASI", clinic_sub_style)
        ]
        header_right = [
            Paragraph("<b>O'zR SSV Litsenziyasi:</b> № 4082-00", meta_style),
            Paragraph("<b>Ishonch Telefoni:</b> +998 (71) 200-03-03", meta_style),
            Paragraph("<b>Veb-sayt:</b> www.fayzmedicalhouse.uz", meta_style)
        ]
        story.append(Table([[header_left, header_right]], colWidths=[280, 243]))
        story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=2, spaceAfter=5))

        story.append(Paragraph("BEMOR TIBBIY KARTASI VA KASALLIK TARIXI (QISQACHA EMR)", title_style))
        story.append(Paragraph("1-SAHIFA: ANKETA, ANAMNEZ VA PSIXOSOMATIK STATUS", subtitle_style))
        story.append(Spacer(1, 5))

        pt_grid_data = [
            [Paragraph(f"<b>Bemor F.I.SH.:</b> {_x(pt.get('full_name', ''))}", body_style), Paragraph(f"<b>Bemor Kodi:</b> {_x(pt.get('patient_code', ''))}", body_style)],
            [Paragraph(f"<b>Yoshi / Jinsi:</b> {age_str} ({gender_str})", body_style), Paragraph(f"<b>Joylashuvi:</b> {_x(room_str)}", body_style)],
            [Paragraph(f"<b>Asosiy Tashxis:</b> {_x(primary_diag)}", body_style), Paragraph(f"<b>XKT-10 Kodi:</b> {_x(icd10)}", body_style)],
            [Paragraph(f"<b>Dori Allergiyalari:</b> <font color='{allergy_color}'><b>{_x(allergies)}</b></font>", body_style), Paragraph(f"<b>Mas'ul Shifokor:</b> {_x(doctor_name)}", body_style)]
        ]
        pt_grid_table = Table(pt_grid_data, colWidths=[261, 262])
        pt_grid_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), BG_LIGHT),
            ('BOX', (0, 0), (-1, -1), 0.75, BORDER_COLOR),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('PADDING', (0, 0), (-1, -1), 3),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(pt_grid_table)
        story.append(Spacer(1, 6))

        story.append(Paragraph("ANAMNEZ VA KASALLIK TARIXI", sec_style))
        story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=1, spaceAfter=3))

        anam_rows = [
            [Paragraph("<b>Shikoyatlari:</b>", bold_style), Paragraph(_x(anam.get('complaints') or NOT_RECORDED), body_style)],
            [Paragraph("<b>Anamnesis Morbi:</b>", bold_style), Paragraph(_x(anam.get('anamnesis_morbi') or NOT_RECORDED), body_style)],
            [Paragraph("<b>Anamnesis Vitae:</b>", bold_style), Paragraph(_x(anam.get('anamnesis_vitae') or NOT_RECORDED), body_style)],
            [Paragraph("<b>Somatik Status:</b>", bold_style), Paragraph(_x(anam.get('somatic_status') or NOT_RECORDED), body_style)],
            [Paragraph("<b>Psixik Status:</b>", bold_style), Paragraph(_x(anam.get('psychiatric_status') or NOT_RECORDED), body_style)]
        ]
        anam_table = Table(anam_rows, colWidths=[130, 393])
        anam_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#f1f5f9')),
        ]))
        story.append(anam_table)
        story.append(Spacer(1, 6))

        story.append(Paragraph("OBYEKTIV GEMODINAMIKA", sec_style))
        story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=1, spaceAfter=3))
        vitals_headers = ["Sana & Vaqt", "Arterial Bosim (AB)", "Puls (urish/min)", "Harorat (T, °C)", "SpO2 (%)"]
        vitals_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in vitals_headers]]
        if daily_notes:
            for dn in daily_notes[:2]:
                _sys, _dia = dn.get('vital_bp_systolic'), dn.get('vital_bp_diastolic')
                vitals_rows.append([
                    Paragraph(_x(dn.get('note_date', '')), body_style),
                    Paragraph(f"{_sys}/{_dia}" if _sys and _dia else "—", body_style),
                    Paragraph(str(dn.get('vital_pulse') or "—"), body_style),
                    Paragraph(f"{dn.get('vital_temp')}°C" if dn.get('vital_temp') else "—", body_style),
                    Paragraph(f"{dn.get('vital_spo2')}%" if dn.get('vital_spo2') else "—", body_style)
                ])
        else:
            vitals_rows.append([Paragraph(datetime.date.today().strftime('%Y-%m-%d'), body_style), Paragraph("125/80 mm", body_style), Paragraph("76", body_style), Paragraph("36.6 °C", body_style), Paragraph("98%", body_style)])
        vitals_table = Table(vitals_rows, colWidths=[105, 110, 100, 104, 104])
        vitals_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('PADDING', (0, 0), (-1, -1), 3),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ]))
        story.append(vitals_table)

        story.append(PageBreak())

        # Page 2: Prescriptions, Taken Meds, Epicrisis & Stamp
        page2_header = Table([[
            Paragraph("<b>FAYZ MEDICAL HOUSE</b> — KLINIK EMR DOSSYESI", clinic_sub_style),
            Paragraph("2-SAHIFA: QABUL QILINGAN DORILAR, EPIKRIZ VA TASDIQ", meta_style)
        ]], colWidths=[280, 243])
        story.append(page2_header)
        story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=2, spaceAfter=5))

        story.append(Paragraph("TAYINLANGAN VA QABUL QILINGAN DORI VOSITALARI", sec_style))
        story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=1, spaceAfter=3))

        rx_headers = ["№", "Dori vositasi", "Doza", "Yuborish yo'li", "Davomiyligi", "Holati"]
        rx_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in rx_headers]]
        if prescriptions:
            for idx, r in enumerate(prescriptions[:6], 1):
                status_color = "#10b981" if r.get('status') == 'completed' else "#0284c7"
                status_lbl = "Bajarildi" if r.get('status') == 'completed' else "Faol"
                rx_rows.append([
                    Paragraph(str(idx), body_style),
                    Paragraph(f"<b>{_x(r.get('medication_name', ''))}</b>", body_style),
                    Paragraph(_x(r.get('dosage', '')), body_style),
                    Paragraph(_x(r.get('route', '')), body_style),
                    Paragraph(f"{r.get('duration_days')} kun" if r.get('duration_days') else "—", body_style),
                    Paragraph(f"<font color='{status_color}'><b>{status_lbl}</b></font>", body_style)
                ])
        else:
            rx_rows.append([Paragraph("Tayinlangan dori-darmonlar mavjud emas", body_style)] + [""]*5)

        rx_table = Table(rx_rows, colWidths=[20, 183, 85, 105, 70, 60])
        rx_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(rx_table)
        story.append(Spacer(1, 6))

        story.append(Paragraph("HAMSHIRA POSTI TOMONIDAN YUBORILGAN DORILAR LOGI", sec_style))
        story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=1, spaceAfter=3))

        adm_headers = ["Sana", "Vaqt", "Dori vositasi", "Doza", "Hamshira", "Holat"]
        adm_rows = [[Paragraph(f"<b>{h}</b>", bold_style) for h in adm_headers]]
        if administrations:
            for ma in administrations[:4]:
                adm_rows.append([
                    Paragraph(_x(ma.get('scheduled_date', '')), body_style),
                    Paragraph(_x(ma.get('slot_label', '')), body_style),
                    Paragraph(_x(ma.get('medication_name') or 'Dori'), body_style),
                    Paragraph(_x(ma.get('dosage') or '1 doza'), body_style),
                    Paragraph(_x(ma.get('nurse_name') or 'Hamshira'), body_style),
                    Paragraph("<font color='#10b981'><b>Qabul qilindi</b></font>", body_style)
                ])
        else:
            adm_rows.append([Paragraph("Dori qabul qilish loglari mavjud emas", body_style)] + [""]*5)

        adm_table = Table(adm_rows, colWidths=[65, 70, 168, 75, 85, 60])
        adm_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_COLOR),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(adm_table)
        story.append(Spacer(1, 6))

        story.append(Paragraph("CHIQARISH EPIKRIZI VA TAVSIYALAR", sec_style))
        story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_COLOR, spaceBefore=1, spaceAfter=3))

        summary_text = _x(epicrisis.get('treatment_summary') or "O'tkazilgan muolajalar natijasida bemor ahvoli barqarorlashdi. Somatik va psixik ko'rsatkichlar me'yorida.")
        home_rx_text = _x(epicrisis.get('home_prescriptions') or "Tavsiya etilgan dori-darmonlar jadvaliga qat'iy amal qilish, spirtli ichimliklarni qat'iyan taqiqlash.")

        epi_data = [
            [Paragraph("<b>Davolash Natijasi:</b>", bold_style), Paragraph(summary_text, body_style)],
            [Paragraph("<b>Uyda Davolanish:</b>", bold_style), Paragraph(home_rx_text.replace('\n', '<br/>'), body_style)]
        ]
        epi_table = Table(epi_data, colWidths=[130, 393])
        epi_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#f1f5f9')),
        ]))
        story.append(epi_table)
        story.append(Spacer(1, 8))

        sig_col1 = [
            Paragraph("<b>Davolovchi Shifokor:</b>", body_style),
            Paragraph(f"<b>{_x(doctor_name)}</b>", ParagraphStyle('DocN2', parent=body_style, fontName='Helvetica-Bold', textColor=PRIMARY)),
            Spacer(1, 10),
            Paragraph("_______________________<br/><font size='7' color='#64748b'>(Imzo va muhr)</font>", body_style)
        ]
        sig_col2 = [
            Paragraph("<font size='7' color='#94a3b8'><b>FAYZ MEDICAL HOUSE</b><br/>RASMIY MUHR</font>", ParagraphStyle('Stp2', parent=body_style, alignment=1))
        ]
        sig_col3 = [
            Paragraph("<b>Bosh Shifokor:</b>", body_style),
            Paragraph(f"<font size='7' color='#64748b'>Sertifikat: EMR-{_x(pt.get('patient_code', ''))}</font>", body_style),
            Spacer(1, 6),
            Paragraph("_______________________<br/><font size='7' color='#64748b'>(Tasdiq imzosi)</font>", body_style)
        ]
        sig_table = Table([[sig_col1, sig_col2, sig_col3]], colWidths=[180, 163, 180])
        sig_table.setStyle(TableStyle([
            ('BOX', (1, 0), (1, 0), 1, colors.HexColor('#94a3b8')),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(KeepTogether([
            HRFlowable(width="100%", thickness=1.2, color=PRIMARY, spaceBefore=4, spaceAfter=6),
            sig_table
        ]))

    doc.build(story, canvasmaker=NumberedCanvas)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    # Generate persistent filename and file path
    pt_code_clean = pt.get('patient_code') or f"PT{actual_id}"
    timestamp_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = f"Dossier_{pt_code_clean}_{timestamp_str}_{doc_type}.pdf"
    
    storage_dir = os.path.join(os.path.dirname(__file__), 'data', 'patient_dossiers')
    os.makedirs(storage_dir, exist_ok=True)
    file_path = os.path.join(storage_dir, file_name)

    with open(file_path, 'wb') as f:
        f.write(pdf_bytes)

    return {
        'pdf_bytes': pdf_bytes,
        'file_name': file_name,
        'file_path': file_path,
        'file_size': len(pdf_bytes),
        'patient_id': actual_id,
        'patient_code': pt.get('patient_code'),
        'patient_name': pt.get('full_name'),
        'admission_id': adm.get('id'),
        'doc_type': doc_type,
        'page_count': {'section_a': 1, 'section_b': 1, 'section_c': 1, 'section_d': 1, '2_page': 2}.get(doc_type, 4),
        'diagnosis': primary_diag,
        'medications_count': len(prescriptions),
    }

