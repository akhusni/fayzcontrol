"""
Fayz Medical House / Fayz Control — Unified Enterprise MySQL 8.0 Engine
Native MySQL 8.0 connection with transparent parameter translation (? to %s) and dual-access DictRows.
"""

import os
import sys
import json
import re
import traceback
import decimal as _dec
import datetime as _dt


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'db_config.json')

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Try importing pymysql
try:
    import pymysql
    import pymysql.cursors
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False

# Default Configuration (Pure MySQL 8.0)
#
# This used to carry the production server's host AND its password, which meant
# a machine with no db_config.json — or one where the file was deleted, renamed
# or failed to parse — silently connected to live patient data instead of
# failing. The default is now a local database with no password, so a missing
# config can only ever reach localhost. Real credentials belong in
# db_config.json (gitignored; see db_config.example.json) or in the
# DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME environment variables.
DEFAULT_CONFIG = {
    "db_type": "mysql",
    "host": "127.0.0.1",
    "port": 3306,
    "user": "fayzhouse",
    "password": "",
    "database": "fayzhouse"
}

def load_config():
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            print(f"[!] Warning reading db_config.json: {e}")
    
    # Environment variables override config
    if os.environ.get('DB_TYPE'):
        config['db_type'] = os.environ.get('DB_TYPE')
    if os.environ.get('DB_HOST'):
        config['host'] = os.environ.get('DB_HOST')
    if os.environ.get('DB_USER'):
        config['user'] = os.environ.get('DB_USER')
    if os.environ.get('DB_PASSWORD'):
        config['password'] = os.environ.get('DB_PASSWORD')
    if os.environ.get('DB_NAME'):
        config['database'] = os.environ.get('DB_NAME')
    if os.environ.get('DB_PORT'):
        try: config['port'] = int(os.environ.get('DB_PORT'))
        except ValueError: pass

    return config

def save_config(config):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"[!] Error saving db_config.json: {e}")

def normalize_db_val(v):
    if isinstance(v, _dec.Decimal):
        return float(v)
    if isinstance(v, _dt.datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, _dt.date):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, _dt.time):
        return v.strftime('%H:%M:%S')
    if isinstance(v, _dt.timedelta):
        return str(v)
    return v


