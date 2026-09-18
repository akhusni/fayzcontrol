"""
Fayz Medical House — Nurse Station / Medication Administration Record

The clinic could prescribe but could not record giving a dose. prescriptions
holds the doctor's order; daily_logs holds one row of vitals per admission per
day; nothing recorded that a particular dose was actually administered, by
whom, when. This module adds that record and the daily round built on top of
it.

How the round is produced
-------------------------
The schedule is DERIVED from the standing prescriptions rather than entered by
hand. That is what makes a future date meaningful — asking "what will this
patient receive on Thursday" is answerable from the orders alone, while asking
"what did they receive last Tuesday" is answered by the administration rows
overlaid on the same derived plan.

Two details of the real data matter:

  * "Kuniga 1-2 mahal" is a range: the doctor left the second dose to
    discretion. Scheduling the upper bound would mark a correctly-treated
    patient as having missed something, so the lower bound is planned and the
    permitted maximum is carried alongside for the nurse to see.

  * "Zarurat tug'ilganda" (as needed) must generate NO scheduled doses at all.
    Planning it would report a missed dose every day it was not required.
    Those orders are listed separately and recorded only when given.
"""

import re
import datetime as _dt

# Status values a recorded dose may carry.
STATUSES = ('given', 'missed', 'refused', 'held')

# Slot names by how many doses fall in a day, so the round reads the way a
# nurse would say it rather than as "dose 1 of 3".
SLOT_LABELS = {
    1: ['Ertalab'],
    2: ['Ertalab', 'Kechqurun'],
    3: ['Ertalab', 'Tushda', 'Kechqurun'],
    4: ['Ertalab', 'Tushda', 'Kechki', 'Tunda'],
    5: ['Ertalab', 'Tushda', 'Kechki', 'Kechqurun', 'Tunda'],
}

# Orders left to the nurse's judgement rather than put on a clock.
_AS_NEEDED_PATTERNS = (
    'zarurat',          # "Zarurat tug'ilganda"
    'kerak bo',         # "kerak bo'lganda"
    'p.r.n', 'prn',
    'ehtiyoj',
)

_schema_checked = False


