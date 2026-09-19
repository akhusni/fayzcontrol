"""
Fayz Medical House — Consultation Intake & Treatment Plan

A structured narcology/psychiatry intake in six sections, and the treatment
plan kept deliberately apart from it.

Why two tables
--------------
The plan is stored, versioned and printed on its own, separate from the
intake. That is not a filing preference: the intake is what the patient
reported and the doctor observed at one moment, and it should not change
afterwards, while the plan is a live instruction that gets revised as the
patient responds. Keeping them in one row would mean either rewriting history
every time the plan changed, or freezing the plan.

So `consultations` is the record of the encounter, and `treatment_plans`
points at it. A consultation can accumulate several plans over time; the
latest active one is what the ward works from, and each can be printed by
itself.

Relationship to medical_histories
---------------------------------
medical_histories already holds the inpatient anamnesis the existing EMR reads
(complaints, anamnesis morbi/vitae, somatic and psychiatric status, ICD-10) and
the A4 blank is generated from it. The intake here is richer and differently
shaped, so it gets its own table — but the fields the two genuinely share are
mirrored across on save, so the existing history tab and the printed blank keep
working instead of silently going stale.
"""

import json
import datetime as _dt

TREATMENT_BASIS = ('voluntary', 'family_initiated', 'court_mandated')
RISK_LEVELS = ('none', 'low', 'moderate', 'high')
PLAN_TYPES = ('outpatient', 'detox', 'inpatient', 'rehab', 'referral')
PLAN_STATUSES = ('draft', 'active', 'completed', 'superseded')

_schema_checked = False


