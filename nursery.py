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
_stock_ready = False


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
    # Separate step: if the stock columns cannot be added (say the database
    # user may not ALTER), doses must still be recorded -- just without
    # taking stock -- rather than every dose failing on a missing column.
    global _stock_ready
    try:
        cur = conn.cursor()
        _ensure_stock_columns(cur)
        conn.commit()
        _stock_ready = True
    except Exception as e:
        print(f"[!] Medicine stock tracking is off: {e}")
        _stock_ready = False


# Stock columns on a dose. A given dose takes one unit off the shelf; the row
# remembers which stock item it took and how many units were really removed,
# so correcting the dose (given -> missed) puts back exactly that, never more.
_STOCK_COLUMNS = (
    ('stock_medication_id', "VARCHAR(64) NULL"),
    ('stock_units', "INT NOT NULL DEFAULT 0"),
    ('stock_unit_cost', "DECIMAL(14,2) NULL"),
)


def _ensure_stock_columns(cur):
    for name, ddl in _STOCK_COLUMNS:
        cur.execute("""
            SELECT COUNT(*) AS n FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'medication_administrations'
              AND COLUMN_NAME = ?
        """, (name,))
        if not cur.fetchone()['n']:
            cur.execute(f"ALTER TABLE medication_administrations ADD COLUMN {name} {ddl}")
    # Doctors type medicine names freely and accounting names the stock items
    # it buys, so the two rarely match letter for letter. Accounting links a
    # prescribed name to a stock item once; every later dose follows the link.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS medication_aliases (
            alias_key VARCHAR(255) PRIMARY KEY,
            medication_id VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (medication_id) REFERENCES medications_catalog(id)
                ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


def alias_key(name):
    """How a medicine name is compared: trimmed, single-spaced, lower case."""
    return re.sub(r'\s+', ' ', (name or '').strip()).lower()


def resolve_stock_item(cur, medication_id, medication_name):
    """
    The stock item a prescription draws from, or None.

    Order: the prescription's own catalog id, a catalog item with the same
    name, then a link accounting made for that name.
    """
    if medication_id:
        cur.execute("SELECT id, unit_price FROM medications_catalog WHERE id = ?", (medication_id,))
        row = cur.fetchone()
        if row:
            return row
    key = alias_key(medication_name)
    if not key:
        return None
    # Compared in Python so both names are normalised the same way (SQL TRIM
    # would leave a double space inside a catalog name unmatched). The
    # catalogue is a few hundred rows at most.
    cur.execute("SELECT id, name, unit_price FROM medications_catalog")
    for row in cur.fetchall():
        if alias_key(row['name']) == key:
            return row
    cur.execute("""
        SELECT mc.id, mc.unit_price FROM medication_aliases ma
        JOIN medications_catalog mc ON mc.id = ma.medication_id
        WHERE ma.alias_key = ?
    """, (key,))
    return cur.fetchone()


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
        except Exception as e:
            # Falling back to the prescription's own start is the safe choice,
            # but it can schedule doses for days before the patient arrived, so
            # say so rather than let the round quietly disagree with the stay.
            print(f"[nursery] unreadable admission start {adm_start!r}: {e}")

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