def ensure_schema(conn):
    """
    Create medication_administrations if it is not there yet.

    Written as a runtime check rather than a migration script so an existing
    clinic database picks it up on the next restart, the same approach used for
    widening the audit table.
    """
    global _schema_checked
    if _schema_checked:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS medication_administrations (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                prescription_id VARCHAR(64) NOT NULL,
                admission_id VARCHAR(64),
                patient_id VARCHAR(64) NOT NULL,
                scheduled_date DATE NOT NULL,
                -- 0-based position within the day for a planned dose. Extra or
                -- as-needed doses start at 100 so they cannot collide with a
                -- planned slot.
                slot_index INT NOT NULL,
                slot_label VARCHAR(32),
                status VARCHAR(16) NOT NULL DEFAULT 'given'
                    CHECK(status IN ('given', 'missed', 'refused', 'held')),
                administered_at DATETIME,
                administered_by_staff_id VARCHAR(64),
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                -- One record per prescription per slot per day: recording the
                -- same dose twice is a data-entry slip, not a second dose.
                UNIQUE KEY uq_dose (prescription_id, scheduled_date, slot_index),
                KEY idx_ma_date (scheduled_date),
                KEY idx_ma_admission (admission_id, scheduled_date),
                FOREIGN KEY (prescription_id) REFERENCES prescriptions(id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY (patient_id) REFERENCES patients(id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY (administered_by_staff_id) REFERENCES staff(id)
                    ON UPDATE CASCADE ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        _schema_checked = True
    except Exception as e:
        print(f"[!] Could not prepare medication_administrations: {e}")
        _schema_checked = True


# ---------------------------------------------------------------------------
# Reading a prescription's frequency
# ---------------------------------------------------------------------------

def is_as_needed(frequency):
    f = (frequency or '').lower()
    return any(p in f for p in _AS_NEEDED_PATTERNS)


def doses_per_day(frequency):
    """
    How many doses a day this order plans, and the most it permits.

    Returns (planned, maximum). For an as-needed order both are 0 — it is not
    on a schedule at all. For a range such as "Kuniga 1-2 mahal" the lower
    bound is planned and the upper is the permitted maximum, so a nurse who
    gave one dose is not shown as having missed a second.
    """
    if is_as_needed(frequency):
        return 0, 0

    text = (frequency or '').lower()

    # Interval notation: "har 8 soatda" means every 8 hours, which is three
    # doses a day — not eight. Read as a count it would triple the round.
    interval = re.search(r'har\s*(\d+)\s*soat', text)
    if interval:
        hours = max(1, int(interval.group(1)))
        n = max(1, min(round(24 / hours), 12))
        return n, n

    # "kuniga 2-3 mahal" / "2-3 marta"
    span = re.search(r'(\d+)\s*[-–]\s*(\d+)', text)
    if span:
        lo, hi = int(span.group(1)), int(span.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return max(1, min(lo, 12)), max(1, min(hi, 12))

    # "kuniga 2 mahal", "2x kunda", "3 marta"
    single = re.search(r'(\d+)', text)
    if single:
        n = max(1, min(int(single.group(1)), 12))
        return n, n

    # Nothing numeric: assume once daily rather than dropping the order.
    return 1, 1


def slot_labels_for(count, timing=None):
    """
    Names for each dose in a day.

    A prescription's free-text `timing` ("Ertalab & Kechqurun") is used when it
    names exactly as many parts as there are doses, since the doctor's own
    wording is better than a generic label.
    """
    if timing:
        parts = [p.strip() for p in re.split(r'[&,+/]| va ', timing) if p.strip()]
        if len(parts) == count:
            return parts
    if count in SLOT_LABELS:
        return list(SLOT_LABELS[count])
    return [f'{i + 1}-doza' for i in range(count)]


def prescription_window(row):
    """
    The inclusive date range a prescription covers.

    prescriptions has no start_date column, so the order begins the day it was
    written and runs for duration_days. Where the admission started later than
    the order was recorded, the later of the two is used so a dose is never
    planned for a day before the patient was in a bed.
    """
    created = row.get('created_at')
    if isinstance(created, str):
        created = created[:10]
    else:
        created = str(created)[:10]
    try:
        start = _dt.date.fromisoformat(created)
    except Exception:
        start = _dt.date.today()

    adm_start = row.get('admission_start')
    if adm_start:
        try:
            adm_start = _dt.date.fromisoformat(str(adm_start)[:10])
            if adm_start > start:
                start = adm_start
        except Exception:
            pass

    days = row.get('duration_days') or 1
    try:
        days = max(1, int(days))
    except Exception:
        days = 1
    return start, start + _dt.timedelta(days=days - 1)


# ---------------------------------------------------------------------------
# The daily round
# ---------------------------------------------------------------------------

def _fetch_orders(conn, day):
    """
    Active prescriptions for patients who are in a bed on `day`, with the bed
    and patient details the round needs to be readable.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            rx.id                AS prescription_id,
            rx.patient_id,
            rx.admission_id,
            rx.medication_name,
            rx.form,
            rx.dosage,
            rx.route,
            rx.frequency,
            rx.duration_days,
            rx.timing,
            rx.instructions,
            rx.status            AS rx_status,
            rx.created_at,
            p.full_name          AS patient_name,
            p.patient_code,
            p.medical_allergies,
            a.start_date         AS admission_start,
            a.planned_end_date,
            a.actual_end_date,
            b.bed_code,
            r.room_number,
            s.full_name          AS doctor_name
        FROM prescriptions rx
        JOIN patients p    ON p.id = rx.patient_id
        JOIN admissions a  ON a.id = rx.admission_id
        JOIN beds b        ON b.id = a.bed_id
        JOIN rooms r       ON r.id = b.room_id
        LEFT JOIN staff s  ON s.id = rx.doctor_id
        WHERE rx.status = 'active'
          AND a.status = 'active'
          AND ? BETWEEN a.start_date AND COALESCE(a.actual_end_date, a.planned_end_date)
        ORDER BY r.room_number, b.bed_code, p.full_name, rx.medication_name
    """, (day.isoformat(),))
    return cur.fetchall()


def _fetch_administrations(conn, day):
    cur = conn.cursor()
    cur.execute("""
        SELECT ma.*, s.full_name AS nurse_name
        FROM medication_administrations ma
        LEFT JOIN staff s ON s.id = ma.administered_by_staff_id
        WHERE ma.scheduled_date = ?
    """, (day.isoformat(),))
    rows = cur.fetchall()
    keyed = {}
    extras = {}
    for r in rows:
        key = (r['prescription_id'], int(r['slot_index']))
        keyed[key] = r
        if int(r['slot_index']) >= 100:
            extras.setdefault(r['prescription_id'], []).append(r)
    return keyed, extras


def build_round(conn, day):
    """
    The medication round for one date, grouped by patient.

    Every planned dose carries its recorded outcome when there is one. A dose
    with no record is reported as 'pending' for today or the future and
    'not_recorded' for a past date — the distinction matters, because an
    unrecorded dose yesterday is a gap in the record, while an unrecorded dose
    tomorrow is simply not due yet.
    """
    ensure_schema(conn)
    today = _dt.date.today()
    orders = _fetch_orders(conn, day)
    recorded, extras = _fetch_administrations(conn, day)

    patients = {}
    for o in orders:
        start, end = prescription_window(o)
        if not (start <= day <= end):
            continue

        pid = o['patient_id']
        entry = patients.setdefault(pid, {
            'patient_id': pid,
            'patient_name': o['patient_name'],
            'patient_code': o['patient_code'],
            'room_number': o['room_number'],
            'bed_code': o['bed_code'],
            'medical_allergies': o['medical_allergies'],
            'admission_id': o['admission_id'],
            'doses': [],
            'as_needed': [],
        })

        planned, maximum = doses_per_day(o['frequency'])

        base = {
            'prescription_id': o['prescription_id'],
            'medication_name': o['medication_name'],
            'form': o['form'],
            'dosage': o['dosage'],
            'route': o['route'],
            'frequency': o['frequency'],
            'timing': o['timing'],
            'instructions': o['instructions'],
            'doctor_name': o['doctor_name'],
            'day_of_course': (day - start).days + 1,
            'course_days': (end - start).days + 1,
            'max_per_day': maximum,
        }

        if planned == 0:
            given = extras.get(o['prescription_id'], [])
            entry['as_needed'].append(dict(base, given_today=[{
                'status': g['status'],
                'administered_at': g['administered_at'],
                'nurse_name': g['nurse_name'],
                'notes': g['notes'],
            } for g in given]))
            continue

        labels = slot_labels_for(planned, o['timing'])
        for i in range(planned):
            rec = recorded.get((o['prescription_id'], i))
            if rec:
                state = rec['status']
            elif day > today:
                state = 'scheduled'
            elif day == today:
                state = 'pending'
            else:
                state = 'not_recorded'
            entry['doses'].append(dict(base,
                slot_index=i,
                slot_label=labels[i],
                state=state,
                administered_at=rec['administered_at'] if rec else None,
                nurse_name=rec['nurse_name'] if rec else None,
                notes=rec['notes'] if rec else None,
            ))

    ordered = sorted(patients.values(),
                     key=lambda p: (str(p['room_number']), str(p['bed_code'])))

    counts = {'planned': 0, 'given': 0, 'missed': 0, 'refused': 0,
              'held': 0, 'pending': 0, 'not_recorded': 0, 'scheduled': 0,
              'as_needed_orders': 0}
    for p in ordered:
        counts['as_needed_orders'] += len(p['as_needed'])
        for d in p['doses']:
            counts['planned'] += 1
            counts[d['state']] = counts.get(d['state'], 0) + 1

    return {
        'date': day.isoformat(),
        'is_past': day < today,
        'is_today': day == today,
        'is_future': day > today,
        'patients': ordered,
        'totals': counts,
    }


def record_dose(conn, prescription_id, day, slot_index, status,
                staff_id=None, notes=None, slot_label=None):
    """
    Record or amend one dose.

    Upserts on (prescription_id, date, slot) so correcting a mistaken entry
    updates it rather than adding a second row for the same dose.
    """
    ensure_schema(conn)
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")

    cur = conn.cursor()
    cur.execute("""
        SELECT rx.id, rx.patient_id, rx.admission_id, rx.status
        FROM prescriptions rx WHERE rx.id = ?
    """, (prescription_id,))
    rx = cur.fetchone()
    if not rx:
        raise LookupError(f"prescription {prescription_id} not found")

    administered_at = None
    if status == 'given':
        administered_at = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cur.execute("""
        INSERT INTO medication_administrations
            (prescription_id, admission_id, patient_id, scheduled_date,
             slot_index, slot_label, status, administered_at,
             administered_by_staff_id, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE
            status = VALUES(status),
            slot_label = VALUES(slot_label),
            administered_at = VALUES(administered_at),
            administered_by_staff_id = VALUES(administered_by_staff_id),
            notes = VALUES(notes)
    """, (prescription_id, rx['admission_id'], rx['patient_id'], day.isoformat(),
          int(slot_index), slot_label, status, administered_at, staff_id, notes))
    conn.commit()
    return True


def next_extra_slot(conn, prescription_id, day):
    """
    The next free slot index at or above 100, for an as-needed or additional
    dose. Planned slots occupy 0..n-1, so extras never collide with them.
    """
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(MAX(slot_index), 99) AS top
        FROM medication_administrations
        WHERE prescription_id = ? AND scheduled_date = ? AND slot_index >= 100
    """, (prescription_id, day.isoformat()))
    row = cur.fetchone()
    top = int(row['top']) if row and row['top'] is not None else 99
    return max(100, top + 1)