def ensure_schema(conn):
    """Create both tables if absent. Runtime check, like the other modules."""
    global _schema_checked
    if _schema_checked:
        return
    try:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS consultations (
                id VARCHAR(64) PRIMARY KEY,
                patient_id VARCHAR(64) NOT NULL,
                doctor_id VARCHAR(64),
                appointment_id VARCHAR(64),
                consultation_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

                -- 1. Patient profile & logistics
                date_of_birth DATE,
                emergency_contact_name VARCHAR(255),
                emergency_contact_phone VARCHAR(64),
                emergency_contact_relation VARCHAR(128),
                living_situation TEXT,
                -- Whether the patient came of their own accord matters
                -- clinically and legally: consent, discharge rights and
                -- reporting obligations all differ.
                treatment_basis VARCHAR(32) NOT NULL DEFAULT 'voluntary'
                    CHECK(treatment_basis IN ('voluntary', 'family_initiated', 'court_mandated')),
                court_reference VARCHAR(255),

                -- 2. The core issue
                primary_complaint TEXT,
                onset_date DATE,
                onset_note TEXT,
                triggers TEXT,

                -- 3. Substance use log
                -- One row per substance, held as JSON: the number and kind of
                -- substances vary per patient, and a fixed set of columns
                -- would either truncate a polysubstance history or sit empty.
                substances JSON,
                overdose_count INT,
                overdose_history TEXT,
                withdrawal_history TEXT,
                -- Called out on its own because a seizure history changes the
                -- detox protocol immediately.
                seizure_history TINYINT(1) NOT NULL DEFAULT 0
                    CHECK(seizure_history IN (0, 1)),
                prior_rehab_attempts INT,
                prior_rehab_detail TEXT,

                -- 4. Psychiatric & medical background
                prior_psych_diagnoses TEXT,
                prior_psych_hospitalizations TEXT,
                self_harm_flag TINYINT(1) NOT NULL DEFAULT 0
                    CHECK(self_harm_flag IN (0, 1)),
                self_harm_history TEXT,
                current_medications TEXT,
                drug_allergies TEXT,
                head_trauma TEXT,
                infectious_diseases TEXT,
                other_medical TEXT,

                -- 5. Family & social context
                family_history_addiction TEXT,
                family_history_depression TEXT,
                family_history_other TEXT,
                employment_status VARCHAR(128),
                relationship_status VARCHAR(128),
                support_network TEXT,

                -- 6. Clinical assessment
                observed_mood TEXT,
                observed_thought TEXT,
                observed_behaviour TEXT,
                risk_to_self VARCHAR(16) NOT NULL DEFAULT 'none'
                    CHECK(risk_to_self IN ('none', 'low', 'moderate', 'high')),
                risk_to_others VARCHAR(16) NOT NULL DEFAULT 'none'
                    CHECK(risk_to_others IN ('none', 'low', 'moderate', 'high')),
                risk_notes TEXT,
                working_diagnosis TEXT,
                icd10_code VARCHAR(32),

                status VARCHAR(16) NOT NULL DEFAULT 'final'
                    CHECK(status IN ('draft', 'final')),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_cons_patient (patient_id, consultation_date),
                KEY idx_cons_doctor (doctor_id, consultation_date),
                FOREIGN KEY (patient_id) REFERENCES patients(id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY (doctor_id) REFERENCES staff(id)
                    ON UPDATE CASCADE ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS treatment_plans (
                id VARCHAR(64) PRIMARY KEY,
                consultation_id VARCHAR(64),
                patient_id VARCHAR(64) NOT NULL,
                doctor_id VARCHAR(64),
                plan_date DATE NOT NULL,
                plan_type VARCHAR(32) NOT NULL DEFAULT 'outpatient'
                    CHECK(plan_type IN ('outpatient', 'detox', 'inpatient', 'rehab', 'referral')),
                -- The clinical instruction.
                immediate_actions TEXT,
                detox_protocol TEXT,
                -- Recommended medication, kept apart from the prescriptions
                -- table on purpose: this is the doctor's proposal on the plan,
                -- and a prescription is a live order the nurse acts on. One
                -- becomes the other only when the doctor prescribes it.
                medication_plan JSON,
                therapy_plan TEXT,
                duration_days INT,
                review_date DATE,
                goals TEXT,
                precautions TEXT,
                status VARCHAR(16) NOT NULL DEFAULT 'active'
                    CHECK(status IN ('draft', 'active', 'completed', 'superseded')),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_plan_patient (patient_id, plan_date),
                KEY idx_plan_consultation (consultation_id),
                FOREIGN KEY (consultation_id) REFERENCES consultations(id)
                    ON UPDATE CASCADE ON DELETE SET NULL,
                FOREIGN KEY (patient_id) REFERENCES patients(id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY (doctor_id) REFERENCES staff(id)
                    ON UPDATE CASCADE ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        _schema_checked = True
    except Exception as e:
        print(f"[!] Could not prepare consultation tables: {e}")
        _schema_checked = True


# ---------------------------------------------------------------------------
# Field map — one place that defines the intake
# ---------------------------------------------------------------------------
# Grouped as the six sections so the API, the form and the printed record all
# read from the same definition rather than three drifting copies.

# Each field is (name, kind, label, hint). The labels live here rather than in
# the page so the form, the validator and the printed record cannot drift
# apart — a clinical form of this size will be revised, and three copies of the
# field list would be three chances to forget one.
SECTIONS = [
    ('profile', "1. Bemor ma'lumotlari va sharoiti", [
        ('date_of_birth', 'date', "Tug'ilgan sana", ''),
        ('emergency_contact_name', 'text', 'Favqulodda aloqa: F.I.SH.', ''),
        ('emergency_contact_phone', 'text', 'Favqulodda aloqa: telefon', '+998 __ ___ __ __'),
        ('emergency_contact_relation', 'text', 'Kim bo\'ladi', "Turmush o'rtog'i, aka, ona..."),
        ('living_situation', 'textarea', 'Yashash sharoiti', 'Kim bilan, qanday sharoitda yashaydi'),
        ('treatment_basis', 'choice', 'Davolash asosi', ''),
        ('court_reference', 'text', 'Sud qarori raqami', 'Faqat sud qarori bilan bo\'lsa'),
    ]),
    ('issue', '2. Asosiy muammo', [
        ('primary_complaint', 'textarea', 'Murojaat sababi (asosiy shikoyat)', 'Bugun nima uchun keldi'),
        ('onset_date', 'date', 'Belgilar / retsidiv boshlangan sana', ''),
        ('onset_note', 'textarea', 'Boshlanishi haqida izoh', 'Qanday boshlandi, qanday kechdi'),
        ('triggers', 'textarea', 'Sabab bo\'lgan hodisalar (triggerlar)', 'Ish, oila, yo\'qotish, qarz...'),
    ]),
    ('substances', '3. Giyohvand moddalar / alkogol tarixi', [
        ('substances', 'substances', 'Qo\'llanilgan moddalar', ''),
        ('overdose_count', 'int', 'Overdoz holatlari soni', ''),
        ('overdose_history', 'textarea', 'Overdoz tarixi', 'Qachon, qanday, oqibati'),
        ('withdrawal_history', 'textarea', 'Abstinensiya (lomka) tarixi', 'Qanchalik og\'ir kechgan'),
        ('seizure_history', 'bool', 'Tutqanoq / talvasa bo\'lganmi', 'Detoks protokolini o\'zgartiradi'),
        ('prior_rehab_attempts', 'int', 'Avvalgi reabilitatsiya urinishlari', ''),
        ('prior_rehab_detail', 'textarea', 'Reabilitatsiya tafsiloti', 'Qayerda, qancha, natija'),
    ]),
    ('background', '4. Psixiatrik va tibbiy anamnez', [
        ('prior_psych_diagnoses', 'textarea', 'Avvalgi psixiatrik tashxislar', ''),
        ('prior_psych_hospitalizations', 'textarea', 'Psixiatrik statsionarda yotganmi', 'Qachon, qancha vaqt'),
        ('self_harm_flag', 'bool', 'O\'ziga zarar yetkazish tarixi bormi', ''),
        ('self_harm_history', 'textarea', 'O\'ziga zarar: tafsilot', ''),
        ('current_medications', 'textarea', 'Hozirda qabul qilayotgan dorilar', ''),
        ('drug_allergies', 'textarea', 'Dori allergiyalari', "Yo'q bo'lsa: Yo'q"),
        ('head_trauma', 'textarea', 'Bosh miya jarohati', ''),
        ('infectious_diseases', 'textarea', 'Yuqumli kasalliklar', 'OIV, HBV, HCV, sil...'),
        ('other_medical', 'textarea', 'Boshqa somatik holatlar', ''),
    ]),
    ('social', '5. Oila va ijtimoiy muhit', [
        ('family_history_addiction', 'textarea', 'Oilada qaramlik bormi', ''),
        ('family_history_depression', 'textarea', 'Oilada depressiya bormi', ''),
        ('family_history_other', 'textarea', 'Oilada boshqa ruhiy kasalliklar', ''),
        ('employment_status', 'text', 'Ish holati', 'Ishlaydi / ishsiz / nafaqada'),
        ('relationship_status', 'text', 'Oilaviy holati', 'Turmush qurgan, ziddiyatli...'),
        ('support_network', 'textarea', 'Kimga tayanadi (support network)', 'Ishonchli yaqinlari'),
    ]),
    ('assessment', '6. Klinik baholash', [
        ('observed_mood', 'textarea', 'Kayfiyat (kuzatuv)', 'Suhbat vaqtidagi holati'),
        ('observed_thought', 'textarea', 'Tafakkur / mantiq (kuzatuv)', ''),
        ('observed_behaviour', 'textarea', 'Xulq-atvor (kuzatuv)', ''),
        ('risk_to_self', 'choice', 'O\'ziga xavf darajasi', ''),
        ('risk_to_others', 'choice', 'Atrofdagilarga xavf darajasi', ''),
        ('risk_notes', 'textarea', 'Xavf bo\'yicha izoh', ''),
        ('working_diagnosis', 'textarea', 'Ishchi tashxis', ''),
        ('icd10_code', 'text', 'XKT-10 kodi', 'F10.2, F11.2...'),
    ]),
]

FIELD_TYPES = {f[0]: f[1] for _k, _label, fields in SECTIONS for f in fields}
ALL_FIELDS = list(FIELD_TYPES)


def next_id(prefix):
    return f"{prefix}-{_dt.datetime.now().strftime('%Y%m%d%H%M%S%f')[:20]}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def clean_intake(body):
    """
    Coerce and check an intake payload.

    Returns (values, error). Only the clinically consequential fields are
    constrained — the narrative fields are free text by nature and a doctor
    should not be fighting a form mid-consultation.
    """
    values = {}
    today = _dt.date.today()

    for name, kind in FIELD_TYPES.items():
        raw = body.get(name)

        if kind == 'date':
            if raw in (None, ''):
                values[name] = None
                continue
            try:
                parsed = _dt.date.fromisoformat(str(raw)[:10])
            except Exception:
                return None, f"'{name}' sanasi noto'g'ri formatda (YYYY-MM-DD kutilgan)."
            if name == 'date_of_birth':
                if parsed > today:
                    return None, "Tug'ilgan sana kelajakda bo'lishi mumkin emas."
                if parsed.year < today.year - 130:
                    return None, "Tug'ilgan sana haqiqiy emas."
            if name == 'onset_date' and parsed > today:
                return None, "Belgilar boshlangan sana kelajakda bo'lishi mumkin emas."
            values[name] = parsed.isoformat()

        elif kind == 'int':
            if raw in (None, ''):
                values[name] = None
                continue
            try:
                n = int(raw)
            except Exception:
                return None, f"'{name}' butun son bo'lishi kerak."
            if n < 0:
                return None, f"'{name}' manfiy bo'lishi mumkin emas."
            values[name] = n

        elif kind == 'bool':
            values[name] = 1 if raw in (True, 1, '1', 'true', 'on', 'yes') else 0

        elif kind == 'choice':
            allowed = {
                'treatment_basis': TREATMENT_BASIS,
                'risk_to_self': RISK_LEVELS,
                'risk_to_others': RISK_LEVELS,
            }[name]
            value = (str(raw).strip().lower() if raw else allowed[0])
            if value not in allowed:
                return None, f"'{name}' qiymati noto'g'ri. Ruxsat etilgan: {', '.join(allowed)}."
            values[name] = value

        elif kind in ('json', 'substances'):
            if raw in (None, '', []):
                values[name] = None
                continue
            if not isinstance(raw, list):
                return None, f"'{name}' ro'yxat bo'lishi kerak."
            cleaned = []
            for item in raw:
                if not isinstance(item, dict):
                    return None, f"'{name}' ichidagi har bir yozuv obyekt bo'lishi kerak."
                if not (item.get('substance') or '').strip():
                    return None, "Har bir modda uchun nomi ko'rsatilishi shart."
                entry = {
                    'substance': str(item.get('substance')).strip()[:128],
                    'age_first_use': item.get('age_first_use'),
                    'peak_daily_amount': str(item.get('peak_daily_amount') or '')[:128],
                    'last_use_date': str(item.get('last_use_date') or '')[:10],
                    'route': str(item.get('route') or '')[:64],
                }
                if entry['age_first_use'] not in (None, ''):
                    try:
                        age = int(entry['age_first_use'])
                    except Exception:
                        return None, "Birinchi qo'llash yoshi son bo'lishi kerak."
                    if not (0 <= age <= 120):
                        return None, "Birinchi qo'llash yoshi haqiqiy emas."
                    entry['age_first_use'] = age
                else:
                    entry['age_first_use'] = None
                cleaned.append(entry)
            values[name] = json.dumps(cleaned, ensure_ascii=False)

        else:  # free text
            if raw in (None, ''):
                values[name] = None
            else:
                values[name] = str(raw).strip()

    # A court-mandated admission without its reference cannot be substantiated
    # later, which is exactly when it matters.
    if values.get('treatment_basis') == 'court_mandated' and not values.get('court_reference'):
        return None, ("Sud qarori bilan davolash uchun qaror raqami "
                      "ko'rsatilishi shart.")

    if not values.get('primary_complaint'):
        return None, "Asosiy shikoyat (murojaat sababi) kiritilishi shart."

    return values, None


def save_intake(conn, patient_id, doctor_id, values, appointment_id=None,
                status='final'):
    """Insert one consultation and mirror the shared fields into the EMR."""
    ensure_schema(conn)
    cid = next_id('CONS')
    cols = ['id', 'patient_id', 'doctor_id', 'appointment_id', 'status'] + ALL_FIELDS
    params = [cid, patient_id, doctor_id, appointment_id, status] + \
             [values.get(f) for f in ALL_FIELDS]
    marks = ', '.join(['?'] * len(cols))
    cur = conn.cursor()
    cur.execute(f"INSERT INTO consultations ({', '.join(cols)}) VALUES ({marks})",
                tuple(params))
    _mirror_to_medical_history(conn, cid, patient_id, doctor_id, values)
    conn.commit()
    return cid


def _mirror_to_medical_history(conn, consultation_id, patient_id, doctor_id, values):
    """
    Copy across the fields medical_histories genuinely shares.

    The existing EMR history tab and the A4 blank read from that table. Without
    this the new intake would be invisible to both, and a doctor printing a
    blank would get a form with no diagnosis on it.
    """
    try:
        cur = conn.cursor()
        allergies = values.get('drug_allergies') or "Yo'q"
        psychiatric = ' | '.join(filter(None, [
            values.get('observed_mood'),
            values.get('observed_thought'),
            values.get('observed_behaviour'),
        ])) or None
        morbi = ' | '.join(filter(None, [
            values.get('onset_note'),
            values.get('triggers'),
            values.get('withdrawal_history'),
        ])) or None
        vitae = ' | '.join(filter(None, [
            values.get('living_situation'),
            values.get('employment_status'),
            values.get('support_network'),
            values.get('family_history_addiction'),
        ])) or None

        cur.execute("""
            INSERT INTO medical_histories
                (id, patient_id, doctor_id, complaints, anamnesis_morbi,
                 anamnesis_vitae, allergic_status, somatic_status,
                 psychiatric_status, diagnosis_primary, icd10_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                complaints = VALUES(complaints),
                anamnesis_morbi = VALUES(anamnesis_morbi),
                anamnesis_vitae = VALUES(anamnesis_vitae),
                allergic_status = VALUES(allergic_status),
                somatic_status = VALUES(somatic_status),
                psychiatric_status = VALUES(psychiatric_status),
                diagnosis_primary = VALUES(diagnosis_primary),
                icd10_code = VALUES(icd10_code)
        """, (
            'MH-' + consultation_id, patient_id, doctor_id,
            values.get('primary_complaint'), morbi, vitae, allergies,
            ' | '.join(filter(None, [values.get('head_trauma'),
                                     values.get('infectious_diseases'),
                                     values.get('other_medical')])) or None,
            psychiatric, values.get('working_diagnosis'), values.get('icd10_code'),
        ))
    except Exception as e:
        # The consultation itself is the record of truth; a failed mirror is
        # worth knowing about but must not lose the doctor's work.
        print(f"[!] Could not mirror consultation {consultation_id} to medical_histories: {e}")


def get_intake(conn, consultation_id):
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT c.*, p.full_name AS patient_name, p.patient_code, p.phone AS patient_phone,
               p.gender, s.full_name AS doctor_name, s.specialty AS doctor_specialty
        FROM consultations c
        JOIN patients p ON p.id = c.patient_id
        LEFT JOIN staff s ON s.id = c.doctor_id
        WHERE c.id = ?
    """, (consultation_id,))
    row = cur.fetchone()
    if not row:
        return None
    data = dict(row)
    if data.get('substances'):
        try:
            data['substances'] = json.loads(data['substances'])
        except Exception:
            pass
    return data


def list_for_patient(conn, patient_id):
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.consultation_date, c.working_diagnosis, c.icd10_code,
               c.treatment_basis, c.risk_to_self, c.risk_to_others, c.status,
               s.full_name AS doctor_name
        FROM consultations c
        LEFT JOIN staff s ON s.id = c.doctor_id
        WHERE c.patient_id = ?
        ORDER BY c.consultation_date DESC
    """, (patient_id,))
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Treatment plan
# ---------------------------------------------------------------------------

def clean_plan(body):
    """Coerce and check a treatment plan payload."""
    plan_type = (str(body.get('plan_type') or 'outpatient')).strip().lower()
    if plan_type not in PLAN_TYPES:
        return None, f"Reja turi noto'g'ri. Ruxsat etilgan: {', '.join(PLAN_TYPES)}."

    status = (str(body.get('status') or 'active')).strip().lower()
    if status not in PLAN_STATUSES:
        return None, f"Reja holati noto'g'ri. Ruxsat etilgan: {', '.join(PLAN_STATUSES)}."

    today = _dt.date.today()
    plan_date = body.get('plan_date')
    try:
        plan_date = _dt.date.fromisoformat(str(plan_date)[:10]) if plan_date else today
    except Exception:
        return None, "Reja sanasi noto'g'ri formatda (YYYY-MM-DD kutilgan)."

    review_date = body.get('review_date')
    if review_date:
        try:
            review_date = _dt.date.fromisoformat(str(review_date)[:10])
        except Exception:
            return None, "Qayta ko'rik sanasi noto'g'ri formatda."
        if review_date < plan_date:
            return None, "Qayta ko'rik sanasi reja sanasidan oldin bo'lishi mumkin emas."
    else:
        review_date = None

    duration = body.get('duration_days')
    if duration in (None, ''):
        duration = None
    else:
        try:
            duration = int(duration)
        except Exception:
            return None, "Davomiylik (kun) son bo'lishi kerak."
        if not (1 <= duration <= 365):
            return None, "Davomiylik 1 va 365 kun orasida bo'lishi kerak."

    meds = body.get('medication_plan')
    if meds in (None, '', []):
        meds = None
    else:
        if not isinstance(meds, list):
            return None, "Dori rejasi ro'yxat bo'lishi kerak."
        cleaned = []
        for m in meds:
            if not isinstance(m, dict) or not (m.get('name') or '').strip():
                return None, "Har bir dori uchun nomi ko'rsatilishi shart."
            cleaned.append({
                'name': str(m['name']).strip()[:255],
                'dosage': str(m.get('dosage') or '')[:128],
                'route': str(m.get('route') or '')[:64],
                'frequency': str(m.get('frequency') or '')[:64],
                'duration_days': m.get('duration_days'),
                'note': str(m.get('note') or '')[:255],
            })
        meds = json.dumps(cleaned, ensure_ascii=False)

    if not (body.get('immediate_actions') or '').strip():
        return None, "Darhol bajarilishi kerak bo'lgan choralar kiritilishi shart."

    if plan_type == 'detox' and not (body.get('detox_protocol') or '').strip():
        return None, "Detoksikatsiya rejasi uchun protokol ko'rsatilishi shart."

    return {
        'plan_type': plan_type,
        'status': status,
        'plan_date': plan_date.isoformat(),
        'review_date': review_date.isoformat() if review_date else None,
        'duration_days': duration,
        'medication_plan': meds,
        'immediate_actions': (body.get('immediate_actions') or '').strip(),
        'detox_protocol': (body.get('detox_protocol') or None),
        'therapy_plan': (body.get('therapy_plan') or None),
        'goals': (body.get('goals') or None),
        'precautions': (body.get('precautions') or None),
    }, None


def save_plan(conn, patient_id, doctor_id, values, consultation_id=None):
    """
    Insert a plan, superseding any plan already active for this patient.

    Only one plan should be the live instruction at a time, or the ward has to
    guess which sheet to follow.
    """
    ensure_schema(conn)
    pid = next_id('PLAN')
    cur = conn.cursor()
    if values['status'] == 'active':
        cur.execute("""UPDATE treatment_plans SET status = 'superseded'
                       WHERE patient_id = ? AND status = 'active'""", (patient_id,))
    cols = ['id', 'consultation_id', 'patient_id', 'doctor_id'] + list(values)
    params = [pid, consultation_id, patient_id, doctor_id] + [values[k] for k in values]
    marks = ', '.join(['?'] * len(cols))
    cur.execute(f"INSERT INTO treatment_plans ({', '.join(cols)}) VALUES ({marks})",
                tuple(params))
    conn.commit()
    return pid


def get_plan(conn, plan_id):
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT tp.*, p.full_name AS patient_name, p.patient_code,
               p.medical_allergies, s.full_name AS doctor_name,
               s.specialty AS doctor_specialty
        FROM treatment_plans tp
        JOIN patients p ON p.id = tp.patient_id
        LEFT JOIN staff s ON s.id = tp.doctor_id
        WHERE tp.id = ?
    """, (plan_id,))
    row = cur.fetchone()
    if not row:
        return None
    data = dict(row)
    if data.get('medication_plan'):
        try:
            data['medication_plan'] = json.loads(data['medication_plan'])
        except Exception:
            pass
    return data


def plans_for_patient(conn, patient_id):
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT tp.id, tp.plan_date, tp.plan_type, tp.status, tp.duration_days,
               tp.review_date, tp.consultation_id, s.full_name AS doctor_name
        FROM treatment_plans tp
        LEFT JOIN staff s ON s.id = tp.doctor_id
        WHERE tp.patient_id = ?
        ORDER BY tp.plan_date DESC, tp.created_at DESC
    """, (patient_id,))
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Queue from registration
# ---------------------------------------------------------------------------

def waiting_queue(conn, doctor_id=None):
    """
    Patients registration has booked for a consultation and who have no
    consultation recorded yet.

    This is the hand-off the intake workflow depends on: reception takes the
    details and routes the patient to a named doctor, and this is what that
    doctor sees waiting.
    """
    ensure_schema(conn)
    cur = conn.cursor()
    sql = """
        SELECT a.id AS appointment_id, a.appointment_date, a.appointment_time,
               a.service_type, a.status, a.notes,
               a.patient_name, a.patient_phone,
               p.id AS patient_id, p.patient_code, p.birth_date, p.birth_year, p.gender,
               p.medical_allergies,
               s.id AS doctor_id, s.full_name AS doctor_name
        FROM appointments a
        LEFT JOIN patients p ON p.id = a.patient_id
        LEFT JOIN staff s ON s.id = a.doctor_id
        WHERE a.status IN ('pending', 'confirmed')
          AND (a.patient_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM consultations c
                WHERE c.appointment_id = a.id
          ))
    """
    params = []
    if doctor_id:
        sql += " AND a.doctor_id = ?"
        params.append(doctor_id)
    sql += " ORDER BY a.appointment_date ASC, a.appointment_time ASC"
    cur.execute(sql, tuple(params))
    return [dict(r) for r in cur.fetchall()]
