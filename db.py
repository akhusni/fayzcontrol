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

from datetime import datetime, date

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

        # 0.1 Concurrent Double-Booking Race Condition Guard
        # Standard interval overlap test: new_start <= existing_end AND new_end >= existing_start.
        # The two date parameters must be bound in that order, otherwise the predicate
        # degrades into a "new stay fully contained in existing stay" check and lets
        # every partially overlapping stay through (two patients in one bed).
        cur.execute("""
            SELECT id FROM admissions
            WHERE bed_id = ?
              AND status = 'active'
              AND (? <= COALESCE(actual_end_date, planned_end_date) AND ? >= start_date)
        """, (bed_id, start_date, planned_end_date))
        if cur.fetchone():
            return False, f"Tanlangan o'rinda ({bed_code}) ko'rsatilgan sanalarda faol bemor mavjud!"

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
        cur.execute("SELECT patient_id, bed_id, start_date, planned_end_date, actual_end_date FROM admissions WHERE id = ?", (admission_id,))
        adm = cur.fetchone()
        if not adm:
            return False, f"Admission {admission_id} not found."
        
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

        # 2.1 Concurrent Overlap Check on Target Bed
        # Same interval overlap test as admit_patient: the stay being moved runs from
        # transfer_date to raw_end, so bind start first, then end.
        cur.execute("""
            SELECT id FROM admissions
            WHERE bed_id = ?
              AND id != ?
              AND status = 'active'
              AND (? <= COALESCE(actual_end_date, planned_end_date) AND ? >= start_date)
        """, (new_bed_id, admission_id, transfer_date, str(raw_end)))
        if cur.fetchone():
            return False, f"Ko'chirilayotgan o'rinda ({new_code}) ko'rsatilgan sanalarda boshqa faol bemor mavjud!"

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