def ward_round(conn, day):
    """
    Everyone in a bed on `day`, and whether the doctor has seen them yet.

    The per-patient check-up already existed but there was no list: a doctor
    had to know who was in the building and open each record in turn, with
    nothing anywhere saying who had been seen and who was still waiting. This
    is that list.

    Each entry carries the stay (which day of how many), the nurse's
    observation for the day, and the doctor's own note if one has been written.
    """
    cur = conn.cursor()
    iso = day.isoformat()

    cur.execute("""
        SELECT a.id AS admission_id, a.patient_id, a.program_type,
               a.start_date, a.planned_end_date, a.actual_end_date,
               a.admission_notes,
               p.full_name AS patient_name, p.patient_code, p.gender,
               p.birth_date, p.birth_year, p.medical_allergies,
               b.bed_code, r.room_number, r.room_name_uz, r.floor_number,
               s.id AS doctor_id, s.full_name AS doctor_name
        FROM admissions a
        JOIN patients p ON a.patient_id = p.id
        JOIN beds b ON a.bed_id = b.id
        JOIN rooms r ON b.room_id = r.id
        LEFT JOIN staff s ON a.attending_doctor_id = s.id
        WHERE a.status = 'active'
          AND a.start_date <= ?
          AND COALESCE(a.actual_end_date, a.planned_end_date) >= ?
        ORDER BY r.floor_number, r.room_number, b.bed_code
    """, (iso, iso))
    stays = [dict(r) for r in cur.fetchall()]
    if not stays:
        return {'date': iso, 'is_past': day < _dt.date.today(),
                'is_today': day == _dt.date.today(), 'is_future': day > _dt.date.today(),
                'patients': [], 'totals': {'total': 0, 'seen': 0, 'waiting': 0}}

    ids = [s['admission_id'] for s in stays]
    marks = ', '.join(['?'] * len(ids))

    cur.execute(f"""
        SELECT dn.*, s.full_name AS doctor_name
        FROM doctor_daily_notes dn
        LEFT JOIN staff s ON dn.doctor_id = s.id
        WHERE dn.note_date = ? AND dn.admission_id IN ({marks})
    """, tuple([iso] + ids))
    notes = {str(r['admission_id']): dict(r) for r in cur.fetchall()}

    cur.execute(f"""
        SELECT dl.*, s.full_name AS nurse_name
        FROM daily_logs dl
        LEFT JOIN staff s ON dl.recorded_by_staff_id = s.id
        WHERE dl.log_date = ? AND dl.admission_id IN ({marks})
    """, tuple([iso] + ids))
    vitals = {str(r['admission_id']): dict(r) for r in cur.fetchall()}

    out = []
    for st in stays:
        adm_id = str(st['admission_id'])
        start = _dt.datetime.strptime(str(st['start_date'])[:10], '%Y-%m-%d').date()
        end_raw = st['actual_end_date'] or st['planned_end_date']
        end = _dt.datetime.strptime(str(end_raw)[:10], '%Y-%m-%d').date()
        entry = dict(st)
        entry['day_of_stay'] = (day - start).days + 1
        entry['total_days'] = max(1, (end - start).days)
        entry['checkup'] = notes.get(adm_id)
        entry['vitals'] = vitals.get(adm_id)
        entry['seen'] = adm_id in notes
        out.append(entry)

    seen = sum(1 for e in out if e['seen'])
    return {
        'date': iso,
        'is_past': day < _dt.date.today(),
        'is_today': day == _dt.date.today(),
        'is_future': day > _dt.date.today(),
        'patients': out,
        'totals': {'total': len(out), 'seen': seen, 'waiting': len(out) - seen},
    }


