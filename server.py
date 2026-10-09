"""
Fayz Medical House — 100% Real Database-Connected REST API & Static Server
Runs out-of-the-box with Python standard library.
Connects all portals (Facility, CRM, Doctor EMR, Accounting, HR, Reception) directly to Enterprise MySQL 8.0.
Enforces real-time relational integrity, autonomous triggers, and live KPI views.
"""

import http.server
import socketserver
import json
import os
import re
import urllib.parse
import sys
import datetime
import datetime as _dt
import decimal
import decimal as _dec
import traceback
import threading
import tempfile
import time


def json_default(obj):
    if isinstance(obj, _dec.Decimal):
        return float(obj)
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, _dt.timedelta):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


_orig_json_dumps = json.dumps
def safe_json_dumps(obj, *args, **kwargs):
    if 'default' not in kwargs:
        kwargs['default'] = json_default
    if 'ensure_ascii' not in kwargs:
        kwargs['ensure_ascii'] = False
    return _orig_json_dumps(obj, *args, **kwargs)

json.dumps = safe_json_dumps


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else int(os.environ.get('PORT', 3000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from pdf_generator import generate_patient_pdf, generate_round_pdf
except Exception as e:
    generate_patient_pdf = None
    generate_round_pdf = None

try:
    import telegram_service
    # No token in the environment means the bot is off: every notify hook
    # below is guarded by `if telegram_service`, so this one switch keeps a
    # dev or test server from posting into the real staff group.
    if not telegram_service.ENABLED:
        telegram_service = None
except Exception as _e_tg:
    telegram_service = None

# ----------------------------------------------------------------------------
# Shared-state safety for the threaded server.
#
# The JSON data files (users.json, clinic_rooms.json, pricing_config.json) are
# read-modify-written by request handlers. ThreadingHTTPServer runs each request
# in its own thread, so without serialization two concurrent writers interleave:
# one thread truncates the file with open(...,'w') while another is still reading
# it, the reader gets a partial document, and the write-back persists that
# truncated state. That silently destroyed whole files.
#
# WRITE_LOCK serializes every mutating request (POST/PUT/DELETE). It also makes
# the read-COUNT-then-INSERT id generators in the staff/user routes correct,
# since a concurrent request can no longer observe the same count.
# write_json_atomic() replaces the file via os.replace(), which is atomic, so a
# concurrent reader always sees either the old or the new complete document and
# never a half-written one.
# ----------------------------------------------------------------------------
WRITE_LOCK = threading.RLock()


# ----------------------------------------------------------------------------
# Public enquiry endpoint: the one route that answers without a session.
#
# The marketing site posts booking enquiries from the visitor's browser, so
# this is the only place the open internet can write to. It is kept narrow:
# it writes to appointment_requests and nothing else, creates no patient and
# no appointment, and is rate limited per address so a script cannot fill the
# table overnight. Nothing it writes reaches a clinical table until somebody
# at the desk reads it and accepts it.
#
# The site is on another domain, so this route -- and only this route --
# answers CORS, for the configured origin only.
# ----------------------------------------------------------------------------
PUBLIC_ENQUIRY_PATH = '/api/public/appointment-request'
PUBLIC_SITE_ORIGINS = tuple(
    o.strip() for o in os.environ.get(
        'FMH_PUBLIC_SITE_ORIGIN',
        'https://fayzmedical.uz,https://www.fayzmedical.uz').split(',')
    if o.strip())
PUBLIC_ENQUIRY_PER_HOUR = int(os.environ.get('FMH_PUBLIC_ENQUIRY_PER_HOUR', 5))
PUBLIC_ENQUIRY_PER_DAY = int(os.environ.get('FMH_PUBLIC_ENQUIRY_PER_DAY', 20))
# Attempts are allowed to run well ahead of accepted submissions: somebody
# mistyping their phone number three times has not used up their booking.
PUBLIC_ENQUIRY_ATTEMPTS_PER_HOUR = int(
    os.environ.get('FMH_PUBLIC_ENQUIRY_ATTEMPTS_PER_HOUR', 30))

_ENQUIRY_HITS = {}          # (bucket, ip) -> list of datetimes
_ENQUIRY_LOCK = threading.RLock()


def enquiry_rate_ok(bucket, ip, per_hour, per_day=None):
    """
    Whether this address may act again, and record that it did.

    Two buckets are counted separately. 'attempt' covers every POST,
    including the ones refused for a bad phone number, and stops a script
    hammering the endpoint. 'stored' counts only enquiries that were
    actually written, so a person fumbling the form does not spend their
    allowance on typing mistakes.

    Counted in memory, like the login throttle: a restart forgives
    everyone, which is the right trade at this size.
    """
    now = datetime.datetime.now()
    key = (bucket, ip)
    with _ENQUIRY_LOCK:
        hits = [t for t in _ENQUIRY_HITS.get(key, [])
                if (now - t).total_seconds() < 86400]
        last_hour = sum(1 for t in hits if (now - t).total_seconds() < 3600)
        if last_hour >= per_hour or (per_day is not None and len(hits) >= per_day):
            _ENQUIRY_HITS[key] = hits
            return False
        hits.append(now)
        _ENQUIRY_HITS[key] = hits
        return True


def read_json_file(path, default=None):
    """
    Load a JSON data file.

    An absent file yields `default` (there is nothing to lose yet). A file that
    exists but cannot be parsed raises, deliberately: the previous code caught
    every exception here and fell back to an empty list, so a handler that read,
    modified and wrote the document back persisted that empty value and erased
    every existing record. Failing the request is always preferable to silently
    truncating live data.
    """
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json_atomic(path, data):
    """
    Write JSON to `path` atomically: serialize into a temporary file in the same
    directory, flush to disk, then os.replace() it over the target. Readers never
    observe a partially written file.
    """
    directory = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp-', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


# ----------------------------------------------------------------------------
# The one price list
#
# data/pricing_config.json is the only place a tariff is set. Every page used
# to carry its own copy of the numbers (reception, accounting, the doctor
# wizard and superpage each had one), and the GET endpoint had a fifth copy
# that lacked the consultation fee, so a price changed in the editor reached
# some screens and not others. DEFAULT_PRICING is the single fallback: it
# fills in a package the file does not have, and stands in for a file that is
# missing or unreadable, so no reader ever sees an empty price list.
# ----------------------------------------------------------------------------
PRICING_FILE = os.path.join(BASE_DIR, 'data', 'pricing_config.json')

DEFAULT_PRICING = {
    "packages": {
        "statsionar_shared": {"daily_rate": 720000, "name_uz": "Statsionar (1 karavot / 2 kishilik xona)"},
        "statsionar_full_room": {"daily_rate": 1100000, "name_uz": "Statsionar Butun Xona (VIP Solo)"},
        "kunlik_statsionar": {"daily_rate": 630000, "name_uz": "Kunlik Statsionar (Kunduzgi o'rin)"},
        "ambulator_1": {"daily_rate": 310000, "name_uz": "Ambulator (1 mahal)"},
        "ambulator_2": {"daily_rate": 500000, "name_uz": "Ambulator (2 mahal)"},
        "consultation": {"daily_rate": 250000, "name_uz": "Shifokor Konsultatsiyasi (Birlamchi ko'rik)"},
    },
    "additional_services": [],
    # Pay for one duty shift. The HR page, the duty roster and the payslip
    # each typed 350 000 / 400 000 / 300 000 into their own text, so a raise
    # would have reached the label on one screen and not the money on another.
    "duty_tariffs": {
        "doctor_night": 350000,
        "nurse_24h": 400000,
        "sanitar_24h": 300000,
    },
}

# The consultation fee is kept as a package key, but it is a one-off fee, not
# a programme a patient is admitted on.
NON_PROGRAM_PACKAGES = ('consultation',)


def load_pricing():
    """
    The price list with every known package present.

    A broken file is not raised here (unlike read_json_file): GET used to answer
    {} for it, which left every page without prices. Readers get the defaults
    instead; the save path reads the raw file itself and refuses to overwrite
    one it cannot parse.
    """
    try:
        data = read_json_file(PRICING_FILE, None)
    except Exception as e:
        print("pricing_config.json is unreadable, serving defaults:", e)
        data = None
    if not isinstance(data, dict):
        data = {}
    result = dict(data)
    packages = data.get('packages') if isinstance(data.get('packages'), dict) else {}
    merged = {}
    for pid, default_pkg in DEFAULT_PRICING['packages'].items():
        pkg = packages.get(pid)
        if isinstance(pkg, dict):
            filled = dict(default_pkg)
            filled.update(pkg)
            merged[pid] = filled
        else:
            merged[pid] = dict(default_pkg)
    for pid, pkg in packages.items():
        if pid not in merged and isinstance(pkg, dict):
            merged[pid] = dict(pkg)
    result['packages'] = merged
    services = data.get('additional_services')
    result['additional_services'] = services if isinstance(services, list) else []
    tariffs = dict(DEFAULT_PRICING['duty_tariffs'])
    stored = data.get('duty_tariffs') if isinstance(data.get('duty_tariffs'), dict) else {}
    for key in tariffs:
        val = stored.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            tariffs[key] = val
    result['duty_tariffs'] = tariffs
    return result


def ensure_roster_sanitarkas(conn):
    """
    Give each sanitarka named in the duty roster a staff row.

    They were only names in data/duty_schedule.json, so payroll had no one to
    pay their shifts to. Only the id and name are copied: the phone numbers in
    that file are placeholders, and no salary is assumed (duty shifts are
    their pay until HR enters one). Rows that already exist are left alone.
    """
    roster = read_json_file(os.path.join(BASE_DIR, 'data', 'duty_schedule.json'), default=None)
    people = roster.get('sanitarkas') if isinstance(roster, dict) else None
    if not isinstance(people, list):
        return
    try:
        cur = conn.cursor()
        added = 0
        for p in people:
            if not isinstance(p, dict):
                continue
            sid = str(p.get('staff_id') or '').strip()[:64]
            name = str(p.get('name') or '').strip()[:255]
            if not sid or not name:
                continue
            cur.execute("SELECT 1 FROM staff WHERE id = ?", (sid,))
            if cur.fetchone():
                continue
            cur.execute("INSERT INTO staff (id, full_name, role, salary_base, shift_type, is_active) "
                        "VALUES (?, ?, 'sanitar', 0, '24h', 1)", (sid, name))
            added += 1
        conn.commit()
        if added:
            print(f"[✓] Added {added} sanitarka(s) from the duty roster to staff.")
    except Exception as e:
        conn.rollback()
        print(f"[!] Could not add roster sanitarkas to staff: {e}")


def rename_in_roster(staff_id, old_name, new_name):
    """
    Carry an employee's new name into the saved duty roster.

    Payroll pays a roster day only when its name matches the staff record
    behind the id (the two were filled separately and disagreed), so fixing a
    typo in someone's name used to stop pay for every shift already saved.
    Only days that carried the old name are renamed: a day that names someone
    else under this id is a roster mistake, and renaming it would pay this
    employee for that person's shift.
    """
    path = os.path.join(BASE_DIR, 'data', 'duty_schedule.json')
    roster = read_json_file(path, default=None)
    if not isinstance(roster, dict):
        return
    changed = False
    for sh in roster.get('shifts') or []:
        if not isinstance(sh, dict):
            continue
        for id_field in [k for k in sh if k.endswith('_id')]:
            name_field = id_field[:-3]
            if (sh.get(id_field) == staff_id and name_field in sh and sh[name_field] != new_name
                    and payroll.same_person(old_name, sh[name_field])):
                sh[name_field] = new_name
                changed = True
    for person in roster.get('sanitarkas') or []:
        if (isinstance(person, dict) and person.get('staff_id') == staff_id
                and person.get('name') != new_name and payroll.same_person(old_name, person.get('name'))):
            person['name'] = new_name
            changed = True
    if changed:
        write_json_atomic(path, roster)


def package_daily_rate(program_type, pricing=None):
    """
    The listed daily rate for a programme id, for a stay sent without a price.

    A programme that is not in the list (the doctor wizard's free-text
    'Statsionar davolanish', the desk's old 'detox' default) gets the shared
    inpatient rate, which is what the hardcoded 720 000 fallback stood for.
    """
    packages = (pricing or load_pricing()).get('packages') or {}
    pkg = packages.get(str(program_type or ''))
    if not isinstance(pkg, dict) or str(program_type) in NON_PROGRAM_PACKAGES:
        pkg = packages.get('statsionar_shared') or DEFAULT_PRICING['packages']['statsionar_shared']
    try:
        return float(pkg.get('daily_rate') or 0)
    except (TypeError, ValueError):
        return float(DEFAULT_PRICING['packages']['statsionar_shared']['daily_rate'])


def price_desk_visit(srv_type, body, pricing=None):
    """
    The one invoice line for a visit the desk records, or an error.

    Returns ({'service_name', 'quantity', 'unit_price', 'item_type'}, None) or
    (None, (message, field)).

    The desk printed the consultation fee on the slip and showed the
    outpatient daily fee in its preview, but neither request carried the fee
    to anything that bills, so both were given away. The price is the one the
    desk typed (the PO decided on 2026-10-08 that a typed price differing from
    the list is not refused) or, when none was typed, the listed one. Nothing
    is guessed: no price on either side, or an outpatient course with no
    length, is refused rather than billed as 0 or as some default.
    """
    packages = (pricing or load_pricing()).get('packages') or {}
    if srv_type == 'consultation':
        pkg_id, fee_key, item_type = 'consultation', 'consultation_fee', 'consultation'
        quantity = 1
    elif srv_type == 'outpatient':
        pkg_id = str(body.get('program_type') or '').strip()
        if not pkg_id.startswith('ambulator') or not isinstance(packages.get(pkg_id), dict):
            return None, ("Ambulator tarifini tanlang.", 'program_type')
        fee_key, item_type = 'visit_fee', 'procedure'
        try:
            quantity = int(str(body.get('days') or '').strip())
        except ValueError:
            quantity = 0
        if quantity < 1 or quantity > 365:
            return None, ("Ambulator kurs kunlari 1 dan 365 gacha bo'lishi kerak.", 'days')
    else:
        return None, ("Bu xizmat turi uchun hisob ochilmaydi.", 'service_type')

    pkg = packages.get(pkg_id) or {}
    raw_fee = body.get(fee_key)
    if raw_fee is None or str(raw_fee).strip() == '':
        price, _err = validate_amount(pkg.get('daily_rate') or 0)
        if _err:
            price = 0
    else:
        price, _err = validate_amount(raw_fee, "Narx")
        if _err or price != price:
            return None, (_err or "Narx raqam bo'lishi kerak.", fee_key)
    if not price or price <= 0:
        return None, ("Narx noldan katta bo'lishi kerak (narxlar ro'yxatida ham yo'q).", fee_key)
    name = str(pkg.get('name_uz') or pkg_id)
    return {'service_name': name[:255], 'quantity': quantity,
            'unit_price': float(price), 'item_type': item_type}, None


# ----------------------------------------------------------------------------
# Input validation
#
# Requests used to reach the database unchecked, so a mistake came back as the
# constraint that caught it — a receptionist who typed the discharge date into
# the admission date saw
#   Check constraint 'chk_admissions_planned_dates' is violated
# which says nothing about what to fix and leaks the schema. Values that a
# person can get wrong are checked here first and refused in plain Uzbek.
# ----------------------------------------------------------------------------

def parse_date_param(raw, default_today=True, field='sana'):
    """
    Read a YYYY-MM-DD value. Returns (date, None) or (None, message).
    An absent value means today, which is what every dashboard wants.
    """
    if raw is None or raw == '':
        if default_today:
            return _dt.date.today(), None
        return None, f"{field.capitalize()} ko'rsatilishi shart."
    try:
        return _dt.date.fromisoformat(str(raw)[:10]), None
    except Exception:
        return None, f"{field.capitalize()} noto'g'ri formatda. Kutilgan format: YYYY-MM-DD."


def validate_date_range(start_raw, end_raw, start_field='Boshlanish sanasi',
                        end_field='Tugash sanasi'):
    """
    Check a start/end pair before it reaches a CHECK constraint.
    Returns (start, end, None) or (None, None, message).
    """
    start, err = parse_date_param(start_raw, default_today=False, field=start_field)
    if err:
        return None, None, err
    end, err = parse_date_param(end_raw, default_today=False, field=end_field)
    if err:
        return None, None, err
    if end < start:
        return None, None, (f"{end_field} {start_field.lower()}dan oldin bo'lishi mumkin emas "
                            f"({end.isoformat()} < {start.isoformat()}).")
    if (end - start).days > 365:
        return None, None, f"Muddat 365 kundan oshmasligi kerak."
    return start, end, None


def validate_birth_year(raw):
    """A birth year that is in the future or implausibly old is a typo."""
    if raw in (None, ''):
        return None, None
    try:
        year = int(raw)
    except Exception:
        return None, "Tug'ilgan yil raqam bo'lishi kerak."
    this_year = _dt.date.today().year
    if year > this_year:
        return None, f"Tug'ilgan yil kelajakda bo'lishi mumkin emas ({year})."
    if year < this_year - 130:
        return None, f"Tug'ilgan yil haqiqiy emas ({year})."
    return year, None


GENDERS = ('male', 'female', 'other')


def parse_birth_and_gender(body):
    """
    Date of birth and gender as the front desk supplies them.

    Returns (birth_date_iso, birth_year, gender, error), where error is None
    or a (message, field) pair naming the input at fault.

    Registration had no field for either, and the inserts said
    body.get('gender', 'male') and body.get('birth_year', 1990). Every patient
    registered at the desk therefore entered the record as a man born in 1990.
    An invented date of birth is worse than a missing one, because nothing
    downstream can tell it apart from a real one -- the PDF header prints an
    age from it and the consultation form pre-fills from it. Both columns are
    now left empty unless someone actually supplies them.

    birth_year is still derived and stored: the CRM list, the PDF header and
    the consultation prefill all read it, and deriving it here is what keeps
    it from drifting away from birth_date.
    """
    raw_date = (body.get('birth_date') or '').strip() if isinstance(body.get('birth_date'), str) else body.get('birth_date')
    birth_date = None
    birth_year = None

    if raw_date:
        try:
            d = _dt.date.fromisoformat(str(raw_date)[:10])
        except Exception:
            return None, None, None, ("Tug'ilgan sana YYYY-MM-DD ko'rinishida bo'lishi kerak.", 'birth_date')
        today = _dt.date.today()
        if d > today:
            return None, None, None, ("Tug'ilgan sana kelajakda bo'lishi mumkin emas.", 'birth_date')
        if d.year < today.year - 130:
            return None, None, None, ("Tug'ilgan sana haqiqiy emas.", 'birth_date')
        birth_date = d.isoformat()
        birth_year = d.year
    elif body.get('birth_year') not in (None, ''):
        birth_year, err = validate_birth_year(body.get('birth_year'))
        if err:
            return None, None, None, (err, 'birth_year')

    gender = body.get('gender')
    gender = gender.strip().lower() if isinstance(gender, str) else gender
    if gender in ('', None):
        gender = None
    elif gender not in GENDERS:
        return None, None, None, ("Jins qiymati noto'g'ri.", 'gender')

    return birth_date, birth_year, gender, None


def validate_amount(raw, field="Summa", allow_negative=False, maximum=10_000_000_000):
    """Money must be a number, and within a sane bound."""
    try:
        value = float(raw)
    except Exception:
        return None, f"{field} raqam bo'lishi kerak."
    if not allow_negative and value < 0:
        return None, f"{field} manfiy bo'lishi mumkin emas."
    if abs(value) > maximum:
        return None, f"{field} juda katta."
    return value, None


# HR-only staff fields (see db.STAFF_HR_COLUMNS). The lists match the options
# of the HR form so a value the page cannot show back is refused, not stored.
STAFF_DEPARTMENTS = ('doctors', 'nurses', 'administration', 'diagnostics', 'support')
STAFF_CATEGORIES = ('Oliy toifa', '1-toifa', '2-toifa', 'Mutaxassis')
STAFF_FLOORS = ('all', '1', '2')


def parse_staff_hr_fields(body):
    """
    The HR-only staff fields present in `body`, validated.

    Returns (fields, None) or (None, (message, field)). Only keys the request
    actually sends are returned: a caller that does not know these fields (the
    Super-Portal hire form) must not wipe what HR entered. A key sent blank
    clears the value to NULL; nothing is filled in on anyone's behalf.
    """
    out = {}

    def _text(key):
        v = body.get(key)
        return v.strip() if isinstance(v, str) else v

    if 'hire_date' in body:
        raw = _text('hire_date')
        if raw in (None, ''):
            out['hire_date'] = None
        else:
            try:
                d = _dt.date.fromisoformat(str(raw)[:10])
            except Exception:
                return None, ("Ishga qabul sanasi YYYY-MM-DD ko'rinishida bo'lishi kerak.", 'hire_date')
            today = _dt.date.today()
            if d > today + _dt.timedelta(days=366):
                return None, ("Ishga qabul sanasi bir yildan ko'p kelajakda bo'lishi mumkin emas.", 'hire_date')
            if d.year < 1950:
                return None, ("Ishga qabul sanasi haqiqiy emas.", 'hire_date')
            out['hire_date'] = d.isoformat()

    if 'experience_years' in body:
        raw = _text('experience_years')
        if raw in (None, ''):
            out['experience_years'] = None
        else:
            try:
                if isinstance(raw, bool):
                    raise ValueError
                years = float(raw)
                if years != int(years):
                    raise ValueError
                years = int(years)
            except Exception:
                return None, ("Ish staji butun son bo'lishi kerak.", 'experience_years')
            if years < 0 or years > 70:
                return None, ("Ish staji 0 dan 70 yilgacha bo'lishi kerak.", 'experience_years')
            out['experience_years'] = years

    for key, allowed, label in (('category', STAFF_CATEGORIES, 'Toifa'),
                                ('department', STAFF_DEPARTMENTS, "Bo'lim"),
                                ('assigned_floor', STAFF_FLOORS, 'Qavat')):
        if key in body:
            raw = _text(key)
            raw = None if raw in (None, '') else str(raw)
            if raw is not None and raw not in allowed:
                return None, (f"{label} qiymati noto'g'ri.", key)
            out[key] = raw

    if 'role_title_uz' in body:
        raw = _text('role_title_uz')
        raw = None if raw in (None, '') else str(raw)
        if raw is not None and len(raw) > 255:
            return None, ("Lavozim nomi juda uzun (255 belgigacha).", 'role_title_uz')
        # HR pages put these two straight into the staff cards; refusing
        # markup characters here backs up the escaping done on the page.
        if raw is not None and any(ch in raw for ch in '<>"'):
            return None, ("Lavozim nomida < > \" belgilari bo'lishi mumkin emas.", 'role_title_uz')
        out['role_title_uz'] = raw

    if 'telegram' in body:
        raw = _text('telegram')
        raw = None if raw in (None, '') else str(raw).lstrip('@').strip() or None
        if raw is not None and len(raw) > 64:
            return None, ("Telegram nomi juda uzun.", 'telegram')
        if raw is not None and any(ch in raw for ch in '<>"'):
            return None, ("Telegram nomida < > \" belgilari bo'lishi mumkin emas.", 'telegram')
        out['telegram'] = raw

    if 'detox_procedure_fee' in body:
        raw = _text('detox_procedure_fee')
        if raw in (None, ''):
            out['detox_procedure_fee'] = None
        else:
            fee, err = validate_amount(raw, field="Protsedura haqi")
            if err or isinstance(raw, bool) or fee != fee:
                return None, (err or "Protsedura haqi raqam bo'lishi kerak.", 'detox_procedure_fee')
            out['detox_procedure_fee'] = fee

    if 'bls_cpr_certified' in body:
        raw = body.get('bls_cpr_certified')
        if raw in (None, ''):
            out['bls_cpr_certified'] = None
        elif isinstance(raw, bool):
            out['bls_cpr_certified'] = 1 if raw else 0
        elif raw in (0, 1, '0', '1'):
            out['bls_cpr_certified'] = int(raw)
        else:
            return None, ("BLS/CPR belgisi noto'g'ri.", 'bls_cpr_certified')

    return out, None


ATTENDANCE_STATUSES = ('present', 'absent', 'late', 'on_leave', 'sick')
ATTENDANCE_SHIFTS = ('day', 'night', '24h')
# Someone who did not come has no arrival or departure time to record.
ATTENDANCE_AWAY = ('absent', 'on_leave', 'sick')


def _parse_hhmm(raw, field, label):
    """'HH:MM' (or 'HH:MM:SS') -> datetime.time, or (None, message) when wrong."""
    s = str(raw).strip()
    try:
        parts = s.split(':')
        if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
            raise ValueError
        return _dt.time(int(parts[0]), int(parts[1])), None
    except Exception:
        return None, (f"{label} SS:DD ko'rinishida bo'lishi kerak.", field)


def parse_attendance(body):
    """
    One attendance entry for POST /api/hr/attendance, validated.

    Returns (row, None) or (None, (message, field)). check_in/check_out are
    times on work_date; a check-out at or before the check-in belongs to the
    next morning (night and 24-hour shifts end the day after they start).
    """
    staff_id = str(body.get('staff_id') or '').strip()
    if not staff_id:
        return None, ("Xodim tanlanmagan.", 'staff_id')

    raw_date = body.get('work_date')
    if raw_date in (None, ''):
        return None, ("Sana ko'rsatilishi shart.", 'work_date')
    try:
        work_date = _dt.date.fromisoformat(str(raw_date).strip()[:10])
        if len(str(raw_date).strip()) != 10:
            raise ValueError
    except Exception:
        return None, ("Sana YYYY-MM-DD ko'rinishida bo'lishi kerak.", 'work_date')
    # One day of slack: the server may run on UTC while the clinic is on
    # Tashkent time (UTC+5), so between 00:00 and 05:00 in Tashkent the
    # browser's "today" is the server's tomorrow and the morning's attendance
    # was refused as a future day.
    if work_date > _dt.date.today() + _dt.timedelta(days=1):
        return None, ("Kelajakdagi kun uchun davomat kiritib bo'lmaydi.", 'work_date')
    if work_date.year < 2000:
        return None, ("Sana haqiqiy emas.", 'work_date')

    status = str(body.get('status') or '').strip()
    if status not in ATTENDANCE_STATUSES:
        return None, ("Davomat holati noto'g'ri.", 'status')
    shift = str(body.get('shift_type') or '').strip()
    if shift not in ATTENDANCE_SHIFTS:
        return None, ("Smena turi noto'g'ri (kunduzgi, tungi yoki 24 soat).", 'shift_type')

    check_in = check_out = None
    raw_in = body.get('check_in')
    raw_out = body.get('check_out')
    if raw_in not in (None, ''):
        t_in, err = _parse_hhmm(raw_in, 'check_in', 'Kelgan vaqti')
        if err:
            return None, err
        check_in = _dt.datetime.combine(work_date, t_in)
    if raw_out not in (None, ''):
        t_out, err = _parse_hhmm(raw_out, 'check_out', 'Ketgan vaqti')
        if err:
            return None, err
        check_out = _dt.datetime.combine(work_date, t_out)
        if check_in is not None and check_out <= check_in:
            check_out += _dt.timedelta(days=1)
    if status in ATTENDANCE_AWAY and (check_in or check_out):
        return None, ("Kelmagan xodim uchun kelgan/ketgan vaqt kiritilmaydi.", 'check_in')

    late_minutes = None
    raw_late = body.get('late_minutes')
    if raw_late not in (None, ''):
        try:
            if isinstance(raw_late, bool):
                raise ValueError
            late_f = float(raw_late)
            if late_f != int(late_f):
                raise ValueError
            late_minutes = int(late_f)
        except Exception:
            return None, ("Kechikish daqiqasi butun son bo'lishi kerak.", 'late_minutes')
        if late_minutes < 0 or late_minutes > 1440:
            return None, ("Kechikish 0 dan 1440 daqiqagacha bo'lishi kerak.", 'late_minutes')
    if status != 'late':
        # Lateness only means something for a 'late' entry; a leftover number
        # from the form must not label an on-time day as late.
        late_minutes = None

    notes = body.get('notes')
    notes = notes.strip() if isinstance(notes, str) else None
    if notes and len(notes) > 1000:
        return None, ("Izoh juda uzun (1000 belgigacha).", 'notes')

    return {
        'staff_id': staff_id,
        'work_date': work_date.isoformat(),
        'shift_type': shift,
        'status': status,
        'check_in': check_in.strftime('%Y-%m-%d %H:%M:%S') if check_in else None,
        'check_out': check_out.strftime('%Y-%m-%d %H:%M:%S') if check_out else None,
        'late_minutes': late_minutes,
        'notes': notes or None,
    }, None


def attendance_out(r):
    """
    An attendance row as the HR page shows it: HH:MM times and the hours
    worked worked out from them (never typed in, so they cannot disagree).
    """
    row = dict(r)

    def _as_dt(v):
        if isinstance(v, _dt.datetime):
            return v
        if isinstance(v, str) and v:
            try:
                return _dt.datetime.fromisoformat(v.replace('T', ' ')[:19])
            except Exception:
                return None
        return None

    cin, cout = _as_dt(row.get('check_in')), _as_dt(row.get('check_out'))
    row['check_in_time'] = cin.strftime('%H:%M') if cin else None
    row['check_out_time'] = cout.strftime('%H:%M') if cout else None
    row['worked_hours'] = round((cout - cin).total_seconds() / 3600.0, 1) if (cin and cout) else None
    return row


from db import (
    get_db,
    get_active_engine,
    admit_patient,
    transfer_patient_bed,
    discharge_patient,
    list_room_availability,
    ensure_patient_columns,
    ensure_ward_round_schema,
    ensure_appointment_requests,
    ensure_medication_purchases,
    ensure_appointment_service_types,
    APPOINTMENT_SERVICE_TYPES,
    ensure_staff_roles,
    ensure_staff_hr_columns,
    ensure_invoice_visit_link,
    ensure_user_sessions,
    ensure_transaction_payroll_month,
    STAFF_HR_COLUMNS,
    STAFF_ROLES,
    load_config
)

import auth
import audit
import permissions
import user_admin
import nursery
import owner_report
import consultation
import inventory
import warehouse_api
import payroll


def validate_prescription_fields(rx):
    """
    The parts of a medication order the prescriber must state.

    Returns (duration_days, None) or (None, (message, field)). Dose, route
    and frequency decide what reaches the patient; a blank one is a question
    for the prescriber, not something to fill in. Shared by the single-order
    endpoint and the consultation case, which used to fill every blank with
    400 ml by IV drip, once a day, for five days.
    """
    if not (rx.get('medication_name') or rx.get('name') or '').strip():
        return None, ('Dori nomi kiritilishi shart.', 'medication_name')
    for field, label in (('dosage', 'Doza'), ('route', 'Yuborish yo\'li'),
                         ('frequency', 'Qabul chastotasi')):
        if not str(rx.get(field) or '').strip():
            return None, (f'{label} kiritilishi shart.', field)
    days_raw = rx.get('duration_days')
    if days_raw in (None, ''):
        days_raw = rx.get('duration')
    if days_raw in (None, ''):
        return None, ('Davomiylik (kun) kiritilishi shart.', 'duration_days')
    try:
        duration_days = int(days_raw)
    except (TypeError, ValueError):
        return None, ('Davomiylik raqam bo\'lishi kerak.', 'duration_days')
    if not (1 <= duration_days <= 365):
        return None, ('Davomiylik 1-365 kun oralig\'ida bo\'lishi kerak.', 'duration_days')
    return duration_days, None


# Every money route used to carry its own copy of this table; the copies
# drifted (only payments knew 'card'), and the accounting page could not match
# the stored names. One table, one place to add a method.
PAYMENT_METHOD_ALIASES = {
    'cash': 'cash', 'cash_register': 'cash_register',
    'card': 'terminal', 'terminal': 'terminal',
    'card_transfer': 'card_transfer',
    'online': 'payme_click', 'payme_click': 'payme_click',
    'click': 'payme_click', 'payme': 'payme_click',
    'bank': 'bank_wire', 'bank_wire': 'bank_wire',
    'mixed': 'cash',
}


def normalize_payment_method(raw):
    """Map a UI or alias method name to the value the payments CHECK accepts."""
    return PAYMENT_METHOD_ALIASES.get(str(raw or 'cash').strip().lower(), 'cash')


def account_source_for(method):
    """Which money account an accounting transaction paid by `method` moves."""
    if method in ('cash', 'cash_register'):
        return 'kassa'
    if method == 'terminal':
        return 'terminal_bank'
    return 'main_bank_account'


def payment_destination_for(method):
    """
    Which account a patient payment paid by `method` lands in. The accounting
    page books Click/Payme to the merchant account; the desk advance used
    account_source_for and filed the same money under the main bank account,
    so per-account balances disagreed between the two pages.
    """
    if method == 'payme_click':
        return 'click_payme_merchant'
    return account_source_for(method)


def new_record_id(cur, table, prefix):
    """
    A free id of the form PREFIX-####, probed against `table`.

    Fourteen handlers drew the four digits at random and inserted without
    looking. With 9,000 possible values the first clash is likely by about
    the 112th row, and every one after that fails as a 500: a prescription,
    an appointment or a discharge summary the doctor has to type again. The
    probe is safe without a transaction because writes run one at a time
    under WRITE_LOCK. A saturated space falls back to a millisecond stamp.
    """
    for _ in range(200):
        candidate = f"{prefix}-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
        cur.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (candidate,))
        if not cur.fetchone():
            return candidate
    return f"{prefix}-{int(datetime.datetime.now().timestamp() * 1000)}"


CLIENT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def validate_client_id(raw, field='id'):
    """
    An id the page chose itself (an edit of an existing row, or a resend),
    checked before it reaches the database.

    Returns (id_or_None, error_or_None); None with no error means "not sent,
    generate one". Ids typed by the caller were stored as given and later
    printed inside inline onclick="...('<id>')" handlers and copied into
    invoice ids (INV-<appointment id>), so an id holding a quote ran script
    in the next viewer's browser -- the Super-Portal is a superadmin's. Every
    id the server generates (PREFIX-####, STF-DOC-01) fits this pattern.
    """
    if raw in (None, ''):
        return None, None
    value = str(raw).strip() if isinstance(raw, (str, int)) and not isinstance(raw, bool) else None
    if not value or not CLIENT_ID_RE.match(value):
        return None, "Identifikator faqat lotin harflari, raqamlar, '-' va '_' dan iborat bo'lishi kerak (64 belgigacha)."
    return value, None


def new_patient_ids(cur, id_prefix='PAT-2026'):
    """
    A free (id, patient_code) pair sharing the same digits.

    patient_code is UNIQUE and was derived from the id's last four digits,
    so even a free id could fail on the code -- PAT-1234 from the CRM and
    PAT-2026-1234 from the desk both make FMH-2026-1234. Both are probed.
    """
    for _ in range(200):
        n = int(os.urandom(3).hex(), 16) % 9000 + 1000
        pid, code = f"{id_prefix}-{n}", f"FMH-2026-{n}"
        cur.execute("SELECT 1 FROM patients WHERE id = ? OR patient_code = ? LIMIT 1",
                    (pid, code))
        if not cur.fetchone():
            return pid, code
    ms = int(datetime.datetime.now().timestamp() * 1000)
    return f"{id_prefix}-{ms}", f"FMH-2026-{ms}"


class ClinicRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    # ------------------------------------------------------------------------
    # Authentication gate
    #
    # Every /api/* route other than the auth endpoints, and every portal page,
    # now requires a signed-in session. API callers get 401 JSON; browsers
    # asking for a page get redirected to the login screen. Stylesheets,
    # scripts and images stay open so the login screen can render.
    # ------------------------------------------------------------------------
    def current_session(self):
        token = auth.token_from_cookie_header(self.headers.get('Cookie'))
        return auth.get_session(token)

    def _reject_unauthenticated(self, path):
        """Send the right kind of refusal. Returns True once handled."""
        if path.startswith('/api/'):
            self._set_json_headers(401)
            self.wfile.write(json.dumps({
                'error': 'Avtorizatsiya talab qilinadi',
                'detail': 'Sessiya topilmadi yoki muddati tugagan. Iltimos, qaytadan kiring.',
                'login_url': '/login.html'
            }, ensure_ascii=False).encode('utf-8'))
        else:
            target = '/login.html'
            if path and path not in ('/', ''):
                target += '?next=' + urllib.parse.quote(path, safe='')
            self.send_response(302)
            self.send_header('Location', target)
            self.end_headers()
        return True

    # ------------------------------------------------------------------------
    # Audit capture
    #
    # The route handlers write their JSON straight to the socket, so to record
    # what actually happened the response is teed as it goes out: the status
    # line is noted, and the first few KB of body are kept so a created row's
    # generated id can be pulled out of it. Auditing then happens once, at the
    # dispatch point, instead of being threaded through thirty write branches.
    # ------------------------------------------------------------------------
    class _Tee:
        """Forwards writes to the real stream while keeping a capped copy."""

        LIMIT = 4096

        def __init__(self, inner):
            self._inner = inner
            self.captured = bytearray()

        def write(self, data):
            if len(self.captured) < self.LIMIT:
                try:
                    self.captured.extend(data[: self.LIMIT - len(self.captured)])
                except Exception:
                    pass
            return self._inner.write(data)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def send_response(self, code, message=None):
        self._audit_status = code
        return super().send_response(code, message)

    def _audit_mutation(self, path, body, captured):
        """Record one completed write. Only 2xx outcomes are logged as changes."""
        status = getattr(self, '_audit_status', None)
        if status is None or not (200 <= status < 300):
            return
        if path.startswith('/api/auth/'):
            return          # handled explicitly by the auth routes themselves
        sess = self.current_session()
        user = sess['user'] if sess else None
        response_body = None
        if captured:
            try:
                # end_headers() writes the status line and headers to the same
                # stream, so the capture holds those before the JSON. Drop
                # everything up to the blank line that separates them —
                # otherwise the parse fails and the trail records the URL tail
                # instead of the generated id.
                raw = bytes(captured)
                sep = raw.find(b'\r\n\r\n')
                if sep == -1:
                    sep = raw.find(b'\n\n')
                    body_bytes = raw[sep + 2:] if sep != -1 else raw
                else:
                    body_bytes = raw[sep + 4:]
                response_body = json.loads(body_bytes.decode('utf-8', 'replace'))
            except Exception:
                response_body = None
        try:
            conn = get_db()
            try:
                audit.ensure_schema(conn)
                audit.record(
                    conn,
                    audit.entity_for_path(path),
                    audit.entity_id_from(path, body, response_body),
                    audit.action_for(self.command, path),
                    user=user,
                    new_data=body if isinstance(body, dict) else None,
                    ip_address=self.client_ip(),
                )
            finally:
                conn.close()
        except Exception as e:
            print(f"[!] Could not audit {self.command} {path}: {e}")

    # Staff columns that are someone's pay.
    PAY_FIELDS = ('salary_base', 'detox_procedure_fee')

    def _strip_pay_fields(self, rows):
        """
        Drop pay columns from staff rows unless the caller handles pay.

        /api/staff and /api/doctors are readable by every login (doctor
        pickers, menus), so they carried everyone's salary -- and, once HR
        could save it, the detox procedure fee -- to the desk, nurses and
        doctors. Pay is for HR, the cashier who pays it and the owner (the
        desk has accounting:read for balances, which is not a reason to see
        pay). One helper so the two routes cannot drift apart again.
        """
        _u = (self.current_session() or {}).get('user')
        if (permissions.can(_u, 'hr') or permissions.can(_u, 'accounting', 'write')
                or permissions.can(_u, 'owner')):
            return rows
        for r in rows:
            for k in self.PAY_FIELDS:
                r.pop(k, None)
        return rows

    def _send_validation_error(self, message, field=None, cors=False):
        """
        Refuse a request because of its input, in words the person who typed it
        can act on. 400, and never the raw database error.
        """
        payload = {'error': message}
        if field:
            payload['field'] = field
        self._set_json_headers(400, cors=cors)
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def _send_enquiry_ok(self, request_id=None):
        """
        The reply the website shows its visitor.

        Deliberately the same whether the enquiry was stored or silently
        dropped as a bot, so a script cannot tell which of its submissions
        landed. It promises a call back rather than a booking, because nobody
        at the clinic has seen it yet.
        """
        self._set_json_headers(201, cors=True)
        payload = {'message': "So'rovingiz qabul qilindi. Qabulxona tez orada "
                              "siz bilan bog'lanadi."}
        if request_id:
            payload['request_id'] = request_id
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def _send_health(self):
        """
        Is the service usable? 200 when yes, 503 when the database is not
        reachable -- which is the failure a monitor needs to catch, because
        the pages still load in that state and only break once staff try to
        do anything.
        """
        db_ok = False
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute('SELECT 1')
            cur.fetchone()
            db_ok = True
        except Exception as e:
            print(f'[health] database unreachable: {e}')
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
        self._set_json_headers(200 if db_ok else 503)
        self.wfile.write(json.dumps({
            'status': 'ok' if db_ok else 'degraded',
            'database': 'ok' if db_ok else 'unreachable',
        }).encode('utf-8'))

    def _actor_staff_id(self, body, field='staff_id'):
        """
        Who is doing this, as a staff id, or None.

        Five handlers used to fall back to a literal 'STF-DOC-01' or
        'STF-REC-01' -- real people -- so a prescription, a transfer or a cash
        receipt with no author was recorded over the name of whoever happened
        to hold that id. On a medical or financial record that is a signature.
        An unknown author is now None, which is honest and which the column
        already allows.
        """
        given = (body or {}).get(field)
        if given:
            return given
        sess = self.current_session()
        return (sess['user'].get('staff_id') if sess else None) or None

    def _record_payment(self, conn, cur, inv_id, amount, method, acc,
                        pay_date, notes, staff_id, transaction_ref=None, pay_id=None):
        """
        Insert one payment row, commit, and notify Telegram.

        Shared by POST /api/payments and by the advance taken at admission,
        so both write the same row (the payments triggers then update the
        invoice and the cash journal) and both reach the accounting topic.
        """
        pay_id = pay_id or new_record_id(cur, 'payments', 'PAY-2026')
        ref = transaction_ref or f"CHK-{pay_id[-4:]}"
        cur.execute("""
            INSERT INTO payments (id, invoice_id, amount, payment_method, account_destination, transaction_ref, payment_date, notes, received_by_staff_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pay_id, inv_id, amount, method, acc, ref, pay_date, notes, staff_id))
        conn.commit()
        if telegram_service:
            try:
                telegram_service.notify_payment_entered_async({
                    'id': pay_id,
                    'invoice_id': inv_id,
                    'amount': amount,
                    'payment_method': method,
                    'account_destination': acc,
                    'transaction_ref': ref,
                    'payment_date': pay_date,
                    'notes': notes,
                    'staff_id': staff_id
                })
            except Exception as _e_notify:
                print(f"[Telegram Notify Error] {_e_notify}")
        return pay_id

    def _send_server_error(self):
        """
        A 500 that says nothing about the inside of the system.

        The traceback is already on the server log, where the people who run
        the clinic can read it. What reaches the browser is a sentence a
        receptionist can act on.
        """
        try:
            self._set_json_headers(500)
            self.wfile.write(json.dumps({
                'error': "Serverda kutilmagan xatolik yuz berdi. "
                         "Iltimos, qayta urinib ko'ring; takrorlansa "
                         "tizim administratoriga xabar bering."
            }, ensure_ascii=False).encode('utf-8'))
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def client_ip(self):
        """
        The caller's address, honouring the proxy header the documented Nginx
        vhost sets. Used for throttling and for the audit trail.
        """
        fwd = self.headers.get('X-Real-IP') or self.headers.get('X-Forwarded-For')
        if fwd:
            return fwd.split(',')[0].strip()
        try:
            return self.client_address[0]
        except Exception:
            return '-'

    def _reject_unauthorized(self, path, reason, user):
        """
        Refuse an authenticated caller who lacks the permission. 403, not 401:
        signing in again will not help, and the difference matters to the
        client-side handler, which must not bounce them to the login screen.
        """
        print(f"[authz] denied {self.command} {path} for "
              f"{(user or {}).get('username')} ({reason})")
        try:
            conn = get_db()
            try:
                audit.record(conn, 'auth', path, 'ACCESS_DENIED', user=user,
                             new_data={'method': self.command, 'required': reason},
                             ip_address=self.client_ip())
            finally:
                conn.close()
        except Exception as e:
            # The refusal still stands -- an unreachable database must not
            # turn a 403 into a 500. But it leaves a hole in the trail, and
            # a hole nobody is told about is worse than the missing row.
            print(f'[audit] refusal of {self.command} {path} was NOT recorded: {e}')

        if path.startswith('/api/'):
            self._set_json_headers(403)
            self.wfile.write(json.dumps({
                'error': 'Ruxsat etilmagan',
                'detail': "Bu amal uchun sizning lavozimingizda ruxsat yo'q.",
                'required': reason,
            }, ensure_ascii=False).encode('utf-8'))
        else:
            # Send them somewhere they are allowed to be rather than showing an
            # empty shell they cannot populate.
            self.send_response(302)
            self.send_header('Location', permissions.home_for(user))
            self.end_headers()
        return True

    def enforce_auth(self, path):
        """
        Authenticate, then authorize. True when the request has been refused
        and the caller should stop processing.
        """
        if not auth.requires_session(path):
            return False

        sess = self.current_session()
        if not sess:
            return self._reject_unauthenticated(path)

        user = sess['user']

        # An account still on the password it was issued may only reach the
        # change-password screen and the endpoints that serve it.
        if auth.must_change_password(user) and path not in (
                '/change-password.html', '/api/auth/change-password', '/api/auth/session'):
            if path.startswith('/api/'):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({
                    'error': "Parolni o'zgartirish talab qilinadi",
                    'detail': "Davom etishdan oldin standart parolni o'zgartiring.",
                    'change_password_url': '/change-password.html',
                }, ensure_ascii=False).encode('utf-8'))
            else:
                self.send_response(302)
                self.send_header('Location', '/change-password.html')
                self.end_headers()
            return True

        if path.startswith('/api/'):
            allowed, reason = permissions.authorize_api(user, self.command, path)
        else:
            allowed, reason = permissions.authorize_page(user, path)
        if not allowed:
            return self._reject_unauthorized(path, reason, user)
        return False

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('X-Robots-Tag', 'noindex, nofollow, noarchive')
        # A clinical record system should not be loadable inside someone
        # else's page, should not have its content types guessed at, and
        # should not leak patient ids through the Referer header when a
        # member of staff follows a link off the portal.
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Referrer-Policy', 'same-origin')
        super().end_headers()

    def _set_json_headers(self, status=200, cors=False):
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            # cors=True only on the public enquiry route, whose caller is
            # the marketing site on another domain.
            if cors:
                self._enquiry_cors()
            # No Access-Control-Allow-Origin. The portals are served from this
            # same origin, so none of them needs CORS, and the header used to
            # say '*' on every clinical response -- an open invitation for any
            # page on the internet to read this API. SameSite=Strict already
            # keeps the session cookie off cross-site requests; this removes
            # the standing offer as well.
            self.end_headers()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def _enquiry_cors(self):
        """
        Allow the marketing site to call the enquiry route, and nothing else
        to call anything. Returns True when the caller's Origin is one we
        publish to; the headers are sent by the caller before end_headers().
        """
        origin = self.headers.get('Origin')
        if origin and origin in PUBLIC_SITE_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.send_header('Access-Control-Max-Age', '600')
            return True
        return False

    def do_OPTIONS(self):
        # Preflight is answered only for the public enquiry route. Every
        # other endpoint is same-origin and needs no CORS at all.
        path = urllib.parse.urlparse(self.path).path
        self.send_response(204 if path == PUBLIC_ENQUIRY_PATH else 404)
        if path == PUBLIC_ENQUIRY_PATH:
            self._enquiry_cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Answered before the session gate, because whatever is watching
        # this server cannot sign in. Nothing here is worth hiding: it
        # says only whether the service and its database are up, with no
        # version, no counts and no error text -- a failing probe should
        # not teach a stranger what went wrong.
        if path == '/api/health':
            self._send_health()
            return

        if self.enforce_auth(path):
            return

        # Answered before the request opens a database connection, so a page
        # can still learn whether it is signed in when MySQL is unreachable.
        # (auth may read user_sessions for a session it has not cached yet,
        # but treats a database failure as "not signed in", never as a 500.)
        if path == '/api/auth/session':
            sess = self.current_session()
            user = sess['user'] if sess else None
            payload = {'authenticated': bool(sess), 'user': user}
            if user:
                # The frontend uses these to build the navigation, so each
                # member of staff is shown only the portals their job needs.
                payload.update({
                    'permissions': permissions.permissions_for(user),
                    'modules': permissions.visible_modules(user),
                    'pages': permissions.visible_pages(user),
                    'home': permissions.home_for(user),
                    'role_label': (permissions.ROLES.get(user.get('role')) or {}).get('label'),
                    'must_change_password': auth.must_change_password(user),
                })
            self._set_json_headers(200)
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            return

        if path in ('/', '', '/index.html'):
            # Each role lands on its own home, not on the Super-Portal, which
            # most roles may not open (they were bounced a second time).
            sess = self.current_session() or {}
            self.send_response(302)
            self.send_header('Location', permissions.home_for(sess.get('user')))
            self.end_headers()
            return

        if path.startswith('/api/'):
            self.handle_api_get(path, query)
            return

        # Anything not on the allow-list is not on disk as far as the web
        # is concerned. Checked after enforce_auth so a signed-in member of
        # staff cannot download db_config.json or the source either.
        if not auth.is_servable_path(path):
            self.send_error(404, 'File not found')
            return
        super().do_GET()

    def do_HEAD(self):
        """
        HEAD went straight to SimpleHTTPRequestHandler, which never asked
        about the session: HEAD /doctor.html answered 200 where GET answers
        302 to the login screen, and HEAD /db_config.json confirmed the
        credentials file and its size. It now takes the same two gates as
        GET.
        """
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.enforce_auth(path):
            return
        if path.startswith('/api/') or not auth.is_servable_path(path):
            self.send_error(404, 'File not found')
            return
        super().do_HEAD()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.enforce_auth(path):
            return
        if path.startswith('/api/'):
            content_len = int(self.headers.get('Content-Length', 0))
            body_raw = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else '{}'
            try:
                body = json.loads(body_raw)
            except Exception:
                body = {}
            tee = self._Tee(self.wfile)
            self.wfile = tee
            try:
                with WRITE_LOCK:
                    self.handle_api_post(path, body)
            finally:
                self.wfile = tee._inner
                self._audit_mutation(path, body, tee.captured)
        else:
            self._set_json_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.enforce_auth(path):
            return
        if path.startswith('/api/'):
            content_len = int(self.headers.get('Content-Length', 0))
            body_raw = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else '{}'
            try:
                body = json.loads(body_raw)
            except Exception:
                body = {}
            tee = self._Tee(self.wfile)
            self.wfile = tee
            try:
                with WRITE_LOCK:
                    self.handle_api_put(path, body)
            finally:
                self.wfile = tee._inner
                self._audit_mutation(path, body, tee.captured)
        else:
            self._set_json_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.enforce_auth(path):
            return
        if path.startswith('/api/'):
            tee = self._Tee(self.wfile)
            self.wfile = tee
            try:
                with WRITE_LOCK:
                    self.handle_api_delete(path)
            finally:
                self.wfile = tee._inner
                self._audit_mutation(path, {}, tee.captured)
        else:
            self._set_json_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))

    # ------------------------------------------------------------------------
    # Warehouse (/api/warehouse/*). The logic is in inventory.py and the routes
    # in warehouse_api.py; this only hands over the request and writes the
    # answer, so a 400 keeps the shape _send_validation_error gives everywhere.
    # ------------------------------------------------------------------------
    def _handle_warehouse(self, method, path, query, body, conn):
        user = (self.current_session() or {}).get('user')
        ctx = {
            'parse_date_param': parse_date_param,
            'normalize_payment_method': normalize_payment_method,
            'account_source_for': account_source_for,
        }
        status, payload = warehouse_api.handle(method, path, query, body, user, conn, ctx)
        if isinstance(payload, dict) and '_csv' in payload:
            data = payload['_csv'].encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="%s"' % payload['_filename'])
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        note = payload.pop('_notify', None) if isinstance(payload, dict) else None
        if status == 400 and isinstance(payload, dict) and 'error' in payload:
            self._send_validation_error(payload['error'], payload.get('field'))
        else:
            self._set_json_headers(status)
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        if note and telegram_service:
            try:
                telegram_service.notify_accounting_transaction_entered_async(note)
            except Exception as _e_notify:
                print(f"[Telegram Notify Error] {_e_notify}")

    # ------------------------------------------------------------------------
    # API GET HANDLERS (100% Real MySQL 8.0 Database Data)
    # ------------------------------------------------------------------------
    def handle_api_get(self, path, query):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()

            # Warehouse stock, lots, ledger and reports.
            if path.startswith('/api/warehouse'):
                self._handle_warehouse('GET', path, query, None, conn)

            # 0. /api/stats/summary -> Real-Time Hospital KPI summary
            elif path == '/api/stats/summary':
                cur.execute("SELECT * FROM v_daily_hospital_kpi")
                kpi_row = cur.fetchone()
                
                # Payment method split
                cur.execute("SELECT COALESCE(SUM(amount), 0.0) FROM payments WHERE payment_method IN ('cash', 'cash_register')")
                cash_paid = cur.fetchone()[0] or 0.0

                cur.execute("SELECT COALESCE(SUM(amount), 0.0) FROM payments WHERE payment_method = 'terminal'")
                terminal_paid = cur.fetchone()[0] or 0.0

                cur.execute("SELECT COALESCE(SUM(amount), 0.0) FROM payments WHERE payment_method IN ('card_transfer', 'payme_click')")
                online_paid = cur.fetchone()[0] or 0.0

                # Staff counts
                cur.execute("SELECT COUNT(*) FROM staff WHERE role IN ('doctor', 'chief_doctor') AND is_active = 1")
                active_doctors = cur.fetchone()[0] or 0

                cur.execute("SELECT COUNT(*) FROM staff WHERE role = 'nurse' AND is_active = 1")
                active_nurses = cur.fetchone()[0] or 0

                # Reception metrics
                cur.execute("SELECT COUNT(*) FROM appointments WHERE appointment_date = DATE('now') AND status != 'cancelled'")
                today_apts = cur.fetchone()[0] or 0

                cur.execute("SELECT COUNT(*) FROM call_logs WHERE status IN ('new', 'in_progress')")
                new_calls = cur.fetchone()[0] or 0

                cur.execute("SELECT COUNT(*) FROM appointments WHERE appointment_date = DATE('now') AND service_type IN ('outpatient', 'home_visit')")
                today_walkins = cur.fetchone()[0] or 0

                # Real-time beds strictly TODAY (Never future reservations)
                cur.execute("""
                    SELECT COUNT(DISTINCT bed_id)
                    FROM admissions
                    WHERE status = 'active'
                      AND DATE('now', 'localtime') >= DATE(start_date)
                      AND DATE('now', 'localtime') <= DATE(COALESCE(actual_end_date, planned_end_date))
                """)
                real_occupied = cur.fetchone()[0] or 0
                real_total = 14
                real_available = max(0, real_total - real_occupied)

                summary = {
                    "total_beds": real_total,
                    "occupied_beds": real_occupied,
                    "available_beds": real_available,
                    "occupancy_rate": kpi_row['occupancy_rate_percent'] if kpi_row else 0.0,
                    "active_inpatients": kpi_row['active_inpatient_count'] if kpi_row else 0,
                    "total_patients": kpi_row['active_patient_count'] if kpi_row else 0,
                    "gross_revenue": kpi_row['total_revenue_billed'] if kpi_row else 0.0,
                    "total_paid": kpi_row['total_revenue_collected'] if kpi_row else 0.0,
                    "balance_due": kpi_row['total_outstanding_debt'] if kpi_row else 0.0,
                    "paid_cash": cash_paid,
                    "paid_terminal": terminal_paid,
                    "paid_online": online_paid,
                    "active_doctors": active_doctors,
                    "active_nurses": active_nurses,
                    "today_appointments": today_apts,
                    "new_calls": new_calls,
                    "today_walkins": today_walkins,
                    "active_prescriptions": kpi_row['active_prescriptions_count'] if kpi_row else 0
                }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(summary, ensure_ascii=False).encode('utf-8'))

            # 1. /api/beds -> Live Bed status with room & active admission
            elif path == '/api/beds':
                cur.execute("SELECT * FROM v_bed_live_status")
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 2. /api/admissions -> List all bookings/admissions
            elif path == '/api/admissions':
                cur.execute("""
                    SELECT a.*, p.patient_code, p.full_name AS patient_name, p.phone AS patient_phone,
                           b.bed_code, r.room_number, r.floor_number, s.full_name AS doctor_name,
                           inv.total_billed, inv.discount_amount, inv.net_amount, inv.total_paid, inv.balance_due, inv.payment_status
                    FROM admissions a
                    JOIN patients p ON a.patient_id = p.id
                    JOIN beds b ON a.bed_id = b.id
                    JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN staff s ON a.attending_doctor_id = s.id
                    LEFT JOIN invoices inv ON a.id = inv.admission_id
                    ORDER BY a.start_date DESC, a.created_at DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 3. /api/patients -> List all registered patients
            elif path == '/api/patients' or path == '/api/crm/patients':
                cur.execute("""
                    SELECT p.*,
                           (SELECT COUNT(*) FROM admissions a WHERE a.patient_id = p.id) AS total_admissions_count,
                           (SELECT COALESCE(SUM(inv.net_amount), 0.0) FROM invoices inv LEFT JOIN admissions a ON a.id = inv.admission_id LEFT JOIN appointments ap ON ap.id = inv.appointment_id WHERE COALESCE(a.patient_id, ap.patient_id) = p.id) AS total_billed,
                           (SELECT COALESCE(SUM(inv.total_billed), 0.0) FROM invoices inv LEFT JOIN admissions a ON a.id = inv.admission_id LEFT JOIN appointments ap ON ap.id = inv.appointment_id WHERE COALESCE(a.patient_id, ap.patient_id) = p.id) AS total_gross,
                           (SELECT COALESCE(SUM(inv.discount_amount), 0.0) FROM invoices inv LEFT JOIN admissions a ON a.id = inv.admission_id LEFT JOIN appointments ap ON ap.id = inv.appointment_id WHERE COALESCE(a.patient_id, ap.patient_id) = p.id) AS total_discount,
                           (SELECT COALESCE(SUM(inv.total_paid), 0.0) FROM invoices inv LEFT JOIN admissions a ON a.id = inv.admission_id LEFT JOIN appointments ap ON ap.id = inv.appointment_id WHERE COALESCE(a.patient_id, ap.patient_id) = p.id) AS total_paid,
                           (SELECT COALESCE(SUM(inv.balance_due), 0.0) FROM invoices inv LEFT JOIN admissions a ON a.id = inv.admission_id LEFT JOIN appointments ap ON ap.id = inv.appointment_id WHERE COALESCE(a.patient_id, ap.patient_id) = p.id) AS balance_due
                    FROM patients p
                    ORDER BY p.created_at DESC
                """)
                patients = [dict(r) for r in cur.fetchall()]

                # Enrich with active admission and latest vitals
                for pt in patients:
                    cur.execute("""
                        SELECT a.id AS admission_id, a.bed_id, b.bed_code, r.room_number, r.floor_number,
                               a.start_date, a.planned_end_date, a.daily_price, a.program_type, a.status AS admission_status,
                               a.attending_doctor_id AS doctor_id, s.full_name AS doctor_name
                        FROM admissions a
                        JOIN beds b ON a.bed_id = b.id
                        JOIN rooms r ON b.room_id = r.id
                        LEFT JOIN staff s ON a.attending_doctor_id = s.id
                        WHERE a.patient_id = ? AND a.status = 'active'
                        LIMIT 1
                    """, (pt['id'],))
                    active_adm = cur.fetchone()
                    pt['active_admission'] = dict(active_adm) if active_adm else None

                    # Also fetch consulting doctor from latest medical history
                    cur.execute("""
                        SELECT mh.doctor_id, s.full_name AS doctor_name, mh.diagnosis_primary, mh.icd10_code
                        FROM medical_histories mh
                        LEFT JOIN staff s ON mh.doctor_id = s.id
                        WHERE mh.patient_id = ?
                        ORDER BY mh.created_at DESC LIMIT 1
                    """, (pt['id'],))
                    doc_mh = cur.fetchone()
                    if doc_mh:
                        pt['consulting_doctor_id'] = doc_mh['doctor_id'] if isinstance(doc_mh, dict) else doc_mh[0]
                        pt['consulting_doctor_name'] = doc_mh['doctor_name'] if isinstance(doc_mh, dict) else doc_mh[1]
                        pt['diagnosis'] = pt.get('diagnosis') or (doc_mh['diagnosis_primary'] if isinstance(doc_mh, dict) else doc_mh[2])
                        pt['icd10_code'] = pt.get('icd10_code') or (doc_mh['icd10_code'] if isinstance(doc_mh, dict) else doc_mh[3])
                    else:
                        pt['consulting_doctor_id'] = None
                        pt['consulting_doctor_name'] = None

                    # Also fetch latest appointment (e.g. reception consultation)
                    cur.execute("""
                        SELECT ap.id AS appointment_id, ap.doctor_id, s.full_name AS doctor_name,
                               ap.service_type, ap.appointment_date, ap.appointment_time, ap.status AS appointment_status,
                               ap.notes AS appointment_notes
                        FROM appointments ap
                        LEFT JOIN staff s ON ap.doctor_id = s.id
                        WHERE ap.patient_id = ?
                        ORDER BY ap.appointment_date DESC, ap.created_at DESC LIMIT 1
                    """, (pt['id'],))
                    apt_row = cur.fetchone()
                    pt['latest_appointment'] = dict(apt_row) if apt_row else None

                    # Also fetch latest consultation
                    cur.execute("""
                        SELECT c.id AS consultation_id, c.doctor_id, s.full_name AS doctor_name,
                               c.primary_complaint, c.working_diagnosis, c.icd10_code, c.consultation_date
                        FROM consultations c
                        LEFT JOIN staff s ON c.doctor_id = s.id
                        WHERE c.patient_id = ?
                        ORDER BY c.consultation_date DESC LIMIT 1
                    """, (pt['id'],))
                    c_row = cur.fetchone()
                    pt['latest_consultation'] = dict(c_row) if c_row else None

                    pt['doctor_id'] = (
                        (pt.get('active_admission') and pt['active_admission'].get('doctor_id'))
                        or pt.get('consulting_doctor_id')
                        or (pt.get('latest_consultation') and pt['latest_consultation'].get('doctor_id'))
                        or (pt.get('latest_appointment') and pt['latest_appointment'].get('doctor_id'))
                    )
                    pt['doctor_name'] = (
                        (pt.get('active_admission') and pt['active_admission'].get('doctor_name'))
                        or pt.get('consulting_doctor_name')
                        or (pt.get('latest_consultation') and pt['latest_consultation'].get('doctor_name'))
                        or (pt.get('latest_appointment') and pt['latest_appointment'].get('doctor_name'))
                    )

                    if pt.get('latest_consultation'):
                        pt['diagnosis'] = pt.get('diagnosis') or pt['latest_consultation'].get('working_diagnosis')
                        pt['icd10_code'] = pt.get('icd10_code') or pt['latest_consultation'].get('icd10_code')

                    # Determine service_type
                    if pt.get('active_admission'):
                        pt['service_type'] = 'inpatient'
                    elif pt.get('latest_appointment') and pt['latest_appointment'].get('service_type'):
                        pt['service_type'] = pt['latest_appointment']['service_type']
                    elif pt.get('latest_consultation'):
                        pt['service_type'] = 'consultation'
                    else:
                        pt['service_type'] = 'consultation' if pt.get('referral_source') in ('reception', 'consultation') else 'outpatient'

                    cur.execute("""
                        SELECT dl.vital_bp_systolic, dl.vital_bp_diastolic, dl.vital_pulse, dl.vital_temp, dl.vital_spo2, dl.log_date, dl.nurse_notes
                        FROM daily_logs dl
                        JOIN admissions a ON dl.admission_id = a.id
                        WHERE a.patient_id = ?
                        ORDER BY dl.log_date DESC, dl.id DESC
                        LIMIT 1
                    """, (pt['id'],))
                    vit = cur.fetchone()
                    pt['latest_vitals'] = dict(vit) if vit else None

                self._set_json_headers(200)
                self.wfile.write(json.dumps(patients, ensure_ascii=False).encode('utf-8'))

            # 3b. /api/crm/patients/<id> -> Full Patient Dossier
            elif path.startswith('/api/crm/patients/'):
                patient_id = path.replace('/api/crm/patients/', '')
                cur.execute("SELECT * FROM patients WHERE id = ? OR patient_code = ?", (patient_id, patient_id))
                pt_row = cur.fetchone()
                if not pt_row:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Patient not found'}).encode('utf-8'))
                else:
                    pt_dict = dict(pt_row)
                    actual_id = pt_dict['id']

                    # All admissions
                    cur.execute("""
                        SELECT a.*, b.bed_code, b.bed_type, r.room_number, r.floor_number, r.room_name_uz,
                               s.full_name AS doctor_name, s.specialty AS doctor_specialty,
                               inv.id AS invoice_id, inv.total_billed, inv.discount_amount, inv.net_amount, inv.total_paid, inv.balance_due, inv.payment_status
                        FROM admissions a
                        JOIN beds b ON a.bed_id = b.id
                        JOIN rooms r ON b.room_id = r.id
                        LEFT JOIN staff s ON a.attending_doctor_id = s.id
                        LEFT JOIN invoices inv ON a.id = inv.admission_id
                        WHERE a.patient_id = ?
                        ORDER BY a.start_date DESC
                    """, (actual_id,))
                    pt_dict['admissions'] = [dict(a) for a in cur.fetchall()]

                    # All payments
                    cur.execute("""
                        SELECT p.*, inv.admission_id, s.full_name AS received_by_name
                        FROM payments p
                        JOIN invoices inv ON p.invoice_id = inv.id
                        LEFT JOIN admissions a ON inv.admission_id = a.id
                        LEFT JOIN appointments ap ON inv.appointment_id = ap.id
                        LEFT JOIN staff s ON p.received_by_staff_id = s.id
                        WHERE COALESCE(a.patient_id, ap.patient_id) = ?
                        ORDER BY p.payment_date DESC
                    """, (actual_id,))
                    pt_dict['payments'] = [dict(pm) for pm in cur.fetchall()]

                    # All vitals logs
                    cur.execute("""
                        SELECT dl.*, s.full_name AS nurse_name
                        FROM daily_logs dl
                        JOIN admissions a ON dl.admission_id = a.id
                        LEFT JOIN staff s ON dl.recorded_by_staff_id = s.id
                        WHERE a.patient_id = ?
                        ORDER BY dl.log_date DESC
                    """, (actual_id,))
                    pt_dict['daily_logs'] = [dict(dl) for dl in cur.fetchall()]

                    # Financial summary
                    cur.execute("""
                        SELECT COALESCE(SUM(inv.net_amount), 0.0) AS total_billed,
                               COALESCE(SUM(inv.total_billed), 0.0) AS total_gross,
                               COALESCE(SUM(inv.discount_amount), 0.0) AS total_discount,
                               COALESCE(SUM(inv.total_paid), 0.0) AS total_paid,
                               COALESCE(SUM(inv.balance_due), 0.0) AS balance_due
                        FROM invoices inv
                        LEFT JOIN admissions a ON a.id = inv.admission_id
                        LEFT JOIN appointments ap ON ap.id = inv.appointment_id
                        WHERE COALESCE(a.patient_id, ap.patient_id) = ?
                    """, (actual_id,))
                    fin = cur.fetchone()
                    pt_dict['financials'] = dict(fin) if fin else {'total_billed': 0, 'total_paid': 0, 'balance_due': 0}

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(pt_dict, ensure_ascii=False).encode('utf-8'))

            # 4. /api/staff -> List staff | /api/doctors -> Only doctors for consultation and treatment
            elif path == '/api/doctors':
                cur.execute("SELECT * FROM staff WHERE role IN ('doctor', 'chief_doctor') AND is_active = 1 ORDER BY role, full_name")
                rows = [dict(r) for r in cur.fetchall()]
                self._strip_pay_fields(rows)
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/staff' or path == '/api/hr/staff':
                req_role = query.get('role', [None])[0]
                if req_role == 'doctor':
                    cur.execute("SELECT * FROM staff WHERE role IN ('doctor', 'chief_doctor') AND is_active = 1 ORDER BY role, full_name")
                elif req_role:
                    cur.execute("SELECT * FROM staff WHERE role = ? AND is_active = 1 ORDER BY full_name", (req_role,))
                else:
                    cur.execute("SELECT * FROM staff WHERE is_active = 1 ORDER BY role, full_name")
                rows = [dict(r) for r in cur.fetchall()]
                self._strip_pay_fields(rows)
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 5. /api/financial-ledger -> Full billing and payment balance sheet
            elif path == '/api/financial-ledger':
                cur.execute("SELECT * FROM v_financial_ledger")
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 5a. GET /api/accounting/patient-invoices?patient_id=<id or code>
            # Every invoice of one patient (stays and desk visits) with its
            # lines and payments, read-only. The cash desk could only see one
            # bill at a time, so a patient's earlier unpaid visit or stay was
            # easy to miss when taking money for the current one.
            elif path == '/api/accounting/patient-invoices':
                pid = (query.get('patient_id', [''])[0] or '').strip()
                if not pid:
                    self._send_validation_error("Bemor tanlanmagan.", 'patient_id')
                    return
                cur.execute("SELECT id, patient_code, full_name, phone FROM patients "
                            "WHERE id = ? OR patient_code = ? LIMIT 1", (pid, pid))
                prow = cur.fetchone()
                if not prow:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Bemor topilmadi.'}, ensure_ascii=False).encode('utf-8'))
                    return
                patient = dict(prow)
                cur.execute("SELECT * FROM v_financial_ledger WHERE patient_id = ? ORDER BY created_at DESC",
                            (patient['id'],))
                invoices = []
                for r in cur.fetchall():
                    inv = dict(r)
                    inv['kind'] = 'stay' if inv.get('admission_id') else 'visit'
                    inv['items'] = []
                    inv['payments'] = []
                    invoices.append(inv)
                by_id = {inv['invoice_id']: inv for inv in invoices}
                if by_id:
                    marks = ', '.join('?' for _ in by_id)
                    ids = tuple(by_id)
                    cur.execute(f"""
                        SELECT id, invoice_id, service_name, quantity, unit_price, total_amount,
                               item_type, service_start_date, service_end_date, created_at
                        FROM invoice_items WHERE invoice_id IN ({marks})
                        ORDER BY created_at, id
                    """, ids)
                    for it in cur.fetchall():
                        by_id[it['invoice_id']]['items'].append(dict(it))
                    cur.execute(f"""
                        SELECT id, invoice_id, amount, payment_method, payment_date, notes, created_at
                        FROM payments WHERE invoice_id IN ({marks})
                        ORDER BY payment_date, created_at
                    """, ids)
                    for pm in cur.fetchall():
                        by_id[pm['invoice_id']]['payments'].append(dict(pm))
                totals = {k: sum(float(inv.get(k) or 0) for inv in invoices)
                          for k in ('total_billed', 'discount_amount', 'net_amount',
                                    'total_paid', 'balance_due')}
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'patient': patient, 'invoices': invoices,
                                             'totals': totals}, ensure_ascii=False).encode('utf-8'))

            # 6. /api/daily-logs/<admission_id>
            # 6a. Consultation intake & treatment plans
            #
            # The queue is the hand-off from registration: reception takes a
            # patient's details, routes them to a named doctor, and this is
            # what that doctor sees waiting.
            elif path == '/api/consultations/queue':
                sess = self.current_session()
                mine = query.get('mine', ['0'])[0] in ('1', 'true', 'yes')
                doctor_id = None
                if mine and sess:
                    doctor_id = sess['user'].get('staff_id')
                rows = consultation.waiting_queue(conn, doctor_id)
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/consultations/sections':
                # The field definition, so the form is built from the same
                # source the server validates against.
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'sections': [{'key': k, 'label': l,
                                  'fields': [{'name': x[0], 'type': x[1],
                                              'label': x[2], 'hint': x[3]}
                                             for x in f]}
                                 for k, l, f in consultation.SECTIONS],
                    'treatment_basis': list(consultation.TREATMENT_BASIS),
                    'risk_levels': list(consultation.RISK_LEVELS),
                    'plan_types': list(consultation.PLAN_TYPES),
                }, ensure_ascii=False).encode('utf-8'))

            elif path.startswith('/api/consultations/patient/'):
                pid = urllib.parse.unquote(path.replace('/api/consultations/patient/', ''))
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'consultations': consultation.list_for_patient(conn, pid),
                    'plans': consultation.plans_for_patient(conn, pid),
                }, ensure_ascii=False).encode('utf-8'))

            elif path.startswith('/api/consultations/'):
                cid = urllib.parse.unquote(path.replace('/api/consultations/', ''))
                record = consultation.get_intake(conn, cid)
                if not record:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Konsultatsiya topilmadi'}, ensure_ascii=False).encode('utf-8'))
                    return
                self._set_json_headers(200)
                self.wfile.write(json.dumps(record, ensure_ascii=False).encode('utf-8'))

            elif path.startswith('/api/treatment-plans/patient/'):
                pid = urllib.parse.unquote(path.replace('/api/treatment-plans/patient/', ''))
                self._set_json_headers(200)
                self.wfile.write(json.dumps(consultation.plans_for_patient(conn, pid), ensure_ascii=False).encode('utf-8'))

            elif path.startswith('/api/treatment-plans/'):
                plan_id = urllib.parse.unquote(path.replace('/api/treatment-plans/', ''))
                plan = consultation.get_plan(conn, plan_id)
                if not plan:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Davolash rejasi topilmadi'}, ensure_ascii=False).encode('utf-8'))
                    return
                self._set_json_headers(200)
                self.wfile.write(json.dumps(plan, ensure_ascii=False).encode('utf-8'))

            # 6b. GET /api/nursery/round?date=YYYY-MM-DD
            #
            # The medication round for one day, derived from the standing
            # prescriptions and overlaid with what was actually recorded. A
            # future date answers "what will this patient receive"; a past one
            # answers "what did they receive".
            # GET /api/nursery/round/pdf?date= -- the same sheet as a file.
            # The round could be printed from the browser but not downloaded,
            # and a signed sheet gets filed: it has to exist as something the
            # ward can keep and re-send, not only as whatever the browser
            # rendered that afternoon.
            # GET /api/doctor/ward-round?date= -- who is in a bed today and
            # who the doctor has already seen. The per-patient check-up
            # existed; the list did not, so a doctor had to already know who
            # was in the building and open each record in turn.
            elif path == '/api/doctor/ward-round':
                day, err = parse_date_param(query.get('date', [None])[0])
                if err:
                    self._send_validation_error(err, 'date')
                    return
                board = nursery.ward_round(conn, day)
                self._set_json_headers(200)
                self.wfile.write(json.dumps(board, ensure_ascii=False,
                                            default=str).encode('utf-8'))

            elif path == '/api/nursery/round/pdf':
                day, err = parse_date_param(query.get('date', [None])[0])
                if err:
                    self._send_validation_error(err, 'date')
                    return
                if not generate_round_pdf:
                    self._set_json_headers(503)
                    self.wfile.write(json.dumps(
                        {'error': "PDF moduli yuklanmagan (reportlab o'rnatilganmi?)."},
                        ensure_ascii=False).encode('utf-8'))
                    return
                pdf_bytes = generate_round_pdf(day)
                if not pdf_bytes:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps(
                        {'error': "Bu kunda dori berish rejasi yo'q."},
                        ensure_ascii=False).encode('utf-8'))
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Disposition',
                                 f'attachment; filename="FMH_dori_varaqasi_{day.isoformat()}.pdf"')
                self.send_header('Content-Length', str(len(pdf_bytes)))
                self.end_headers()
                self.wfile.write(pdf_bytes)

            elif path == '/api/nursery/round':
                day, err = parse_date_param(query.get('date', [None])[0])
                if err:
                    self._send_validation_error(err)
                    return
                data = nursery.build_round(conn, day)
                self._set_json_headers(200)
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

            elif path.startswith('/api/daily-logs/'):
                admission_id = path.replace('/api/daily-logs/', '')
                cur.execute("""
                    SELECT dl.*, s.full_name AS nurse_name
                    FROM daily_logs dl
                    LEFT JOIN staff s ON dl.recorded_by_staff_id = s.id
                    WHERE dl.admission_id = ?
                    ORDER BY dl.log_date ASC
                """, (admission_id,))
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 7. /api/accounting/data -> 100% Dynamic MySQL-Powered Accounting Dataset
            elif path == '/api/accounting/data' or path == '/api/accounting':
                # services_catalog (MySQL) is not sent any more. Nothing ever
                # wrote to it and no page read it, and its seeded prices
                # disagreed with pricing_config.json (ECG 80 000 vs 120 000),
                # so it was a third price list waiting to be trusted by
                # mistake. Extra services come from the one price list
                # (GET /api/settings/pricing -> additional_services). The
                # table is left in place.

                # Pharmacy stock
                cur.execute("SELECT id, name, category, form, standard_dosage, unit_price, stock_quantity, min_stock_level FROM medications_catalog WHERE is_active = 1")
                pharmacy_stock = [dict(r) for r in cur.fetchall()]

                # Patients billing ledger
                cur.execute("SELECT * FROM v_financial_ledger")
                patients_billing = [dict(r) for r in cur.fetchall()]

                # Lines added to bills besides the stay itself, so the page
                # can show them after a reload instead of only until the
                # next sync.
                cur.execute(
                    "SELECT id, invoice_id, service_name, quantity, unit_price, total_amount, "
                    "item_type, created_at FROM invoice_items WHERE item_type != 'bed_stay' "
                    "ORDER BY created_at, id")
                invoice_items = [dict(r) for r in cur.fetchall()]

                # Transactions (single-source from accounting_transactions)
                transactions = []
                ensure_transaction_payroll_month(conn)
                cur.execute("""
                    SELECT id, transaction_type AS type, category, description AS title,
                           amount, payment_method, account_source, related_invoice_id AS invoice_id,
                           related_staff_id, payroll_month,
                           transaction_date AS date, '12:00' AS time, 'Kassir' AS cashier, description AS notes
                    FROM accounting_transactions
                    ORDER BY transaction_date DESC, id DESC
                """)
                for r in cur.fetchall():
                    transactions.append(dict(r))

                # There was a 'doctor payroll' here: salary_base plus 10 % of
                # everything the doctor's patients had paid. Nobody ever set
                # that rate, no page used the figure, and it sent every
                # doctor's salary to anyone with accounting:read (the desk,
                # the chief doctor). Pay comes from GET /api/hr/payroll only.

                # Medication purchases (clinic restock & expenses)
                ensure_medication_purchases(conn)
                cur.execute("""
                    SELECT mp.id, mp.purchase_date, mp.medication_id, mp.medication_name,
                           mp.category, mp.form, mp.quantity, mp.unit_price, mp.total_price,
                           mp.payment_method, mp.supplier_name, mp.invoice_number, mp.notes,
                           mp.accounting_transaction_id, mp.recorded_by_staff_id, mp.created_at,
                           COALESCE(s.full_name, 'Buxgalter') AS recorded_by_name
                    FROM medication_purchases mp
                    LEFT JOIN staff s ON mp.recorded_by_staff_id = s.id
                    ORDER BY mp.purchase_date DESC, mp.created_at DESC
                """)
                medication_purchases = [dict(r) for r in cur.fetchall()]

                acc_data = {
                    "clinic_info": {
                        "name": "FAYZ MEDICAL HOUSE",
                        "license": "№ 14285-L Toshkent Sh. SSV",
                        "inn": "309812456",
                        "bank_account": "20208000900123456001",
                        "bank_name": "Ipak Yo'li Banki Chilonzor filiali",
                        "mfo": "00444",
                        "address": "Toshkent sh., Chilonzor tumani, Muqimiy ko'chasi 44-uy",
                        "phone": "+998 71 200-44-00",
                        "telegram": "@fayz_medical_house"
                    },
                    "pharmacy_stock": pharmacy_stock,
                    "patients_billing": patients_billing,
                    "invoice_items": invoice_items,
                    "transactions": transactions,
                    "medication_purchases": medication_purchases,
                    "expense_categories": [
                        {"id": "medication_purchase", "name_uz": "Dori-darmon xaridi (Ombor)"},
                        {"id": "salary", "name_uz": "Xodimlar va Shifokorlar maoshi"},
                        {"id": "utilities", "name_uz": "Kommunal to'lovlar & Internet"},
                        {"id": "rent", "name_uz": "Bino ijarasi"},
                        {"id": "food_catering", "name_uz": "Bemorlar oziq-ovqati (Katering)"},
                        {"id": "equipment", "name_uz": "Tibbiy jihozlar & Sarflov materiallari"},
                        {"id": "operational_expense", "name_uz": "Boshqa xo'jalik xarajatlari"}
                    ]
                }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(acc_data, ensure_ascii=False).encode('utf-8'))

            # 7b. /api/accounting/medication-purchases -> List all medication purchases
            # 7d. /api/owner/summary -> the owner's phone report: money in by
            # source, money out by purpose, per day, per payment method.
            elif path == '/api/owner/summary':
                start_d, end_d, err = validate_date_range(
                    query.get('start', [''])[0], query.get('end', [''])[0])
                if err:
                    self._send_validation_error(err, 'start')
                    return
                if (end_d - start_d).days > 400:
                    self._send_validation_error("Davr 400 kundan oshmasligi kerak", 'start')
                    return
                report = owner_report.summary(conn, start_d, end_d)
                self._set_json_headers(200)
                self.wfile.write(json.dumps(report, ensure_ascii=False).encode('utf-8'))

            # 7c. /api/accounting/medicine-usage -> medicines given on the ward,
            # what they took from stock and what they cost.
            elif path == '/api/accounting/medicine-usage':
                start_raw = query.get('start', [''])[0]
                end_raw = query.get('end', [''])[0]
                if not start_raw and not end_raw:
                    today = datetime.date.today()
                    start_d, end_d = today.replace(day=1), today
                else:
                    start_d, end_d, err = validate_date_range(start_raw, end_raw)
                    if err:
                        self._send_validation_error(err, 'start')
                        return
                usage = nursery.medicine_usage(conn, start_d.isoformat(), end_d.isoformat())
                self._set_json_headers(200)
                self.wfile.write(json.dumps(usage, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/accounting/medication-purchases' or path.startswith('/api/accounting/medication-purchases?'):
                ensure_medication_purchases(conn)
                cur.execute("""
                    SELECT mp.id, mp.purchase_date, mp.medication_id, mp.medication_name,
                           mp.category, mp.form, mp.quantity, mp.unit_price, mp.total_price,
                           mp.payment_method, mp.supplier_name, mp.invoice_number, mp.notes,
                           mp.accounting_transaction_id, mp.recorded_by_staff_id, mp.created_at,
                           COALESCE(s.full_name, 'Buxgalter') AS recorded_by_name
                    FROM medication_purchases mp
                    LEFT JOIN staff s ON mp.recorded_by_staff_id = s.id
                    ORDER BY mp.purchase_date DESC, mp.created_at DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 8. /api/hr/data -> 100% Dynamic MySQL-Powered HR Dataset
            # 8a. GET /api/hr/payroll?month=YYYY-MM -> pay counted from the
            # saved duty roster (see payroll.py for why it left the browser).
            elif path == '/api/hr/payroll':
                month = (query.get('month', [''])[0] or '').strip() or \
                    datetime.date.today().strftime('%Y-%m')
                if not payroll.MONTH_RE.match(month):
                    self._send_validation_error("Oy YYYY-MM ko'rinishida bo'lishi kerak", 'month')
                    return
                cur.execute("SELECT id, full_name, role, salary_base, is_active FROM staff ORDER BY role, full_name")
                staff_rows = [dict(r) for r in cur.fetchall()]
                roster = read_json_file(os.path.join(BASE_DIR, 'data', 'duty_schedule.json'), default=None)
                shifts = roster.get('shifts') if isinstance(roster, dict) else None
                result = payroll.build_payroll(month, staff_rows,
                                               shifts if isinstance(shifts, list) else [],
                                               load_pricing()['duty_tariffs'])
                self._set_json_headers(200)
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/hr/data' or path.startswith('/api/hr'):
                hr_file = os.path.join(BASE_DIR, 'data', 'hr_db.json')
                hr_data = read_json_file(hr_file, default=None) or {}

                cur.execute("SELECT * FROM staff ORDER BY role, full_name")
                raw_staff_list = [dict(r) for r in cur.fetchall()]

                cur.execute("""
                    SELECT sa.*, s.full_name AS staff_name, s.role, s.specialty
                    FROM staff_attendance sa
                    JOIN staff s ON sa.staff_id = s.id
                    ORDER BY sa.work_date DESC, sa.created_at DESC
                """)
                attendance = [attendance_out(r) for r in cur.fetchall()]

                dept_map = {
                    'chief_doctor': 'doctors',
                    'doctor': 'doctors',
                    'nurse': 'nurses',
                    'receptionist': 'administration',
                    'admin': 'administration',
                    'accountant': 'administration',
                    'pharmacist': 'diagnostics',
                    'sanitar': 'support',
                    'support': 'support'
                }
                role_title_map = {
                    'chief_doctor': 'chief_doctor',
                    'doctor': 'doctor',
                    'nurse': 'nurse',
                    'receptionist': 'receptionist'
                }

                dept_labels = {
                    'doctors': "Shifokorlar Bo'limi",
                    'nurses': "Hamshiralar Bo'limi",
                    'administration': "Ma'muriyat & Qabulxona",
                    'diagnostics': 'Diagnostika & Laboratoriya',
                    'support': 'Xizmat & Xavfsizlik',
                }

                json_staff_by_id = {s.get('id'): s for s in hr_data.get('staff', []) if 'id' in s}
                staff_list = []
                for s in raw_staff_list:
                    sid = s.get('id')
                    merged = dict(json_staff_by_id.get(sid, {}))
                    merged.update(s)
                    merged['status'] = 'active' if s.get('is_active', 1) else 'inactive'
                    merged['base_salary'] = float(s.get('salary_base') or 0.0)
                    merged['salary_base'] = float(s.get('salary_base') or 0.0)
                    merged['department'] = merged.get('department') or dept_map.get(s.get('role'), 'doctors')
                    # Label from the saved department: the legacy hr_db.json
                    # label stayed behind when HR moved someone.
                    merged['department_name_uz'] = dept_labels.get(merged['department'], merged['department'])
                    merged['role_title_uz'] = merged.get('role_title_uz') or role_title_map.get(s.get('role'), s.get('role'))
                    # The HR columns are now real (db.STAFF_HR_COLUMNS); an
                    # empty one stays empty. 'Mutaxassis' was shown for
                    # everyone whose category nobody had entered.
                    merged['category'] = merged.get('category') or None
                    merged['kpi_rating'] = float(merged.get('kpi_rating') or 5.0)
                    if s.get('role') == 'chief_doctor':
                        merged['avatar_color'] = '#2563eb'
                    elif s.get('role') == 'doctor' and sid == 'STF-DOC-03':
                        merged['avatar_color'] = '#4f46e5'
                    elif s.get('role') == 'doctor':
                        merged['avatar_color'] = '#3b82f6'
                    elif s.get('role') == 'nurse' and sid == 'STF-NRS-01':
                        merged['avatar_color'] = '#6366f1'
                    elif s.get('role') == 'nurse':
                        merged['avatar_color'] = '#4f46e5'
                    else:
                        merged['avatar_color'] = '#6366f1'
                    staff_list.append(merged)

                if not staff_list and hr_data.get('staff'):
                    staff_list = hr_data['staff']

                hr_response = {
                    "facility_info": hr_data.get("facility_info", {
                        "name": "FAYZ MEDICAL HOUSE",
                        "total_floors": 2,
                        "total_beds": 14,
                        "operating_mode": "24/7 Statsionar & Poliklinika"
                    }),
                    # From the one price list, not the legacy hr_db.json.
                    "duty_tariffs": load_pricing()['duty_tariffs'],
                    "staff": staff_list,
                    "total_staff_count": len(staff_list),
                    "attendance_records": attendance,
                    "monthly_duty_schedule": hr_data.get("monthly_duty_schedule", []),
                    "brigades": hr_data.get("brigades", [])
                }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(hr_response, ensure_ascii=False).encode('utf-8'))

            # 8b. /api/duty-schedule -> 24/7 Duty Roster (Doctors, Nurses, Sanitarkas)
            elif path == '/api/duty-schedule':
                # Who may be put on duty, from the staff table. The pages
                # suggested unsaved months from names typed into duty_schedule.js
                # (no ids, so nothing they produced could be paid).
                cur.execute("SELECT id, full_name, role FROM staff WHERE is_active = 1 "
                            "AND role IN ('doctor', 'chief_doctor', 'nurse', 'sanitar') "
                            "ORDER BY full_name")
                pool = {'doctors': [], 'nurses': [], 'sanitarkas': []}
                for r in cur.fetchall():
                    group = 'nurses' if r['role'] == 'nurse' else (
                        'sanitarkas' if r['role'] == 'sanitar' else 'doctors')
                    pool[group].append({'id': r['id'], 'name': r['full_name']})
                conn.close()
                ds_file = os.path.join(BASE_DIR, 'data', 'duty_schedule.json')
                ds_data = read_json_file(ds_file, default=None)
                # The old fallback divided by an empty sanitarka list (500 on every
                # load) and wrote made-up doctors and nurses with fake phone
                # numbers to disk. With no saved roster, answer an empty one and
                # let the page suggest a rotation from the staff pool.
                if not isinstance(ds_data, dict):
                    ds_data = {"sanitarkas": [], "nurses": [], "doctors": [], "shifts": []}
                ds_data['staff_pool'] = pool
                ds_data['duty_tariffs'] = load_pricing()['duty_tariffs']
                self._set_json_headers(200)
                self.wfile.write(json.dumps(ds_data, ensure_ascii=False).encode('utf-8'))

            # 9. /api/reception/* -> Dynamic Reception Portal Data
            elif path == '/api/reception/data' or path == '/api/reception':
                cur.execute("""
                    SELECT apt.*, p.patient_code, s.full_name AS doctor_name, s.specialty AS doctor_specialty
                    FROM appointments apt
                    LEFT JOIN patients p ON apt.patient_id = p.id
                    LEFT JOIN staff s ON apt.doctor_id = s.id
                    ORDER BY apt.appointment_date DESC, apt.appointment_time ASC
                """)
                appointments = [dict(r) for r in cur.fetchall()]

                cur.execute("""
                    SELECT cl.*, s.full_name AS handled_by_name
                    FROM call_logs cl
                    LEFT JOIN staff s ON cl.handled_by_staff_id = s.id
                    ORDER BY cl.call_time DESC
                """)
                call_logs = [dict(r) for r in cur.fetchall()]

                cur.execute("SELECT id, full_name AS name, specialty, role, phone FROM staff WHERE role IN ('doctor', 'chief_doctor') AND is_active = 1")
                doctors = [dict(r) for r in cur.fetchall()]

                # services_catalog is no longer read here: reception.js never
                # used it and its prices disagreed with the one price list
                # (see /api/accounting/data). The table is left in place.

                # The desk needs the tariff list and the referral sources
                # to render its intake form, and neither was ever in this
                # payload. reception.js assigns the response straight over
                # its own state, so both lists were deleted on every load:
                # the programme <select> was left with no <option> at all,
                # the rich picker could not select the full-room tariff,
                # and the daily rate stayed on the 720 000 written into
                # the HTML however the desk chose. The prices are read from
                # the same pricing_config.json the accounting page edits,
                # so the desk and the invoice cannot drift apart.
                _pricing = load_pricing()
                packages = _pricing.get('packages') or {}
                program_types = []
                for _pid, _pkg in packages.items():
                    # The consultation fee is a package key too, and it used to
                    # reach the desk as a sixth inpatient programme priced
                    # "250 000 so'm/kun". It is sent on its own below.
                    if _pid in NON_PROGRAM_PACKAGES:
                        continue
                    _pkg = _pkg or {}
                    program_types.append({
                        "id": _pid,
                        "name_uz": _pkg.get('name_uz') or _pid,
                        "default_rate": _pkg.get('daily_rate') or 0,
                        "default_days": _pkg.get('default_days') or 10,
                        "package_type": 'outpatient' if str(_pid).startswith('ambulator') else 'inpatient',
                    })

                rec_data = {
                    "facility_info": {
                        "name": "FAYZ MEDICAL HOUSE",
                        "hotline": "+998 71 200-44-00",
                        "reception_desk": "1-Qavat Qabulxona"
                    },
                    "appointments": appointments,
                    "call_logs": call_logs,
                    "doctors": doctors,
                    "program_types": program_types,
                    # The desk shows the doctor's consultation fee, which is
                    # the 'consultation' package of the price list.
                    "consultation_fee": float(
                        ((packages.get('consultation') or {}).get('daily_rate')) or 0),
                    # (service_types -- the desk's four intake modes -- is not
                    # sent: overwriting it with billable services once left
                    # the intake modes with no name_uz, icon or colour.)
                    "walk_ins": [a for a in appointments if a.get('service_type') in ('outpatient', 'home_visit')]
                }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rec_data, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/reception/appointments':
                cur.execute("""
                    SELECT apt.*, p.patient_code, s.full_name AS doctor_name
                    FROM appointments apt
                    LEFT JOIN patients p ON apt.patient_id = p.id
                    LEFT JOIN staff s ON apt.doctor_id = s.id
                    ORDER BY apt.appointment_date DESC, apt.appointment_time ASC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/reception/calls':
                cur.execute("""
                    SELECT cl.*, s.full_name AS handled_by_name
                    FROM call_logs cl
                    LEFT JOIN staff s ON cl.handled_by_staff_id = s.id
                    ORDER BY cl.call_time DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # GET /api/reception/requests?status=new -- enquiries from the
            # public website, waiting for someone at the desk to look at them.
            elif path == '/api/reception/requests':
                ensure_appointment_requests(conn)
                wanted = (query.get('status', ['new'])[0] or 'new').strip()
                if wanted == 'all':
                    cur.execute("""SELECT * FROM appointment_requests
                                   ORDER BY created_at DESC LIMIT 200""")
                else:
                    if wanted not in ('new', 'accepted', 'rejected'):
                        self._send_validation_error("Holat noto'g'ri.", 'status')
                        return
                    cur.execute("""SELECT * FROM appointment_requests
                                   WHERE status = ?
                                   ORDER BY created_at DESC LIMIT 200""", (wanted,))
                rows = [dict(r) for r in cur.fetchall()]
                cur.execute("SELECT COUNT(*) AS n FROM appointment_requests WHERE status = 'new'")
                waiting = cur.fetchone()['n']
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'requests': rows, 'waiting': waiting},
                                            ensure_ascii=False, default=str).encode('utf-8'))

            elif path == '/api/reception/walk-ins':
                cur.execute("""
                    SELECT apt.*, p.patient_code, s.full_name AS doctor_name
                    FROM appointments apt
                    LEFT JOIN patients p ON apt.patient_id = p.id
                    LEFT JOIN staff s ON apt.doctor_id = s.id
                    WHERE apt.service_type IN ('outpatient', 'home_visit')
                    ORDER BY apt.appointment_date DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 10. /api/doctor/anamnesis (Medical Histories)
            elif path.startswith('/api/doctor/anamnesis'):
                pid = query.get('patient_id', [None])[0]
                if not pid and '/' in path.replace('/api/doctor/anamnesis', ''):
                    pid = path.replace('/api/doctor/anamnesis/', '')
                
                if pid:
                    cur.execute("""
                        SELECT mh.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM medical_histories mh
                        JOIN patients p ON mh.patient_id = p.id OR mh.patient_id = p.patient_code
                        LEFT JOIN staff s ON mh.doctor_id = s.id
                        WHERE mh.patient_id = ? OR p.patient_code = ?
                        ORDER BY mh.updated_at DESC LIMIT 1
                    """, (pid, pid))
                    row = cur.fetchone()
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(dict(row) if row else None, ensure_ascii=False).encode('utf-8'))
                else:
                    cur.execute("""
                        SELECT mh.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM medical_histories mh
                        JOIN patients p ON mh.patient_id = p.id
                        LEFT JOIN staff s ON mh.doctor_id = s.id
                        ORDER BY mh.updated_at DESC
                    """)
                    rows = [dict(r) for r in cur.fetchall()]
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 11. /api/doctor/prescriptions (Medication orders / List Naznacheniy)
            elif path.startswith('/api/doctor/prescriptions'):
                pid = query.get('patient_id', [None])[0]
                if not pid and '/' in path.replace('/api/doctor/prescriptions', ''):
                    pid = path.replace('/api/doctor/prescriptions/', '')
                
                if pid:
                    cur.execute("""
                        SELECT rx.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM prescriptions rx
                        JOIN patients p ON rx.patient_id = p.id OR rx.patient_id = p.patient_code
                        LEFT JOIN staff s ON rx.doctor_id = s.id
                        WHERE rx.patient_id = ? OR p.patient_code = ?
                        ORDER BY rx.created_at DESC
                    """, (pid, pid))
                else:
                    cur.execute("""
                        SELECT rx.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM prescriptions rx
                        JOIN patients p ON rx.patient_id = p.id
                        LEFT JOIN staff s ON rx.doctor_id = s.id
                        ORDER BY rx.created_at DESC
                    """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 12. /api/doctor/notes (Daily progress examination diary)
            elif path.startswith('/api/doctor/notes'):
                pid = query.get('patient_id', [None])[0]
                if not pid and '/' in path.replace('/api/doctor/notes', ''):
                    pid = path.replace('/api/doctor/notes/', '')
                
                if pid:
                    cur.execute("""
                        SELECT dn.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM doctor_daily_notes dn
                        JOIN patients p ON dn.patient_id = p.id OR dn.patient_id = p.patient_code
                        LEFT JOIN staff s ON dn.doctor_id = s.id
                        WHERE dn.patient_id = ? OR p.patient_code = ?
                        ORDER BY dn.note_date DESC, dn.created_at DESC
                    """, (pid, pid))
                else:
                    cur.execute("""
                        SELECT dn.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM doctor_daily_notes dn
                        JOIN patients p ON dn.patient_id = p.id
                        LEFT JOIN staff s ON dn.doctor_id = s.id
                        ORDER BY dn.note_date DESC, dn.created_at DESC
                    """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 13. /api/doctor/epicrisis (Discharge Epicrises)
            elif path.startswith('/api/doctor/epicrisis'):
                pid = query.get('patient_id', [None])[0]
                if not pid and '/' in path.replace('/api/doctor/epicrisis', ''):
                    pid = path.replace('/api/doctor/epicrisis/', '')
                
                if pid:
                    cur.execute("""
                        SELECT de.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM discharge_epicrises de
                        JOIN patients p ON de.patient_id = p.id OR de.patient_id = p.patient_code
                        LEFT JOIN staff s ON de.doctor_id = s.id
                        WHERE de.patient_id = ? OR p.patient_code = ?
                        ORDER BY de.epicrisis_date DESC, de.created_at DESC LIMIT 1
                    """, (pid, pid))
                    row = cur.fetchone()
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(dict(row) if row else None, ensure_ascii=False).encode('utf-8'))
                else:
                    cur.execute("""
                        SELECT de.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM discharge_epicrises de
                        JOIN patients p ON de.patient_id = p.id
                        LEFT JOIN staff s ON de.doctor_id = s.id
                        ORDER BY de.epicrisis_date DESC, de.created_at DESC
                    """)
                    rows = [dict(r) for r in cur.fetchall()]
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 14. /api/doctor/clinical/<patient_id> -> Complete EMR dossier
            elif path.startswith('/api/doctor/clinical/'):
                pid = path.replace('/api/doctor/clinical/', '')
                cur.execute("SELECT * FROM patients WHERE id = ? OR patient_code = ?", (pid, pid))
                p_row = cur.fetchone()
                if not p_row:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Patient not found'}).encode('utf-8'))
                else:
                    patient = dict(p_row)
                    actual_id = patient['id']

                    # Anamnesis
                    cur.execute("SELECT * FROM medical_histories WHERE patient_id = ? ORDER BY updated_at DESC LIMIT 1", (actual_id,))
                    mh_row = cur.fetchone()
                    patient['anamnesis'] = dict(mh_row) if mh_row else None

                    # Consultation
                    cur.execute("""
                        SELECT c.*, s.full_name AS doctor_name 
                        FROM consultations c 
                        LEFT JOIN staff s ON c.doctor_id = s.id 
                        WHERE c.patient_id = ? 
                        ORDER BY c.consultation_date DESC LIMIT 1
                    """, (actual_id,))
                    c_row = cur.fetchone()
                    patient['consultation'] = dict(c_row) if c_row else None

                    # Latest Appointment
                    cur.execute("""
                        SELECT ap.*, s.full_name AS doctor_name 
                        FROM appointments ap 
                        LEFT JOIN staff s ON ap.doctor_id = s.id 
                        WHERE ap.patient_id = ? 
                        ORDER BY ap.appointment_date DESC, ap.created_at DESC LIMIT 1
                    """, (actual_id,))
                    apt_row = cur.fetchone()
                    patient['latest_appointment'] = dict(apt_row) if apt_row else None

                    # If no medical_history recorded yet, synthesize from consultation or appointment
                    if not patient.get('anamnesis'):
                        if patient.get('consultation'):
                            c_dict = patient['consultation']
                            patient['anamnesis'] = {
                                'id': c_dict.get('id'),
                                'patient_id': actual_id,
                                'doctor_id': c_dict.get('doctor_id'),
                                'complaints': c_dict.get('primary_complaint') or '',
                                'anamnesis_morbi': c_dict.get('onset_note') or c_dict.get('triggers') or '',
                                'anamnesis_vitae': c_dict.get('living_situation') or '',
                                'allergic_status': c_dict.get('drug_allergies') or patient.get('medical_allergies') or '',
                                'somatic_status': c_dict.get('other_medical') or '',
                                'psychiatric_status': c_dict.get('observed_mood') or c_dict.get('observed_thought') or '',
                                'diagnosis_primary': c_dict.get('working_diagnosis') or '',
                                'diagnosis_secondary': '',
                                'icd10_code': c_dict.get('icd10_code') or ''
                            }
                        elif patient.get('latest_appointment') and patient['latest_appointment'].get('notes'):
                            patient['anamnesis'] = {
                                'id': None,
                                'patient_id': actual_id,
                                'doctor_id': patient['latest_appointment'].get('doctor_id'),
                                'complaints': patient['latest_appointment'].get('notes') or '',
                                'anamnesis_morbi': '',
                                'anamnesis_vitae': '',
                                'allergic_status': patient.get('medical_allergies') or '',
                                'somatic_status': '',
                                'psychiatric_status': '',
                                'diagnosis_primary': '',
                                'diagnosis_secondary': '',
                                'icd10_code': ''
                            }

                    # Prescriptions
                    cur.execute("SELECT * FROM prescriptions WHERE patient_id = ? ORDER BY created_at DESC", (actual_id,))
                    patient['prescriptions'] = [dict(r) for r in cur.fetchall()]

                    # Daily Notes
                    cur.execute("SELECT * FROM doctor_daily_notes WHERE patient_id = ? ORDER BY note_date DESC", (actual_id,))
                    patient['daily_notes'] = [dict(r) for r in cur.fetchall()]

                    # Epicrisis
                    # Newest save first, with a tiebreak: several saves on one day picked
                    # an arbitrary one, so a corrected summary could revert.
                    cur.execute("SELECT * FROM discharge_epicrises WHERE patient_id = ? ORDER BY epicrisis_date DESC, updated_at DESC, created_at DESC LIMIT 1", (actual_id,))
                    epi_row = cur.fetchone()
                    patient['discharge_epicrisis'] = dict(epi_row) if epi_row else None

                    # Active Admission
                    cur.execute("""
                        SELECT a.*, b.bed_code, r.room_number, r.floor_number, s.full_name AS doctor_name
                        FROM admissions a
                        JOIN beds b ON a.bed_id = b.id
                        JOIN rooms r ON b.room_id = r.id
                        LEFT JOIN staff s ON a.attending_doctor_id = s.id
                        WHERE a.patient_id = ? AND a.status = 'active'
                        LIMIT 1
                    """, (actual_id,))
                    adm_row = cur.fetchone()
                    patient['active_admission'] = dict(adm_row) if adm_row else None

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(patient, ensure_ascii=False).encode('utf-8'))

            # 15. /api/doctor/download-pdf/<patient_id>
            elif path.startswith('/api/doctor/download-pdf/'):
                pid = path.replace('/api/doctor/download-pdf/', '')
                if generate_patient_pdf:
                    try:
                        # generate_patient_pdf() returns the rendered PDF as bytes.
                        # This branch used to pass that value straight to
                        # os.path.exists(), which is never true for a PDF byte
                        # string, so every export fell through to the 404 below.
                        # Both shapes are accepted now: raw bytes, or a path to a
                        # file already written to disk.
                        # The page's document type was ignored, so every
                        # choice downloaded the prescription sheet.
                        doc_type = (query.get('doc_type', ['prescriptions'])[0] or 'prescriptions')
                        if doc_type not in ('prescriptions', 'anamnesis', 'epicrisis', 'full_dossier'):
                            doc_type = 'prescriptions'
                        # Keyword argument: with two positional arguments the
                        # generator reads the second one as the patient id.
                        pdf_result = generate_patient_pdf(pid, doc_type=doc_type)
                        pdf_data = None
                        if isinstance(pdf_result, (bytes, bytearray)):
                            pdf_data = bytes(pdf_result)
                        elif pdf_result and isinstance(pdf_result, str) and os.path.exists(pdf_result):
                            with open(pdf_result, 'rb') as f:
                                pdf_data = f.read()
                        if pdf_data:
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/pdf')
                            self.send_header('Content-Disposition', f'attachment; filename="Fayz_Medical_History_{pid}.pdf"')
                            self.send_header('Content-Length', str(len(pdf_data)))
                            self.end_headers()
                            self.wfile.write(pdf_data)
                            return
                    except Exception as e_pdf:
                        print("PDF Generation error:", e_pdf)
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'PDF generator unavailable or patient not found'}).encode('utf-8'))

            # 16. /api/settings/pricing -> Dynamic Pricing Config
            elif path == '/api/settings/pricing':
                # Every signed-in role reads this (permissions.API_READ_EXEMPT):
                # it is the one list each page takes its prices from.
                p_data = load_pricing()
                self._set_json_headers(200)
                self.wfile.write(json.dumps(p_data, ensure_ascii=False).encode('utf-8'))

            # 17. /api/users -> List platform user accounts
            elif path == '/api/users':
                # A damaged file is an error, not an empty list: the old
                # catch-all showed "no users" and invited re-creating them.
                u_data = read_json_file(os.path.join(BASE_DIR, 'data', 'users.json'), [])
                caller = (self.current_session() or {}).get('user')
                # 'protected' tells the console which rows it may not delete,
                # block or demote; the PUT/DELETE handlers enforce it anyway.
                sanitized = [user_admin.sanitize(u, caller, u_data) for u in u_data]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(sanitized, ensure_ascii=False).encode('utf-8'))

            # The role picker reads the roles from permissions.ROLES, so the
            # console offers all of them instead of a hand-typed six.
            elif path == '/api/users/roles':
                self._set_json_headers(200)
                self.wfile.write(json.dumps(user_admin.role_list(),
                                            ensure_ascii=False).encode('utf-8'))

            # Read-only audit trail viewer for administrators.
            elif path == '/api/audit':
                filters, _err = audit.parse_search(query)
                if _err:
                    self._send_validation_error(_err[0], _err[1])
                    return
                result = audit.search(conn, filters)
                self._set_json_headers(200)
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))

            # /api/facility/availability?start=&end=
            # The occupancy board for a range of dates, room by room.
            # v_bed_live_status behind /api/beds is pinned to CURDATE() and
            # can only ever answer for today, so the reception desk worked
            # availability out in the browser instead - from a static room
            # file plus bookings held in localStorage, which no other machine
            # could see and which the booking guard never knew about.
            elif path == '/api/facility/availability':
                today = datetime.date.today()
                start_raw = query.get('start', [None])[0] or today.isoformat()
                end_raw = (query.get('end', [None])[0]
                           or (today + datetime.timedelta(days=7)).isoformat())
                _s, _e, _err = validate_date_range(
                    start_raw, end_raw,
                    start_field='Kelish sanasi', end_field='Ketish sanasi')
                if _err:
                    self._send_validation_error(_err, 'start')
                    return
                board = list_room_availability(conn, _s.isoformat(), _e.isoformat())
                self._set_json_headers(200)
                self.wfile.write(json.dumps(board, ensure_ascii=False,
                                            default=str).encode('utf-8'))

            # 18. /api/facility/rooms -> Rooms & Bed layout
            elif path == '/api/facility/rooms':
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                if os.path.exists(rooms_file):
                    try:
                        with open(rooms_file, 'r', encoding='utf-8') as f:
                            r_data = json.load(f)
                    except Exception:
                        r_data = {"floors": []}
                else:
                    r_data = {"floors": []}
                self._set_json_headers(200)
                self.wfile.write(json.dumps(r_data, ensure_ascii=False).encode('utf-8'))

            else:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'API Endpoint not found'}).encode('utf-8'))

        except Exception as e:
            # The detail goes to the server log, not to the browser: str(e) on
            # a database error carries table and column names, file paths and
            # sometimes the failing statement, which is a map of the system
            # for anyone who can provoke a 500.
            traceback.print_exc()
            self._send_server_error()
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

    # ------------------------------------------------------------------------
    # API POST HANDLERS (100% Real MySQL Database Data & Triggers)
    # ------------------------------------------------------------------------
    def handle_api_post(self, path, body):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()

            # Warehouse writes: one request is one transaction (warehouse_api.handle
            # commits on success and rolls back on any failure).
            if path.startswith('/api/warehouse'):
                self._handle_warehouse('POST', path, {}, body, conn)

            # 1. POST /api/admissions (Book / Admit Inpatient via Atomic db.py Workflow)
            elif path == '/api/admissions':
                patient_id = body.get('patient_id')
                patient_name = (body.get('patient_name') or '').strip()
                patient_phone = body.get('patient_phone', '')
                bed_id = body.get('bed_id')
                start_date = (body.get('start_date') or datetime.date.today().isoformat())[:10]
                end_date = (body.get('planned_end_date') or body.get('end_date') or datetime.date.today().isoformat())[:10]
                doc_id = body.get('attending_doctor_id') or body.get('doctor_id')

                # Validate before anything is written. The placeholder patient
                # below used to be created and committed first, so an admission
                # that then failed left an orphan record named 'Yangi Bemor'
                # behind with no stay attached to it.
                if not bed_id:
                    self._send_validation_error('Karavot tanlanmadi.', 'bed_id')
                    return
                # A new patient with no name was registered as 'Yangi Bemor',
                # so the ward board, the invoice and the nurse's round all
                # carried a person nobody could identify. An anonymous stay
                # says so explicitly ('Anonim Bemor' from the desk); a blank
                # is a form that was not filled in.
                if not patient_id and not patient_name:
                    self._send_validation_error("Bemorning ismi kiritilmagan.", 'patient_name')
                    return
                _s, _e, _err = validate_date_range(
                    start_date, end_date,
                    start_field='Kelish sanasi', end_field='Ketish sanasi')
                if _err:
                    self._send_validation_error(_err, 'planned_end_date')
                    return
                # A stay sent without a price is billed at its programme's
                # rate from the one price list; it used to be a hardcoded
                # 720 000 whatever the programme. An explicit daily_price
                # from the page is still accepted as before: whether the
                # server should refuse a rate that differs from the list
                # was decided with the PO (2026-10-08): no, it is kept.
                _raw_price = body.get('daily_price')
                if _raw_price in (None, ''):
                    _raw_price = package_daily_rate(body.get('program_type'))
                daily_price, _err = validate_amount(_raw_price, field='Kunlik narx')
                if _err:
                    self._send_validation_error(_err, 'daily_price')
                    return

                # The desk types a discount percentage and the intake form
                # showed it in the cost preview, but it was never sent and
                # never stored, so every stay was invoiced at the full rate
                # and the figure the patient had agreed to existed nowhere.
                # It is taken as a percentage and turned into money here,
                # not trusted as an amount from the browser: the invoice
                # triggers are the only authority on what a stay costs.
                try:
                    discount_pct = float(body.get('discount_percent') or 0)
                except (TypeError, ValueError):
                    self._send_validation_error(
                        "Chegirma foizi noto'g'ri kiritilgan.", 'discount_percent')
                    return
                if discount_pct < 0 or discount_pct > 100:
                    self._send_validation_error(
                        "Chegirma 0 va 100 foiz orasida bo'lishi kerak.", 'discount_percent')
                    return

                # Advance taken at the desk. It used to be a second request
                # to POST /api/payments, which needs accounting write; the
                # receptionist has only accounting read, so the server
                # refused it and the page never looked. The advance is now
                # part of the admission itself: it can only be paid onto the
                # invoice this request creates, so the desk gains no general
                # right to take or refund money.
                advance_amount = 0.0
                if body.get('advance_amount') not in (None, '', 0, '0'):
                    advance_amount, _err = validate_amount(
                        body.get('advance_amount'), field='Avans')
                    if _err:
                        self._send_validation_error(_err, 'advance_amount')
                        return
                    if advance_amount <= 0:
                        self._send_validation_error(
                            "Avans summasi musbat bo'lishi kerak.", 'advance_amount')
                        return
                advance_method = normalize_payment_method(body.get('advance_method') or 'cash')

                if not patient_id:
                    # No patient given: register one from the details supplied.
                    # Date of birth and gender come from the desk now; they were
                    # not asked for and not stored, so the column default filled
                    # gender in as 'male' for everyone admitted this way.
                    _bdate, _byear, _gender, _err = parse_birth_and_gender(body)
                    if _err:
                        self._send_validation_error(_err[0], _err[1])
                        return
                    patient_id, pcode = new_patient_ids(cur)
                    cur.execute("""
                        INSERT INTO patients (id, patient_code, full_name, phone,
                                              gender, birth_date, birth_year,
                                              referral_source, is_anonymous, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'reception', 0, 'active')
                    """, (patient_id, pcode, patient_name, patient_phone,
                          _gender, _bdate, _byear))
                    conn.commit()

                # No doctor chosen used to mean whichever active doctor the
                # table returned first, so that person became responsible for
                # a stay they were never told about and it appeared on their
                # ward round. The stay is recorded without an attending
                # doctor instead, which the ward board shows as a gap.
                doc_id = doc_id or None

                prog_type = body.get('program_type') or 'detox'

                success, res_data = admit_patient(
                    conn, patient_id, bed_id, doc_id, prog_type,
                    start_date, end_date, daily_price, body.get('notes', '')
                )

                if not success:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': str(res_data)}, ensure_ascii=False).encode('utf-8'))
                    return

                # admit_patient has inserted the bed-stay line, and the
                # invoice_items trigger has already rebalanced total_billed,
                # so the discount can be taken off a real figure. Writing
                # discount_amount is enough: trg_invoices_before_update
                # recomputes net_amount, balance_due and payment_status.
                discount_amount = 0.0
                if discount_pct > 0 and res_data.get('invoice_id'):
                    cur.execute('SELECT total_billed FROM invoices WHERE id = ?',
                                (res_data.get('invoice_id'),))
                    _row = cur.fetchone()
                    _billed = float((_row or {}).get('total_billed') or 0)
                    if _billed > 0:
                        discount_amount = round(_billed * discount_pct / 100.0, 2)
                        cur.execute(
                            'UPDATE invoices SET discount_amount = ? WHERE id = ?',
                            (discount_amount, res_data.get('invoice_id')))
                        conn.commit()

                # The stay and its invoice are already committed. A failed
                # advance used to turn that into a 500, so the desk resubmitted
                # and created a second patient for a bed now taken. Answer 201
                # with no advance instead; the page then tells the desk to
                # enter the advance in accounting.
                advance_payment_id = None
                if advance_amount > 0 and res_data.get('invoice_id'):
                    try:
                        advance_payment_id = self._record_payment(
                            conn, cur, res_data.get('invoice_id'), advance_amount,
                            advance_method, payment_destination_for(advance_method),
                            datetime.date.today().isoformat(),
                            'Birlamchi qabul avans to`lovi',
                            self._actor_staff_id(body, 'received_by_staff_id'))
                    except Exception:
                        traceback.print_exc()
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        advance_payment_id = None

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'advance_payment_id': advance_payment_id,
                    'advance_amount': advance_amount if advance_payment_id else 0,
                    'message': 'Admission created successfully',
                    'id': res_data.get('admission_id'),
                    'admission_id': res_data.get('admission_id'),
                    'invoice_id': res_data.get('invoice_id'),
                    'patient_id': patient_id,
                    'days': res_data.get('days'),
                    'bed_code': res_data.get('bed_code'),
                    'discount_percent': discount_pct,
                    'discount_amount': discount_amount
                }, ensure_ascii=False).encode('utf-8'))

            # 1b. POST /api/admissions/<id>/discharge or /api/admissions/discharge
            elif '/discharge' in path:
                adm_id = body.get('admission_id') or (path.split('/')[3] if len(path.split('/')) > 3 else None)
                today_str = datetime.date.today().isoformat()
                discharge_date = (body.get('discharge_date') or body.get('actual_end_date') or today_str)[:10]
                summary = body.get('discharge_summary') or body.get('summary') or "Statsionardan chiqarildi"

                success, res_data = discharge_patient(conn, adm_id, discharge_date, summary)
                if not success:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': str(res_data)}, ensure_ascii=False).encode('utf-8'))
                    return

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Bemor muvaffaqiyatli chiqarildi va karavot tozalash holatiga (cleaning) o\'tkazildi',
                    'result': res_data
                }, ensure_ascii=False).encode('utf-8'))

            # 1c. POST /api/admissions/<id>/transfer or /api/admissions/transfer
            elif '/transfer' in path:
                adm_id = body.get('admission_id') or (path.split('/')[3] if len(path.split('/')) > 3 else None)
                new_bed_id = str(body.get('new_bed_id') or '').strip()
                raw_transfer_date = body.get('transfer_date')
                transfer_date = (str(raw_transfer_date).strip() if raw_transfer_date
                                 else datetime.date.today().isoformat())[:10]
                reason = str(body.get('reason') or '').strip()[:1000] or "Palata ko'chirildi"
                staff_id = self._actor_staff_id(body)

                if not adm_id:
                    self._send_validation_error("Yotqizish (admission) ko'rsatilmagan.", 'admission_id')
                    return
                if not new_bed_id:
                    self._send_validation_error("Yangi karavotni tanlang.", 'new_bed_id')
                    return
                # Optional: a new daily price from the move date. Left empty,
                # the stay keeps its agreed price (PO, 2026-10-08).
                new_daily_price = None
                if body.get('new_daily_price') not in (None, ''):
                    new_daily_price, _perr = validate_amount(body.get('new_daily_price'), field='Kunlik narx')
                    if _perr:
                        self._send_validation_error(_perr, 'new_daily_price')
                        return

                # transfer_patient_bed returns (False, message) only for
                # refusals written for staff in Uzbek. Unexpected failures are
                # re-raised and reach the generic 500 handler of this method,
                # which logs the traceback; str(e) used to be sent to the
                # browser here, database internals included.
                success, res_data = transfer_patient_bed(conn, adm_id, new_bed_id, transfer_date, reason, staff_id,
                                                         new_daily_price=new_daily_price)
                if not success:
                    self._send_validation_error(str(res_data))
                    return

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Bemor yangi karavotga ko\'chirildi, avvalgi karavot tozalashga yuborildi',
                    'result': res_data
                }, ensure_ascii=False).encode('utf-8'))

            # 1d. POST /api/beds/<id>/status or /api/beds/<id>/clean (Sanitation Handover)
            elif path.startswith('/api/beds/') and (path.endswith('/status') or path.endswith('/clean')):
                bed_id = path.split('/')[3]
                # The beds.status column accepts only the physical states in its
                # CHECK constraint: operational, cleaning, maintenance,
                # out_of_service. 'available', 'occupied' and 'reserved' are
                # values the v_bed_live_status view DERIVES from admissions, not
                # things that can be stored. This route used to map the other way
                # round -- rewriting 'operational' to 'available' -- so every
                # request violated beds_chk_3 and failed with a 500. Discharge and
                # transfer both leave a bed 'cleaning', so the action that returns
                # it to service never worked and beds accumulated as unusable.
                PHYSICAL = {'operational', 'cleaning', 'maintenance', 'out_of_service'}
                DERIVED_TO_PHYSICAL = {'available': 'operational',
                                       'occupied': 'operational',
                                       'reserved': 'operational'}
                requested = 'operational' if path.endswith('/clean') else str(body.get('status', 'operational')).strip().lower()
                new_status = DERIVED_TO_PHYSICAL.get(requested, requested)
                if new_status not in PHYSICAL:
                    new_status = 'operational'

                cur.execute("UPDATE beds SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? OR bed_code = ?", (new_status, bed_id, bed_id))
                conn.commit()

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': f"Karavot holati muvaffaqiyatli saqlandi: {new_status}",
                    'bed_id': bed_id,
                    'status': new_status
                }, ensure_ascii=False).encode('utf-8'))

            # 2. POST /api/payments (Record Signed Patient Payment or Refund Payout)
            elif path == '/api/payments' or path == '/api/crm/payments':
                # Same bounded random space as patient ids: probe for a free id so a
                # collision cannot reject a real payment.
                pay_id, _id_err = validate_client_id(body.get('id'))
                if _id_err:
                    self._send_validation_error(_id_err, 'id')
                    return
                pay_id = pay_id or new_record_id(cur, 'payments', 'PAY-2026')
                inv_id = body.get('invoice_id')
                amount = float(body.get('amount', 0))

                # Normalize payment method
                method = normalize_payment_method(body.get('payment_method', 'cash'))

                # Normalize account destination
                raw_acc = str(body.get('account_destination', 'kassa')).lower()
                acc_map = {
                    'kassa': 'kassa', 'bank': 'terminal_bank',
                    'terminal_bank': 'terminal_bank',
                    'click_payme_merchant': 'click_payme_merchant',
                    'main_bank_account': 'main_bank_account'
                }
                acc = acc_map.get(raw_acc, 'kassa')
                pay_date = (body.get('payment_date') or datetime.date.today().isoformat())[:10]

                # If invoice_id not provided directly, resolve from admission_id
                if not inv_id and body.get('admission_id'):
                    cur.execute("SELECT id FROM invoices WHERE admission_id = ?", (body.get('admission_id'),))
                    inv_row = cur.fetchone()
                    if inv_row:
                        inv_id = inv_row['id'] if isinstance(inv_row, dict) or hasattr(inv_row, 'keys') else inv_row[0]

                if not inv_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invoice ID is required for payment'}, ensure_ascii=False).encode('utf-8'))
                    return

                if amount == 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'To`lov summasi 0 bo`lishi mumkin emas'}, ensure_ascii=False).encode('utf-8'))
                    return

                self._record_payment(
                    conn, cur, inv_id, amount, method, acc, pay_date,
                    body.get('notes', ''),
                    self._actor_staff_id(body, 'received_by_staff_id'),
                    transaction_ref=body.get('transaction_ref'), pay_id=pay_id)
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': 'Payment recorded successfully',
                    'payment_id': pay_id,
                    'invoice_id': inv_id,
                    'amount': amount,
                    'is_refund': amount < 0
                }, ensure_ascii=False).encode('utf-8'))

            # 3. POST /api/accounting/transaction (Create Expense / Incasso / Operational Cash Flow)
            elif path == '/api/accounting/transaction':
                # The salary payout sent no amount at all (the figure lived
                # only in the page's render code), and this stored 0 so'm, or
                # failed the amount > 0 CHECK with a 500 that the page
                # reported as paid. The id is always ours: the page's
                # TXN-2026-<time> ids are not unique.
                amount, _aerr = validate_amount(body.get('amount'))
                if _aerr:
                    self._send_validation_error(_aerr, 'amount')
                    return
                if amount <= 0:
                    self._send_validation_error("Summa noldan katta bo'lishi kerak.", 'amount')
                    return
                txn_type = body.get('type', 'expense')
                if txn_type not in ('income', 'expense'):
                    self._send_validation_error("Operatsiya turi noto'g'ri (income yoki expense).", 'type')
                    return
                trx_id = new_record_id(cur, 'accounting_transactions', 'TRX-2026')
                category = body.get('category', 'operational_expense')
                method = normalize_payment_method(body.get('payment_method', 'cash'))
                account_source = account_source_for(method)
                date_str = (body.get('date') or datetime.date.today().isoformat())[:10]
                desc = body.get('title') or body.get('description') or 'Kassa operatsiyasi'

                # Which employee a salary was paid to; the journal held only
                # free text, so a payout could not be traced to the person.
                _staff_ref = str(body.get('related_staff_id') or '').strip()[:64] or None
                if _staff_ref:
                    cur.execute("SELECT id FROM staff WHERE id = ?", (_staff_ref,))
                    if not cur.fetchone():
                        _staff_ref = None

                # The month a salary payout pays for, and one payout per
                # person per month. The "already paid" guard lived only in
                # the accounting page and looked at the recording date, so a
                # second tab, a double click past the check or a payout made
                # early next month paid the same salary twice.
                payroll_month = None
                if category == 'salary' and _staff_ref:
                    ensure_transaction_payroll_month(conn)
                    payroll_month = str(body.get('payroll_month') or date_str[:7]).strip()
                    if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', payroll_month):
                        self._send_validation_error(
                            "Maosh oyi YYYY-MM ko'rinishida bo'lishi kerak.", 'payroll_month')
                        return
                    if payroll_month > (datetime.date.today() + datetime.timedelta(days=1)).isoformat()[:7]:
                        self._send_validation_error(
                            "Kelgusi oy uchun maosh to'lab bo'lmaydi.", 'payroll_month')
                        return
                    _y, _m = int(payroll_month[:4]), int(payroll_month[5:7])
                    _m_start = f"{payroll_month}-01"
                    _m_next = f"{_y + (_m // 12):04d}-{_m % 12 + 1:02d}-01"
                    # Rows written before payroll_month existed count by the
                    # day they were recorded, as the page used to.
                    cur.execute("""
                        SELECT id FROM accounting_transactions
                        WHERE category = 'salary' AND related_staff_id = ?
                          AND (payroll_month = ?
                               OR (payroll_month IS NULL AND transaction_date >= ? AND transaction_date < ?))
                        LIMIT 1
                    """, (_staff_ref, payroll_month, _m_start, _m_next))
                    _dup = cur.fetchone()
                    if _dup:
                        self._set_json_headers(409)
                        self.wfile.write(json.dumps({
                            'error': f"Bu xodimga {payroll_month} oyi uchun maosh allaqachon to'langan ({_dup['id']}).",
                            'field': 'payroll_month'}, ensure_ascii=False).encode('utf-8'))
                        return
                if payroll_month:
                    cur.execute("""
                        INSERT INTO accounting_transactions (id, transaction_type, category, amount, payment_method, account_source, description, transaction_date, related_staff_id, payroll_month)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (trx_id, txn_type, category, amount, method, account_source, desc,
                          date_str, _staff_ref, payroll_month))
                else:
                    cur.execute("""
                        INSERT INTO accounting_transactions (id, transaction_type, category, amount, payment_method, account_source, description, transaction_date, related_staff_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trx_id,
                        txn_type,
                        category,
                        amount,
                        method,
                        account_source,
                        desc,
                        date_str,
                        _staff_ref
                    ))
                conn.commit()
                if telegram_service:
                    try:
                        telegram_service.notify_accounting_transaction_entered_async({
                            'id': trx_id,
                            'transaction_type': txn_type,
                            'category': category,
                            'amount': amount,
                            'payment_method': method,
                            'description': desc,
                            'date': date_str,
                            'recorded_by_staff_id': self._actor_staff_id(body, 'recorded_by_staff_id')
                        })
                    except Exception as _e_notify:
                        print(f"[Telegram Notify Error] {_e_notify}")
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Transaction saved', 'id': trx_id}, ensure_ascii=False).encode('utf-8'))

            # 3b. POST /api/accounting/invoice-items -- add a service or a
            # medicine from stock to a patient's bill.
            #
            # There was no such route: the page added the line to its own copy
            # of the bill and the next 4-second sync dropped it, with the
            # charge and the "taken from stock" it claimed. The price is
            # looked up here (price list or stock), not taken from the page;
            # the invoice triggers then rebalance the bill.
            elif path == '/api/accounting/invoice-items':
                invoice_id = str(body.get('invoice_id') or '').strip()
                code = str(body.get('service_code') or '').strip()
                try:
                    qty = int(body.get('quantity') or 0)
                except (TypeError, ValueError):
                    qty = 0
                if not invoice_id:
                    self._send_validation_error("Hisob tanlanmagan.", 'invoice_id')
                    return
                if not code:
                    self._send_validation_error("Xizmat yoki dorini tanlang.", 'service_code')
                    return
                if qty < 1 or qty > 50:
                    self._send_validation_error("Miqdor 1 dan 50 gacha bo'lishi kerak.", 'quantity')
                    return
                cur.execute("SELECT id, payment_status FROM invoices WHERE id = ?", (invoice_id,))
                inv = cur.fetchone()
                if not inv:
                    self._send_validation_error("Hisob topilmadi.", 'invoice_id')
                    return
                # A refund in progress or done: a new line would quietly eat
                # into the money owed back to the patient.
                if inv['payment_status'] in ('refund_due', 'refunded'):
                    self._send_validation_error(
                        "Qaytarish jarayonidagi hisobga xizmat qo'shib bo'lmaydi.", 'invoice_id')
                    return

                med_id = None
                if code.startswith('MED:'):
                    med_id = code[4:]
                    cur.execute(
                        "SELECT id, name, form, unit_price, stock_quantity FROM medications_catalog "
                        "WHERE id = ? AND is_active = 1 FOR UPDATE", (med_id,))
                    med = cur.fetchone()
                    if not med:
                        self._send_validation_error("Dori omborda topilmadi.", 'service_code')
                        return
                    if int(med['stock_quantity'] or 0) < qty:
                        self._send_validation_error(
                            f"Omborda yetarli qoldiq yo'q. Mavjud: {int(med['stock_quantity'] or 0)}.",
                            'quantity')
                        return
                    item_name = med['name'] + (f" ({med['form']})" if med.get('form') else '')
                    unit_price = float(med['unit_price'] or 0)
                    item_type = 'medication'
                else:
                    pricing = load_pricing()
                    svc = next((s for s in (pricing.get('additional_services') or [])
                                if isinstance(s, dict) and str(s.get('id')) == code), None)
                    if not svc:
                        self._send_validation_error("Xizmat narxlar ro'yxatida topilmadi.", 'service_code')
                        return
                    item_name = str(svc.get('name') or code)
                    unit_price, _perr = validate_amount(svc.get('price'))
                    if _perr:
                        self._send_validation_error("Xizmat narxi noto'g'ri.", 'service_code')
                        return
                    _cat = str(svc.get('category') or '').lower()
                    item_type = 'lab_test' if 'labor' in _cat else 'procedure'

                notes = str(body.get('notes') or '').strip()[:200]
                if notes:
                    item_name = f"{item_name} — {notes}"
                cur.execute(
                    "INSERT INTO invoice_items (invoice_id, service_name, quantity, unit_price, item_type, "
                    "service_start_date) VALUES (?, ?, ?, ?, ?, ?)",
                    (invoice_id, item_name[:255], qty, unit_price, item_type,
                     datetime.date.today().isoformat()))
                item_id = cur.lastrowid
                if med_id:
                    cur.execute(
                        "UPDATE medications_catalog SET stock_quantity = stock_quantity - ? WHERE id = ?",
                        (qty, med_id))
                conn.commit()
                cur.execute("SELECT total_billed, net_amount, total_paid, balance_due, payment_status "
                            "FROM invoices WHERE id = ?", (invoice_id,))
                totals = dict(cur.fetchone() or {})
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': "Xizmat hisobga qo'shildi",
                    'id': item_id, 'invoice_id': invoice_id, 'service_name': item_name,
                    'quantity': qty, 'unit_price': unit_price, 'total': unit_price * qty,
                    'item_type': item_type, 'invoice': totals,
                }, ensure_ascii=False).encode('utf-8'))

            # 3a. POST /api/accounting/medication-purchases (Record Medication Purchase Expense & Restock)
            # 3c. POST /api/accounting/medicine-links -> link a prescribed
            # medicine name to a stock item so its doses come off the shelf.
            elif path == '/api/accounting/medicine-links':
                med_name = str(body.get('medication_name') or '').strip()
                med_id = str(body.get('medication_id') or '').strip()
                if not med_name:
                    self._send_validation_error("Dori nomi ko'rsatilishi shart", 'medication_name')
                    return
                if not med_id:
                    self._send_validation_error("Ombordagi dorini tanlang", 'medication_id')
                    return
                try:
                    key, settled = nursery.link_medicine_name(conn, med_name, med_id)
                except LookupError:
                    self._send_validation_error("Bunday dori omborda topilmadi", 'medication_id')
                    return
                except RuntimeError:
                    self._send_validation_error("Ombor hisobi o'chiq: ma'lumotlar bazasini yangilab bo'lmadi. Administratorga murojaat qiling.", 'medication_id')
                    return
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': "Dori ombor bilan bog'landi", 'alias': key, 'medication_id': med_id, 'settled_doses': settled}, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/accounting/medication-purchases':
                ensure_medication_purchases(conn)
                purchase_date = (body.get('purchase_date') or datetime.date.today().isoformat())[:10]
                payment_method = normalize_payment_method(body.get('payment_method', 'cash'))
                account_source = account_source_for(payment_method)
                supplier_name = (body.get('supplier_name') or '').strip()
                invoice_number = (body.get('invoice_number') or '').strip()
                notes = (body.get('notes') or '').strip()

                items = body.get('items')
                if not items or not isinstance(items, list):
                    if body.get('medication_name'):
                        items = [{
                            'medication_id': body.get('medication_id'),
                            'medication_name': body.get('medication_name'),
                            'category': body.get('category'),
                            'form': body.get('form'),
                            'quantity': body.get('quantity'),
                            'unit_price': body.get('unit_price')
                        }]
                    else:
                        conn.close()
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': "Xarid qilingan dorilar ro'yxati kiritilishi shart"}, ensure_ascii=False).encode('utf-8'))
                        return

                validated_items = []
                grand_total = 0.0
                item_summaries = []

                for it in items:
                    med_name = (it.get('medication_name') or it.get('name') or '').strip()
                    if not med_name:
                        continue
                    try:
                        qty = float(it.get('quantity', 0))
                        unit_p = float(it.get('unit_price', 0))
                    except (ValueError, TypeError):
                        conn.close()
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': f"'{med_name}' dori miqdori yoki narxi noto'g'ri"}, ensure_ascii=False).encode('utf-8'))
                        return

                    # Stock is counted in whole units (an INT column); 2.5 used to
                    # be booked as an expense for 2.5 but added only 2 to stock.
                    if qty != int(qty):
                        conn.close()
                        self._send_validation_error(f"'{med_name}' miqdori butun son bo'lishi kerak", 'quantity')
                        return

                    if qty <= 0 or unit_p < 0:
                        conn.close()
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': f"'{med_name}' dori miqdori musbat va narxi 0 dan kam bo'lmasligi kerak"}, ensure_ascii=False).encode('utf-8'))
                        return

                    total_p = round(qty * unit_p, 2)
                    grand_total += total_p
                    category = (it.get('category') or it.get('group') or 'Dori-darmon').strip()
                    form = (it.get('form') or it.get('unit') or 'dona').strip()
                    med_id = it.get('medication_id') or it.get('id')
                    validated_items.append({
                        'medication_id': med_id,
                        'medication_name': med_name,
                        'category': category,
                        'form': form,
                        'quantity': qty,
                        'unit_price': unit_p,
                        'total_price': total_p
                    })
                    item_summaries.append(f"{med_name} ({qty:g} {form} x {unit_p:,.0f} so'm)")

                if not validated_items:
                    conn.close()
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Kamida bitta dori kiritilishi shart'}, ensure_ascii=False).encode('utf-8'))
                    return

                actor_sid = self._actor_staff_id(body, 'recorded_by_staff_id')
                trx_id = new_record_id(cur, 'accounting_transactions', 'TRX-MED-2026')

                desc_parts = [f"Dori xaridi: {', '.join(item_summaries)}"]
                if supplier_name:
                    desc_parts.append(f"Yetkazib beruvchi: {supplier_name}")
                if invoice_number:
                    desc_parts.append(f"Chek №: {invoice_number}")
                if notes:
                    desc_parts.append(f"Izoh: {notes}")
                trx_desc = ". ".join(desc_parts)
                if len(trx_desc) > 500:
                    trx_desc = trx_desc[:497] + "..."

                # 1. Insert into accounting_transactions as EXPENSE
                cur.execute("""
                    INSERT INTO accounting_transactions (
                        id, transaction_type, category, amount, payment_method,
                        account_source, description, transaction_date, recorded_by_staff_id
                    ) VALUES (?, 'expense', 'medication_purchase', ?, ?, ?, ?, ?, ?)
                """, (
                    trx_id,
                    grand_total,
                    payment_method,
                    account_source,
                    trx_desc,
                    purchase_date,
                    actor_sid
                ))

                # 2. Insert into medication_purchases and update medications_catalog
                created_purchases = []
                for it in validated_items:
                    pur_id = new_record_id(cur, 'medication_purchases', 'PUR-MED-2026')
                    target_med_id = it['medication_id']

                    if target_med_id:
                        cur.execute("SELECT id FROM medications_catalog WHERE id = ?", (target_med_id,))
                        if not cur.fetchone():
                            target_med_id = None

                    if not target_med_id:
                        cur.execute("SELECT id FROM medications_catalog WHERE LOWER(name) = LOWER(?) LIMIT 1", (it['medication_name'],))
                        existing_med = cur.fetchone()
                        if existing_med:
                            target_med_id = existing_med['id']

                    if target_med_id:
                        cur.execute("""
                            UPDATE medications_catalog
                            SET stock_quantity = stock_quantity + ?,
                                unit_price = ?
                            WHERE id = ?
                        """, (int(it['quantity']), it['unit_price'], target_med_id))
                    else:
                        target_med_id = new_record_id(cur, 'medications_catalog', 'MED')
                        cur.execute("""
                            INSERT INTO medications_catalog (
                                id, name, category, form, standard_dosage,
                                unit_price, stock_quantity, min_stock_level, is_active
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, 10, 1)
                        """, (
                            target_med_id,
                            it['medication_name'],
                            it['category'],
                            it['form'],
                            None,  # dosage is a clinical fact the purchase form never asks for
                            it['unit_price'],
                            int(it['quantity'])
                        ))

                    cur.execute("""
                        INSERT INTO medication_purchases (
                            id, purchase_date, medication_id, medication_name,
                            category, form, quantity, unit_price, total_price,
                            payment_method, supplier_name, invoice_number, notes,
                            accounting_transaction_id, recorded_by_staff_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pur_id,
                        purchase_date,
                        target_med_id,
                        it['medication_name'],
                        it['category'],
                        it['form'],
                        it['quantity'],
                        it['unit_price'],
                        it['total_price'],
                        payment_method,
                        supplier_name or None,
                        invoice_number or None,
                        notes or None,
                        trx_id,
                        actor_sid
                    ))
                    created_purchases.append(pur_id)

                conn.commit()

                if telegram_service:
                    try:
                        telegram_service.notify_accounting_transaction_entered_async({
                            'id': trx_id,
                            'transaction_type': 'expense',
                            'category': 'medication_purchase',
                            'amount': grand_total,
                            'payment_method': payment_method,
                            'description': trx_desc,
                            'date': purchase_date,
                            'recorded_by_staff_id': actor_sid
                        })
                    except Exception as _e_notify:
                        print(f"[Telegram Notify Error] {_e_notify}")

                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': "Dori xaridi muvaffaqiyatli saqlandi va kassa xarajatiga yozildi",
                    'transaction_id': trx_id,
                    'purchase_ids': created_purchases,
                    'amount': grand_total
                }, ensure_ascii=False).encode('utf-8'))

            # 3b. POST /api/duty-schedule (Update Duty Schedule / Shifts)
            elif path == '/api/duty-schedule':
                conn.close()
                # The page sends only sanitarkas + shifts; writing the body as
                # the whole file erased the stored nurses and doctors on every
                # swap. Merge into the saved roster instead, and refuse markup
                # in names because the page renders them as HTML.
                if not isinstance(body, dict) or not isinstance(body.get('shifts'), list):
                    self._send_validation_error("Navbatchilik jadvali noto'g'ri formatda", 'shifts')
                    return
                if len(body['shifts']) > 400:
                    self._send_validation_error("Navbatchilik jadvalida juda ko'p kun bor", 'shifts')
                    return

                def _has_markup(v):
                    if isinstance(v, str):
                        return any(ch in v for ch in '<>"')
                    if isinstance(v, dict):
                        return any(_has_markup(x) for x in v.values())
                    if isinstance(v, list):
                        return any(_has_markup(x) for x in v)
                    return False

                if any(not isinstance(sh, dict) for sh in body['shifts']) or _has_markup(body.get('shifts')) or _has_markup(body.get('sanitarkas')):
                    self._send_validation_error("Ismlarda < > \" belgilariga ruxsat yo'q", 'shifts')
                    return
                ds_file = os.path.join(BASE_DIR, 'data', 'duty_schedule.json')
                saved = read_json_file(ds_file, default=None)
                if not isinstance(saved, dict):
                    saved = {}
                # Merge by date. Replacing the list let a one-month payload
                # (the swap's fallback for a month not yet stored) erase every
                # other month of the roster.
                merged = {}
                for sh in (saved.get('shifts') or []):
                    if isinstance(sh, dict) and sh.get('date'):
                        merged[str(sh['date'])] = sh
                # A real calendar day only. The pattern alone let 2026-13-45
                # (and a date with a trailing newline) in, and since saves
                # now merge instead of replacing, no save could remove it.
                for sh in body['shifts']:
                    _d = sh.get('date') if isinstance(sh, dict) else None
                    try:
                        _ok = (isinstance(_d, str) and len(_d) == 10 and
                               datetime.date.fromisoformat(_d).isoformat() == _d)
                    except ValueError:
                        _ok = False
                    if not _ok:
                        self._send_validation_error("Smena sanasi noto'g'ri", 'shifts')
                        return
                    merged[_d] = sh
                saved['shifts'] = [merged[d] for d in sorted(merged)]
                if isinstance(body.get('sanitarkas'), list):
                    saved['sanitarkas'] = body['sanitarkas']
                saved['updated_at'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                write_json_atomic(ds_file, saved)
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Navbatchilik jadvali muvaffaqiyatli saqlandi'}, ensure_ascii=False).encode('utf-8'))

            # POST /api/hr/attendance -> one day's attendance for one person.
            # The HR page used to keep attendance in the browser only, so it
            # was gone on another computer and never reached the database
            # that GET /api/hr/data reads. One row per person per day
            # (uq_staff_work_date): a second save for the same day corrects it.
            elif path == '/api/hr/attendance':
                row, _att_err = parse_attendance(body if isinstance(body, dict) else {})
                if _att_err:
                    self._send_validation_error(_att_err[0], _att_err[1])
                    return
                cur.execute("SELECT id FROM staff WHERE id = ?", (row['staff_id'],))
                if not cur.fetchone():
                    self._send_validation_error("Bunday xodim topilmadi.", 'staff_id')
                    return
                cur.execute("""
                    INSERT INTO staff_attendance
                        (staff_id, work_date, shift_type, check_in, check_out, status, late_minutes, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(staff_id, work_date) DO UPDATE SET
                        shift_type = excluded.shift_type,
                        check_in = excluded.check_in,
                        check_out = excluded.check_out,
                        status = excluded.status,
                        late_minutes = excluded.late_minutes,
                        notes = excluded.notes
                """, (row['staff_id'], row['work_date'], row['shift_type'], row['check_in'],
                      row['check_out'], row['status'], row['late_minutes'], row['notes']))
                cur.execute("""
                    SELECT sa.*, s.full_name AS staff_name, s.role, s.specialty
                    FROM staff_attendance sa JOIN staff s ON sa.staff_id = s.id
                    WHERE sa.staff_id = ? AND sa.work_date = ?
                """, (row['staff_id'], row['work_date']))
                saved = attendance_out(cur.fetchone())
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Davomat saqlandi',
                    'id': saved.get('id'),
                    'attendance': saved
                }, ensure_ascii=False).encode('utf-8'))

            # POST /api/staff/<id>/reactivate -> undo a deactivation.
            # DELETE only ever set is_active = 0 (clinical records name their
            # author through staff), but the HR page called it "o'chirish"
            # and offered no way back. Re-saving the whole record would also
            # work, but it rewrites every field from whatever the page holds.
            elif path.startswith('/api/staff/') and path.endswith('/reactivate'):
                stf_id = urllib.parse.unquote(path[len('/api/staff/'):-len('/reactivate')]).strip()
                cur.execute("SELECT id FROM staff WHERE id = ?", (stf_id,))
                if not stf_id or not cur.fetchone():
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Bunday xodim topilmadi.'}, ensure_ascii=False).encode('utf-8'))
                    return
                cur.execute("UPDATE staff SET is_active = 1 WHERE id = ?", (stf_id,))
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Xodim qayta faollashtirildi', 'id': stf_id},
                                            ensure_ascii=False).encode('utf-8'))

            # 4. POST /api/staff or POST /api/hr/staff (Create / Update Staff & Doctor)
            elif path == '/api/staff' or path == '/api/hr/staff':
                raw_role = body.get('role', 'doctor')
                # Every role the staff table accepts (db.STAFF_ROLES). The
                # shorter list here turned a pharmacist, ward manager, HR
                # manager or kitchen worker into 'admin' whenever HR saved them.
                valid_roles = set(STAFF_ROLES)
                role = raw_role if raw_role in valid_roles else 'admin'

                full_name = (body.get('full_name') or '').strip()
                if not full_name:
                    conn.close()
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Xodim F.I.Sh kiritilishi shart'}, ensure_ascii=False).encode('utf-8'))
                    return
                
                prefix = 'DOC' if role in ('doctor', 'chief_doctor') else (
                    'NRS' if role == 'nurse' else ('SAN' if role == 'sanitar' else 'ADM'))
                # A client-chosen id is checked (see validate_client_id): a
                # quote in it ran script in the Super-Portal fire button.
                staff_id, _id_err = validate_client_id(body.get('id'))
                if _id_err:
                    conn.close()
                    self._send_validation_error(_id_err, 'id')
                    return
                if not staff_id:
                    # COUNT + 1 named an id that could already exist (after a
                    # deletion, or ids added by hand), and the upsert below then
                    # overwrote that employee. Probe for a free number instead.
                    cur.execute("SELECT COUNT(*) FROM staff WHERE id LIKE ?", (f"STF-{prefix}-%",))
                    count = (cur.fetchone()[0] or 0) + 1
                    while True:
                        staff_id = f"STF-{prefix}-{str(count).zfill(2)}"
                        cur.execute("SELECT 1 FROM staff WHERE id = ?", (staff_id,))
                        if not cur.fetchone():
                            break
                        count += 1
                specialty = body.get('specialty', '')
                phone = body.get('phone', '')
                email = body.get('email', '')
                shift_raw = str(body.get('shift_type') or 'day').lower()
                shift_db = 'night' if 'night' in shift_raw else ('24h' if '24h' in shift_raw else ('rotating' if 'call' in shift_raw or 'rotating' in shift_raw else 'day'))
                # A blank salary was saved as 10 000 000 and then paid. A
                # sanitarka paid only by duty shifts has 0, which is valid.
                raw_salary = body.get('base_salary', body.get('salary_base'))
                if raw_salary in (None, ''):
                    salary_base = 0.0
                else:
                    salary_base, _err = validate_amount(raw_salary, field='Oklad')
                    if _err or isinstance(raw_salary, bool) or salary_base != salary_base:
                        conn.close()
                        self._send_validation_error(_err or "Oklad raqam bo'lishi kerak.", 'base_salary')
                        return
                hr_fields, _hr_err = parse_staff_hr_fields(body)
                if _hr_err:
                    conn.close()
                    self._send_validation_error(_hr_err[0], _hr_err[1])
                    return

                cur.execute("SELECT full_name FROM staff WHERE id = ?", (staff_id,))
                _old = cur.fetchone()
                old_name = _old['full_name'] if _old else None
                cur.execute("""
                    INSERT INTO staff (id, full_name, role, specialty, phone, email, salary_base, shift_type, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(id) DO UPDATE SET
                        full_name = excluded.full_name,
                        role = excluded.role,
                        specialty = excluded.specialty,
                        phone = excluded.phone,
                        email = excluded.email,
                        salary_base = excluded.salary_base,
                        shift_type = excluded.shift_type
                """, (staff_id, full_name, role, specialty, phone, email, salary_base, shift_db))
                # An edit keeps is_active as it is. The upsert used to set it
                # to 1, so correcting a phone number of someone who had left
                # put them back on the roster and the payroll without anyone
                # deciding it; reactivation is POST /api/staff/<id>/reactivate.
                # Only the HR fields this request sent are written, so a save
                # from a form that does not have them keeps what HR entered.
                if hr_fields:
                    _cols = sorted(hr_fields)
                    cur.execute("UPDATE staff SET " + ", ".join(f"{c} = ?" for c in _cols) +
                                " WHERE id = ?", tuple(hr_fields[c] for c in _cols) + (staff_id,))
                cur.execute("SELECT * FROM staff WHERE id = ?", (staff_id,))
                _saved_row = cur.fetchone()
                _saved = dict(_saved_row) if _saved_row else {}
                conn.commit()
                conn.close()
                if old_name and old_name != full_name:
                    rename_in_roster(staff_id, old_name, full_name)
                _staff_out = {k: _saved.get(k) for k in [c for c, _ddl in STAFF_HR_COLUMNS]}
                _staff_out.update({
                    'id': staff_id,
                    'full_name': full_name,
                    'role': role,
                    'specialty': specialty,
                    'phone': phone,
                    'email': email,
                    'base_salary': salary_base,
                    'salary_base': salary_base,
                    'shift_type': shift_raw,
                    'is_active': 1 if _saved.get('is_active', 1) else 0,
                    'status': 'active' if _saved.get('is_active', 1) else 'inactive'
                })
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': 'Xodim muvaffaqiyatli saqlandi',
                    'id': staff_id,
                    'staff': _staff_out
                }, ensure_ascii=False).encode('utf-8'))

            # 5. POST /api/crm/patients (Create new patient)
            elif path == '/api/crm/patients' or path == '/api/patients':
                # A random 4-digit id draws from only 9000 values with no uniqueness
                # check, so registrations started failing on duplicate primary keys
                # well before the clinic reached a few hundred patients. Probe for a
                # free id in the same PAT-#### format, falling back to a millisecond
                # timestamp if the random space is saturated. The code is probed
                # with it (see new_patient_ids).
                pid, _id_err = validate_client_id(body.get('id'))
                if _id_err:
                    self._send_validation_error(_id_err, 'id')
                    return
                pcode = body.get('patient_code')
                if not pid:
                    pid, _pcode = new_patient_ids(cur, 'PAT')
                    pcode = pcode or _pcode
                pcode = pcode or f"FMH-2026-{pid[-4:]}"
                birth_date, birth_year, gender, _err = parse_birth_and_gender(body)
                if _err:
                    self._send_validation_error(_err[0], _err[1])
                    return
                cur.execute("""
                    INSERT INTO patients (id, patient_code, full_name, phone, emergency_contact, gender, birth_date, birth_year, referral_source, is_anonymous, medical_allergies, chronic_conditions, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pid,
                    pcode,
                    body.get('full_name', 'Anonim Bemor'),
                    body.get('phone', ''),
                    body.get('emergency_contact', ''),
                    gender,
                    birth_date,
                    birth_year,
                    body.get('referral_source', 'hotline'),
                    1 if body.get('is_anonymous', True) else 0,
                    # Not asked is not the same as none. These defaulted to
                    # "Yo'q", so a record nobody had questioned asserted the
                    # patient had no allergies -- and the doctor's page raises
                    # its allergy warning from this column, so the warning
                    # stayed silent. Unknown is now NULL and shows as unknown.
                    (body.get('medical_allergies') or '').strip() or None,
                    (body.get('chronic_conditions') or '').strip() or None,
                    body.get('status', 'active')
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Patient created', 'id': pid, 'patient_code': pcode}).encode('utf-8'))

            # 6. POST /api/reception/appointment (Book Consultation / Appointment)
            # POST /api/public/appointment-request
            #
            # An enquiry from the public website. The only unauthenticated
            # write in the system, so it is deliberately the narrowest one:
            # it inserts a row into appointment_requests and does nothing
            # else. No patient is registered, no appointment is booked, no
            # clinical table is touched, and the desk decides what is real.
            # POST /api/reception/requests/<id>/accept|reject
            #
            # Accepting is the moment an enquiry becomes clinical data: only
            # here is a patient registered and an appointment booked, and only
            # by someone who has read it. Rejecting leaves the row for the
            # record and creates nothing.
            elif path.startswith('/api/reception/requests/'):
                parts = [p for p in path.split('/') if p]
                if len(parts) < 5 or parts[-1] not in ('accept', 'reject'):
                    self._send_validation_error("Noma'lum amal.", 'action')
                    return
                req_id, action = parts[-2], parts[-1]

                ensure_appointment_requests(conn)
                cur.execute('SELECT * FROM appointment_requests WHERE id = ?', (req_id,))
                row = cur.fetchone()
                if not row:
                    self._send_validation_error(f"So'rov topilmadi ({req_id}).", 'id')
                    return
                if row['status'] != 'new':
                    self._send_validation_error(
                        f"Bu so'rov allaqachon ko'rib chiqilgan ({row['status']}).", 'status')
                    return

                sess = self.current_session()
                actor = (sess['user'].get('username') if sess else None)

                if action == 'reject':
                    cur.execute("""UPDATE appointment_requests
                                   SET status = 'rejected', handled_by = ?,
                                       handled_at = NOW()
                                   WHERE id = ?""", (actor, req_id))
                    conn.commit()
                    audit.record(conn, 'appointment_requests', req_id, 'REJECT',
                                 user=(sess['user'] if sess else None),
                                 ip_address=self.client_ip())
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({'message': "So'rov rad etildi"},
                                                ensure_ascii=False).encode('utf-8'))
                    return

                # --- accept: register the patient and book the visit --------
                #
                # The desk's accept button sent an empty body, so every
                # accepted enquiry was booked with no doctor at 10:00 -- a
                # visit nobody's diary showed, at a time nobody chose. A
                # booking is a slot in one doctor's day (the same rule as
                # /api/reception/appointment), so both are required, checked
                # before anything is written, and the slot must be free.
                doc_id = (str(body.get('doctor_id') or '')).strip()
                if not doc_id:
                    self._send_validation_error("Shifokor tanlanmagan.", 'doctor_id')
                    return
                # Any staff id was accepted, so a visit could be booked with a
                # nurse, the cashier or someone who had left.
                cur.execute("SELECT id FROM staff WHERE id = ? AND role IN ('doctor', 'chief_doctor') "
                            "AND is_active = 1", (doc_id,))
                if not cur.fetchone():
                    self._send_validation_error(f"Faol shifokor topilmadi ({doc_id}).", 'doctor_id')
                    return
                apt_day, _derr = parse_date_param(
                    body.get('appointment_date') or str(row['preferred_date'] or '')[:10],
                    default_today=True, field='Qabul sanasi')
                if _derr:
                    self._send_validation_error(_derr, 'appointment_date')
                    return
                # The website's preferred day is often already past when the
                # desk gets to it; booking it put the visit in yesterday's
                # diary where nobody would see it.
                if apt_day < datetime.date.today():
                    self._send_validation_error(
                        "Qabul sanasi o'tib ketgan. Bugungi yoki keyingi kunni tanlang.",
                        'appointment_date')
                    return
                apt_date = apt_day.isoformat()
                apt_time = (str(body.get('appointment_time') or '')).strip()
                if not apt_time:
                    self._send_validation_error("Qabul vaqti tanlanmagan.", 'appointment_time')
                    return
                if not re.match(r'^([01]?\d|2[0-3]):[0-5]\d(:[0-5]\d)?$', apt_time):
                    self._send_validation_error(
                        "Qabul vaqti noto'g'ri. Kutilgan format: SS:DD (masalan 14:30).",
                        'appointment_time')
                    return
                cur.execute("""
                    SELECT id FROM appointments
                    WHERE doctor_id = ? AND appointment_date = ? AND appointment_time = ?
                      AND status != 'cancelled'
                    LIMIT 1
                """, (doc_id, apt_date, apt_time))
                if cur.fetchone():
                    self._send_validation_error(
                        f"Bu vaqt band: shifokorda {apt_date} soat {apt_time} ga allaqachon yozilgan bemor bor.",
                        'appointment_time')
                    return
                # The website's service field is free text; a value the
                # appointments CHECK does not know made the insert fail with a
                # 500 after the patient row was already built.
                # No home visits for now (PO, 2026-10-08): an enquiry asking
                # for one is booked as a visit to the clinic.
                apt_service = row['service_type'] if row['service_type'] in APPOINTMENT_SERVICE_TYPES else 'outpatient'
                if apt_service == 'home_visit':
                    apt_service = 'outpatient'

                phone = (row['phone'] or '').strip()
                name = (row['full_name'] or '').strip() or 'Bemor'
                patient_id = None
                if phone:
                    # Phone AND name, as at the desk (/api/reception/appointment).
                    # The phone alone filed a relative who shares the family
                    # phone into the other person's record and history.
                    cur.execute('SELECT id FROM patients WHERE phone = ? AND full_name = ? LIMIT 1',
                                (phone, name))
                    found = cur.fetchone()
                    if found:
                        patient_id = found['id']
                if not patient_id:
                    patient_id, _pcode = new_patient_ids(cur)
                    cur.execute("""
                        INSERT INTO patients (id, patient_code, full_name, phone,
                                              referral_source, is_anonymous, status)
                        VALUES (?, ?, ?, ?, 'website', 0, 'active')
                    """, (patient_id, _pcode, name, phone))

                apt_id = new_record_id(cur, 'appointments', 'APT-2026')
                cur.execute("""
                    INSERT INTO appointments (id, patient_id, patient_name, patient_phone,
                                              doctor_id, service_type, appointment_date,
                                              appointment_time, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
                """, (apt_id, patient_id, name, phone,
                      doc_id,
                      apt_service,
                      apt_date, apt_time,
                      row['note'] or 'Saytdan kelgan so\'rov'))

                cur.execute("""UPDATE appointment_requests
                               SET status = 'accepted', handled_by = ?, handled_at = NOW(),
                                   patient_id = ?, appointment_id = ?
                               WHERE id = ?""", (actor, patient_id, apt_id, req_id))
                conn.commit()
                audit.record(conn, 'appointment_requests', req_id, 'ACCEPT',
                             user=(sess['user'] if sess else None),
                             new_data={'patient_id': patient_id, 'appointment_id': apt_id},
                             ip_address=self.client_ip())
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': "So'rov qabul qilindi va navbatga yozildi",
                    'patient_id': patient_id, 'appointment_id': apt_id,
                }, ensure_ascii=False).encode('utf-8'))

            elif path == PUBLIC_ENQUIRY_PATH:
                ip = self.client_ip()

                # A hidden field no person fills in. Bots fill every input
                # they find, so a non-empty one is a bot; answer 201 anyway so
                # it learns nothing, and record nothing.
                if (body.get('website') or body.get('company') or '').strip():
                    self._send_enquiry_ok()
                    return

                if not enquiry_rate_ok('attempt', ip,
                                      PUBLIC_ENQUIRY_ATTEMPTS_PER_HOUR):
                    self._set_json_headers(429, cors=True)
                    self.wfile.write(json.dumps({
                        'error': "Juda ko'p so'rov yuborildi. Iltimos, keyinroq "
                                 "urinib ko'ring yoki klinikaga qo'ng'iroq qiling."
                    }, ensure_ascii=False).encode('utf-8'))
                    return

                name = (body.get('full_name') or body.get('name') or '').strip()
                phone = (body.get('phone') or '').strip()
                if len(name) < 2 or len(name) > 160:
                    self._send_validation_error('Ism kiritilishi kerak.', 'full_name',
                                                cors=True)
                    return
                digits = ''.join(ch for ch in phone if ch.isdigit())
                if not (7 <= len(digits) <= 15):
                    self._send_validation_error("Telefon raqami to'g'ri emas.", 'phone',
                                                cors=True)
                    return

                preferred = None
                if (body.get('preferred_date') or '').strip():
                    day, derr = parse_date_param(body.get('preferred_date'))
                    if derr:
                        self._send_validation_error(derr, 'preferred_date', cors=True)
                        return
                    if day < datetime.date.today():
                        self._send_validation_error(
                            "Sana o'tib ketgan.", 'preferred_date', cors=True)
                        return
                    preferred = day.isoformat()

                # The input is good; now spend one of this address's actual
                # bookings.
                if not enquiry_rate_ok('stored', ip, PUBLIC_ENQUIRY_PER_HOUR,
                                      PUBLIC_ENQUIRY_PER_DAY):
                    self._set_json_headers(429, cors=True)
                    self.wfile.write(json.dumps({
                        'error': "Juda ko'p so'rov yuborildi. Iltimos, keyinroq "
                                 "urinib ko'ring yoki klinikaga qo'ng'iroq qiling."
                    }, ensure_ascii=False).encode('utf-8'))
                    return

                ensure_appointment_requests(conn)
                req_id = f"REQ-{datetime.datetime.now():%Y%m%d%H%M%S}-{os.urandom(2).hex()}"
                cur.execute("""
                    INSERT INTO appointment_requests
                        (id, full_name, phone, preferred_date, service_type,
                         note, source, status, ip_address)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?)
                """, (
                    req_id, name[:160], phone[:60], preferred,
                    (body.get('service_type') or '')[:60] or None,
                    (body.get('note') or body.get('message') or '')[:1000] or None,
                    (body.get('source') or 'website')[:60],
                    ip[:60],
                ))
                conn.commit()
                self._send_enquiry_ok(req_id)
                # Tell the staff group, so a lead is answered while it is
                # warm instead of when somebody next opens the tab. Runs on a
                # background thread after the reply has been sent, so a slow
                # or failing Telegram can neither delay nor fail the website;
                # with no bot token configured telegram_service is None.
                if telegram_service:
                    try:
                        telegram_service.notify_enquiry_async({
                            'full_name': name[:160],
                            'phone': phone[:60],
                            'preferred_date': preferred,
                            'note': (body.get('note') or body.get('message') or '')[:1000],
                        })
                    except Exception as _e_notify:
                        print(f"[Telegram Notify Error] {_e_notify}")

            elif path == '/api/reception/appointment':
                apt_id, _id_err = validate_client_id(body.get('id'))
                if _id_err:
                    self._send_validation_error(_id_err, 'id')
                    return
                apt_id = apt_id or new_record_id(cur, 'appointments', 'APT-2026')
                patient_name = (body.get('patient_name') or '').strip()
                patient_phone = body.get('patient_phone', '')
                doc_id = body.get('doctor_id')
                date_str = body.get('date') or datetime.date.today().isoformat()
                time_str = body.get('time') or '10:00'
                srv_type = body.get('service_type', 'outpatient')

                # The name defaulted to 'Bemor' and the page sent 'STF-DOC-01'
                # when no doctor was picked, so a half-filled form booked a
                # nameless patient into a real doctor's diary. An appointment
                # is a slot in one doctor's day; without a doctor or a person
                # there is nothing to book.
                if not patient_name:
                    self._send_validation_error("Bemorning ismi kiritilmagan.", 'patient_name')
                    return
                if not doc_id:
                    self._send_validation_error("Shifokor tanlanmagan.", 'doctor_id')
                    return

                # The desk's intake form records a visit happening now and
                # prints a slip with its fee; the appointments tab books a
                # future slot and bills nothing. Only the former sends
                # bill_visit, and its fee is billed with the appointment (see
                # price_desk_visit). Priced before anything is written, so a
                # bad price refuses the whole visit.
                bill_visit = str(body.get('bill_visit') or '').lower() in ('1', 'true')
                visit_line = None
                if bill_visit:
                    visit_line, _verr = price_desk_visit(srv_type, body)
                    if _verr:
                        self._send_validation_error(_verr[0], _verr[1])
                        return

                _bdate, _byear, _gender, _err = parse_birth_and_gender(body)
                if _err:
                    self._send_validation_error(_err[0], _err[1])
                    return

                # Find the patient (registered further down if not found).
                #
                # The match was `phone = ? OR full_name = ?` with the phone bound
                # even when it was empty. Most records carry an empty phone, so
                # booking a consultation for someone who did not leave a number
                # matched the first such patient in the table and filed the visit
                # under a stranger. An empty phone now matches nobody.
                #
                # It then matched on the phone alone, or on the name alone. A
                # family sharing one phone became one patient, two people
                # called Aziz Karimov became one patient, and every anonymous
                # visit -- all named 'Anonim Bemor', phone '—' -- was filed in
                # one record, so each stranger's history showed the others'.
                # A match now needs the phone AND the name, or with no phone
                # the name AND the date of birth. Anything less registers a
                # new patient: a duplicate can be merged later, a merged
                # stranger's allergies cannot be un-read.
                is_anon = str(body.get('is_anonymous') or '').lower() in ('1', 'true')
                patient_phone = (patient_phone or '').strip()
                if is_anon or patient_phone in ('—', '-'):
                    patient_phone = ''
                p_exist = None
                if is_anon:
                    pass
                elif patient_phone:
                    cur.execute("SELECT id FROM patients WHERE phone = ? AND full_name = ? LIMIT 1",
                                (patient_phone, patient_name))
                    p_exist = cur.fetchone()
                elif _bdate:
                    cur.execute("SELECT id FROM patients WHERE full_name = ? AND birth_date = ? LIMIT 1",
                                (patient_name, _bdate))
                    p_exist = cur.fetchone()

                # A retried intake (a second click, or a resend after the
                # answer was lost) would book and bill the same visit again.
                # The same patient, doctor, day and service already recorded
                # with a bill is that visit: answer with it, write nothing.
                # Only an unpaid bill written in the last 10 minutes counts.
                # Matching any earlier visit that day treated a second real
                # consultation (the patient came back in the afternoon, paid
                # in the morning) as a retry, so it was never billed. The page
                # sends no request id, and a retry comes seconds after the
                # first send, before anyone could have paid.
                if bill_visit and p_exist:
                    cur.execute("""
                        SELECT ap.id, inv.id AS invoice_id
                        FROM appointments ap
                        JOIN invoices inv ON inv.appointment_id = ap.id
                        WHERE ap.patient_id = ? AND ap.doctor_id = ? AND ap.appointment_date = ?
                          AND ap.service_type = ? AND ap.status NOT IN ('cancelled', 'completed')
                          AND inv.payment_status = 'unpaid' AND inv.total_paid = 0
                          AND inv.created_at >= NOW() - INTERVAL 10 MINUTE
                        LIMIT 1
                    """, (p_exist[0], doc_id, date_str, srv_type))
                    _same = cur.fetchone()
                    if _same:
                        conn.close()
                        self._set_json_headers(200)
                        self.wfile.write(json.dumps({
                            'message': "Bu tashrif allaqachon qayd etilgan",
                            'id': _same['id'], 'patient_id': p_exist[0],
                            'invoice_id': _same['invoice_id'], 'already_recorded': True,
                        }, ensure_ascii=False).encode('utf-8'))
                        return

                # One doctor, one patient per slot. The desk's slot grid never
                # showed booked times (it read fields the API does not send),
                # and nothing here checked either, so two receptionists could
                # book the same doctor at the same minute. Only a chosen time
                # claims a slot; the 10:00 filled in above for a request that
                # names none is a placeholder, not a booking of 10:00.
                _slot_taken = None
                if body.get('time'):
                    cur.execute("""
                        SELECT id FROM appointments
                        WHERE doctor_id = ? AND appointment_date = ? AND appointment_time = ?
                          AND status != 'cancelled'
                        LIMIT 1
                    """, (doc_id, date_str, time_str))
                    _slot_taken = cur.fetchone()
                if _slot_taken:
                    self._send_validation_error(
                        f"Bu vaqt band: shifokorda {date_str} soat {time_str} ga allaqachon yozilgan bemor bor.",
                        'time')
                    return

                if p_exist:
                    patient_id = p_exist[0]
                    # Fill in details the desk has now and the record lacks,
                    # without overwriting anything already known.
                    cur.execute("""
                        UPDATE patients
                        SET gender     = COALESCE(gender, ?),
                            birth_date = COALESCE(birth_date, ?),
                            birth_year = COALESCE(birth_year, ?)
                        WHERE id = ?
                    """, (_gender, _bdate, _byear, patient_id))
                else:
                    patient_id, _pcode = new_patient_ids(cur)
                    cur.execute("""
                        INSERT INTO patients (id, patient_code, full_name, phone,
                                              gender, birth_date, birth_year,
                                              referral_source, is_anonymous, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'reception', ?, 'active')
                    """, (patient_id, _pcode, patient_name,
                          patient_phone, _gender, _bdate, _byear, 1 if is_anon else 0))

                cur.execute("""
                    INSERT INTO appointments (id, patient_id, patient_name, patient_phone, doctor_id, service_type, appointment_date, appointment_time, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    apt_id,
                    patient_id,
                    patient_name,
                    patient_phone,
                    doc_id,
                    srv_type,
                    date_str,
                    time_str,
                    body.get('status', 'confirmed'),
                    body.get('notes', '')
                ))
                invoice_id = None
                if visit_line:
                    # The visit's own invoice, through the same triggers as a
                    # stay: the line sets total_billed, payments set the rest.
                    # appointment_id is unique, so a visit is billed once.
                    invoice_id = f"INV-{apt_id}"
                    cur.execute("""
                        INSERT INTO invoices (id, appointment_id, total_billed, discount_amount,
                                              net_amount, total_paid, balance_due, payment_status)
                        VALUES (?, ?, 0.00, 0.00, 0.00, 0.00, 0.00, 'unpaid')
                    """, (invoice_id, apt_id))
                    cur.execute("""
                        INSERT INTO invoice_items (invoice_id, service_name, quantity, unit_price,
                                                   item_type, service_start_date)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (invoice_id, visit_line['service_name'], visit_line['quantity'],
                          visit_line['unit_price'], visit_line['item_type'], date_str))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                _out = {'message': 'Appointment booked', 'id': apt_id, 'patient_id': patient_id}
                if visit_line:
                    _out.update({'invoice_id': invoice_id,
                                 'billed': visit_line['quantity'] * visit_line['unit_price'],
                                 'unit_price': visit_line['unit_price'],
                                 'quantity': visit_line['quantity']})
                self.wfile.write(json.dumps(_out, ensure_ascii=False).encode('utf-8'))

            # 7. POST /api/reception/call-log (Log Hotline / CRM Call)
            elif path == '/api/reception/call-log':
                call_id, _id_err = validate_client_id(body.get('id'))
                if _id_err:
                    self._send_validation_error(_id_err, 'id')
                    return
                call_id = call_id or new_record_id(cur, 'call_logs', 'CALL-2026')
                cur.execute("""
                    INSERT INTO call_logs (id, caller_name, caller_phone, call_direction, source, category, priority, status, notes)
                    VALUES (?, ?, ?, 'inbound', ?, ?, ?, ?, ?)
                """, (
                    call_id,
                    body.get('caller_name', "Noma'lum qo'ng'iroqchi"),
                    body.get('caller_phone', ''),
                    body.get('source', 'hotline'),
                    body.get('category', 'Konsultatsiya'),
                    body.get('priority', 'medium'),
                    body.get('status', 'new'),
                    body.get('notes', '')
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Call log saved', 'id': call_id}, ensure_ascii=False).encode('utf-8'))

            # 8. POST /api/doctor/anamnesis (Save/Update Medical History)
            elif path == '/api/doctor/anamnesis':
                pid = body.get('patient_id')
                cur.execute("SELECT id FROM medical_histories WHERE patient_id = ? OR patient_id = (SELECT id FROM patients WHERE patient_code = ?)", (pid, pid))
                existing = cur.fetchone()
                
                if existing:
                    hid = existing[0]
                    cur.execute("""
                        UPDATE medical_histories
                        SET doctor_id = COALESCE(?, doctor_id),
                            complaints = COALESCE(?, complaints),
                            anamnesis_morbi = COALESCE(?, anamnesis_morbi),
                            anamnesis_vitae = COALESCE(?, anamnesis_vitae),
                            allergic_status = COALESCE(?, allergic_status),
                            somatic_status = COALESCE(?, somatic_status),
                            psychiatric_status = COALESCE(?, psychiatric_status),
                            diagnosis_primary = COALESCE(?, diagnosis_primary),
                            diagnosis_secondary = COALESCE(?, diagnosis_secondary),
                            icd10_code = COALESCE(?, icd10_code),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (
                        body.get('doctor_id'),
                        body.get('complaints'),
                        body.get('anamnesis_morbi'),
                        body.get('anamnesis_vitae'),
                        body.get('allergic_status'),
                        body.get('somatic_status'),
                        body.get('psychiatric_status'),
                        body.get('diagnosis_primary'),
                        body.get('diagnosis_secondary'),
                        body.get('icd10_code'),
                        hid
                    ))
                else:
                    hid, _id_err = validate_client_id(body.get('id'))
                    if _id_err:
                        self._send_validation_error(_id_err, 'id')
                        return
                    hid = hid or new_record_id(cur, 'medical_histories', 'MH-2026')
                    cur.execute("""
                        INSERT INTO medical_histories (id, patient_id, admission_id, doctor_id, complaints, anamnesis_morbi, anamnesis_vitae, allergic_status, somatic_status, psychiatric_status, diagnosis_primary, diagnosis_secondary, icd10_code)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        hid,
                        pid,
                        body.get('admission_id'),
                        self._actor_staff_id(body, 'doctor_id'),
                        body.get('complaints', ''),
                        body.get('anamnesis_morbi', ''),
                        body.get('anamnesis_vitae', ''),
                        body.get('allergic_status', ''),
                        body.get('somatic_status', ''),
                        body.get('psychiatric_status', ''),
                        body.get('diagnosis_primary', ''),
                        body.get('diagnosis_secondary', ''),
                        body.get('icd10_code') or None
                    ))
                
                if body.get('allergic_status'):
                    cur.execute("UPDATE patients SET medical_allergies = ? WHERE id = ? OR patient_code = ?", (body.get('allergic_status'), pid, pid))

                # The anamnesis used to be copied into the patient's latest
                # consultation (or a new 'final' one), recording a suicide-risk
                # assessment of 'none' that nobody made and overwriting signed
                # intakes. Consultations are written only by the consultation
                # page now.

                conn.commit()
                conn.close()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Medical history saved', 'id': hid}).encode('utf-8'))

            # 9. POST /api/doctor/prescriptions -- a medication order.
            #
            # Every field here used to have a fallback: a request naming only
            # the drug was stored as 400 ml of it, intravenously by drip, once
            # every morning for five days, signed by STF-DOC-01. The nurse
            # station builds the medication round from exactly these columns,
            # so a nurse would have been handed a five-day infusion order that
            # no doctor wrote. Nothing clinical is invented now: what the
            # prescriber did not say is refused or left empty.
            elif path == '/api/doctor/prescriptions':
                rx_id, _id_err = validate_client_id(body.get('id'))
                if _id_err:
                    self._send_validation_error(_id_err, 'id')
                    return
                rx_id = rx_id or new_record_id(cur, 'prescriptions', 'RX-2026')

                med = (body.get('medication_name') or '').strip()
                duration_days, _err = validate_prescription_fields(body)
                if _err:
                    self._send_validation_error(_err[0], _err[1])
                    return

                # Authorship is a signature on a medical order. It comes from
                # the request or from whoever is signed in, and is left NULL
                # when neither is known -- never attributed to a named doctor
                # who was not asked, which is what it used to do. Unknown is
                # not a reason to refuse the order: the audit trail still
                # records which account wrote it.
                rx_doctor = self._actor_staff_id(body, 'doctor_id')

                # Optional warehouse link: the catalogue item and how much was
                # prescribed (in that item's base unit). Neither is invented:
                # absent stays NULL, and a quantity with no unit stated is kept
                # as given. Prescribing never changes stock (inventory.py).
                rx_extra = {}
                rx_link = str(body.get('medication_id') or '').strip()
                if rx_link:
                    cur.execute("SELECT 1 FROM medications_catalog WHERE id = ?", (rx_link,))
                    if not cur.fetchone():
                        self._send_validation_error("Ombordagi dori topilmadi.", 'medication_id')
                        return
                    rx_extra['medication_id'] = rx_link
                if body.get('quantity_prescribed') not in (None, ''):
                    try:
                        rx_extra['quantity_prescribed'] = inventory.parse_qty(
                            body.get('quantity_prescribed'), 'quantity_prescribed', 'Buyurilgan miqdor')
                        rx_extra['quantity_unit'] = inventory.parse_text(
                            body.get('quantity_unit'), 'quantity_unit', 'Miqdor birligi', 32)
                    except inventory.InventoryError as _e_rx:
                        self._send_validation_error(_e_rx.message, _e_rx.field)
                        return

                cur.execute("""
                    INSERT INTO prescriptions (id, patient_id, admission_id, doctor_id, medication_name, form, dosage, route, frequency, duration_days, timing, instructions, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rx_id,
                    body.get('patient_id'),
                    body.get('admission_id'),
                    rx_doctor,
                    med,
                    (body.get('form') or '').strip() or None,
                    str(body.get('dosage')).strip(),
                    str(body.get('route')).strip(),
                    str(body.get('frequency')).strip(),
                    duration_days,
                    (body.get('timing') or '').strip() or None,
                    (body.get('instructions') or '').strip() or None,
                    body.get('status', 'active')
                ))
                if rx_extra:
                    cur.execute("UPDATE prescriptions SET " + ", ".join(f"{k} = ?" for k in rx_extra)
                                + " WHERE id = ?", list(rx_extra.values()) + [rx_id])
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Prescription created', 'id': rx_id}).encode('utf-8'))

            # 10. POST /api/doctor/notes -- the daily ward-round assessment.
            #
            # This wrote a column named vital_bp. The table has
            # vital_bp_systolic and vital_bp_diastolic and never had
            # vital_bp, so every save raised 'Unknown column' and answered
            # 500: the check-up tab had never once recorded anything, and
            # doctor_daily_notes was empty in a database that had been in use.
            #
            # It also invented the observations it was given no values for --
            # 120/80, pulse 72, 36.6 degrees, SpO2 98, 'Holat barqaror'. In a
            # medical record an invented vital sign is indistinguishable from
            # a measured one; blank now stays blank.
            elif path == '/api/doctor/notes':
                pid = (body.get('patient_id') or '').strip()
                adm_id = (body.get('admission_id') or '').strip() or None
                if not pid:
                    self._send_validation_error('Bemor tanlanmadi.', 'patient_id')
                    return

                day, err = parse_date_param(body.get('note_date') or body.get('date'))
                if err:
                    self._send_validation_error(err, 'note_date')
                    return
                if day > datetime.date.today():
                    self._send_validation_error(
                        "Kelajakdagi kun uchun ko'rik yozilmaydi.", 'note_date')
                    return

                condition = (body.get('patient_condition') or 'moderate').strip()
                if condition not in ('satisfactory', 'moderate', 'severe', 'critical'):
                    self._send_validation_error(
                        "Holat noto'g'ri. Ruxsat etilgan: satisfactory, moderate, "
                        "severe, critical.", 'patient_condition')
                    return

                dynamics = (body.get('dynamics_notes') or '').strip()
                if not dynamics:
                    # The column is NOT NULL, and a round with nothing written
                    # in it is not a round.
                    self._send_validation_error(
                        "Dinamika (ko'rik xulosasi) to'ldirilishi shart.",
                        'dynamics_notes')
                    return

                # Same ranges and the same messages as the nurse's vitals.
                vitals, verr = nursery.parse_vitals(body)
                if verr:
                    self._send_validation_error(verr[0], verr[1])
                    return

                sess = self.current_session()
                doc_id = (body.get('doctor_id')
                          or (sess['user'].get('staff_id') if sess else None))

                # As on the nurse's sheet, an amendment only touches what it
                # names: correcting the written assessment must not silently
                # erase a pulse recorded on the same round.
                _upd = ['doctor_id', 'patient_condition', 'dynamics_notes']
                _upd += [f for f in nursery.VITAL_RANGES if f in vitals]
                if 'treatment_adjustments' in body:
                    _upd.append('treatment_adjustments')
                _clause = ', '.join(f"{c} = VALUES({c})" for c in _upd)
                _treat = (body.get('treatment_adjustments') or '').strip() or None
                # The unique key is (admission_id, note_date), and NULLs never
                # collide, so for a patient with no stay every save added
                # another row for the same day. Update that day's row instead.
                _existing = None
                if adm_id is None:
                    cur.execute(
                        "SELECT id FROM doctor_daily_notes WHERE patient_id = ? "
                        "AND admission_id IS NULL AND note_date = ? ORDER BY id DESC LIMIT 1",
                        (pid, day.isoformat()))
                    _existing = cur.fetchone()
                if _existing:
                    _vals = {'doctor_id': doc_id, 'patient_condition': condition,
                             'dynamics_notes': dynamics, 'treatment_adjustments': _treat}
                    _vals.update(vitals)
                    cur.execute(
                        "UPDATE doctor_daily_notes SET " + ', '.join(f"{c} = ?" for c in _upd) +
                        " WHERE id = ?",
                        tuple(_vals.get(c) for c in _upd) + (_existing['id'],))
                else:
                    cur.execute(f"""
                        INSERT INTO doctor_daily_notes (
                            patient_id, admission_id, doctor_id, note_date,
                            patient_condition, vital_bp_systolic, vital_bp_diastolic,
                            vital_pulse, vital_temp, vital_spo2,
                            dynamics_notes, treatment_adjustments)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE {_clause}
                    """, (
                        pid, adm_id, doc_id, day.isoformat(), condition,
                        vitals.get('vital_bp_systolic'), vitals.get('vital_bp_diastolic'),
                        vitals.get('vital_pulse'), vitals.get('vital_temp'),
                        vitals.get('vital_spo2'), dynamics, _treat,
                    ))
                conn.commit()
                audit.record(conn, 'doctor_daily_notes', adm_id or pid, 'WARD_ROUND',
                             user=(sess['user'] if sess else None),
                             new_data={'date': day.isoformat(), 'condition': condition},
                             ip_address=self.client_ip())
                self._set_json_headers(201)
                self.wfile.write(json.dumps(
                    {'message': "Ko'rik saqlandi", 'date': day.isoformat()},
                    ensure_ascii=False).encode('utf-8'))

            # 11. POST /api/doctor/epicrisis -- the discharge summary.
            #
            # This is the document the patient leaves with and the clinic is
            # held to. Saving it empty used to produce a complete one:
            # diagnosis 'Alkogol intoksikatsiyasi remissiya davri', ICD-10
            # F10.2, outcome 'recovered', signed by STF-DOC-01 -- a diagnosis
            # nobody made, over the name of a doctor who was not asked. The
            # clinical findings are now required and the signature comes from
            # whoever is signed in.
            elif path == '/api/doctor/epicrisis':
                epi_id, _id_err = validate_client_id(body.get('id'))
                if _id_err:
                    self._send_validation_error(_id_err, 'id')
                    return
                epi_id = epi_id or new_record_id(cur, 'discharge_epicrises', 'EPI-2026')

                diagnosis = (body.get('diagnosis_final') or '').strip()
                if not diagnosis:
                    self._send_validation_error(
                        'Yakuniy tashxis kiritilishi shart.', 'diagnosis_final')
                    return

                status_val = (body.get('discharge_status') or '').strip()
                if not status_val:
                    self._send_validation_error(
                        'Chiqish holati tanlanishi shart.', 'discharge_status')
                    return

                epi_date, derr = parse_date_param(body.get('epicrisis_date'))
                if derr:
                    self._send_validation_error(derr, 'epicrisis_date')
                    return

                # As on the prescription: recorded when known, NULL when not,
                # never someone else's name.
                epi_doctor = self._actor_staff_id(body, 'doctor_id')

                cur.execute("""
                    INSERT INTO discharge_epicrises (id, patient_id, admission_id, doctor_id, epicrisis_date, diagnosis_final, icd10_code, treatment_summary, home_prescriptions, psycho_recommendations, discharge_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    epi_id,
                    body.get('patient_id'),
                    body.get('admission_id'),
                    epi_doctor,
                    epi_date.isoformat(),
                    diagnosis,
                    (body.get('icd10_code') or '').strip() or None,
                    (body.get('treatment_summary') or '').strip() or None,
                    (body.get('home_prescriptions') or '').strip() or None,
                    (body.get('psycho_recommendations') or '').strip() or None,
                    status_val
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Epicrisis saved', 'id': epi_id}).encode('utf-8'))

            # 11b. POST /api/doctor/consultation-case (Atomic Consultation, Kasallik Varaqasi & Retseptlar)
            elif path == '/api/doctor/consultation-case':
                doc_id = self._actor_staff_id(body, 'doctor_id')
                # The name is printed into the notes this handler generates.
                # It defaulted to a real doctor's name, so a case saved by
                # anyone else read as that doctor's work. Look it up from
                # the id, and say nothing rather than name the wrong person.
                doc_name = (body.get('doctor_name') or '').strip()
                if not doc_name and doc_id:
                    cur.execute('SELECT full_name FROM staff WHERE id = ?', (doc_id,))
                    _dr = cur.fetchone()
                    if _dr:
                        doc_name = _dr['full_name']
                doc_name = doc_name or 'Shifokor'
                
                # Verify doctor name from staff table if possible
                try:
                    cur.execute("SELECT full_name FROM staff WHERE id = ?", (doc_id,))
                    d_row = cur.fetchone()
                    if d_row:
                        doc_name = d_row['full_name'] if isinstance(d_row, dict) else d_row[0]
                except Exception:
                    pass

                pt_data = body.get('patient') or {}
                pt_name = (pt_data.get('full_name') or body.get('patient_name') or '').strip()
                pt_phone = pt_data.get('phone') or body.get('patient_phone') or ''
                # These used to fall back to 'male' and 1990. On the UPDATE
                # below that did not merely invent data for a new patient: it
                # overwrote an existing one, so a woman born in 1985 recorded
                # correctly at the desk became a man born in 1990 the first
                # time a doctor saved her consultation. Unsupplied now means
                # NULL, and the UPDATE keeps whatever is already on file.
                _birth_src = dict(body)
                for _k in ('birth_date', 'birth_year', 'gender'):
                    if pt_data.get(_k) not in (None, ''):
                        _birth_src[_k] = pt_data.get(_k)
                pt_birth_date, pt_birth, pt_gender, _err = parse_birth_and_gender(_birth_src)
                if _err:
                    self._send_validation_error(_err[0], _err[1])
                    return

                # Checked before anything is written: the patient and the
                # consultation are committed first below, so refusing an
                # order half-way would leave a case saved without the drugs
                # the doctor thought they had ordered.
                rx_checked = []
                for rx in (body.get('prescriptions') or []):
                    if not (rx.get('medication_name') or rx.get('name') or '').strip():
                        continue
                    _days, _err = validate_prescription_fields(rx)
                    if _err:
                        _drug = (rx.get('medication_name') or rx.get('name')).strip()
                        self._send_validation_error(f"{_drug}: {_err[0]}", _err[1])
                        return
                    rx_checked.append((rx, _days))
                pt_address = pt_data.get('address') or body.get('address') or ''
                pt_emergency = pt_data.get('emergency_contact') or body.get('emergency_contact') or ''

                anam_data = body.get('anamnesis') or {}
                # Same rule as above: an allergy history nobody took is
                # unknown, not absent.
                allergy = (anam_data.get('allergic_status')
                           or body.get('allergic_status') or '').strip() or None

                pid = body.get('patient_id') or pt_data.get('id')
                p_row = None
                if pid:
                    cur.execute("SELECT id, patient_code FROM patients WHERE id = ? OR patient_code = ?", (pid, pid))
                    p_row = cur.fetchone()
                elif pt_phone and pt_name:
                    # The phone alone used to decide, and the UPDATE below then
                    # renamed that record: a mother's consultation saved with
                    # her son's phone turned his record into hers. Phone and
                    # name must both match; otherwise a new patient is made.
                    cur.execute("SELECT id, patient_code FROM patients WHERE phone = ? AND full_name = ?",
                                (pt_phone, pt_name))
                    p_row = cur.fetchone()

                if p_row:
                    patient_id = p_row['id'] if isinstance(p_row, dict) else p_row[0]
                    patient_code = p_row['patient_code'] if isinstance(p_row, dict) else p_row[1]
                    # A field the request does not carry keeps what is on
                    # file. The name used to become 'Yangi Bemor' and the
                    # allergy NULL whenever they were left out, so saving a
                    # case wiped a recorded penicillin allergy -- and the
                    # doctor's allergy warning with it.
                    cur.execute("""
                        UPDATE patients
                        SET full_name = COALESCE(NULLIF(?, ''), full_name),
                            phone = COALESCE(NULLIF(?, ''), phone),
                            emergency_contact = COALESCE(NULLIF(?, ''), emergency_contact),
                            gender = COALESCE(?, gender),
                            birth_date = COALESCE(?, birth_date),
                            birth_year = COALESCE(?, birth_year),
                            address = COALESCE(NULLIF(?, ''), address),
                            medical_allergies = COALESCE(?, medical_allergies),
                            status = 'active',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (pt_name, pt_phone, pt_emergency, pt_gender, pt_birth_date,
                          pt_birth, pt_address, allergy, patient_id))
                else:
                    if not pt_name:
                        self._send_validation_error("Bemorning ismi kiritilmagan.", 'full_name')
                        return
                    patient_id, patient_code = new_patient_ids(cur)
                    # chronic_conditions was the literal "Yo'q" -- none -- for
                    # a history nobody took.
                    cur.execute("""
                        INSERT INTO patients (id, patient_code, full_name, phone, emergency_contact, gender, birth_date, birth_year, address, referral_source, is_anonymous, medical_allergies, chronic_conditions, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'doctor_consultation', 0, ?, NULL, 'active')
                    """, (patient_id, patient_code, pt_name, pt_phone, pt_emergency,
                          pt_gender, pt_birth_date, pt_birth, pt_address, allergy))
                conn.commit()

                consultation_type = body.get('consultation_type', 'outpatient')
                admission_id = None

                if consultation_type == 'inpatient':
                    inpatient_info = body.get('inpatient_details') or {}
                    bed_id = inpatient_info.get('bed_id')
                    prog_type = inpatient_info.get('program_type') or 'Statsionar davolanish'
                    start_date = (inpatient_info.get('start_date') or datetime.date.today().isoformat())[:10]
                    end_date = (inpatient_info.get('end_date') or datetime.date.today().isoformat())[:10]
                    # No price from the wizard: the programme's rate from the
                    # one price list, not a hardcoded 720 000. An explicit
                    # price is taken as sent (PO, 2026-10-08: the server
                    # does not refuse a price that differs from the list).
                    daily_price = float(inpatient_info.get('daily_price')
                                        or package_daily_rate(prog_type))

                    if bed_id:
                        success, res_data = admit_patient(
                            conn, patient_id, bed_id, doc_id, prog_type,
                            start_date, end_date, daily_price, body.get('notes', f"Shifokor {doc_name} statsionar ko'rigi")
                        )
                        if success:
                            admission_id = res_data.get('admission_id')
                            try:
                                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                                if os.path.exists(rooms_file):
                                    with open(rooms_file, 'r', encoding='utf-8') as rf:
                                        cr_data = json.load(rf)
                                    bookings_list = cr_data.get('sample_calendar_bookings', [])
                                    bookings_list.append({
                                        'id': admission_id,
                                        'bed_id': res_data.get('bed_code') or bed_id,
                                        'patient_name': pt_name,
                                        'patient_phone': pt_phone,
                                        'doctor': doc_name,
                                        'program': prog_type,
                                        'daily_rate': daily_price,
                                        'start_date': start_date,
                                        'end_date': end_date,
                                        'status': 'active'
                                    })
                                    cr_data['sample_calendar_bookings'] = bookings_list
                                    write_json_atomic(rooms_file, cr_data)
                            except Exception as e_cr:
                                print("Warning syncing clinic_rooms.json on admission:", e_cr)

                apt_id = new_record_id(cur, 'appointments', 'APT-2026')
                apt_service = 'inpatient_consult' if consultation_type == 'inpatient' else 'outpatient'
                cur.execute("""
                    INSERT INTO appointments (id, patient_id, patient_name, patient_phone, doctor_id, service_type, appointment_date, appointment_time, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?)
                """, (
                    apt_id,
                    patient_id,
                    pt_name,
                    pt_phone,
                    doc_id,
                    apt_service,
                    datetime.date.today().isoformat(),
                    datetime.datetime.now().strftime('%H:%M'),
                    body.get('notes', f"Shifokor {doc_name} konsultatsiyasi")
                ))
                conn.commit()

                hid = new_record_id(cur, 'medical_histories', 'MH-2026')
                complaints = anam_data.get('complaints') or body.get('complaints', '')
                anam_morbi = anam_data.get('anamnesis_morbi') or body.get('anamnesis_morbi', '')
                anam_vitae = anam_data.get('anamnesis_vitae') or body.get('anamnesis_vitae', '')
                somatic = anam_data.get('somatic_status') or body.get('somatic_status', '')
                psychiatric = anam_data.get('psychiatric_status') or body.get('psychiatric_status', '')
                diag_pri = anam_data.get('diagnosis_primary') or body.get('diagnosis_primary', '')
                diag_sec = anam_data.get('diagnosis_secondary') or body.get('diagnosis_secondary', '')
                # The ICD-10 code defaulted to F10.2 (alcohol dependence) for every
                # case that did not state one -- a diagnosis code nobody made.
                icd10 = anam_data.get('icd10_code') or body.get('icd10_code') or None

                cur.execute("""
                    INSERT INTO medical_histories (id, patient_id, admission_id, doctor_id, complaints, anamnesis_morbi, anamnesis_vitae, allergic_status, somatic_status, psychiatric_status, diagnosis_primary, diagnosis_secondary, icd10_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    hid,
                    patient_id,
                    admission_id,
                    doc_id,
                    complaints,
                    anam_morbi,
                    anam_vitae,
                    allergy,
                    somatic,
                    psychiatric,
                    diag_pri,
                    diag_sec,
                    icd10
                ))
                conn.commit()

                saved_rx = []
                for rx, duration in rx_checked:
                    rx_id = new_record_id(cur, 'prescriptions', 'RX-2026')
                    med_name = (rx.get('medication_name') or rx.get('name')).strip()
                    # Optional parts stay empty rather than guessed; the
                    # required ones were checked above.
                    form = rx.get('form') or None
                    dosage = str(rx.get('dosage')).strip()
                    route = str(rx.get('route')).strip()
                    frequency = str(rx.get('frequency')).strip()
                    timing = rx.get('timing') or None
                    instructions = rx.get('instructions') or ''

                    cur.execute("""
                        INSERT INTO prescriptions (id, patient_id, admission_id, doctor_id, medication_name, form, dosage, route, frequency, duration_days, timing, instructions, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                    """, (
                        rx_id,
                        patient_id,
                        admission_id,
                        doc_id,
                        med_name,
                        form,
                        dosage,
                        route,
                        frequency,
                        duration,
                        timing,
                        instructions
                    ))
                    saved_rx.append(rx_id)

                conn.commit()
                conn.close()

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'success': True,
                    'message': f"Kasallik varaqasi va {len(saved_rx)} ta dori retsepti muvaffaqiyatli rasmiylashtirildi!",
                    'patient_id': patient_id,
                    'patient_code': patient_code,
                    'patient_name': pt_name,
                    'doctor_id': doc_id,
                    'doctor_name': doc_name,
                    'admission_id': admission_id,
                    'history_id': hid,
                    'prescriptions_count': len(saved_rx),
                    'consultation_type': consultation_type
                }, ensure_ascii=False).encode('utf-8'))

            # 12. POST /api/settings/pricing (Superadmin updates any price dynamically)
            elif path == '/api/settings/pricing':
                # Nothing here was checked: any package name was merged in,
                # a price could be text or negative and was then billed, and
                # updated_by was whatever the browser typed. Every value is
                # validated before the file is touched.
                new_packages = None
                if 'packages' in body:
                    if not isinstance(body.get('packages'), dict):
                        self._send_validation_error("Narxlar ro'yxati noto'g'ri.", 'packages')
                        return
                    new_packages = {}
                    for pid, pkg in body['packages'].items():
                        if pid not in DEFAULT_PRICING['packages']:
                            self._send_validation_error(
                                f"Noma'lum tarif: {str(pid)[:60]}.", f'packages.{str(pid)[:60]}')
                            return
                        if not isinstance(pkg, dict) or 'daily_rate' not in pkg:
                            self._send_validation_error(
                                "Tarif narxi kiritilmagan.", f'packages.{pid}.daily_rate')
                            return
                        raw_rate = pkg.get('daily_rate')
                        rate, _err = (None, "Narx raqam bo'lishi kerak.") \
                            if isinstance(raw_rate, bool) or raw_rate in (None, '') \
                            else validate_amount(raw_rate, field='Narx')
                        if not _err and rate != rate:   # NaN passes float()
                            _err = "Narx raqam bo'lishi kerak."
                        if _err:
                            self._send_validation_error(_err, f'packages.{pid}.daily_rate')
                            return
                        entry = {'daily_rate': int(rate) if float(rate).is_integer() else rate}
                        name_uz = str(pkg.get('name_uz') or '').strip()[:120]
                        if name_uz:
                            entry['name_uz'] = name_uz
                        new_packages[pid] = entry

                new_services = None
                if 'additional_services' in body:
                    if not isinstance(body.get('additional_services'), list):
                        self._send_validation_error(
                            "Qo'shimcha xizmatlar ro'yxati noto'g'ri.", 'additional_services')
                        return
                    new_services = []
                    seen_ids = set()
                    for i, svc in enumerate(body['additional_services']):
                        fld = f'additional_services.{i}'
                        if not isinstance(svc, dict):
                            self._send_validation_error("Xizmat ma'lumoti noto'g'ri.", fld)
                            return
                        sid = str(svc.get('id') or '').strip()[:60]
                        sname = str(svc.get('name') or '').strip()[:200]
                        if not sid:
                            self._send_validation_error("Xizmat identifikatori kiritilmagan.", fld + '.id')
                            return
                        if sid in seen_ids:
                            self._send_validation_error(
                                f"Xizmat identifikatori takrorlangan: {sid}.", fld + '.id')
                            return
                        if not sname:
                            self._send_validation_error("Xizmat nomi kiritilmagan.", fld + '.name')
                            return
                        raw_price = svc.get('price')
                        price, _err = (None, "Narx raqam bo'lishi kerak.") \
                            if isinstance(raw_price, bool) or raw_price in (None, '') \
                            else validate_amount(raw_price, field='Narx')
                        if not _err and price != price:
                            _err = "Narx raqam bo'lishi kerak."
                        if _err:
                            self._send_validation_error(_err, fld + '.price')
                            return
                        seen_ids.add(sid)
                        row = {'id': sid, 'name': sname,
                               'price': int(price) if float(price).is_integer() else price}
                        for opt in ('category', 'description'):
                            val = str(svc.get(opt) or '').strip()[:300]
                            if val:
                                row[opt] = val
                        new_services.append(row)

                new_tariffs = None
                if 'duty_tariffs' in body:
                    if not isinstance(body.get('duty_tariffs'), dict):
                        self._send_validation_error("Navbatchilik tariflari noto'g'ri.", 'duty_tariffs')
                        return
                    new_tariffs = {}
                    for key, raw in body['duty_tariffs'].items():
                        if key not in DEFAULT_PRICING['duty_tariffs']:
                            self._send_validation_error(
                                f"Noma'lum navbatchilik tarifi: {str(key)[:60]}.", f'duty_tariffs.{str(key)[:60]}')
                            return
                        val, _err = (None, "Narx raqam bo'lishi kerak.") \
                            if isinstance(raw, bool) or raw in (None, '') \
                            else validate_amount(raw, field='Narx')
                        if not _err and val != val:
                            _err = "Narx raqam bo'lishi kerak."
                        if _err:
                            self._send_validation_error(_err, f'duty_tariffs.{key}')
                            return
                        new_tariffs[key] = int(val) if float(val).is_integer() else val

                # The raw file is read (not load_pricing) so that a file that
                # cannot be parsed fails this request instead of being
                # overwritten with defaults.
                existing = read_json_file(PRICING_FILE, {})
                if not isinstance(existing, dict):
                    existing = {}
                if new_packages is not None:
                    if not isinstance(existing.get('packages'), dict):
                        existing['packages'] = {}
                    for pid, entry in new_packages.items():
                        merged_pkg = dict(existing['packages'].get(pid) or {})
                        merged_pkg.update(entry)
                        if not merged_pkg.get('name_uz'):
                            merged_pkg['name_uz'] = DEFAULT_PRICING['packages'][pid]['name_uz']
                        existing['packages'][pid] = merged_pkg
                if new_services is not None:
                    existing['additional_services'] = new_services
                if new_tariffs is not None:
                    if not isinstance(existing.get('duty_tariffs'), dict):
                        existing['duty_tariffs'] = {}
                    existing['duty_tariffs'].update(new_tariffs)
                existing['updated_at'] = datetime.datetime.now().isoformat()
                _sess = self.current_session() or {}
                _suser = _sess.get('user') or {}
                existing['updated_by'] = (_suser.get('full_name') or _suser.get('username') or '')[:120]

                write_json_atomic(PRICING_FILE, existing)

                # Also update MySQL beds default_daily_rate if shared rate updated
                if new_packages and 'statsionar_shared' in new_packages:
                    try:
                        new_shared = float(new_packages['statsionar_shared']['daily_rate'])
                        cur.execute("UPDATE beds SET default_daily_rate = ? WHERE bed_type = 'standard'", (new_shared,))
                        conn.commit()
                    except Exception as e_pr:
                        print("Error updating beds daily_rate:", e_pr)
                existing = load_pricing()

                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': "Narxlar muvaffaqiyatli saqlandi va barcha bo'limlarga tatbiq etildi", 'pricing': existing}, ensure_ascii=False).encode('utf-8'))

            # 12a. POST /api/consultations -- the six-section intake
            #
            # The plan is NOT part of this payload. The intake records what the
            # patient reported and the doctor observed at one moment and should
            # not change afterwards; the plan is a live instruction that gets
            # revised. They are saved and printed separately.
            elif path == '/api/consultations':
                patient_id = (body.get('patient_id') or '').strip()
                if not patient_id:
                    self._send_validation_error('Bemor tanlanmadi.', 'patient_id')
                    return
                cur.execute('SELECT id FROM patients WHERE id = ?', (patient_id,))
                if not cur.fetchone():
                    self._send_validation_error('Bemor topilmadi.', 'patient_id')
                    return

                values, err = consultation.clean_intake(body)
                if err:
                    self._send_validation_error(err)
                    return

                sess = self.current_session()
                doctor_id = (body.get('doctor_id')
                             or (sess['user'].get('staff_id') if sess else None) or None)
                status = 'draft' if body.get('status') == 'draft' else 'final'
                cid = consultation.save_intake(
                    conn, patient_id, doctor_id, values,
                    appointment_id=(body.get('appointment_id') or None),
                    status=status)

                # Close the booking this consultation answers, so the queue
                # does not keep offering a patient who has been seen.
                if body.get('appointment_id'):
                    cur.execute("UPDATE appointments SET status = 'completed' WHERE id = ?",
                                (body.get('appointment_id'),))
                    conn.commit()

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': 'Konsultatsiya saqlandi',
                    'id': cid, 'consultation_id': cid, 'patient_id': patient_id,
                }, ensure_ascii=False).encode('utf-8'))

            # 12a2. POST /api/treatment-plans -- stored and printed on its own
            elif path == '/api/treatment-plans':
                patient_id = (body.get('patient_id') or '').strip()
                if not patient_id:
                    self._send_validation_error('Bemor tanlanmadi.', 'patient_id')
                    return
                cur.execute('SELECT id FROM patients WHERE id = ?', (patient_id,))
                if not cur.fetchone():
                    self._send_validation_error('Bemor topilmadi.', 'patient_id')
                    return

                values, err = consultation.clean_plan(body)
                if err:
                    self._send_validation_error(err)
                    return

                sess = self.current_session()
                doctor_id = (body.get('doctor_id')
                             or (sess['user'].get('staff_id') if sess else None) or None)
                plan_id = consultation.save_plan(
                    conn, patient_id, doctor_id, values,
                    consultation_id=(body.get('consultation_id') or None))

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': 'Davolash rejasi saqlandi',
                    'id': plan_id, 'plan_id': plan_id, 'patient_id': patient_id,
                }, ensure_ascii=False).encode('utf-8'))

            # 12b. POST /api/nursery/administer
            #
            # Record one dose of the round: given, missed, refused or held.
            # Upserts on (prescription, date, slot), so correcting a mistaken
            # entry amends it instead of implying a second dose was given.
            # POST /api/daily-logs/<admission_id> -- the daily observation.
            # daily_logs had a read endpoint and no way to write one, so the
            # vitals the ward takes every morning had nowhere to go.
            elif path.startswith('/api/daily-logs'):
                adm_id = (path.replace('/api/daily-logs', '').strip('/')
                          or body.get('admission_id') or '').strip()
                if not adm_id:
                    self._send_validation_error('Yotish (admission) tanlanmadi.',
                                                'admission_id')
                    return

                day, err = parse_date_param(body.get('date') or body.get('log_date'))
                if err:
                    self._send_validation_error(err, 'date')
                    return
                if day > datetime.date.today():
                    self._send_validation_error(
                        "Kelajakdagi kun uchun ko'rsatkich yozilmaydi.", 'date')
                    return

                cur.execute("""SELECT a.id, a.start_date,
                                      COALESCE(a.actual_end_date, a.planned_end_date) AS end_date
                               FROM admissions a WHERE a.id = ?""", (adm_id,))
                adm = cur.fetchone()
                if not adm:
                    self._send_validation_error(f'Yotish topilmadi ({adm_id}).',
                                                'admission_id')
                    return
                # A reading dated outside the stay belongs to a different
                # admission, or to a typo.
                if not (str(adm['start_date'])[:10] <= day.isoformat()
                        <= str(adm['end_date'])[:10]):
                    self._send_validation_error(
                        f"Sana yotish muddatidan tashqarida "
                        f"({str(adm['start_date'])[:10]} - {str(adm['end_date'])[:10]}).",
                        'date')
                    return

                vitals, verr = nursery.parse_vitals(body)
                if verr:
                    self._send_validation_error(verr[0], verr[1])
                    return

                sess = self.current_session()
                staff_id = (sess['user'].get('staff_id') if sess else None) or None
                attended = body.get('attended', True)
                attended = attended not in (False, 0, '0', 'false', 'no')
                notes = (body.get('nurse_notes') or body.get('notes') or '').strip() or None

                row = nursery.record_vitals(conn, adm_id, day, vitals,
                                            attended=attended, nurse_notes=notes,
                                            staff_id=staff_id)
                audit.record(conn, 'daily_logs', adm_id, 'RECORD_VITALS',
                             user=(sess['user'] if sess else None),
                             new_data={'date': day.isoformat(), **vitals},
                             ip_address=self.client_ip())
                self._set_json_headers(201)
                self.wfile.write(json.dumps(
                    {'message': "Ko'rsatkichlar saqlandi", 'log': dict(row) if row else None},
                    ensure_ascii=False, default=str).encode('utf-8'))

            elif path == '/api/nursery/administer':
                day, err = parse_date_param(body.get('date'))
                if err:
                    self._send_validation_error(err, 'date')
                    return

                rx_id = (body.get('prescription_id') or '').strip()
                if not rx_id:
                    self._send_validation_error('Retsept tanlanmadi.', 'prescription_id')
                    return

                status = (body.get('status') or 'given').strip().lower()
                if status not in nursery.STATUSES:
                    self._send_validation_error(
                        "Holat noto'g'ri. Ruxsat etilgan: " + ', '.join(nursery.STATUSES), 'status')
                    return

                # A dose cannot be recorded as given before it is due.
                if day > datetime.date.today() and status == 'given':
                    self._send_validation_error(
                        "Kelajakdagi doza berilgan deb belgilanmaydi.", 'date')
                    return

                sess = self.current_session()
                staff_id = (sess['user'].get('staff_id') if sess else None) or None

                slot_raw = body.get('slot_index')
                try:
                    if slot_raw is None or str(slot_raw).strip() == '':
                        # No slot named: an as-needed or additional dose.
                        slot_index = nursery.next_extra_slot(conn, rx_id, day)
                    else:
                        slot_index = int(slot_raw)
                except Exception:
                    self._send_validation_error("Doza raqami noto'g'ri.", 'slot_index')
                    return

                try:
                    nursery.record_dose(
                        conn, rx_id, day, slot_index, status,
                        staff_id=staff_id,
                        notes=(body.get('notes') or None),
                        slot_label=(body.get('slot_label') or None))
                except LookupError as e:
                    self._send_validation_error(str(e), 'prescription_id')
                    return

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': 'Doza qayd etildi',
                    'prescription_id': rx_id,
                    'date': day.isoformat(),
                    'slot_index': slot_index,
                    'status': status,
                }, ensure_ascii=False).encode('utf-8'))

            # 13. POST /api/auth/login
            #
            # Verifies against a PBKDF2 hash (and still accepts a not-yet
            # migrated plaintext record), then issues an HttpOnly session
            # cookie. The password comparison is constant-time, and a failure
            # says only that the pair was wrong — never which half.
            elif path == '/api/auth/login':
                username = (body.get('username') or '').strip().lower()
                password = body.get('password') or ''

                ip = self.client_ip()
                found = auth.find_user(username)
                # A failed sign-in for a login that does not exist is often a
                # password typed into the login box. The audit viewer showed
                # that text to every administrator, so it is masked; a real
                # account's name is kept (that is the useful part).
                audit_login = (username or '-') if (found or not username) else audit.UNKNOWN_LOGIN

                # Refuse while locked out, before the password is even checked,
                # so a throttled attacker learns nothing from the response.
                locked = auth.lockout_remaining(username, ip)
                if locked:
                    minutes = max(1, locked // 60)
                    audit.record(conn, 'auth', audit_login, 'LOGIN_FAILED',
                                 new_data={'reason': 'locked_out', 'seconds_remaining': locked},
                                 ip_address=ip)
                    self._set_json_headers(429)
                    self.wfile.write(json.dumps({
                        'error': "Juda ko'p urinish",
                        'detail': f"Xavfsizlik uchun kirish vaqtincha bloklandi. "
                                  f"{minutes} daqiqadan so'ng qayta urinib ko'ring.",
                        'retry_after_seconds': locked,
                    }, ensure_ascii=False).encode('utf-8'))
                    return

                ok = bool(found) and found.get('is_active', True) and \
                    auth.verify_password(password, found.get('password'))

                if ok:
                    auth.note_login_success(username, ip)
                    token = auth.create_session(found, ip=ip,
                                                user_agent=self.headers.get('User-Agent'))
                    user_info = auth.sanitize_user(found)
                    needs_change = auth.must_change_password(found)
                    is_https = self.headers.get('X-Forwarded-Proto') == 'https'
                    audit.ensure_schema(conn)
                    audit.record(conn, 'auth', username, 'LOGIN', user=found,
                                 new_data={'role': found.get('role')}, ip_address=ip)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Set-Cookie', auth.build_session_cookie(
                        token, secure=is_https, max_age=auth.SESSION_IDLE_SECONDS))
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'message': 'Muvaffaqiyatli tizimga kirildi',
                        'user': user_info,
                        'permissions': permissions.permissions_for(found),
                        'pages': permissions.visible_pages(found),
                        'home': '/change-password.html' if needs_change else permissions.home_for(found),
                        'must_change_password': needs_change,
                    }, ensure_ascii=False).encode('utf-8'))
                    print(f"[auth] login ok: {username} ({found.get('role')})")
                else:
                    remaining = auth.note_login_failure(username, ip)
                    print(f"[auth] login failed for {audit_login!r} from {ip} "
                          f"({remaining} attempt(s) before lockout)")
                    audit.ensure_schema(conn)
                    audit.record(conn, 'auth', audit_login, 'LOGIN_FAILED',
                                 new_data={'attempts_remaining': remaining}, ip_address=ip)
                    self._set_json_headers(401)
                    # The message never distinguishes a wrong username from a
                    # wrong password, so the endpoint cannot be used to find
                    # out which accounts exist.
                    payload = {'error': "Login yoki parol noto'g'ri"}
                    if remaining <= 3:
                        payload['detail'] = (f"Yana {remaining} ta urinish qoldi, "
                                             f"so'ngra kirish vaqtincha bloklanadi.")
                    self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

            # 13b. POST /api/auth/logout — discard the session server-side.
            elif path == '/api/auth/logout':
                token = auth.token_from_cookie_header(self.headers.get('Cookie'))
                sess = auth.get_session(token)
                if sess:
                    audit.ensure_schema(conn)
                    audit.record(conn, 'auth', sess['user'].get('username', '-'),
                                 'LOGOUT', user=sess['user'], ip_address=self.client_ip())
                auth.destroy_session(token)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                # Expire the cookie in the browser too.
                self.send_header('Set-Cookie',
                                 f"{auth.SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
                self.end_headers()
                self.wfile.write(json.dumps({'message': 'Tizimdan chiqildi'}, ensure_ascii=False).encode('utf-8'))

            # 13c. POST /api/auth/change-password
            #
            # Reachable by any signed-in user for their own account, including
            # one still locked to the change-password screen. Changing the
            # password revokes that account's other sessions, so a password
            # handed out and then changed cannot still be in use elsewhere.
            elif path == '/api/auth/change-password':
                sess = self.current_session()
                if not sess:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Avtorizatsiya talab qilinadi'},
                                                ensure_ascii=False).encode('utf-8'))
                    return

                username = sess['user'].get('username')
                current = body.get('current_password') or ''
                new = body.get('new_password') or ''
                confirm = body.get('confirm_password')

                record = auth.find_user(username)
                if not record or not auth.verify_password(current, record.get('password')):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps(
                        {'error': "Hozirgi parol noto'g'ri"}, ensure_ascii=False).encode('utf-8'))
                    return
                if confirm is not None and new != confirm:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps(
                        {'error': 'Yangi parollar mos kelmadi'}, ensure_ascii=False).encode('utf-8'))
                    return
                if len(new) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps(
                        {'error': "Yangi parol kamida 8 belgidan iborat bo'lishi kerak"},
                        ensure_ascii=False).encode('utf-8'))
                    return
                if auth.verify_password(new, record.get('password')):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps(
                        {'error': "Yangi parol avvalgisidan farq qilishi kerak"},
                        ensure_ascii=False).encode('utf-8'))
                    return

                if not auth.set_password(username, new):
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps(
                        {'error': "Parolni saqlab bo'lmadi"}, ensure_ascii=False).encode('utf-8'))
                    return

                audit.ensure_schema(conn)
                audit.record(conn, 'users', username, 'PASSWORD_CHANGED',
                             user=sess['user'], ip_address=self.client_ip())

                # Revoke every session for this account, then issue a fresh one
                # so the person who just changed it stays signed in here.
                auth.destroy_sessions_for_user(username)
                refreshed = auth.find_user(username)
                token = auth.create_session(refreshed, ip=self.client_ip(),
                                            user_agent=self.headers.get('User-Agent'))
                is_https = self.headers.get('X-Forwarded-Proto') == 'https'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Set-Cookie', auth.build_session_cookie(
                    token, secure=is_https, max_age=auth.SESSION_IDLE_SECONDS))
                self.end_headers()
                self.wfile.write(json.dumps({
                    'message': "Parol muvaffaqiyatli o'zgartirildi",
                    'home': permissions.home_for(refreshed),
                }, ensure_ascii=False).encode('utf-8'))

            # 14. POST /api/users (Create / Register user)
            elif path == '/api/users':
                users_file = os.path.join(BASE_DIR, 'data', 'users.json')
                # A missing store is not an empty store. read_json_file
                # returns the default for an absent file, and this handler
                # then writes that default back plus the new account --
                # rebuilding the whole user list from one row and losing
                # every existing login, silently. The file has gone missing
                # once already on this project. Refuse instead: something is
                # wrong that creating a user will not fix.
                if not os.path.exists(users_file):
                    print(f'[!] user store missing at {users_file}; refusing to recreate it')
                    self._set_json_headers(503)
                    self.wfile.write(json.dumps({
                        'error': "Foydalanuvchilar bazasi topilmadi. Yangi hisob "
                                 "yaratilmadi - tizim administratoriga murojaat qiling."
                    }, ensure_ascii=False).encode('utf-8'))
                    return
                u_list = read_json_file(users_file, [])

                # Checks live in user_admin.build_new_user: only a role that
                # permissions.ROLES knows (an unknown one signed in with no
                # access at all), a real login and name, a password of at
                # least 8 characters when one is typed, a staff link that
                # exists, and an id that is not taken. The old id was built
                # from the user count and repeated after a deletion.
                new_u, _issued_password, _err = user_admin.build_new_user(
                    body, u_list, cur, (self.current_session() or {}).get('user'))
                if _err:
                    if len(_err) > 2:
                        # Superadmin-only grant (role, '*', admin write).
                        self._set_json_headers(_err[2])
                        self.wfile.write(json.dumps({'error': _err[0], 'field': _err[1]},
                                                    ensure_ascii=False).encode('utf-8'))
                        return
                    self._send_validation_error(_err[0], _err[1])
                    return
                u_list.append(new_u)
                write_json_atomic(users_file, u_list)

                self._set_json_headers(201)
                payload = {'message': "Foydalanuvchi muvaffaqiyatli ro'yxatdan o'tkazildi",
                           'id': new_u['id'],
                           'user': user_admin.sanitize(new_u)}
                # Shown once. The account cannot be used until its owner sets
                # their own password, so this is only for handing over. The
                # audit row is built from the request, never from this reply.
                if _issued_password:
                    payload['temporary_password'] = _issued_password
                    payload['note'] = ("Bu parol faqat bir marta ko'rsatiladi. "
                                       "Xodim birinchi kirishda uni almashtirishi shart.")
                self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

            # POST /api/users/<id>/reset-password
            #
            # A member of staff who forgot their password had no way back in
            # short of someone editing users.json. This issues a new one-time
            # password, shown once to the administrator, that must be changed
            # at the next sign-in; every open session of that account ends.
            elif path.startswith('/api/users/') and path.endswith('/reset-password'):
                uid = urllib.parse.unquote(path[len('/api/users/'):-len('/reset-password')])
                users_file = os.path.join(BASE_DIR, 'data', 'users.json')
                if not os.path.exists(users_file):
                    self._set_json_headers(503)
                    self.wfile.write(json.dumps({'error': "Foydalanuvchilar bazasi topilmadi."},
                                                ensure_ascii=False).encode('utf-8'))
                    return
                u_list = read_json_file(users_file, [])
                target = user_admin.find(u_list, uid)
                if not target:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Foydalanuvchi topilmadi'},
                                                ensure_ascii=False).encode('utf-8'))
                    return
                caller = (self.current_session() or {}).get('user')
                why = user_admin.protection_reason(target, caller, u_list, 'reset')
                if why:
                    self._set_json_headers(403)
                    self.wfile.write(json.dumps({'error': why, 'field': 'id'},
                                                ensure_ascii=False).encode('utf-8'))
                    return
                issued = auth.generate_temp_password()
                target['password'] = auth.hash_password(issued)
                target['must_change_password'] = True
                write_json_atomic(users_file, u_list)
                auth.destroy_sessions_for_user(target.get('username'))
                # A lockout from the forgotten-password attempts would
                # otherwise keep the new password from working for 15 minutes.
                auth.clear_user_lockout(target.get('username'))
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': "Yangi bir martalik parol berildi",
                    'id': target.get('id'),
                    'username': target.get('username'),
                    'temporary_password': issued,
                    'note': ("Bu parol faqat bir marta ko'rsatiladi. "
                             "Xodim kirgach uni almashtirishi shart."),
                }, ensure_ascii=False).encode('utf-8'))

            # 15. POST /api/facility/rooms (Create Room)
            elif path == '/api/facility/rooms':
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                floor_num = int(body.get('floor_number', 1))
                room_num = str(body.get('room_number', '15')).strip()
                room_id = f"ROOM-WARD-{room_num}"
                room_name = body.get('room_name_uz') or f"{room_num}-xona"
                room_type = body.get('room_type') or 'stationary'
                
                floor_obj = None
                for fl in r_data.get('floors', []):
                    if fl.get('floor_number') == floor_num:
                        floor_obj = fl
                        break
                if not floor_obj:
                    floor_obj = {
                        "floor_number": floor_num,
                        "name_uz": f"{floor_num}-Qavat",
                        "name_ru": f"{floor_num}-й Этаж",
                        "total_beds": 0,
                        "rooms": []
                    }
                    r_data['floors'].append(floor_obj)

                new_room = {
                    "id": room_id,
                    "floor": floor_num,
                    "room_number": room_num,
                    "name_uz": room_name,
                    "name_ru": f"{room_num}-палата",
                    "name_en": f"Room {room_num}",
                    "type": room_type,
                    "has_beds": True,
                    "beds": []
                }
                floor_obj['rooms'].append(new_room)
                r_data['facility_info']['total_inpatient_rooms'] = sum(1 for fl in r_data.get('floors', []) for r in fl.get('rooms', []) if r.get('has_beds'))

                write_json_atomic(rooms_file, r_data)

                try:
                    cur.execute("""
                        INSERT INTO rooms (id, floor_number, room_number, room_name_uz, room_type, total_capacity, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                        ON DUPLICATE KEY UPDATE room_name_uz = VALUES(room_name_uz), room_type = VALUES(room_type)
                    """, (room_id, floor_num, room_num, room_name, 'standard_ward' if room_type == 'stationary' else 'vip_ward', int(body.get('capacity', 2))))
                    conn.commit()
                except Exception as e_rm:
                    print("MySQL room sync error:", e_rm)

                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Xona muvaffaqiyatli qo\'shildi', 'room': new_room}, ensure_ascii=False).encode('utf-8'))

            # 16. POST /api/facility/beds (Attach bed to room)
            elif path == '/api/facility/beds':
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                target_room_id = body.get('room_id')
                bed_num = str(body.get('bed_number', '1A')).strip()
                bed_id = body.get('bed_id') or f"BED-{bed_num}"
                daily_rate = float(body.get('daily_rate', 720000))
                bed_type = body.get('bed_type', 'standard')

                attached = False
                for fl in r_data.get('floors', []):
                    for r in fl.get('rooms', []):
                        if r.get('id') == target_room_id or r.get('room_number') == target_room_id:
                            r['has_beds'] = True
                            if 'beds' not in r or not isinstance(r['beds'], list):
                                r['beds'] = []
                            new_bed = {
                                "bed_id": bed_id,
                                "floor": fl.get('floor_number', 1),
                                "room_id": r.get('id'),
                                "room_number": r.get('room_number'),
                                "bed_number": bed_num,
                                "full_label": f"{r.get('room_number')}-xona {bed_num} karavot",
                                "type": bed_type,
                                "status": "available",
                                "daily_rate": daily_rate,
                                "equipment": ["Smart TV", "IV shtativ", "EKG monitor"]
                            }
                            r['beds'].append(new_bed)
                            attached = True
                            break

                if attached:
                    total_beds = sum(len(r.get('beds', [])) for fl in r_data.get('floors', []) for r in fl.get('rooms', []))
                    r_data['facility_info']['total_inpatient_beds'] = total_beds
                    write_json_atomic(rooms_file, r_data)

                    try:
                        cur.execute("""
                            INSERT INTO beds (id, room_id, bed_code, bed_type, default_daily_rate, status)
                            VALUES (?, ?, ?, ?, ?, 'operational')
                            ON DUPLICATE KEY UPDATE default_daily_rate = VALUES(default_daily_rate), status = 'operational'
                        """, (bed_id, target_room_id, bed_id, bed_type, daily_rate))
                        conn.commit()
                    except Exception as e_bd:
                        print("MySQL bed sync error:", e_bd)

                    self._set_json_headers(201)
                    self.wfile.write(json.dumps({'message': f"{bed_id} karavot muvaffaqiyatli ulandi (Attached)", 'bed_id': bed_id}, ensure_ascii=False).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': f"'{target_room_id}' xonasi topilmadi"}, ensure_ascii=False).encode('utf-8'))

            else:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'POST Endpoint not found'}).encode('utf-8'))

        except Exception as e:
            # The detail goes to the server log, not to the browser: str(e) on
            # a database error carries table and column names, file paths and
            # sometimes the failing statement, which is a map of the system
            # for anyone who can provoke a 500.
            traceback.print_exc()
            self._send_server_error()
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

    # ------------------------------------------------------------------------
    # API PUT HANDLERS
    # ------------------------------------------------------------------------
    def handle_api_put(self, path, body):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()

            if path.startswith('/api/warehouse'):
                self._handle_warehouse('PUT', path, {}, body, conn)

            # PUT /api/doctor/prescriptions/<id>/status
            elif path.startswith('/api/doctor/prescriptions/') and path.endswith('/status'):
                rx_id = path.split('/')[4]
                new_status = body.get('status', 'completed')
                cur.execute("UPDATE prescriptions SET status = ? WHERE id = ?", (new_status, rx_id))
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Prescription status updated', 'status': new_status}).encode('utf-8'))

            # PUT /api/reception/appointment/<id>/cancel
            #
            # Cancelling only changed the desk's own screen; the row stayed
            # 'confirmed'. Once the server began refusing a second booking of
            # the same doctor, date and time, a cancelled slot looked free on
            # the grid but could never be booked again.
            elif path.startswith('/api/reception/appointment/') and path.endswith('/cancel'):
                parts = [p for p in path.split('/') if p]
                if len(parts) != 5:
                    self._send_validation_error("Noma'lum amal.", 'id')
                    return
                apt_id = urllib.parse.unquote(parts[3])
                cur.execute("SELECT id, status FROM appointments WHERE id = ?", (apt_id,))
                row = cur.fetchone()
                if not row:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Yozuv topilmadi.'}, ensure_ascii=False).encode('utf-8'))
                    return
                if row['status'] in ('completed', 'cancelled'):
                    self._send_validation_error(
                        f"Bu yozuvni bekor qilib bo'lmaydi (holati: {row['status']}).", 'status')
                    return
                cur.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (apt_id,))
                # A visit recorded at the desk is billed when it is recorded.
                # Cancelled before anyone paid, the bill goes with it, or the
                # patient would owe for a visit that never happened. Once
                # money was taken the bill stays: giving it back is a refund
                # the cash desk records, not something to erase here.
                _msg = 'Yozuv bekor qilindi'
                cur.execute("SELECT id FROM invoices WHERE appointment_id = ?", (apt_id,))
                _inv = cur.fetchone()
                if _inv:
                    cur.execute("SELECT COUNT(*) AS n FROM payments WHERE invoice_id = ?", (_inv['id'],))
                    if int(cur.fetchone()['n'] or 0) == 0:
                        # Only the visit's own fee line goes: it is the first
                        # line, written with the invoice when the visit was
                        # booked. Deleting every line also erased medicines
                        # and services added later in Accounting, whose stock
                        # had already left the shelf -- the bill and the
                        # stock count then disagreed with nothing to show why.
                        cur.execute("SELECT id FROM invoice_items WHERE invoice_id = ? ORDER BY id LIMIT 1",
                                    (_inv['id'],))
                        _fee = cur.fetchone()
                        if _fee:
                            cur.execute("DELETE FROM invoice_items WHERE id = ?", (_fee['id'],))
                        cur.execute("SELECT COUNT(*) AS n FROM invoice_items WHERE invoice_id = ?", (_inv['id'],))
                        if int(cur.fetchone()['n'] or 0) == 0:
                            cur.execute("DELETE FROM invoices WHERE id = ?", (_inv['id'],))
                        else:
                            _msg = ("Yozuv bekor qilindi. Tashrif haqi hisobdan olib tashlandi; "
                                    "hisobga keyin qo'shilgan dori va xizmatlar qoldi — ularni "
                                    "buxgalteriya ko'rib chiqadi.")
                    else:
                        _msg = ("Yozuv bekor qilindi. Bu tashrif uchun to'lov olingan — "
                                "pulni qaytarish buxgalteriyada rasmiylashtiriladi.")
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': _msg, 'id': apt_id, 'status': 'cancelled'}, ensure_ascii=False).encode('utf-8'))

            # PUT /api/crm/patients/<id> -- the CRM edit form.
            #
            # There was no such route: the CRM sent its edits here, got a 404,
            # ignored it and said "saved". An allergy recorded in the CRM
            # therefore never reached the record the doctor's warning reads.
            # Only the fields the request carries change.
            elif path.startswith('/api/crm/patients/') or path.startswith('/api/patients/'):
                pid = urllib.parse.unquote(path.rstrip('/').rsplit('/', 1)[-1])
                cur.execute("SELECT id FROM patients WHERE id = ? OR patient_code = ?", (pid, pid))
                row = cur.fetchone()
                if not row:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Bemor topilmadi.'}, ensure_ascii=False).encode('utf-8'))
                    return
                patient_id = row['id'] if isinstance(row, dict) or hasattr(row, 'keys') else row[0]
                if 'full_name' in body and not str(body.get('full_name') or '').strip():
                    self._send_validation_error("Bemorning ismi kiritilmagan.", 'full_name')
                    return
                bdate, byear, gender, _err = parse_birth_and_gender(body)
                if _err:
                    self._send_validation_error(_err[0], _err[1])
                    return
                sets, params = [], []
                # Blank text clears to unknown (NULL); an absent key is left alone.
                for col in ('full_name', 'phone', 'emergency_contact', 'address',
                            'referral_source', 'medical_allergies', 'chronic_conditions'):
                    if col in body:
                        val = body.get(col)
                        sets.append(f"{col} = ?")
                        params.append(None if val is None else (str(val).strip() or None))
                for col, val in (('gender', gender), ('birth_date', bdate), ('birth_year', byear)):
                    if val is not None:
                        sets.append(f"{col} = ?")
                        params.append(val)
                if sets:
                    cur.execute(f"UPDATE patients SET {', '.join(sets)} WHERE id = ?",
                                tuple(params) + (patient_id,))
                    conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Patient updated', 'id': patient_id}, ensure_ascii=False).encode('utf-8'))

            # PUT /api/admissions/<id>/discharge
            elif '/discharge' in path:
                adm_id = body.get('admission_id') or (path.split('/')[3] if len(path.split('/')) > 3 else None)
                today_str = datetime.date.today().isoformat()
                discharge_date = (body.get('discharge_date') or body.get('actual_end_date') or today_str)[:10]
                summary = body.get('discharge_summary') or body.get('summary') or "Statsionardan chiqarildi"

                success, res_data = discharge_patient(conn, adm_id, discharge_date, summary)
                if not success:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': str(res_data)}, ensure_ascii=False).encode('utf-8'))
                    return

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Bemor muvaffaqiyatli chiqarildi va karavot tozalash holatiga (cleaning) o\'tkazildi',
                    'result': res_data
                }, ensure_ascii=False).encode('utf-8'))

            # PUT /api/admissions/<id>/transfer
            elif '/transfer' in path:
                adm_id = body.get('admission_id') or (path.split('/')[3] if len(path.split('/')) > 3 else None)
                new_bed_id = str(body.get('new_bed_id') or '').strip()
                raw_transfer_date = body.get('transfer_date')
                transfer_date = (str(raw_transfer_date).strip() if raw_transfer_date
                                 else datetime.date.today().isoformat())[:10]
                reason = str(body.get('reason') or '').strip()[:1000] or "Palata ko'chirildi"
                staff_id = self._actor_staff_id(body)

                if not adm_id:
                    self._send_validation_error("Yotqizish (admission) ko'rsatilmagan.", 'admission_id')
                    return
                if not new_bed_id:
                    self._send_validation_error("Yangi karavotni tanlang.", 'new_bed_id')
                    return
                # Optional: a new daily price from the move date. Left empty,
                # the stay keeps its agreed price (PO, 2026-10-08).
                new_daily_price = None
                if body.get('new_daily_price') not in (None, ''):
                    new_daily_price, _perr = validate_amount(body.get('new_daily_price'), field='Kunlik narx')
                    if _perr:
                        self._send_validation_error(_perr, 'new_daily_price')
                        return

                # transfer_patient_bed returns (False, message) only for
                # refusals written for staff in Uzbek. Unexpected failures are
                # re-raised and reach the generic 500 handler of this method,
                # which logs the traceback; str(e) used to be sent to the
                # browser here, database internals included.
                success, res_data = transfer_patient_bed(conn, adm_id, new_bed_id, transfer_date, reason, staff_id,
                                                         new_daily_price=new_daily_price)
                if not success:
                    self._send_validation_error(str(res_data))
                    return

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Bemor yangi karavotga ko\'chirildi, avvalgi karavot tozalashga yuborildi',
                    'result': res_data
                }, ensure_ascii=False).encode('utf-8'))

            # PUT /api/beds/<id>/status or /clean
            elif path.startswith('/api/beds/') and (path.endswith('/status') or path.endswith('/clean')):
                bed_id = path.split('/')[3]
                # The beds.status column accepts only the physical states in its
                # CHECK constraint: operational, cleaning, maintenance,
                # out_of_service. 'available', 'occupied' and 'reserved' are
                # values the v_bed_live_status view DERIVES from admissions, not
                # things that can be stored. This route used to map the other way
                # round -- rewriting 'operational' to 'available' -- so every
                # request violated beds_chk_3 and failed with a 500. Discharge and
                # transfer both leave a bed 'cleaning', so the action that returns
                # it to service never worked and beds accumulated as unusable.
                PHYSICAL = {'operational', 'cleaning', 'maintenance', 'out_of_service'}
                DERIVED_TO_PHYSICAL = {'available': 'operational',
                                       'occupied': 'operational',
                                       'reserved': 'operational'}
                requested = 'operational' if path.endswith('/clean') else str(body.get('status', 'operational')).strip().lower()
                new_status = DERIVED_TO_PHYSICAL.get(requested, requested)
                if new_status not in PHYSICAL:
                    new_status = 'operational'

                cur.execute("UPDATE beds SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? OR bed_code = ?", (new_status, bed_id, bed_id))
                conn.commit()

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': f"Karavot holati muvaffaqiyatli saqlandi: {new_status}",
                    'bed_id': bed_id,
                    'status': new_status
                }, ensure_ascii=False).encode('utf-8'))
            elif path.startswith('/api/facility/beds/'):
                bed_id = urllib.parse.unquote(path.replace('/api/facility/beds/', ''))
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                updated = False
                for fl in r_data.get('floors', []):
                    for r in fl.get('rooms', []):
                        for b in r.get('beds', []):
                            if b.get('bed_id') == bed_id:
                                if 'daily_rate' in body:
                                    b['daily_rate'] = float(body['daily_rate'])
                                if 'type' in body:
                                    b['type'] = body['type']
                                if 'status' in body:
                                    b['status'] = body['status']
                                updated = True

                if updated:
                    write_json_atomic(rooms_file, r_data)
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({'message': f"{bed_id} karavot yangilandi"}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': f"'{bed_id}' karavot topilmadi"}).encode('utf-8'))

            # PUT /api/users/<id>: edit name, phone, role, staff link, block.
            #
            # This took any role name, set a typed password with no rotation,
            # stored any 'permissions' value, and would block or demote the
            # superadmin or the caller's own account. user_admin.apply_update
            # holds the checks. A change to what the account may do ends its
            # open sessions, which carry a copy of the record made at sign-in:
            # a blocked employee otherwise kept working until the 12 h timeout.
            elif path.startswith('/api/users/'):
                uid = urllib.parse.unquote(path.replace('/api/users/', ''))
                users_file = os.path.join(BASE_DIR, 'data', 'users.json')
                if not os.path.exists(users_file):
                    self._set_json_headers(503)
                    self.wfile.write(json.dumps({'error': "Foydalanuvchilar bazasi topilmadi."},
                                                ensure_ascii=False).encode('utf-8'))
                    return
                u_list = read_json_file(users_file, [])
                found = user_admin.find(u_list, uid)
                if not found:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Foydalanuvchi topilmadi'},
                                                ensure_ascii=False).encode('utf-8'))
                    return
                caller = (self.current_session() or {}).get('user')
                security, _err = user_admin.apply_update(found, body, caller, u_list, cur)
                if _err:
                    _msg, _field, _status = _err
                    if _status == 400:
                        self._send_validation_error(_msg, _field)
                    else:
                        self._set_json_headers(_status)
                        self.wfile.write(json.dumps({'error': _msg, 'field': _field},
                                                    ensure_ascii=False).encode('utf-8'))
                    return
                write_json_atomic(users_file, u_list)
                if security:
                    auth.destroy_sessions_for_user(found.get('username'))
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': "Foydalanuvchi ma'lumotlari yangilandi",
                    'id': found.get('id'),
                    'user': user_admin.sanitize(found, caller, u_list),
                }, ensure_ascii=False).encode('utf-8'))

            else:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Endpoint not found'}).encode('utf-8'))

        except Exception as e:
            # The detail goes to the server log, not to the browser: str(e) on
            # a database error carries table and column names, file paths and
            # sometimes the failing statement, which is a map of the system
            # for anyone who can provoke a 500.
            traceback.print_exc()
            self._send_server_error()
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

    # ------------------------------------------------------------------------
    # API DELETE HANDLERS
    # ------------------------------------------------------------------------
    def handle_api_delete(self, path):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()

            if path.startswith('/api/doctor/prescriptions/'):
                rx_id = path.replace('/api/doctor/prescriptions/', '')
                cur.execute("DELETE FROM prescriptions WHERE id = ?", (rx_id,))
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Prescription deleted'}).encode('utf-8'))

            elif path.startswith('/api/patients/') or path.startswith('/api/crm/patients/'):
                pid = urllib.parse.unquote(path.replace('/api/patients/', '').replace('/api/crm/patients/', ''))
                cur.execute("PRAGMA foreign_keys = OFF;")
                # Never match on full_name: names are not unique, and the bed
                # board once sent a name here, wiping every namesake's records.
                cur.execute("SELECT id, full_name, patient_code FROM patients WHERE id = ? OR patient_code = ?", (pid, pid))
                p_rows = cur.fetchall()
                target_ids = [r[0] for r in p_rows] if p_rows else [pid]

                for tid in target_ids:
                    # Same two traps as the admission delete: cascades do not
                    # fire while FOREIGN_KEY_CHECKS is off, and a subquery on
                    # `invoices` collides with the triggers that write to it.
                    # Visit invoices (consultation, outpatient) hang off the
                    # patient's appointments rather than a stay.
                    cur.execute("SELECT id FROM invoices WHERE admission_id IN (SELECT id FROM admissions WHERE patient_id = ?) "
                                "OR appointment_id IN (SELECT id FROM appointments WHERE patient_id = ?)", (tid, tid))
                    _inv_ids = [r['id'] for r in cur.fetchall()]
                    if _inv_ids:
                        _marks = ','.join(['?'] * len(_inv_ids))
                        cur.execute(f"DELETE FROM payments WHERE invoice_id IN ({_marks})", tuple(_inv_ids))
                        cur.execute(f"DELETE FROM invoice_items WHERE invoice_id IN ({_marks})", tuple(_inv_ids))
                        cur.execute(f"DELETE FROM invoices WHERE id IN ({_marks})", tuple(_inv_ids))
                    cur.execute("DELETE FROM medication_administrations WHERE patient_id = ?", (tid,))
                    # These key on the stay, not the patient, and with
                    # FOREIGN_KEY_CHECKS off nothing cascades: a later stay
                    # given the same id would inherit the deleted patient's
                    # logs and bed moves. Same as the single-stay delete.
                    cur.execute("SELECT id FROM admissions WHERE patient_id = ?", (tid,))
                    _adm_ids = [r['id'] for r in cur.fetchall()]
                    if _adm_ids:
                        _am = ','.join(['?'] * len(_adm_ids))
                        cur.execute(f"DELETE FROM daily_logs WHERE admission_id IN ({_am})", tuple(_adm_ids))
                        cur.execute(f"DELETE FROM bed_transfers WHERE admission_id IN ({_am})", tuple(_adm_ids))
                    # 'operational', not 'available': the latter is a value the
                    # v_bed_live_status view derives, and beds.status rejects it.
                    cur.execute("UPDATE beds SET status = 'operational' WHERE id IN (SELECT bed_id FROM admissions WHERE patient_id = ?)", (tid,))
                    cur.execute("DELETE FROM admissions WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM medical_histories WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM prescriptions WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM doctor_daily_notes WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM discharge_epicrises WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM appointments WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM patients WHERE id = ?", (tid,))

                cur.execute("PRAGMA foreign_keys = ON;")
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Patient and all linked clinical & billing records deleted'}).encode('utf-8'))

            elif path.startswith('/api/admissions/'):
                adm_id = urllib.parse.unquote(path.replace('/api/admissions/', ''))
                cur.execute("PRAGMA foreign_keys = OFF;")
                # 'operational', not 'available' -- see above.
                cur.execute("UPDATE beds SET status = 'operational' WHERE id IN (SELECT bed_id FROM admissions WHERE id = ?)", (adm_id,))
                # Children of the invoice are removed explicitly, and by literal
                # id rather than through a subquery on `invoices`.
                #
                # Two traps sit here. Their foreign keys are ON DELETE CASCADE,
                # but FOREIGN_KEY_CHECKS is disabled just above (a PRAGMA carried
                # over from the SQLite era) and MySQL skips cascades while checks
                # are off, so the rows were orphaned. And because an invoice id is
                # derived from its admission id, a later admission that reused the
                # id inherited those lines and billed a new patient for the
                # previous one's stay.
                #
                # The id list also cannot come from a subquery: triggers on
                # payments and invoice_items update `invoices`, and MySQL refuses
                # (error 1442) to let a trigger write to a table the invoking
                # statement already names.
                cur.execute("SELECT id FROM invoices WHERE admission_id = ?", (adm_id,))
                _inv_ids = [r['id'] for r in cur.fetchall()]
                if _inv_ids:
                    _marks = ','.join(['?'] * len(_inv_ids))
                    cur.execute(f"DELETE FROM payments WHERE invoice_id IN ({_marks})", tuple(_inv_ids))
                    cur.execute(f"DELETE FROM invoice_items WHERE invoice_id IN ({_marks})", tuple(_inv_ids))
                    cur.execute(f"DELETE FROM invoices WHERE id IN ({_marks})", tuple(_inv_ids))
                cur.execute("DELETE FROM medication_administrations WHERE admission_id = ?", (adm_id,))
                cur.execute("DELETE FROM prescriptions WHERE admission_id = ?", (adm_id,))
                cur.execute("DELETE FROM daily_logs WHERE admission_id = ?", (adm_id,))
                cur.execute("DELETE FROM bed_transfers WHERE admission_id = ?", (adm_id,))
                cur.execute("DELETE FROM admissions WHERE id = ?", (adm_id,))
                cur.execute("PRAGMA foreign_keys = ON;")
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Admission and linked records deleted'}).encode('utf-8'))

            elif path.startswith('/api/staff/') or path.startswith('/api/hr/staff/'):
                stf_id = urllib.parse.unquote(path.replace('/api/staff/', '').replace('/api/hr/staff/', ''))
                cur.execute("UPDATE staff SET is_active = 0 WHERE id = ?", (stf_id,))
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Staff member deactivated'}).encode('utf-8'))

            elif path.startswith('/api/facility/beds/'):
                bid = urllib.parse.unquote(path.replace('/api/facility/beds/', ''))
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                detached = False
                for fl in r_data.get('floors', []):
                    for r in fl.get('rooms', []):
                        if 'beds' in r and isinstance(r['beds'], list):
                            orig_len = len(r['beds'])
                            r['beds'] = [b for b in r['beds'] if b.get('bed_id') != bid]
                            if len(r['beds']) < orig_len:
                                detached = True

                if detached:
                    total_beds = sum(len(r.get('beds', [])) for fl in r_data.get('floors', []) for r in fl.get('rooms', []))
                    r_data['facility_info']['total_inpatient_beds'] = total_beds
                    write_json_atomic(rooms_file, r_data)

                    try:
                        cur.execute("DELETE FROM beds WHERE id = ? OR bed_code = ?", (bid, bid))
                        conn.commit()
                    except Exception as e_dbd:
                        print("MySQL bed delete warning:", e_dbd)

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({'message': f"{bid} karavot muvaffaqiyatli ajratildi (Detached)"}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': f"'{bid}' karavot topilmadi"}).encode('utf-8'))

            elif path.startswith('/api/facility/rooms/'):
                rid = urllib.parse.unquote(path.replace('/api/facility/rooms/', ''))
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                removed = False
                for fl in r_data.get('floors', []):
                    orig_len = len(fl.get('rooms', []))
                    fl['rooms'] = [r for r in fl.get('rooms', []) if r.get('id') != rid and r.get('room_number') != rid]
                    if len(fl['rooms']) < orig_len:
                        removed = True

                if removed:
                    total_beds = sum(len(r.get('beds', [])) for fl in r_data.get('floors', []) for r in fl.get('rooms', []))
                    r_data['facility_info']['total_inpatient_beds'] = total_beds
                    r_data['facility_info']['total_inpatient_rooms'] = sum(1 for fl in r_data.get('floors', []) for r in fl.get('rooms', []) if r.get('has_beds'))
                    write_json_atomic(rooms_file, r_data)

                    try:
                        cur.execute("DELETE FROM rooms WHERE id = ? OR room_number = ?", (rid, rid))
                        conn.commit()
                    except Exception as e_drm:
                        print("MySQL room delete warning:", e_drm)

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({'message': f"Xona muvaffaqiyatli o'chirildi"}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': f"'{rid}' xonasi topilmadi"}).encode('utf-8'))

            # DELETE /api/users/<id>
            #
            # Removed every account whose id OR username matched -- ids built
            # from the user count repeated, so one delete could take two
            # people -- answered 200 for an account that did not exist, and
            # would delete the superadmin or the caller's own login.
            elif path.startswith('/api/users/'):
                uid = urllib.parse.unquote(path.replace('/api/users/', ''))
                users_file = os.path.join(BASE_DIR, 'data', 'users.json')
                if not os.path.exists(users_file):
                    self._set_json_headers(503)
                    self.wfile.write(json.dumps({'error': "Foydalanuvchilar bazasi topilmadi."},
                                                ensure_ascii=False).encode('utf-8'))
                    return
                u_list = read_json_file(users_file, [])
                target = user_admin.find(u_list, uid)
                if not target:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Foydalanuvchi topilmadi'},
                                                ensure_ascii=False).encode('utf-8'))
                    return
                caller = (self.current_session() or {}).get('user')
                why = user_admin.protection_reason(target, caller, u_list, 'delete')
                if why:
                    self._set_json_headers(403)
                    self.wfile.write(json.dumps({'error': why, 'field': 'id'},
                                                ensure_ascii=False).encode('utf-8'))
                    return
                u_list = [u for u in u_list if u is not target]
                write_json_atomic(users_file, u_list)
                auth.destroy_sessions_for_user(target.get('username'))
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': "Foydalanuvchi muvaffaqiyatli o'chirildi",
                                             'id': target.get('id')},
                                            ensure_ascii=False).encode('utf-8'))

            elif path.startswith('/api/accounting/medication-purchases/'):
                pur_id = urllib.parse.unquote(path.replace('/api/accounting/medication-purchases/', ''))
                cur.execute("SELECT * FROM medication_purchases WHERE id = ?", (pur_id,))
                pur = cur.fetchone()
                if not pur:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Xarid yozuvi topilmadi'}).encode('utf-8'))
                    return

                # Deduct stock in catalog
                if pur.get('medication_id'):
                    cur.execute("""
                        UPDATE medications_catalog
                        SET stock_quantity = GREATEST(0, stock_quantity - ?)
                        WHERE id = ?
                    """, (int(pur['quantity']), pur['medication_id']))

                # Clean up or adjust accounting transaction
                trx_id = pur.get('accounting_transaction_id')
                if trx_id:
                    cur.execute("SELECT COUNT(*) AS c FROM medication_purchases WHERE accounting_transaction_id = ? AND id != ?", (trx_id, pur_id))
                    row_c = cur.fetchone()
                    other_count = (row_c['c'] if isinstance(row_c, dict) or hasattr(row_c, 'keys') else row_c[0])
                    if other_count == 0:
                        cur.execute("DELETE FROM accounting_transactions WHERE id = ?", (trx_id,))
                    else:
                        cur.execute("UPDATE accounting_transactions SET amount = GREATEST(0.01, amount - ?) WHERE id = ?", (float(pur['total_price']), trx_id))

                cur.execute("DELETE FROM medication_purchases WHERE id = ?", (pur_id,))
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Dori xaridi bekor qilindi va ombor qayta hisoblandi'}).encode('utf-8'))

            else:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Delete endpoint not found'}).encode('utf-8'))

        except Exception as e:
            # The detail goes to the server log, not to the browser: str(e) on
            # a database error carries table and column names, file paths and
            # sometimes the failing statement, which is a map of the system
            # for anyone who can provoke a 500.
            traceback.print_exc()
            self._send_server_error()
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