class DictRow(dict):
    """
    Dual-access dictionary row compatible with both dict['col'] and tuple row[0].
    Normalizes MySQL types (Decimal, date, datetime) to standard Python primitives
    so application code and JSON serializers experience seamless execution.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in list(self.items()):
            self[k] = normalize_db_val(v)
        self._vals = list(self.values())

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._vals[item]
        return super().__getitem__(item)

    def get(self, key, default=None):
        return super().get(key, default)

class MySQLCursorWrapper:
    def __init__(self, cursor):
        self._cur = cursor

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def _convert_sql(self, sql):
        converted_sql = sql.replace('?', '%s')
        # Transparent function translation for standard datetime and inserts
        converted_sql = re.sub(r"\bDATE\(\s*['\"]now['\"]\s*(?:,\s*['\"][^'\"]+['\"]\s*)?\)", 'CURDATE()', converted_sql, flags=re.IGNORECASE)
        converted_sql = re.sub(r"\bDATETIME\(\s*['\"]now['\"]\s*(?:,\s*['\"][^'\"]+['\"]\s*)?\)", 'NOW()', converted_sql, flags=re.IGNORECASE)
        converted_sql = re.sub(r'\bINSERT\s+OR\s+IGNORE\b', 'INSERT IGNORE', converted_sql, flags=re.IGNORECASE)
        converted_sql = re.sub(r'\bINSERT\s+OR\s+REPLACE\b', 'REPLACE', converted_sql, flags=re.IGNORECASE)
        if 'ON CONFLICT' in converted_sql.upper():
            converted_sql = re.sub(r'ON\s+CONFLICT\s*\([^\)]+\)\s+DO\s+UPDATE\s+SET', 'ON DUPLICATE KEY UPDATE', converted_sql, flags=re.IGNORECASE)
            converted_sql = re.sub(r'\bexcluded\.([a-zA-Z0-9_]+)', r'VALUES(\1)', converted_sql, flags=re.IGNORECASE)
        if re.search(r'PRAGMA\s+foreign_keys\s*=\s*OFF', converted_sql, re.IGNORECASE):
            return "SET FOREIGN_KEY_CHECKS = 0"
        if re.search(r'PRAGMA\s+foreign_keys\s*=\s*ON', converted_sql, re.IGNORECASE):
            return "SET FOREIGN_KEY_CHECKS = 1"
        return converted_sql


    def execute(self, sql, params=None):
        converted_sql = self._convert_sql(sql)
        if params is not None:
            if isinstance(params, (list, tuple)):
                return self._cur.execute(converted_sql, params)
            elif isinstance(params, dict):
                return self._cur.execute(converted_sql, params)
            else:
                return self._cur.execute(converted_sql, (params,))
        return self._cur.execute(converted_sql)

    def executemany(self, sql, seq_of_params):
        converted_sql = self._convert_sql(sql)
        return self._cur.executemany(converted_sql, seq_of_params)

    def fetchone(self):
        r = self._cur.fetchone()
        return DictRow(r) if r is not None else None

    def fetchall(self):
        rows = self._cur.fetchall()
        return [DictRow(r) for r in rows]

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size)
        return [DictRow(r) for r in rows]

    def close(self):
        self._cur.close()

class MySQLConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return MySQLCursorWrapper(self._conn.cursor(pymysql.cursors.DictCursor))

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def executescript(self, sql_script):
        # Execute multiple statements
        cur = self._conn.cursor()
        statements = sql_script.split(';')
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    print(f"[!] Warning in executescript: {e}")
        self._conn.commit()
        cur.close()

def get_mysql_connection(config):
    if not HAS_PYMYSQL:
        raise ImportError("pymysql is not installed.")
    conn = pymysql.connect(
        host=config.get('host', '127.0.0.1'),
        port=int(config.get('port', 3306)),
        user=config.get('user', 'root'),
        password=config.get('password', ''),
        database=config.get('database', 'fayzcontrol_db'),
        charset='utf8mb4',
        connect_timeout=5,
        autocommit=False
    )
    return MySQLConnectionWrapper(conn)

_ACTIVE_ENGINE = 'mysql'

def get_db():
    """
    Primary database connection factory for the entire hospital management system.
    Connects strictly to MySQL 8.0.
    """
    global _ACTIVE_ENGINE
    config = load_config()
    try:
        conn = get_mysql_connection(config)
        _ACTIVE_ENGINE = 'mysql'
        return conn
    except Exception as err:
        _ACTIVE_ENGINE = None
        print(f"[!] FATAL: Failed to connect to MySQL ({config.get('user')}@{config.get('host')}:{config.get('port')}/{config.get('database')}): {err}")
        raise ConnectionError(f"MySQL connection failed: {err}")

def get_active_engine():
    return 'mysql'

def is_duplicate_key_error(err):
    """
    True when an exception is a MySQL duplicate-key violation (errno 1062).
    Used to retry generated primary keys that collided instead of failing the
    whole operation. InnoDB does not abort the surrounding transaction on 1062,
    so a retry inside the same transaction is safe.
    """
    code = None
    args = getattr(err, 'args', None)
    if args:
        code = args[0]
    if code == 1062:
        return True
    return 'Duplicate entry' in str(err)

def test_mysql_connection(host, port, user, password, database):
    """
    Test a MySQL connection with specific parameters and return (success, message).
    """
    if not HAS_PYMYSQL:
        return False, "PyMySQL package is not installed."
    try:
        conn = pymysql.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=database,
            charset='utf8mb4',
            connect_timeout=5
        )
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION(), DATABASE(), USER();")
            ver, db, usr = cur.fetchone()
        conn.close()
        return True, f"Connected to MySQL {ver} | DB: {db} | User: {usr}"
    except Exception as e:
        return False, str(e)


# =============================================================================
# TRANSACTIONAL CLINICAL & FINANCIAL WORKFLOW SERVICES (SEPARATION OF CONCERNS)
# =============================================================================

from datetime import datetime, date, timedelta

# Programmes sold as exclusive use of the whole room. The tariff (1.1M/day
# against 720k for a shared bed) is the price of the second bed staying empty,
# so the partner bed must be held even though nobody is lying in it.
FULL_ROOM_PROGRAMS = ('statsionar_full_room',)


def _row_get(row, key, index):
    """Read one column whether the cursor yields dicts or tuples."""
    if isinstance(row, dict) or hasattr(row, 'keys'):
        return row[key]
    return row[index]


def is_full_room_program(program_type):
    return str(program_type or '').strip().lower() in FULL_ROOM_PROGRAMS


def find_booking_conflict(cur, bed_id, start_date, end_date, program_type=None,
                          exclude_admission_id=None):
    """
    Decide whether [start_date, end_date) may be booked on bed_id.

    Returns None when the dates are free, or a ready-to-show Uzbek message
    naming the bed and the dates that clash.

    Two rules, kept together because they are one question ("can this patient
    have this bed on these dates?") and were previously answered in two places
    that had already drifted apart:

    1. The bed itself must be free. The interval is half-open, matching how
       the stay is billed: total_days is DATEDIFF(end, start), so the last
       date is the day the patient leaves and is not a night in the bed. A
       stay ending on the 8th and one starting on the 8th do not overlap, and
       refusing that turnover made the booking board disagree with the server.
       A stay is never shorter than one night, mirroring the GREATEST(1, ...)
       in the total_days column, so a same-day admission still holds the bed.

    2. A room sold whole is held whole. Either the incoming stay claims the
       room, or a stay already in it does; in both cases no second patient may
       take any bed of that room. Without this the clinic could bill a patient
       1.1M/day for a private room and then put a stranger in the other bed.
    """
    cur.execute("SELECT room_id, bed_code FROM beds WHERE id = ?", (bed_id,))
    bed_row = cur.fetchone()
    if not bed_row:
        return f"O'rin ({bed_id}) topilmadi."
    room_id = _row_get(bed_row, 'room_id', 0)
    bed_code = _row_get(bed_row, 'bed_code', 1)

    # One query for the whole room: the bed's own clashes and its room-mates'
    # arrive together, and the caller cannot forget the second half.
    sql = """
        SELECT a.id, a.bed_id, a.program_type, a.start_date,
               COALESCE(a.actual_end_date, a.planned_end_date) AS end_date,
               b.bed_code, p.full_name AS patient_name
        FROM admissions a
        JOIN beds b ON a.bed_id = b.id
        JOIN patients p ON a.patient_id = p.id
        WHERE b.room_id = ?
          AND a.status = 'active'
          AND ? < GREATEST(COALESCE(a.actual_end_date, a.planned_end_date),
                           DATE_ADD(a.start_date, INTERVAL 1 DAY))
          AND ? > a.start_date
    """
    params = [room_id, str(start_date), str(end_date)]
    if exclude_admission_id:
        sql += " AND a.id != ?"
        params.append(exclude_admission_id)

    cur.execute(sql, tuple(params))
    clashes = cur.fetchall()
    if not clashes:
        return None

    incoming_is_full_room = is_full_room_program(program_type)

    for row in clashes:
        other_bed = _row_get(row, 'bed_id', 1)
        if str(other_bed) == str(bed_id):
            return (f"Tanlangan o'rinda ({bed_code}) ko'rsatilgan sanalarda "
                    f"faol bemor mavjud!")

    # Nothing on this bed, so any remaining clash is a room-mate. It only
    # matters when one side of it has bought the room outright.
    for row in clashes:
        other_full_room = is_full_room_program(_row_get(row, 'program_type', 2))
        if not (incoming_is_full_room or other_full_room):
            continue
        other_code = _row_get(row, 'bed_code', 5)
        other_name = _row_get(row, 'patient_name', 6)
        if incoming_is_full_room:
            return (f"Butun xona buyurtmasi: shu xonadagi {other_code} o'rnida "
                    f"ko'rsatilgan sanalarda faol bemor bor ({other_name}).")
        return (f"Bu xona ko'rsatilgan sanalarda butun xona sifatida band "
                f"({other_code}, {other_name}) — ikkinchi o'rin berilmaydi.")

    return None


def admit_patient(conn, patient_id, bed_id, attending_doctor_id, program_type,
                  start_date, planned_end_date, daily_price, admission_notes=None):
    """
    Atomic patient admission:
    1. Fetches human-readable bed_code
    2. Validates against concurrent double-booking on target bed
    3. Creates admission record
    4. Initializes empty invoice container
    5. Creates first bed stay segment in invoice_items with boundary dates
    6. Triggers rebalance the invoice atomically
    """
    try:
        cur = conn.cursor()
        # Admission ids are second-resolution timestamps, so two admissions registered
        # in the same second used to collide on the primary key and one was lost.
        # The first candidate keeps the original ADM-YYYYMMDDHHMMSS format; a numeric
        # suffix is only appended when that exact id is already taken.
        adm_stamp = datetime.now().strftime('%Y%m%d%H%M%S')
        adm_id = f"ADM-{adm_stamp}"
        inv_id = f"INV-{adm_id}"

        # 0. Fetch human-readable bed code & verify operational status
        cur.execute("SELECT bed_code, status FROM beds WHERE id = ?", (bed_id,))
        b_row = cur.fetchone()
        bed_code = (b_row['bed_code'] if isinstance(b_row, dict) or hasattr(b_row, 'keys') else b_row[0]) if b_row else bed_id
        b_status = (b_row['status'] if isinstance(b_row, dict) or hasattr(b_row, 'keys') else b_row[1]) if b_row else 'operational'

        if b_status in ('cleaning', 'maintenance', 'out_of_service'):
            return False, f"O'rin ({bed_code}) hozirda band yoki tozalash/ta'mirlash holatida ({b_status})!"

        # 0.1 Concurrent Double-Booking Race Condition Guard.
        # The bed's own dates and the whole-room rule are one question, so they
        # are asked in one place — see find_booking_conflict.
        conflict = find_booking_conflict(cur, bed_id, start_date, planned_end_date,
                                         program_type=program_type)
        if conflict:
            return False, conflict

        # 1. Insert Admission (retrying only the id on a same-second collision)
        for attempt in range(100):
            candidate = f"ADM-{adm_stamp}" if attempt == 0 else f"ADM-{adm_stamp}-{attempt}"
            try:
                cur.execute("""
                    INSERT INTO admissions (
                        id, patient_id, bed_id, attending_doctor_id, program_type,
                        start_date, planned_end_date, daily_price, status, admission_notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """, (candidate, patient_id, bed_id, attending_doctor_id, program_type,
                      start_date, planned_end_date, daily_price, admission_notes))
                adm_id = candidate
                inv_id = f"INV-{adm_id}"
                break
            except Exception as e_dup:
                if is_duplicate_key_error(e_dup):
                    continue
                raise
        else:
            return False, "Admission ID generatsiyasi muvaffaqiyatsiz (100 urinish)."

        # 2. Insert Invoice Container
        cur.execute("""
            INSERT INTO invoices (
                id, admission_id, total_billed, discount_amount, net_amount,
                total_paid, balance_due, payment_status
            ) VALUES (?, ?, 0.00, 0.00, 0.00, 0.00, 0.00, 'unpaid')
        """, (inv_id, adm_id))

        # 3. Calculate initial days
        d_start = datetime.strptime(str(start_date), '%Y-%m-%d').date()
        d_end = datetime.strptime(str(planned_end_date), '%Y-%m-%d').date()
        stay_days = max(1, (d_end - d_start).days)

        # 4. Insert Initial Bed Stay Line Item with human-readable bed code
        cur.execute("""
            INSERT INTO invoice_items (
                invoice_id, service_name, quantity, unit_price, item_type,
                service_start_date, service_end_date, bed_id
            ) VALUES (?, ?, ?, ?, 'bed_stay', ?, ?, ?)
        """, (inv_id, f"Statsionar yotoq: {bed_code} (Boshlang'ich segment)",
              stay_days, daily_price, start_date, planned_end_date, bed_id))

        # 5. Update patient status
        cur.execute("UPDATE patients SET status = 'active' WHERE id = ?", (patient_id,))

        conn.commit()
        return True, {"admission_id": adm_id, "invoice_id": inv_id, "days": stay_days, "bed_code": bed_code}
    except Exception as e:
        conn.rollback()
        return False, str(e)


def transfer_patient_bed(conn, admission_id, new_bed_id, transfer_date, transfer_reason=None, performed_by_staff_id=None):
    """
    Atomic bed transfer and segmented billing (Dialect-agnostic):
    1. Validates destination bed against concurrent overlapping admissions.
    2. Handles same-day room switches without double-tariff inflation.
    3. Clamps previous segment to elapsed days from service_start_date to transfer_date.
    4. Opens new segment from transfer_date to planned_end_date.
    5. Sets previous bed to 'cleaning' status for clinical sanitation.
    6. Records entry in bed_transfers and updates admission.
    """
    try:
        cur = conn.cursor()
        t_date = datetime.strptime(str(transfer_date), '%Y-%m-%d').date()

        # 1. Fetch admission & old bed info
        cur.execute("SELECT patient_id, bed_id, start_date, planned_end_date, actual_end_date, program_type FROM admissions WHERE id = ?", (admission_id,))
        adm = cur.fetchone()
        if not adm:
            return False, f"Admission {admission_id} not found."
        adm_program = _row_get(adm, 'program_type', 5)
        
        old_bed_id = adm['bed_id'] if isinstance(adm, dict) or hasattr(adm, 'keys') else adm[1]
        raw_end = adm['actual_end_date'] if isinstance(adm, dict) or hasattr(adm, 'keys') else adm[4]
        if not raw_end:
            raw_end = adm['planned_end_date'] if isinstance(adm, dict) or hasattr(adm, 'keys') else adm[3]
        d_end = datetime.strptime(str(raw_end), '%Y-%m-%d').date()

        # 2. Fetch new bed tariff & status
        cur.execute("SELECT bed_code, default_daily_rate, status FROM beds WHERE id = ?", (new_bed_id,))
        new_bed = cur.fetchone()
        if not new_bed:
            return False, f"Target bed {new_bed_id} not found."
        new_code = new_bed['bed_code'] if isinstance(new_bed, dict) or hasattr(new_bed, 'keys') else new_bed[0]
        new_rate = new_bed['default_daily_rate'] if isinstance(new_bed, dict) or hasattr(new_bed, 'keys') else new_bed[1]
        new_status = new_bed['status'] if isinstance(new_bed, dict) or hasattr(new_bed, 'keys') else new_bed[2]

        if new_status in ('cleaning', 'maintenance', 'out_of_service'):
            return False, f"Ko'chirilayotgan o'rin ({new_code}) hozirda band yoki tozalash/ta'mirlash holatida ({new_status})!"

        # 2.1 Concurrent Overlap Check on Target Bed.
        # The same rule as admission, asked through the same helper: the stay
        # being moved runs from transfer_date to raw_end, and it carries its
        # programme with it, so a whole-room booking stays whole after a move.
        conflict = find_booking_conflict(cur, new_bed_id, transfer_date, str(raw_end),
                                         program_type=adm_program,
                                         exclude_admission_id=admission_id)
        if conflict:
            return False, conflict

        inv_id = f"INV-{admission_id}"

        # 3. Locate active prior bed_stay segment
        cur.execute("""
            SELECT id, service_name, service_start_date, unit_price FROM invoice_items 
            WHERE invoice_id = ? AND item_type = 'bed_stay' AND bed_id = ?
            ORDER BY id DESC LIMIT 1
        """, (inv_id, old_bed_id))
        old_item = cur.fetchone()

        elapsed_days = 0
        remaining_days = max(1, (d_end - t_date).days)

        if old_item:
            item_id = old_item['id'] if isinstance(old_item, dict) or hasattr(old_item, 'keys') else old_item[0]
            orig_name = old_item['service_name'] if isinstance(old_item, dict) or hasattr(old_item, 'keys') else old_item[1]
            raw_prev_start = old_item['service_start_date'] if isinstance(old_item, dict) or hasattr(old_item, 'keys') else old_item[2]
            d_prev_start = datetime.strptime(str(raw_prev_start), '%Y-%m-%d').date()

            # Same-day room switch: avoid 1+5=6 inflation when transferred on the arrival date
            if t_date == d_prev_start:
                cur.execute("""
                    UPDATE invoice_items 
                    SET bed_id = ?, unit_price = ?, service_name = ?
                    WHERE id = ?
                """, (new_bed_id, new_rate, f"Statsionar yotoq: {new_code} (Ko'chirildi)", item_id))
                elapsed_days = 0
            else:
                elapsed_days = max(1, (t_date - d_prev_start).days)
                updated_name = f"{orig_name} (Ko'chirildi: {transfer_date})"
                cur.execute("""
                    UPDATE invoice_items 
                    SET service_end_date = ?,
                        quantity = ?,
                        service_name = ?
                    WHERE id = ?
                """, (transfer_date, elapsed_days, updated_name, item_id))

                # Insert New Tariff Segment for remaining duration
                cur.execute("""
                    INSERT INTO invoice_items (
                        invoice_id, service_name, quantity, unit_price, item_type,
                        service_start_date, service_end_date, bed_id
                    ) VALUES (?, ?, ?, ?, 'bed_stay', ?, ?, ?)
                """, (inv_id, f"Statsionar yotoq: {new_code} (Yangi palata segmenti)",
                      remaining_days, new_rate, transfer_date, str(raw_end), new_bed_id))
        else:
            # Fallback if no prior segment found
            cur.execute("""
                INSERT INTO invoice_items (
                    invoice_id, service_name, quantity, unit_price, item_type,
                    service_start_date, service_end_date, bed_id
                ) VALUES (?, ?, ?, ?, 'bed_stay', ?, ?, ?)
            """, (inv_id, f"Statsionar yotoq: {new_code} (Yangi palata segmenti)",
                  remaining_days, new_rate, transfer_date, str(raw_end), new_bed_id))

        # 4. Sanitation: set departed bed to cleaning status
        cur.execute("UPDATE beds SET status = 'cleaning', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (old_bed_id,))

        # 5. Record Bed Transfer audit log
        cur.execute("""
            INSERT INTO bed_transfers (admission_id, from_bed_id, to_bed_id, transfer_date, transfer_reason, performed_by_staff_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (admission_id, old_bed_id, new_bed_id, transfer_date, transfer_reason, performed_by_staff_id))

        # 6. Update admission pointer and rate
        cur.execute("""
            UPDATE admissions 
            SET bed_id = ?, daily_price = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (new_bed_id, new_rate, admission_id))

        conn.commit()
        return True, {"old_bed_days": elapsed_days, "new_bed_days": remaining_days, "new_rate": new_rate}
    except Exception as e:
        conn.rollback()
        return False, str(e)


_patient_columns_checked = False


def ensure_patient_columns(conn):
    """
    Add patients.birth_date to a database created before it existed.

    Idempotent and cheap, so it can run on every start. The column is new
    because registration only ever stored a birth *year* -- and in practice
    not even that: the desk had no field for it, so every patient registered
    through reception was written as gender 'male', born 1990. A fabricated
    date of birth in a medical record is worse than an empty one, so both are
    now nullable and the desk is asked for them.
    """
    global _patient_columns_checked
    if _patient_columns_checked:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) AS n FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'patients'
              AND COLUMN_NAME = 'birth_date'
        """)
        row = cur.fetchone()
        have = (row['n'] if isinstance(row, dict) or hasattr(row, 'keys') else row[0])
        if not have:
            cur.execute("ALTER TABLE patients ADD COLUMN birth_date DATE NULL AFTER gender")
            # Anything already on file keeps its year; 1 January is a marker
            # that only the year was ever known, not a claim about the day.
            conn.commit()
        _patient_columns_checked = True
    except Exception as e:
        print(f"[!] Could not add patients.birth_date: {e}")


_requests_table_checked = False


def ensure_appointment_requests(conn):
    """
    Create appointment_requests on a database made before it existed.

    Enquiries from the public website used to POST straight at
    /api/reception/appointment. Once the API required authentication that
    endpoint answered 401 and the enquiry vanished with nothing recorded and
    nobody told. They land here instead, where the desk can see them; this is
    unverified input from the open internet, so it is kept out of the patients
    and appointments tables until someone accepts it.
    """
    global _requests_table_checked
    if _requests_table_checked:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS appointment_requests (
                id VARCHAR(64) PRIMARY KEY,
                full_name VARCHAR(255) NOT NULL,
                phone VARCHAR(64) NOT NULL,
                preferred_date DATE,
                service_type VARCHAR(64),
                note TEXT,
                source VARCHAR(64) NOT NULL DEFAULT 'website',
                status VARCHAR(32) NOT NULL DEFAULT 'new'
                    CHECK(status IN ('new', 'accepted', 'rejected')),
                ip_address VARCHAR(64),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                handled_by VARCHAR(64),
                handled_at DATETIME,
                patient_id VARCHAR(64),
                appointment_id VARCHAR(64),
                INDEX idx_request_status (status, created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        _requests_table_checked = True
    except Exception as e:
        print(f"[!] Could not create appointment_requests: {e}")


_ward_round_checked = False


def ensure_ward_round_schema(conn):
    """
    One doctor's note per stay per day.

    doctor_daily_notes had no unique key, so the ward round could file two
    contradictory assessments of the same patient on the same morning and
    nothing would object. The round is a daily record; a doctor amending what
    they wrote an hour ago should replace it, not add to it.

    Idempotent, so it can run on every start.
    """
    global _ward_round_checked
    if _ward_round_checked:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) AS n FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'doctor_daily_notes'
              AND INDEX_NAME = 'uq_admission_note_date'
        """)
        row = cur.fetchone()
        have = (row['n'] if isinstance(row, dict) or hasattr(row, 'keys') else row[0])
        if not have:
            # Collapse any duplicates a previous version could have written
            # before adding the constraint, keeping the most recent of each day.
            cur.execute("""
                DELETE n FROM doctor_daily_notes n
                JOIN (
                    SELECT admission_id, note_date, MAX(id) AS keep_id
                    FROM doctor_daily_notes
                    WHERE admission_id IS NOT NULL
                    GROUP BY admission_id, note_date
                    HAVING COUNT(*) > 1
                ) d ON n.admission_id = d.admission_id
                   AND n.note_date = d.note_date
                   AND n.id <> d.keep_id
            """)
            cur.execute("""
                ALTER TABLE doctor_daily_notes
                ADD UNIQUE KEY uq_admission_note_date (admission_id, note_date)
            """)
            conn.commit()
        _ward_round_checked = True
    except Exception as e:
        print(f"[!] Could not add the ward-round unique key: {e}")


_medication_purchases_checked = False


def ensure_medication_purchases(conn):
    """
    Create medication_purchases table if it does not exist yet.
    Allows recording clinic medication purchases and linking them directly
    to accounting expenses and inventory stock.
    """
    global _medication_purchases_checked
    if _medication_purchases_checked:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS medication_purchases (
                id VARCHAR(64) PRIMARY KEY,
                purchase_date DATE NOT NULL,
                medication_id VARCHAR(64),
                medication_name VARCHAR(255) NOT NULL,
                category VARCHAR(128),
                form VARCHAR(64),
                quantity DECIMAL(10,2) NOT NULL CHECK(quantity > 0),
                unit_price DECIMAL(14,2) NOT NULL CHECK(unit_price >= 0),
                total_price DECIMAL(14,2) NOT NULL CHECK(total_price >= 0),
                payment_method VARCHAR(32) NOT NULL DEFAULT 'cash' CHECK(payment_method IN (
                    'cash', 'cash_register', 'terminal', 'card_transfer', 'payme_click', 'bank_wire'
                )),
                supplier_name VARCHAR(255),
                invoice_number VARCHAR(128),
                notes TEXT,
                accounting_transaction_id VARCHAR(128),
                recorded_by_staff_id VARCHAR(64),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (medication_id) REFERENCES medications_catalog(id) ON UPDATE CASCADE ON DELETE SET NULL,
                FOREIGN KEY (accounting_transaction_id) REFERENCES accounting_transactions(id) ON UPDATE CASCADE ON DELETE SET NULL,
                FOREIGN KEY (recorded_by_staff_id) REFERENCES staff(id) ON UPDATE CASCADE ON DELETE SET NULL,
                INDEX idx_med_purchase_date (purchase_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        _medication_purchases_checked = True
    except Exception as e:
        print(f"[!] Could not create medication_purchases table: {e}")


def list_room_availability(conn, start_date, end_date):
    """
    The occupancy board for one date range, room by room.

    The reception desk needs to answer "what is free between these two dates?",
    which v_bed_live_status cannot do: that view is fixed on CURDATE() and only
    ever describes today. This walks the same admissions with the same overlap
    rule as find_booking_conflict, so a bed the board paints green is a bed the
    booking guard will actually accept — they used to be two separate pieces of
    arithmetic in two languages, and the browser's copy also mixed in bookings
    held in localStorage that no other machine could see.

    Per bed the verdict is one of:
      out_of_service / maintenance / cleaning   the bed is physically unusable
      occupied           a stay already covers the first day of the range
      room_locked        a room-mate holds the whole room for these dates
      partial_conflict   free on the first day, but a stay lands later in range
      available          free for the whole range
    """
    cur = conn.cursor()
    ws = str(start_date)[:10]
    we = str(end_date)[:10]
    # A stay is never shorter than one night, so a window that starts and ends
    # on the same day still asks about that night rather than about nothing.
    if we <= ws:
        we = (datetime.strptime(ws, '%Y-%m-%d').date() + timedelta(days=1)).isoformat()

    cur.execute("""
        SELECT r.id AS room_id, r.floor_number, r.room_number, r.room_name_uz,
               r.room_type, r.total_capacity,
               b.id AS bed_id, b.bed_code, b.bed_type, b.default_daily_rate,
               b.status AS physical_status
        FROM rooms r
        JOIN beds b ON b.room_id = r.id
        WHERE r.is_active = 1
        ORDER BY r.floor_number, r.room_number, b.bed_code
    """)
    bed_rows = [dict(r) for r in cur.fetchall()]

    # Every active stay touching the window, plus the next one after it so the
    # desk can see how long a free bed stays free before the next arrival.
    cur.execute("""
        SELECT a.id, a.bed_id, a.patient_id, a.program_type, a.start_date,
               COALESCE(a.actual_end_date, a.planned_end_date) AS end_date,
               p.full_name AS patient_name, p.patient_code,
               s.full_name AS doctor_name
        FROM admissions a
        JOIN patients p ON a.patient_id = p.id
        LEFT JOIN staff s ON a.attending_doctor_id = s.id
        WHERE a.status = 'active'
          AND ? > a.start_date
          AND ? < GREATEST(COALESCE(a.actual_end_date, a.planned_end_date),
                           DATE_ADD(a.start_date, INTERVAL 1 DAY))
    """, (we, ws))
    overlapping = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT a.bed_id, MIN(a.start_date) AS next_start
        FROM admissions a
        WHERE a.status = 'active' AND a.start_date >= ?
        GROUP BY a.bed_id
    """, (we,))
    next_by_bed = {str(r['bed_id'] if isinstance(r, dict) or hasattr(r, 'keys') else r[0]):
                   str((r['next_start'] if isinstance(r, dict) or hasattr(r, 'keys') else r[1]))[:10]
                   for r in cur.fetchall()}

    by_bed = {}
    for stay in overlapping:
        by_bed.setdefault(str(stay['bed_id']), []).append(stay)

    rooms = {}
    for row in bed_rows:
        room_id = str(row['room_id'])
        room = rooms.get(room_id)
        if room is None:
            room = rooms[room_id] = {
                'room_id': room_id,
                'floor_number': row['floor_number'],
                'room_number': row['room_number'],
                'room_name_uz': row['room_name_uz'],
                'room_type': row['room_type'],
                'total_capacity': row['total_capacity'],
                'beds': [],
            }
        room['beds'].append(row)

    result = []
    for room in rooms.values():
        room_bed_ids = [str(b['bed_id']) for b in room['beds']]
        # A whole-room booking on any bed of this room holds all of them.
        room_lock = None
        for bid in room_bed_ids:
            for stay in by_bed.get(bid, []):
                if is_full_room_program(stay['program_type']):
                    room_lock = stay
                    break
            if room_lock:
                break

        beds_out = []
        for bed in room['beds']:
            bid = str(bed['bed_id'])
            stays = sorted(by_bed.get(bid, []), key=lambda s: str(s['start_date']))
            covering = [s for s in stays if str(s['start_date'])[:10] <= ws]
            later = [s for s in stays if str(s['start_date'])[:10] > ws]
            physical = str(bed['physical_status'])

            entry = {
                'bed_id': bid,
                'bed_code': bed['bed_code'],
                'bed_type': bed['bed_type'],
                'default_daily_rate': float(bed['default_daily_rate'] or 0),
                'physical_status': physical,
                'room_id': room['room_id'],
                'room_number': room['room_number'],
                'room_name_uz': room['room_name_uz'],
                'floor_number': room['floor_number'],
                'occupant': None,
                'conflict': None,
                'next_booking': next_by_bed.get(bid),
            }

            if physical in ('maintenance', 'out_of_service', 'cleaning'):
                entry['status'] = physical
            elif covering:
                s = covering[0]
                entry['status'] = 'occupied'
                entry['occupant'] = _stay_brief(s)
            elif room_lock and str(room_lock['bed_id']) != bid:
                entry['status'] = 'room_locked'
                entry['occupant'] = _stay_brief(room_lock)
            elif later:
                entry['status'] = 'partial_conflict'
                entry['conflict'] = _stay_brief(later[0])
            else:
                entry['status'] = 'available'
            beds_out.append(entry)

        free = [b for b in beds_out if b['status'] == 'available']
        room_out = dict(room)
        room_out['beds'] = beds_out
        room_out['free_beds'] = len(free)
        room_out['status'] = ('free' if len(free) == len(beds_out)
                              else 'full' if not free else 'partial')
        room_out['locked_whole_room'] = bool(room_lock)
        result.append(room_out)

    all_beds = [b for r in result for b in r['beds']]
    summary = {
        'total_beds': len(all_beds),
        'available': sum(1 for b in all_beds if b['status'] == 'available'),
        'occupied': sum(1 for b in all_beds if b['status'] == 'occupied'),
        'room_locked': sum(1 for b in all_beds if b['status'] == 'room_locked'),
        'partial_conflict': sum(1 for b in all_beds if b['status'] == 'partial_conflict'),
        'cleaning': sum(1 for b in all_beds if b['status'] == 'cleaning'),
        'unusable': sum(1 for b in all_beds
                        if b['status'] in ('maintenance', 'out_of_service')),
        'free_rooms': sum(1 for r in result if r['status'] == 'free'),
        'total_rooms': len(result),
    }
    return {'start': ws, 'end': we, 'summary': summary, 'rooms': result}


def _stay_brief(stay):
    """The few fields the reception board shows about whoever holds a bed."""
    return {
        'admission_id': stay['id'],
        'patient_id': stay['patient_id'],
        'patient_name': stay['patient_name'],
        'patient_code': stay['patient_code'],
        'doctor_name': stay['doctor_name'],
        'program_type': stay['program_type'],
        'start_date': str(stay['start_date'])[:10],
        'end_date': str(stay['end_date'])[:10],
        'is_full_room': is_full_room_program(stay['program_type']),
    }


def discharge_patient(conn, admission_id, actual_end_date, discharge_summary=None):
    """
    Atomic patient discharge:
    1. Sets admission status to 'discharged' and records actual_end_date.
    2. Prunes or deletes any future bed segments to prevent check constraint collisions on backdated discharges.
    3. Clamps active stay segment safely.
    4. Transitions bed hardware state to 'cleaning' for mandatory clinical sanitation.
    5. Updates patient status to 'discharged'.
    """
    try:
        cur = conn.cursor()
        d_discharge = datetime.strptime(str(actual_end_date), '%Y-%m-%d').date()

        cur.execute("SELECT patient_id, bed_id FROM admissions WHERE id = ?", (admission_id,))
        adm = cur.fetchone()
        if not adm:
            return False, f"Admission {admission_id} not found."

        patient_id = adm['patient_id'] if isinstance(adm, dict) or hasattr(adm, 'keys') else adm[0]
        bed_id = adm['bed_id'] if isinstance(adm, dict) or hasattr(adm, 'keys') else adm[1]

        # 1. Update Admission record
        cur.execute("""
            UPDATE admissions 
            SET status = 'discharged', actual_end_date = ?, discharge_summary = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (actual_end_date, discharge_summary, admission_id))

        inv_id = f"INV-{admission_id}"

        # 2. Backdated Discharge Safety: Prune any segments that started after actual_end_date
        cur.execute("""
            DELETE FROM invoice_items 
            WHERE invoice_id = ? AND item_type = 'bed_stay' AND service_start_date > ?
        """, (inv_id, actual_end_date))

        # 3. Locate the latest remaining bed_stay segment and clamp
        cur.execute("""
            SELECT id, service_name, service_start_date FROM invoice_items 
            WHERE invoice_id = ? AND item_type = 'bed_stay' 
            ORDER BY id DESC LIMIT 1
        """, (inv_id,))
        latest_item = cur.fetchone()

        if latest_item:
            item_id = latest_item['id'] if isinstance(latest_item, dict) or hasattr(latest_item, 'keys') else latest_item[0]
            orig_name = latest_item['service_name'] if isinstance(latest_item, dict) or hasattr(latest_item, 'keys') else latest_item[1]
            raw_start = latest_item['service_start_date'] if isinstance(latest_item, dict) or hasattr(latest_item, 'keys') else latest_item[2]

            d_start = datetime.strptime(str(raw_start), '%Y-%m-%d').date()

            if d_discharge < d_start:
                # Discharge occurred prior to this segment's start date: delete it
                cur.execute("DELETE FROM invoice_items WHERE id = ?", (item_id,))
            else:
                actual_days = max(1, (d_discharge - d_start).days)
                updated_name = f"{orig_name} (Muddatidan oldin chiqarildi)"
                cur.execute("""
                    UPDATE invoice_items 
                    SET service_end_date = ?,
                        quantity = ?,
                        service_name = ?
                    WHERE id = ?
                """, (actual_end_date, actual_days, updated_name, item_id))

        # 4. Mandatory Clinical Sanitation: transition bed hardware status to 'cleaning'
        cur.execute("UPDATE beds SET status = 'cleaning', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (bed_id,))

        # 5. Update patient master status
        cur.execute("UPDATE patients SET status = 'discharged', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (patient_id,))

        conn.commit()
        return True, {"admission_id": admission_id, "actual_end_date": str(actual_end_date), "bed_status": "cleaning"}
    except Exception as e:
        conn.rollback()
        return False, str(e)