def _fetch_vitals(conn, day):
    """One day's recorded observations, keyed by admission."""
    cur = conn.cursor()
    cur.execute("""
        SELECT dl.*, s.full_name AS nurse_name
        FROM daily_logs dl
        LEFT JOIN staff s ON dl.recorded_by_staff_id = s.id
        WHERE dl.log_date = ?
    """, (day.isoformat(),))
    return {str(r['admission_id']): dict(r) for r in cur.fetchall()}


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

    # Whatever the ward already observed on this day, so the sheet shows the
    # morning's figures instead of an empty form.
    vitals_by_admission = _fetch_vitals(conn, day)
    for p in ordered:
        p['vitals'] = vitals_by_admission.get(str(p['admission_id']))

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
        SELECT rx.id, rx.patient_id, rx.admission_id, rx.status,
               rx.medication_id, rx.medication_name
        FROM prescriptions rx WHERE rx.id = ?
    """, (prescription_id,))
    rx = cur.fetchone()
    if not rx:
        raise LookupError(f"prescription {prescription_id} not found")

    administered_at = None
    if status == 'given':
        administered_at = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not _stock_ready:
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

    # Stock: what this dose took before, and what it should take now.
    cur.execute("""
        SELECT stock_medication_id, stock_units FROM medication_administrations
        WHERE prescription_id = ? AND scheduled_date = ? AND slot_index = ?
        FOR UPDATE
    """, (prescription_id, day.isoformat(), int(slot_index)))
    prev = cur.fetchone()
    if prev and prev['stock_medication_id'] and prev['stock_units']:
        cur.execute("UPDATE medications_catalog SET stock_quantity = stock_quantity + ? WHERE id = ?",
                    (int(prev['stock_units']), prev['stock_medication_id']))

    stock_id, stock_units, stock_cost = None, 0, None
    if status == 'given':
        item = resolve_stock_item(cur, rx['medication_id'], rx['medication_name'])
        if item:
            stock_id, stock_cost = item['id'], item['unit_price']
            # An empty shelf still records the dose (the nurse gave it from
            # somewhere); it just removes nothing, so a later correction
            # cannot put back a unit that was never taken.
            cur.execute("""
                UPDATE medications_catalog SET stock_quantity = stock_quantity - 1
                WHERE id = ? AND stock_quantity > 0
            """, (stock_id,))
            stock_units = 1 if cur.rowcount else 0

    cur.execute("""
        INSERT INTO medication_administrations
            (prescription_id, admission_id, patient_id, scheduled_date,
             slot_index, slot_label, status, administered_at,
             administered_by_staff_id, notes,
             stock_medication_id, stock_units, stock_unit_cost)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE
            status = VALUES(status),
            slot_label = VALUES(slot_label),
            administered_at = VALUES(administered_at),
            administered_by_staff_id = VALUES(administered_by_staff_id),
            notes = VALUES(notes),
            stock_medication_id = VALUES(stock_medication_id),
            stock_units = VALUES(stock_units),
            stock_unit_cost = VALUES(stock_unit_cost)
    """, (prescription_id, rx['admission_id'], rx['patient_id'], day.isoformat(),
          int(slot_index), slot_label, status, administered_at, staff_id, notes,
          stock_id, stock_units, stock_cost))
    conn.commit()
    return True


def medicine_usage(conn, start, end):
    """
    Medicines given between start and end (inclusive ISO dates).

    `linked` rows are stock items with doses, units taken off the shelf and
    their cost at the buying price of the time; `unlinked` are prescribed names
    that match no stock item, so accounting can link them.
    """
    ensure_schema(conn)
    if not _stock_ready:
        return {'start': start, 'end': end, 'linked': [], 'unlinked': [],
                'total_cost': 0.0, 'total_doses': 0, 'stock_tracking': False}
    cur = conn.cursor()
    cur.execute("""
        SELECT mc.id AS medication_id, mc.name, mc.form, mc.stock_quantity,
               mc.min_stock_level,
               COUNT(*) AS doses,
               COALESCE(SUM(ma.stock_units), 0) AS units_taken,
               COALESCE(SUM(ma.stock_unit_cost), 0) AS cost
        FROM medication_administrations ma
        JOIN medications_catalog mc ON mc.id = ma.stock_medication_id
        WHERE ma.status = 'given' AND ma.scheduled_date BETWEEN ? AND ?
        GROUP BY mc.id, mc.name, mc.form, mc.stock_quantity, mc.min_stock_level
        ORDER BY cost DESC, doses DESC
    """, (start, end))
    linked = [dict(r) for r in cur.fetchall()]
    cur.execute("""
        SELECT rx.medication_name, COUNT(*) AS doses
        FROM medication_administrations ma
        JOIN prescriptions rx ON rx.id = ma.prescription_id
        WHERE ma.status = 'given' AND ma.stock_medication_id IS NULL
          AND ma.scheduled_date BETWEEN ? AND ?
        GROUP BY rx.medication_name
        ORDER BY doses DESC
    """, (start, end))
    unlinked = [dict(r) for r in cur.fetchall()]
    for row in linked:
        for k in ('cost',):
            row[k] = float(row[k] or 0)
        for k in ('doses', 'units_taken', 'stock_quantity', 'min_stock_level'):
            row[k] = int(row[k] or 0)
    for row in unlinked:
        row['doses'] = int(row['doses'] or 0)
    return {
        'start': start, 'end': end,
        'linked': linked,
        'unlinked': unlinked,
        'total_cost': round(sum(r['cost'] for r in linked), 2),
        'total_doses': sum(r['doses'] for r in linked) + sum(r['doses'] for r in unlinked),
        'stock_tracking': True,
    }


def link_medicine_name(conn, medication_name, medication_id):
    """Point a prescribed name at a stock item for all doses from now on."""
    ensure_schema(conn)
    key = alias_key(medication_name)
    if not key:
        raise ValueError('medication_name')
    cur = conn.cursor()
    cur.execute("SELECT id FROM medications_catalog WHERE id = ?", (medication_id,))
    if not cur.fetchone():
        raise LookupError(medication_id)
    if not _stock_ready:
        raise RuntimeError('stock tracking is off')
    cur.execute("""
        INSERT INTO medication_aliases (alias_key, medication_id) VALUES (?, ?)
        ON DUPLICATE KEY UPDATE medication_id = VALUES(medication_id)
    """, (key, medication_id))

    # Doses already given under this name were used from the shelf too: take
    # them off now, so linking leaves the stock count right and the name stops
    # showing as unlinked.
    cur.execute("SELECT unit_price FROM medications_catalog WHERE id = ?", (medication_id,))
    cost = cur.fetchone()['unit_price']
    cur.execute("""
        SELECT ma.id, rx.medication_name FROM medication_administrations ma
        JOIN prescriptions rx ON rx.id = ma.prescription_id
        WHERE ma.status = 'given' AND ma.stock_medication_id IS NULL
    """)
    pending = [r['id'] for r in cur.fetchall() if alias_key(r['medication_name']) == key]
    settled = 0
    for adm_id in pending:
        cur.execute("""
            UPDATE medications_catalog SET stock_quantity = stock_quantity - 1
            WHERE id = ? AND stock_quantity > 0
        """, (medication_id,))
        units = 1 if cur.rowcount else 0
        cur.execute("""
            UPDATE medication_administrations
            SET stock_medication_id = ?, stock_units = ?, stock_unit_cost = ?
            WHERE id = ?
        """, (medication_id, units, cost, adm_id))
        settled += 1
    conn.commit()
    return key, settled


# Vitals, and the range each one is believable in. The table carries the same
# bounds as CHECK constraints, but a constraint violation reaches the nurse as
# a MySQL error; these produce a sentence she can act on, naming the field.
VITAL_RANGES = {
    'vital_bp_systolic':  (50, 300,  "Sistolik bosim"),
    'vital_bp_diastolic': (30, 200,  "Diastolik bosim"),
    'vital_pulse':        (30, 250,  "Puls"),
    'vital_temp':         (30.0, 45.0, "Harorat"),
    'vital_spo2':         (50, 100,  "SpO2"),
}


def parse_vitals(body):
    """
    Read the vitals out of a request body.

    Returns (values, error). Only fields the body actually mentions appear in
    values: a key that is present but empty clears the reading, a key that is
    absent leaves it alone. A blank is None rather than zero, because a missing
    reading and a reading of nought are different clinical claims and the
    column is nullable so the difference survives.
    """
    values = {}
    for field, (low, high, label) in VITAL_RANGES.items():
        if field not in body:
            # Absent is not the same as blank. An amend that names only the
            # pulse must not wipe the blood pressure recorded an hour earlier,
            # so a field nobody mentioned is left out entirely and
            # record_vitals keeps whatever is already stored.
            continue
        raw = body.get(field)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            # Present but empty: an explicit clear.
            values[field] = None
            continue
        try:
            num = float(raw) if field == 'vital_temp' else int(raw)
        except (TypeError, ValueError):
            return None, (f"{label} raqam bo'lishi kerak.", field)
        if not (low <= num <= high):
            return None, (f"{label} {low}-{high} oralig'ida bo'lishi kerak "
                          f"(kiritilgan: {num}).", field)
        values[field] = num

    sys_bp = values.get('vital_bp_systolic')
    dia_bp = values.get('vital_bp_diastolic')
    if sys_bp is not None and dia_bp is not None and dia_bp >= sys_bp:
        return None, ("Diastolik bosim sistolikdan kichik bo'lishi kerak.",
                      'vital_bp_diastolic')
    return values, None


def record_vitals(conn, admission_id, day, vitals, attended=True,
                  nurse_notes=None, staff_id=None):
    """
    Write one day's observation for one stay.

    daily_logs is unique on (admission_id, log_date), so a second reading for
    the same day amends the first rather than adding a row -- the same rule the
    medication round already follows, and for the same reason: a nurse
    correcting a figure she mistyped should not leave two contradictory records
    of the same morning.

    Only what `vitals` names is overwritten. A round that records a pulse in
    the afternoon leaves the morning's blood pressure where it is.
    """
    cur = conn.cursor()
    columns = ['attended'] + list(VITAL_RANGES)
    if nurse_notes is not None:
        columns.append('nurse_notes')
    row_values = {
        'attended': 1 if attended else 0,
        'nurse_notes': nurse_notes,
        'recorded_by_staff_id': staff_id,
    }
    row_values.update({f: vitals.get(f) for f in VITAL_RANGES})

    insert_cols = ['admission_id', 'log_date', 'attended', 'nurse_notes',
                   'recorded_by_staff_id'] + list(VITAL_RANGES)
    insert_params = [admission_id, day.isoformat(), row_values['attended'],
                     nurse_notes, staff_id] + [vitals.get(f) for f in VITAL_RANGES]

    # Amend only the fields this call carried, plus who recorded it.
    update_cols = ['attended', 'recorded_by_staff_id'] + [f for f in VITAL_RANGES if f in vitals]
    if nurse_notes is not None:
        update_cols.append('nurse_notes')
    update_clause = ', '.join(f"{c} = VALUES({c})" for c in update_cols)

    cur.execute(f"""
        INSERT INTO daily_logs ({', '.join(insert_cols)})
        VALUES ({', '.join(['?'] * len(insert_cols))})
        ON DUPLICATE KEY UPDATE {update_clause}
    """, tuple(insert_params))
    conn.commit()

    cur.execute("""
        SELECT dl.*, s.full_name AS nurse_name
        FROM daily_logs dl
        LEFT JOIN staff s ON dl.recorded_by_staff_id = s.id
        WHERE dl.admission_id = ? AND dl.log_date = ?
    """, (admission_id, day.isoformat()))
    return cur.fetchone()


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