def run_server():
    cfg = load_config()

    # Upgrade any plaintext password still sitting in data/users.json. Logins
    # keep working across the change because verification accepts both forms.
    auth.migrate_plaintext_passwords()

    # Startup migrations and clean-ups. Each step has its own try: they used
    # to share one, so a single failure (say the audit scrub) silently
    # skipped every step after it -- user_sessions was never created and
    # sign-ins stopped surviving restarts with nothing in the log saying why.
    def _scrub_secrets(c):
        # The user console's create request carried the typed password and
        # the write hook stored the request as-is. New rows are masked in
        # audit.record; this masks the ones written before.
        n = audit.scrub_secrets(c)
        if n:
            print(f'[✓] Masked passwords in {n} old audit row(s).')

    def _scrub_unknown_logins(c):
        # Failed sign-ins for logins that are not accounts (often a
        # password typed in the login box) are masked; see the login route.
        try:
            names = [u.get('username') for u in auth.load_users()]
        except Exception as e:
            print(f'[!] users.json unreadable; failed-login rows left as they are: {e}')
            return
        n = audit.scrub_unknown_logins(c, names)
        if n:
            print(f'[✓] Masked the typed login in {n} failed sign-in row(s).')

    def _sessions(c):
        # Sign-ins are kept in MySQL so a restart does not sign the whole
        # clinic out; drop the ones that went idle meanwhile.
        ensure_user_sessions(c)
        auth.prune_expired_sessions()

    _steps = (
        # Widen audit_logs.action_type so sign-ins and refusals can be recorded.
        ('audit_logs schema', audit.ensure_schema),
        # Index the trail by time: without it a retention sweep, or any
        # question about a date range, reads every row.
        ('audit_logs index', audit.ensure_index),
        ('audit password scrub', _scrub_secrets),
        ('audit failed-login scrub', _scrub_unknown_logins),
        # Adds patients.birth_date to a database made before it existed.
        ('patients columns', ensure_patient_columns),
        # One ward-round note per stay per day.
        ('ward round schema', ensure_ward_round_schema),
        # Where the public website's enquiries land.
        ('appointment requests', ensure_appointment_requests),
        # Table for clinic medication purchases and restock expenses.
        ('medication purchases', ensure_medication_purchases),
        # The medical warehouse: lots, ledger, receipts, alerts (inventory.py).
        # Also brings the low-stock and expiry alerts up to date after a restart.
        ('warehouse schema', inventory.ensure_schema),
        # Older databases refuse 'consultation' appointments.
        ('appointment service types', ensure_appointment_service_types),
        # Sanitarkas need staff rows to be paid for duty shifts.
        ('staff roles', ensure_staff_roles),
        # HR form fields (hire date, category, ...) and attendance lateness
        # had no columns and were lost on reload.
        ('staff HR columns', ensure_staff_hr_columns),
        ('roster sanitarkas', ensure_roster_sanitarkas),
        # Desk visits (consultation, outpatient course) get invoices.
        ('invoice visit link', ensure_invoice_visit_link),
        # The month a salary payout pays for (one payout per month).
        ('salary payroll month', ensure_transaction_payroll_month),
        ('user sessions', _sessions),
    )
    _c = None
    try:
        _c = get_db()
    except Exception as _e:
        print(f'[!] Startup migrations skipped: database unreachable ({_e})')
    if _c is not None:
        try:
            for _label, _step in _steps:
                try:
                    _step(_c)
                except Exception as _e:
                    print(f'[!] Startup step "{_label}" failed: {_e}')
                    try:
                        _c.rollback()
                    except Exception:
                        pass
        finally:
            try:
                _c.close()
            except Exception:
                pass

    # Listen on loopback only by default.
    #
    # This used to bind "" (every interface) and additionally try to seize port
    # 80, which exposed the EMR to every machine on the network — and, where the
    # documented Nginx vhost is in use, to the public internet. That contradicts
    # the project's own deployment guide, which proxies to 127.0.0.1:3000, so
    # the server never needed a public socket of its own; port 80 belongs to
    # Nginx in that setup.
    #
    # Set BIND_HOST to override (BIND_HOST=0.0.0.0 restores the old behaviour)
    # and BIND_PORT_80=1 to additionally serve port 80 directly. Do neither
    # without a reverse proxy, TLS and the authentication below in front.
    bind_host = os.environ.get('BIND_HOST', '127.0.0.1')
    print(f"🏥 FAYZ CONTROL — Enterprise Pure MySQL 8.0 Server running at http://{bind_host}:{PORT}")
    print(f"   Connected Engine: MySQL 8.0 ({cfg.get('user')}@{cfg.get('host')}:{cfg.get('port')}/{cfg.get('database')})")
    if bind_host not in ('127.0.0.1', 'localhost', '::1'):
        print(f"   [!] WARNING: bound to {bind_host} — reachable beyond this machine.")
        print( "       Ensure a reverse proxy and TLS are in front of it.")
    http.server.ThreadingHTTPServer.allow_reuse_address = True

    if PORT != 80 and os.environ.get('BIND_PORT_80') == '1':
        try:
            httpd_80 = http.server.ThreadingHTTPServer((bind_host, 80), ClinicRequestHandler)
            t = threading.Thread(target=httpd_80.serve_forever, daemon=True)
            t.start()
            print(f"🌐 Port 80 also bound on {bind_host} (BIND_PORT_80=1).")
        except Exception as e:
            print(f"[i] Port 80 not bound ({e}), running on port {PORT}.")

    if telegram_service:
        try:
            telegram_service.start_transaction_watchdog()
            telegram_service.start_daily_closing_scheduler()
            print("🤖 Telegram 21:00 Kassa Scheduleri va Tranzaksiya Watchdog faollashtirildi.")
        except Exception as _e_sched:
            print(f"[!] Telegram scheduler ishga tushmadi: {_e_sched}")

    while True:
        # A port that is already taken (an old server still running) must stop
        # this process: retrying it forever kept the old code serving while
        # systemd reported the new one as up.
        try:
            httpd_main = http.server.ThreadingHTTPServer((bind_host, PORT), ClinicRequestHandler)
        except OSError as e:
            print(f"[!] Port {PORT} band qilinmadi: {e}")
            sys.exit(1)
        try:
            with httpd_main as httpd:
                try:
                    httpd.serve_forever()
                except KeyboardInterrupt:
                    print("\nStopping server...")
                    break
                except Exception as e:
                    traceback.print_exc()
                    time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception as e:
            traceback.print_exc()
            time.sleep(1)

if __name__ == '__main__':
    run_server()
