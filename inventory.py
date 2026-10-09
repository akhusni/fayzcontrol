"""
Fayz Medical House — medical warehouse (stock, lots, ledger, dispensing).

This module is the ONLY place that may change `medications_catalog.stock_quantity`
or `inventory_batches.remaining_qty`. Every change writes an immutable ledger
row (`inventory_transactions`) in the same database transaction, so the item
balance, the lots and the ledger can always be reconciled (see `reconciliation`).

Contract shared by every public function that writes:

* The connection is passed in. The function never commits and never rolls
  back; the caller commits only after the whole operation succeeded and rolls
  back on any exception. One public call is one transaction.
* Quantities are `decimal.Decimal` in the item's base unit (DECIMAL(14,3));
  money is `Decimal` (unit cost 4 dp, totals 2 dp, ROUND_HALF_UP). Never float.
* The item row is locked (`SELECT ... FOR UPDATE`) before its lots, lots in `id`
  order, so two workers (even two processes) cannot sell the same last tablet.
* Business refusals raise `InventoryError` with an Uzbek message that is safe to
  show; nothing else from this module should reach a person.

The design and the API contract are in docs/WAREHOUSE_DESIGN.md.
"""

import datetime as _dt
import decimal
import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP

try:
    import pymysql
    import pymysql.cursors
except ImportError:                      # pragma: no cover - same guard as db.py
    pymysql = None


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
QTY = Decimal('0.001')
COST = Decimal('0.0001')
MONEY = Decimal('0.01')
ZERO = Decimal('0')
MAX_QTY = Decimal('1000000000')
MAX_MONEY = Decimal('1000000000000')

ITEM_TYPES = ('medicine', 'vitamin', 'injection', 'syringe', 'consumable', 'equipment', 'other')
# Types that are handed to a patient on a doctor's order.
PRESCRIPTION_TYPES = ('medicine', 'vitamin', 'injection')
ITEM_TYPE_LABELS = {
    'medicine': 'Dori-darmon', 'vitamin': 'Vitamin', 'injection': "Inyeksiya / eritma",
    'syringe': 'Shprits', 'consumable': 'Sarf materiali', 'equipment': 'Jihoz', 'other': 'Boshqa',
}
UNITS = ('dona', 'tabletka', 'kapsula', 'ampula', 'flakon', 'shisha', 'shprits', 'paket',
         'ml', 'l', 'g', 'mg', 'kg', 'qadoq', 'quti', 'blister', 'tuba', 'doza', 'juft')
TXN_TYPES = ('receipt', 'dispense', 'adjustment_in', 'adjustment_out', 'supplier_return',
             'patient_return', 'writeoff', 'reversal', 'opening')
ADJUSTMENT_KINDS = {
    'increase': 'adjustment_in', 'decrease': 'adjustment_out', 'writeoff': 'writeoff',
    'supplier_return': 'supplier_return', 'patient_return': 'patient_return',
}
DISPENSING_SOURCES = ('manual', 'nurse_round', 'billing')
PAYMENT_METHODS = ('cash', 'cash_register', 'terminal', 'card_transfer', 'payme_click', 'bank_wire')

SETTING_DEFAULT_MIN = 'inventory.default_min_stock'
SETTING_EXPIRY_DAYS = 'inventory.expiry_warning_days'
_SETTING_DEFAULTS = {SETTING_DEFAULT_MIN: '10', SETTING_EXPIRY_DAYS: '30'}


class InventoryError(Exception):
    """A refusal with a message for the person at the screen (Uzbek)."""

    def __init__(self, message, field=None, status=400):
        super().__init__(message)
        self.message = message
        self.field = field
        self.status = status


class NotFound(InventoryError):
    def __init__(self, message):
        super().__init__(message, None, 404)


class Forbidden(InventoryError):
    def __init__(self, message):
        super().__init__(message, None, 403)


def _q(x):
    return Decimal(x).quantize(QTY, rounding=ROUND_HALF_UP)


def _c(x):
    return Decimal(x).quantize(COST, rounding=ROUND_HALF_UP)


def _m(x):
    return Decimal(x).quantize(MONEY, rounding=ROUND_HALF_UP)


def _dec(v):
    """A database value as Decimal (NULL is zero)."""
    if v is None:
        return ZERO
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _is_whole(d):
    return d == d.to_integral_value()


# ---------------------------------------------------------------------------
# Database access
#
# db.py's cursor converts every Decimal to float (DictRow). Money and stock must
# stay Decimal end to end, so this module talks to the raw PyMySQL cursor. The
# SQL uses `?` placeholders like the rest of the project. A literal percent sign
# in SQL text must be written %% when parameters are passed; this module passes
# patterns such as LIKE values as parameters instead.
# ---------------------------------------------------------------------------

class _Cur:
    def __init__(self, conn):
        self.conn = conn
        raw = getattr(conn, '_conn', conn)
        self._c = raw.cursor(pymysql.cursors.DictCursor)

    def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        if params is None:
            self._c.execute(sql)
        else:
            self._c.execute(sql, tuple(params))
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return list(self._c.fetchall())

    @property
    def lastrowid(self):
        return self._c.lastrowid

    @property
    def rowcount(self):
        return self._c.rowcount

    def close(self):
        try:
            self._c.close()
        except Exception:
            pass


def _cursor(conn):
    return _Cur(conn)


def _gen_id(cur, table, prefix):
    """
    A free id of the form PREFIX-#####, probed against `table`.

    server.new_record_id does the same, but server.py cannot be imported from
    here (it imports this module and runs as __main__). The probe is race-free
    under WRITE_LOCK; the primary key still refuses a clash from a second
    process, and that refusal rolls the whole operation back.
    """
    for _ in range(200):
        candidate = f"{prefix}-{int(os.urandom(3).hex(), 16) % 90000 + 10000}"
        cur.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (candidate,))
        if not cur.fetchone():
            return candidate
    return f"{prefix}-{int(_dt.datetime.now().timestamp() * 1000)}"


def _today():
    return _dt.date.today()


def _now():
    return _dt.datetime.now().replace(microsecond=0)


# ---------------------------------------------------------------------------
# Input validation (shared by items, receipts, adjustments, dispensing)
# ---------------------------------------------------------------------------

def parse_decimal(value, field, label, places, minimum=ZERO, maximum=MAX_QTY, allow_zero=False):
    """
    A strict non-negative Decimal: no float noise, no more decimals than the
    column keeps, zero only when `allow_zero`.
    """
    if value is None or value == '' or isinstance(value, (bool, list, dict)):
        raise InventoryError(f"{label} ko'rsatilishi shart.", field)
    try:
        d = Decimal(str(value).strip())
    except (decimal.InvalidOperation, ValueError):
        raise InventoryError(f"{label} raqam bo'lishi kerak.", field)
    if not d.is_finite():
        raise InventoryError(f"{label} raqam bo'lishi kerak.", field)
    if d.normalize().as_tuple().exponent < -places:
        raise InventoryError(f"{label}: ko'pi bilan {places} ta kasr raqam yozish mumkin.", field)
    if d < 0:
        raise InventoryError(f"{label} manfiy bo'lishi mumkin emas.", field)
    if d == 0 and not allow_zero:
        raise InventoryError(f"{label} noldan katta bo'lishi kerak.", field)
    if d > maximum:
        raise InventoryError(f"{label} juda katta.", field)
    return d


def parse_qty(value, field='quantity', label='Miqdor', allow_zero=False):
    return _q(parse_decimal(value, field, label, 3, ZERO, MAX_QTY, allow_zero))


def parse_money(value, field, label, allow_zero=True):
    return _m(parse_decimal(value, field, label, 2, ZERO, MAX_MONEY, allow_zero))


def parse_date(value, field, label, required=False):
    if value in (None, ''):
        if required:
            raise InventoryError(f"{label} ko'rsatilishi shart.", field)
        return None
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except Exception:
        raise InventoryError(f"{label} noto'g'ri formatda. Kutilgan format: YYYY-MM-DD.", field)


_BAD_TEXT = re.compile(r'[<>\x00-\x08\x0b\x0c\x0e-\x1f]')


def parse_text(value, field, label, max_len=255, required=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise InventoryError(f"{label} ko'rsatilishi shart.", field)
        return None
    if isinstance(value, (dict, list, bool)):
        raise InventoryError(f"{label} noto'g'ri.", field)
    text = re.sub(r'\s+', ' ', str(value)).strip()
    if _BAD_TEXT.search(text):
        raise InventoryError(f"{label}da ruxsat etilmagan belgilar bor.", field)
    if len(text) > max_len:
        raise InventoryError(f"{label} {max_len} belgidan oshmasligi kerak.", field)
    return text


def parse_flag(value, field, label, default):
    if value is None or value == '':
        return default
    if value in (True, 1, '1', 'true', 'True'):
        return 1
    if value in (False, 0, '0', 'false', 'False'):
        return 0
    raise InventoryError(f"{label} noto'g'ri qiymat.", field)


def parse_unit(value, field, label, default=None):
    if value in (None, ''):
        return default
    unit = str(value).strip().lower()
    if unit not in UNITS:
        raise InventoryError(f"{label} noto'g'ri. Ruxsat etilgan: {', '.join(UNITS)}.", field)
    return unit


def parse_reason(value, field='reason', required=True):
    reason = parse_text(value, field, 'Sabab', 500, required)
    if reason is not None and len(reason) < 3:
        raise InventoryError("Sabab kamida 3 ta belgidan iborat bo'lishi kerak.", field)
    return reason


def _actor_ref(cur, actor):
    """(username, staff_id) of whoever acts; a staff id that does not exist is dropped."""
    actor = actor or {}
    staff_id = actor.get('staff_id') or None
    if staff_id:
        cur.execute("SELECT 1 FROM staff WHERE id = ? LIMIT 1", (staff_id,))
        if not cur.fetchone():
            staff_id = None
    return (str(actor.get('username') or 'system')[:128], staff_id)


# ---------------------------------------------------------------------------
# Schema / migration
# ---------------------------------------------------------------------------
_ENGINE = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

_TABLE_DDL = [
    ('settings', f"""
CREATE TABLE IF NOT EXISTS inventory_settings (
    setting_key VARCHAR(64) NOT NULL PRIMARY KEY,
    setting_value VARCHAR(255) NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) {_ENGINE}"""),
    ('suppliers', f"""
CREATE TABLE IF NOT EXISTS inventory_suppliers (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(64) NULL,
    address VARCHAR(255) NULL,
    notes TEXT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_inv_supplier_name (name)
) {_ENGINE}"""),
    ('receipts', f"""
CREATE TABLE IF NOT EXISTS inventory_receipts (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    supplier_id VARCHAR(64) NULL,
    supplier_name VARCHAR(255) NULL,
    invoice_number VARCHAR(128) NULL,
    receipt_date DATE NOT NULL,
    payment_method VARCHAR(32) NOT NULL DEFAULT 'cash' CHECK(payment_method IN (
        'cash', 'cash_register', 'terminal', 'card_transfer', 'payme_click', 'bank_wire'
    )),
    status VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'posted', 'reversed', 'cancelled')),
    notes TEXT NULL,
    total_amount DECIMAL(18,2) NOT NULL DEFAULT 0.00,
    client_request_id VARCHAR(64) NULL,
    accounting_transaction_id VARCHAR(128) NULL,
    accounting_transaction_ref VARCHAR(128) NULL,
    created_by VARCHAR(128) NULL,
    created_by_staff_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    posted_at DATETIME NULL,
    posted_by VARCHAR(128) NULL,
    cancelled_at DATETIME NULL,
    reversed_at DATETIME NULL,
    reversed_by VARCHAR(128) NULL,
    reverse_reason VARCHAR(500) NULL,
    UNIQUE KEY uq_inv_receipt_client (client_request_id),
    KEY idx_inv_receipt_date (receipt_date, status),
    KEY idx_inv_receipt_supplier (supplier_id),
    CONSTRAINT fk_inv_receipt_supplier FOREIGN KEY (supplier_id)
        REFERENCES inventory_suppliers(id) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_inv_receipt_acc FOREIGN KEY (accounting_transaction_id)
        REFERENCES accounting_transactions(id) ON UPDATE CASCADE ON DELETE SET NULL
) {_ENGINE}"""),
    ('receipt_lines', f"""
CREATE TABLE IF NOT EXISTS inventory_receipt_lines (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    receipt_id VARCHAR(64) NOT NULL,
    line_no INT NOT NULL,
    item_id VARCHAR(64) NOT NULL,
    item_name VARCHAR(255) NOT NULL,
    packages DECIMAL(14,3) NOT NULL CHECK(packages > 0),
    units_per_package DECIMAL(14,3) NOT NULL CHECK(units_per_package > 0),
    quantity_base DECIMAL(14,3) NOT NULL CHECK(quantity_base > 0),
    package_price DECIMAL(18,2) NOT NULL CHECK(package_price >= 0),
    unit_cost DECIMAL(18,4) NOT NULL CHECK(unit_cost >= 0),
    line_total DECIMAL(18,2) NOT NULL CHECK(line_total >= 0),
    batch_no VARCHAR(64) NULL,
    expiry_date DATE NULL,
    batch_id BIGINT NULL,
    KEY idx_inv_line_receipt (receipt_id, line_no),
    KEY idx_inv_line_item (item_id),
    CONSTRAINT fk_inv_line_receipt FOREIGN KEY (receipt_id)
        REFERENCES inventory_receipts(id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_inv_line_item FOREIGN KEY (item_id)
        REFERENCES medications_catalog(id) ON UPDATE CASCADE ON DELETE RESTRICT
) {_ENGINE}"""),
    ('batches', f"""
CREATE TABLE IF NOT EXISTS inventory_batches (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    item_id VARCHAR(64) NOT NULL,
    batch_no VARCHAR(64) NOT NULL,
    expiry_date DATE NULL,
    received_qty DECIMAL(14,3) NOT NULL CHECK(received_qty > 0),
    remaining_qty DECIMAL(14,3) NOT NULL CHECK(remaining_qty >= 0),
    unit_cost DECIMAL(18,4) NOT NULL DEFAULT 0 CHECK(unit_cost >= 0),
    source VARCHAR(16) NOT NULL DEFAULT 'receipt',
    receipt_id VARCHAR(64) NULL,
    receipt_line_id BIGINT NULL,
    supplier_id VARCHAR(64) NULL,
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_inv_batch_item (item_id, expiry_date, id),
    KEY idx_inv_batch_receipt (receipt_id),
    CONSTRAINT chk_inv_batch_le CHECK(remaining_qty <= received_qty),
    CONSTRAINT fk_inv_batch_item FOREIGN KEY (item_id)
        REFERENCES medications_catalog(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_inv_batch_receipt FOREIGN KEY (receipt_id)
        REFERENCES inventory_receipts(id) ON UPDATE CASCADE ON DELETE SET NULL
) {_ENGINE}"""),
    ('transactions', f"""
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    txn_type VARCHAR(24) NOT NULL CHECK(txn_type IN (
        'receipt', 'dispense', 'adjustment_in', 'adjustment_out', 'supplier_return',
        'patient_return', 'writeoff', 'reversal', 'opening'
    )),
    item_id VARCHAR(64) NOT NULL,
    batch_id BIGINT NULL,
    qty_delta DECIMAL(14,3) NOT NULL CHECK(qty_delta <> 0),
    balance_before DECIMAL(14,3) NOT NULL,
    balance_after DECIMAL(14,3) NOT NULL,
    unit_cost DECIMAL(18,4) NOT NULL DEFAULT 0,
    value_delta DECIMAL(18,2) NOT NULL DEFAULT 0.00,
    source VARCHAR(24) NULL,
    operation_id VARCHAR(64) NULL,
    patient_id VARCHAR(64) NULL,
    prescription_id VARCHAR(64) NULL,
    consultation_id VARCHAR(64) NULL,
    admission_id VARCHAR(64) NULL,
    receipt_id VARCHAR(64) NULL,
    dispensing_id VARCHAR(64) NULL,
    supplier_id VARCHAR(64) NULL,
    accounting_transaction_id VARCHAR(128) NULL,
    performed_by VARCHAR(128) NULL,
    performed_by_staff_id VARCHAR(64) NULL,
    reason VARCHAR(500) NULL,
    notes TEXT NULL,
    reversal_of BIGINT NULL,
    client_request_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_inv_txn_reversal (reversal_of),
    UNIQUE KEY uq_inv_txn_client (client_request_id),
    KEY idx_inv_txn_item (item_id, id),
    KEY idx_inv_txn_patient (patient_id),
    KEY idx_inv_txn_created (created_at),
    KEY idx_inv_txn_operation (operation_id),
    KEY idx_inv_txn_dispensing (dispensing_id),
    KEY idx_inv_txn_receipt (receipt_id),
    CONSTRAINT fk_inv_txn_item FOREIGN KEY (item_id)
        REFERENCES medications_catalog(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_inv_txn_batch FOREIGN KEY (batch_id)
        REFERENCES inventory_batches(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_inv_txn_reversal FOREIGN KEY (reversal_of)
        REFERENCES inventory_transactions(id) ON UPDATE CASCADE ON DELETE RESTRICT
) {_ENGINE}"""),
    ('dispensings', f"""
CREATE TABLE IF NOT EXISTS inventory_dispensings (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    client_request_id VARCHAR(64) NULL,
    patient_id VARCHAR(64) NOT NULL,
    patient_name VARCHAR(255) NULL,
    prescription_id VARCHAR(64) NULL,
    consultation_id VARCHAR(64) NULL,
    admission_id VARCHAR(64) NULL,
    item_id VARCHAR(64) NOT NULL,
    item_name VARCHAR(255) NOT NULL,
    base_unit VARCHAR(32) NULL,
    quantity DECIMAL(14,3) NOT NULL CHECK(quantity > 0),
    unit_cost DECIMAL(18,4) NOT NULL DEFAULT 0,
    total_cost DECIMAL(18,2) NOT NULL DEFAULT 0.00,
    dosage VARCHAR(128) NULL,
    route VARCHAR(64) NULL,
    frequency VARCHAR(64) NULL,
    instructions TEXT NULL,
    rx_doctor_id VARCHAR(64) NULL,
    rx_doctor_name VARCHAR(255) NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'manual' CHECK(source IN ('manual', 'nurse_round', 'billing')),
    status VARCHAR(16) NOT NULL DEFAULT 'completed' CHECK(status IN ('completed', 'reversed')),
    notes TEXT NULL,
    dispensed_by VARCHAR(128) NULL,
    dispensed_by_staff_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reversed_at DATETIME NULL,
    reversed_by VARCHAR(128) NULL,
    reverse_reason VARCHAR(500) NULL,
    UNIQUE KEY uq_inv_disp_client (client_request_id),
    KEY idx_inv_disp_patient (patient_id, created_at),
    KEY idx_inv_disp_item (item_id, created_at),
    KEY idx_inv_disp_rx (prescription_id, status),
    CONSTRAINT fk_inv_disp_item FOREIGN KEY (item_id)
        REFERENCES medications_catalog(id) ON UPDATE CASCADE ON DELETE RESTRICT
) {_ENGINE}"""),
    ('dispensing_batches', f"""
CREATE TABLE IF NOT EXISTS inventory_dispensing_batches (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    dispensing_id VARCHAR(64) NOT NULL,
    batch_id BIGINT NOT NULL,
    batch_no VARCHAR(64) NULL,
    expiry_date DATE NULL,
    quantity DECIMAL(14,3) NOT NULL CHECK(quantity > 0),
    unit_cost DECIMAL(18,4) NOT NULL DEFAULT 0,
    txn_id BIGINT NULL,
    KEY idx_inv_dbatch_disp (dispensing_id),
    CONSTRAINT fk_inv_dbatch_disp FOREIGN KEY (dispensing_id)
        REFERENCES inventory_dispensings(id) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_inv_dbatch_batch FOREIGN KEY (batch_id)
        REFERENCES inventory_batches(id) ON UPDATE CASCADE ON DELETE RESTRICT
) {_ENGINE}"""),
    ('alerts', f"""
CREATE TABLE IF NOT EXISTS inventory_alerts (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    item_id VARCHAR(64) NOT NULL,
    alert_type VARCHAR(24) NOT NULL CHECK(alert_type IN ('low_stock', 'out_of_stock', 'expired', 'expiring_soon')),
    batch_id BIGINT NULL,
    batch_key BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(12) NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'resolved')),
    active_marker TINYINT NULL,
    message VARCHAR(255) NULL,
    quantity DECIMAL(14,3) NULL,
    threshold DECIMAL(14,3) NULL,
    expiry_date DATE NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME NULL,
    UNIQUE KEY uq_inv_alert_active (item_id, alert_type, batch_key, active_marker),
    KEY idx_inv_alert_status (status, alert_type),
    CONSTRAINT fk_inv_alert_item FOREIGN KEY (item_id)
        REFERENCES medications_catalog(id) ON UPDATE CASCADE ON DELETE CASCADE
) {_ENGINE}"""),
]

# Columns added to medications_catalog (name, DDL fragment). A fresh install
# has them in data/schema.mysql.sql; an older database gets them here.
_ITEM_COLUMNS = [
    ('sku', "VARCHAR(64) NULL"),
    ('barcode', "VARCHAR(64) NULL"),
    ('generic_name', "VARCHAR(255) NULL"),
    ('strength', "VARCHAR(64) NULL"),
    ('manufacturer', "VARCHAR(255) NULL"),
    ('item_type', "VARCHAR(24) NOT NULL DEFAULT 'medicine' CHECK(item_type IN ("
                  "'medicine', 'vitamin', 'injection', 'syringe', 'consumable', 'equipment', 'other'))"),
    ('description', "TEXT NULL"),
    ('base_unit', "VARCHAR(32) NOT NULL DEFAULT 'dona'"),
    ('package_unit', "VARCHAR(32) NULL"),
    ('units_per_package', "DECIMAL(14,3) NOT NULL DEFAULT 1 CHECK(units_per_package > 0)"),
    ('allow_fraction', "TINYINT(1) NOT NULL DEFAULT 0"),
    ('track_expiry', "TINYINT(1) NOT NULL DEFAULT 0"),
    ('supplier_id', "VARCHAR(64) NULL"),
    ('last_package_price', "DECIMAL(18,2) NULL"),
    ('last_unit_cost', "DECIMAL(18,4) NULL"),
    ('avg_unit_cost', "DECIMAL(18,4) NOT NULL DEFAULT 0"),
    ('updated_at', "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
]

LOW_STOCK_VIEW_DDL = """
CREATE OR REPLACE VIEW v_pharmacy_low_stock AS
SELECT
    id AS medication_id,
    name AS medication_name,
    category,
    form,
    stock_quantity,
    min_stock_level,
    (min_stock_level - stock_quantity) AS deficit_quantity,
    unit_price
FROM medications_catalog
WHERE stock_quantity < min_stock_level AND is_active = 1
ORDER BY (stock_quantity - min_stock_level) ASC"""

_TRIGGERS = [
    ('trg_inv_txn_no_update',
     "CREATE TRIGGER trg_inv_txn_no_update BEFORE UPDATE ON inventory_transactions "
     "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'inventory_transactions is append-only'"),
    ('trg_inv_txn_no_delete',
     "CREATE TRIGGER trg_inv_txn_no_delete BEFORE DELETE ON inventory_transactions "
     "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'inventory_transactions is append-only'"),
]

_schema_ready = False


def _step(label, fn):
    """One migration step in its own try: a failure is logged, the rest still run."""
    try:
        fn()
        return True
    except Exception as e:
        print(f"[!] inventory schema step '{label}' failed: {e}")
        return False


def _column_exists(cur, table, column):
    cur.execute("""SELECT 1 FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?""",
                (table, column))
    return cur.fetchone() is not None


def _column_type(cur, table, column):
    cur.execute("""SELECT DATA_TYPE AS t FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?""",
                (table, column))
    row = cur.fetchone()
    return (row or {}).get('t')


def _constraint_exists(cur, table, name):
    cur.execute("""SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND CONSTRAINT_NAME = ?""",
                (table, name))
    return cur.fetchone() is not None


def _index_exists(cur, table, name):
    cur.execute("""SELECT 1 FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND INDEX_NAME = ? LIMIT 1""",
                (table, name))
    return cur.fetchone() is not None


def ensure_schema(conn):
    """
    Create or upgrade everything the warehouse needs. Idempotent, safe to run on
    every start. Each step has its own try and its own log line: the server's
    old migrations shared one try and a single failure skipped the rest.
    """
    global _schema_ready
    cur = _cursor(conn)
    ok = True

    def _commit():
        conn.commit()

    # 1. New tables, in dependency order.
    for name, ddl in _TABLE_DDL:
        def _make(ddl=ddl):
            cur.execute(ddl)
            _commit()
        ok &= _step(f'create inventory_{name}', _make)

    # 2. New columns on the item table.
    added = set()
    for col, frag in _ITEM_COLUMNS:
        def _add(col=col, frag=frag):
            if not _column_exists(cur, 'medications_catalog', col):
                cur.execute(f"ALTER TABLE medications_catalog ADD COLUMN {col} {frag}")
                added.add(col)
                _commit()
        ok &= _step(f'add medications_catalog.{col}', _add)

    # 3. Constraints and indexes on the item table.
    def _sku_unique():
        if not _index_exists(cur, 'medications_catalog', 'uq_med_sku'):
            cur.execute("ALTER TABLE medications_catalog ADD UNIQUE INDEX uq_med_sku (sku)")
            _commit()
    ok &= _step('unique sku', _sku_unique)

    def _supplier_fk():
        if not _constraint_exists(cur, 'medications_catalog', 'fk_med_supplier'):
            cur.execute("""ALTER TABLE medications_catalog ADD CONSTRAINT fk_med_supplier
                           FOREIGN KEY (supplier_id) REFERENCES inventory_suppliers(id)
                           ON UPDATE CASCADE ON DELETE SET NULL""")
            _commit()
    ok &= _step('supplier foreign key', _supplier_fk)

    # 4. Whole numbers become fractions: stock and threshold are DECIMAL(14,3).
    def _decimal_stock():
        if _column_type(cur, 'medications_catalog', 'stock_quantity') != 'decimal':
            cur.execute("ALTER TABLE medications_catalog "
                        "MODIFY stock_quantity DECIMAL(14,3) NOT NULL DEFAULT 0")
            _commit()
    ok &= _step('stock_quantity decimal', _decimal_stock)

    def _decimal_min():
        if _column_type(cur, 'medications_catalog', 'min_stock_level') != 'decimal':
            cur.execute("ALTER TABLE medications_catalog "
                        "MODIFY min_stock_level DECIMAL(14,3) NOT NULL DEFAULT 10")
            _commit()
    ok &= _step('min_stock_level decimal', _decimal_min)

    # 5. Prescriptions: how much was prescribed (optional; NULL = not stated).
    def _rx_cols():
        if not _column_exists(cur, 'prescriptions', 'quantity_prescribed'):
            cur.execute("ALTER TABLE prescriptions ADD COLUMN quantity_prescribed DECIMAL(14,3) NULL")
            _commit()
        if not _column_exists(cur, 'prescriptions', 'quantity_unit'):
            cur.execute("ALTER TABLE prescriptions ADD COLUMN quantity_unit VARCHAR(32) NULL")
            _commit()
    ok &= _step('prescriptions quantity columns', _rx_cols)

    # 6. Sensible starting values for the new columns of existing rows. Only
    #    for columns added in THIS run, so a person's later edits are never
    #    overwritten. No cost is invented: avg_unit_cost stays 0.
    def _derive_units():
        if 'base_unit' in added:
            cur.execute("""
                UPDATE medications_catalog SET base_unit = CASE
                    WHEN LOWER(form) LIKE '%ampul%' THEN 'ampula'
                    WHEN LOWER(form) LIKE '%flakon%' THEN 'flakon'
                    WHEN LOWER(form) LIKE '%tablet%' THEN 'tabletka'
                    WHEN LOWER(form) LIKE '%kapsul%' THEN 'kapsula'
                    ELSE 'dona' END""")
            _commit()
    ok &= _step('derive base_unit', _derive_units)

    def _derive_types():
        if 'item_type' in added:
            cur.execute("""
                UPDATE medications_catalog SET item_type = CASE
                    WHEN LOWER(category) LIKE '%vitamin%' THEN 'vitamin'
                    WHEN LOWER(form) LIKE '%ampul%' OR LOWER(form) LIKE '%flakon%' THEN 'injection'
                    ELSE 'medicine' END""")
            _commit()
    ok &= _step('derive item_type', _derive_types)

    # 7. Settings.
    def _settings():
        for key, value in _SETTING_DEFAULTS.items():
            cur.execute("INSERT IGNORE INTO inventory_settings (setting_key, setting_value) "
                        "VALUES (?, ?)", (key, value))
        _commit()
    ok &= _step('settings', _settings)

    # 8. Opening balance: stock that existed before the ledger gets one opening
    #    lot (cost 0: the real cost is unknown and is not guessed) and one
    #    `opening` ledger row, so batches and ledger reconcile with the balance.
    def _opening():
        cur.execute("""
            SELECT mc.id, mc.stock_quantity FROM medications_catalog mc
            WHERE mc.stock_quantity > 0
              AND NOT EXISTS (SELECT 1 FROM inventory_transactions t WHERE t.item_id = mc.id)
              AND NOT EXISTS (SELECT 1 FROM inventory_batches b WHERE b.item_id = mc.id)""")
        rows = cur.fetchall()
        for r in rows:
            qty = _q(_dec(r['stock_quantity']))
            cur.execute("""INSERT INTO inventory_batches
                           (item_id, batch_no, expiry_date, received_qty, remaining_qty,
                            unit_cost, source) VALUES (?, 'OCHILISH', NULL, ?, ?, 0, 'opening')""",
                        (r['id'], qty, qty))
            batch_id = cur.lastrowid
            cur.execute("""INSERT INTO inventory_transactions
                           (txn_type, item_id, batch_id, qty_delta, balance_before, balance_after,
                            unit_cost, value_delta, source, operation_id, performed_by, reason)
                           VALUES ('opening', ?, ?, ?, 0, ?, 0, 0, 'migration', 'OPENING', 'system',
                                   ?)""",
                        (r['id'], batch_id, qty, qty, "Ombor hisobi yuritila boshlagandagi qoldiq"))
        _commit()
        if rows:
            print(f"[✓] Warehouse opening balance written for {len(rows)} item(s).")
    ok &= _step('opening balances', _opening)
    # The tables, columns and opening lots are what the services need; a missing
    # trigger or view is logged but must not make every call re-run the migration.
    core_ok = ok

    # 9. The ledger is append-only: the database refuses UPDATE and DELETE.
    #    Creating triggers needs the TRIGGER privilege and, with binary logging
    #    on, log_bin_trust_function_creators=1 or SUPER. Where the app user
    #    lacks that, the log says so and an administrator applies the two
    #    statements from data/schema.mysql.sql once.
    for tname, ddl in _TRIGGERS:
        def _trigger(tname=tname, ddl=ddl):
            cur.execute("""SELECT 1 FROM information_schema.TRIGGERS
                           WHERE TRIGGER_SCHEMA = DATABASE() AND TRIGGER_NAME = ?""", (tname,))
            if not cur.fetchone():
                cur.execute(ddl)
                _commit()
        ok &= _step(f'trigger {tname}', _trigger)

    # 10. Low stock means strictly below the threshold (was <=).
    def _view():
        cur.execute(LOW_STOCK_VIEW_DDL)
        _commit()
    ok &= _step('low stock view', _view)

    # 11. Alerts reflect the state right now.
    def _alerts():
        refresh_alerts(conn)
        _commit()
    ok &= _step('refresh alerts', _alerts)

    try:
        conn.rollback()
    except Exception:
        pass
    if core_ok:
        _schema_ready = True
    return ok


def ensure_ready(conn):
    """Run the migration once per process (cheap guard for services and tests)."""
    if not _schema_ready:
        ensure_schema(conn)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(cur, key):
    cur.execute("SELECT setting_value FROM inventory_settings WHERE setting_key = ?", (key,))
    row = cur.fetchone()
    return row['setting_value'] if row else _SETTING_DEFAULTS.get(key)


def default_min_stock(cur):
    try:
        return _q(Decimal(str(get_setting(cur, SETTING_DEFAULT_MIN))))
    except Exception:
        return _q(Decimal(_SETTING_DEFAULTS[SETTING_DEFAULT_MIN]))


def expiry_warning_days(cur):
    try:
        return max(0, int(get_setting(cur, SETTING_EXPIRY_DAYS)))
    except Exception:
        return int(_SETTING_DEFAULTS[SETTING_EXPIRY_DAYS])


def get_settings(conn):
    cur = _cursor(conn)
    return {'default_min_stock': default_min_stock(cur),
            'expiry_warning_days': expiry_warning_days(cur),
            'units': list(UNITS),
            'item_types': [{'id': t, 'label': ITEM_TYPE_LABELS[t]} for t in ITEM_TYPES]}


# ---------------------------------------------------------------------------
# Status (pure functions, so the rule lives in one place)
# ---------------------------------------------------------------------------

def compute_status(available, minimum, expired=ZERO, expiring=ZERO):
    """
    ok | low | out | expired | expiring.

    out: nothing usable (available <= 0). low: STRICTLY below the threshold, so
    stock equal to the threshold is still fine. Only an item that is neither
    out nor low is reported as expired / expiring, so the more urgent state
    wins; the quantities themselves are always returned alongside.
    """
    available, minimum = _dec(available), _dec(minimum)
    if available <= 0:
        return 'out'
    if available < minimum:
        return 'low'
    if _dec(expired) > 0:
        return 'expired'
    if _dec(expiring) > 0:
        return 'expiring'
    return 'ok'


COST_ITEM_FIELDS = ('last_package_price', 'last_unit_cost', 'avg_unit_cost', 'stock_value',
                    'expired_value', 'available_value')


def strip_costs(row, fields):
    for f in fields:
        row.pop(f, None)
    return row


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
_ITEM_SELECT = """
    SELECT mc.id, mc.sku, mc.barcode, mc.name, mc.generic_name, mc.item_type, mc.category,
           mc.strength, mc.form, mc.standard_dosage, mc.manufacturer, mc.description,
           mc.base_unit, mc.package_unit, mc.units_per_package, mc.allow_fraction,
           mc.track_expiry, mc.supplier_id, s.name AS supplier_name,
           mc.min_stock_level, mc.stock_quantity, mc.unit_price,
           mc.last_package_price, mc.last_unit_cost, mc.avg_unit_cost,
           mc.is_active, mc.created_at, mc.updated_at,
           COALESCE(b.avail_qty, 0) AS available_quantity,
           COALESCE(b.expired_qty, 0) AS expired_quantity,
           COALESCE(b.expiring_qty, 0) AS expiring_quantity,
           b.nearest_expiry AS nearest_expiry
    FROM medications_catalog mc
    LEFT JOIN inventory_suppliers s ON s.id = mc.supplier_id
    LEFT JOIN (
        SELECT item_id,
               SUM(CASE WHEN expiry_date IS NOT NULL AND expiry_date < ? THEN remaining_qty ELSE 0 END) AS expired_qty,
               SUM(CASE WHEN expiry_date IS NULL OR expiry_date >= ? THEN remaining_qty ELSE 0 END) AS avail_qty,
               SUM(CASE WHEN expiry_date IS NOT NULL AND expiry_date >= ? AND expiry_date <= ?
                        THEN remaining_qty ELSE 0 END) AS expiring_qty,
               MIN(CASE WHEN expiry_date >= ? THEN expiry_date END) AS nearest_expiry
        FROM inventory_batches WHERE remaining_qty > 0 GROUP BY item_id
    ) b ON b.item_id = mc.id
"""


def _agg_params(today, warn_days):
    return [today, today, today, today + _dt.timedelta(days=warn_days), today]


def _item_view(row, today=None):
    """Derived fields on one item row (status, shortage, values)."""
    row = dict(row)
    avail = _dec(row['available_quantity'])
    expired = _dec(row['expired_quantity'])
    expiring = _dec(row['expiring_quantity'])
    minimum = _dec(row['min_stock_level'])
    avg = _dec(row['avg_unit_cost'])
    row['available_quantity'] = _q(avail)
    row['expired_quantity'] = _q(expired)
    row['expiring_quantity'] = _q(expiring)
    row['stock_status'] = compute_status(avail, minimum, expired, expiring)
    row['shortage'] = _q(max(minimum - avail, ZERO))
    row['stock_value'] = _m((avail + expired) * avg)
    row['expired_value'] = _m(expired * avg)
    row['available_value'] = _m(avail * avg)
    row['is_active'] = int(row['is_active'])
    row['allow_fraction'] = int(row['allow_fraction'])
    row['track_expiry'] = int(row['track_expiry'])
    return row


def _fetch_items(cur, where='', params=(), today=None, order='ORDER BY mc.name'):
    today = today or _today()
    days = expiry_warning_days(cur)
    cur.execute(_ITEM_SELECT + ' ' + where + ' ' + order, _agg_params(today, days) + list(params))
    return [_item_view(r) for r in cur.fetchall()]


def _get_item_row(cur, item_id):
    rows = _fetch_items(cur, 'WHERE mc.id = ?', (item_id,))
    if not rows:
        raise NotFound("Mahsulot topilmadi.")
    return rows[0]


def list_items(conn, filters=None, can_cost=False):
    """Filtered, sorted, paginated item rows -> (items, total)."""
    f = filters or {}
    cur = _cursor(conn)
    where, params = [], []
    q = (f.get('q') or '').strip()
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where.append("(mc.name LIKE ? OR mc.generic_name LIKE ? OR mc.sku LIKE ? OR mc.barcode LIKE ?)")
        params += [like] * 4
    for key, col in (('category', 'mc.category'), ('item_type', 'mc.item_type'),
                     ('supplier_id', 'mc.supplier_id')):
        if f.get(key):
            where.append(f"{col} = ?")
            params.append(f[key])
    if f.get('active') in ('0', '1', 0, 1):
        where.append("mc.is_active = ?")
        params.append(int(f['active']))
    clause = ('WHERE ' + ' AND '.join(where)) if where else ''
    items = _fetch_items(cur, clause, params, order='')
    status = f.get('status')
    if status:
        if status == 'expired':
            items = [i for i in items if i['expired_quantity'] > 0]
        elif status == 'expiring':
            items = [i for i in items if i['expiring_quantity'] > 0]
        else:
            items = [i for i in items if i['stock_status'] == status]
    sort = f.get('sort') or 'name'
    if sort not in ('name', 'category', 'stock_quantity', 'available_quantity', 'nearest_expiry',
                    'stock_status', 'min_stock_level', 'stock_value', 'shortage'):
        sort = 'name'
    if sort == 'stock_value' and not can_cost:
        sort = 'name'
    reverse = (f.get('dir') or 'asc').lower() == 'desc'

    def key(i):
        v = i.get(sort)
        if sort == 'nearest_expiry':
            return (v is None, v or _dt.date.max)
        if isinstance(v, str):
            return (False, v.lower())
        return (False, v if v is not None else ZERO)
    items.sort(key=key, reverse=reverse)
    total = len(items)
    limit = max(1, min(int(f.get('limit') or 100), 500))
    offset = max(0, int(f.get('offset') or 0))
    page = items[offset:offset + limit]
    if not can_cost:
        for i in page:
            strip_costs(i, COST_ITEM_FIELDS)
    return page, total


def get_item(conn, item_id, can_cost=False):
    cur = _cursor(conn)
    item = _get_item_row(cur, item_id)
    cur.execute("""SELECT id, batch_no, expiry_date, received_qty, remaining_qty, unit_cost,
                          source, receipt_id, supplier_id, received_at
                   FROM inventory_batches WHERE item_id = ?
                   ORDER BY (remaining_qty = 0), (expiry_date IS NULL), expiry_date, received_at, id
                   LIMIT 100""", (item_id,))
    batches = cur.fetchall()
    today = _today()
    for b in batches:
        b['is_expired'] = bool(b['expiry_date'] and b['expiry_date'] < today)
    cur.execute("""SELECT * FROM inventory_transactions WHERE item_id = ?
                   ORDER BY id DESC LIMIT 20""", (item_id,))
    ledger = cur.fetchall()
    if not can_cost:
        strip_costs(item, COST_ITEM_FIELDS)
        for b in batches:
            b.pop('unit_cost', None)
        for t in ledger:
            _strip_txn(t)
    item['batches'] = batches
    item['ledger'] = ledger
    return item


def _strip_txn(t):
    for k in ('unit_cost', 'value_delta', 'accounting_transaction_id'):
        t.pop(k, None)
    return t


def _clean_item_fields(data, cur, existing=None, can_cost=False, creating=False):
    """
    Validate item fields. Returns a dict of column -> value for the fields that
    were present (all of them when creating). Threshold and patient price are
    accounting's: a caller without that right who sends them is refused rather
    than silently ignored.
    """
    out = {}
    has = lambda k: k in data  # noqa: E731
    if creating or has('name'):
        out['name'] = parse_text(data.get('name'), 'name', 'Nomi', 255, required=True)
    if has('generic_name'):
        out['generic_name'] = parse_text(data.get('generic_name'), 'generic_name', 'Xalqaro nomi', 255)
    if has('strength'):
        out['strength'] = parse_text(data.get('strength'), 'strength', 'Dozasi', 64)
    if has('manufacturer'):
        out['manufacturer'] = parse_text(data.get('manufacturer'), 'manufacturer', 'Ishlab chiqaruvchi', 255)
    if has('description'):
        out['description'] = parse_text(data.get('description'), 'description', 'Izoh', 2000)
    if has('standard_dosage'):
        out['standard_dosage'] = parse_text(data.get('standard_dosage'), 'standard_dosage', 'Standart doza', 128)
    if has('sku'):
        sku = parse_text(data.get('sku'), 'sku', 'Artikul (SKU)', 64)
        out['sku'] = sku.upper() if sku else None
    if has('barcode'):
        out['barcode'] = parse_text(data.get('barcode'), 'barcode', 'Shtrix-kod', 64)
    if creating or has('item_type'):
        t = (data.get('item_type') or (existing or {}).get('item_type') or 'medicine')
        t = str(t).strip().lower()
        if t not in ITEM_TYPES:
            raise InventoryError(f"Mahsulot turi noto'g'ri. Ruxsat etilgan: {', '.join(ITEM_TYPES)}.", 'item_type')
        out['item_type'] = t
    if creating or has('base_unit'):
        out['base_unit'] = parse_unit(data.get('base_unit'), 'base_unit', "O'lchov birligi", 'dona')
    if has('package_unit'):
        out['package_unit'] = parse_unit(data.get('package_unit'), 'package_unit', 'Qadoq birligi', None)
    if creating or has('units_per_package'):
        upp = data.get('units_per_package')
        upp = parse_decimal(1 if upp in (None, '') else upp, 'units_per_package',
                            'Qadoqdagi miqdor', 3, ZERO, MAX_QTY)
        out['units_per_package'] = _q(upp)
    if creating or has('allow_fraction'):
        out['allow_fraction'] = parse_flag(data.get('allow_fraction'), 'allow_fraction', 'Kasr miqdor', 0)
    if creating or has('track_expiry'):
        out['track_expiry'] = parse_flag(data.get('track_expiry'), 'track_expiry', 'Yaroqlilik muddati', 0)
    # category and form are NOT NULL columns: blank on create means "use the
    # default", but a blank sent on an edit is refused rather than stored as NULL.
    if has('category') and (data.get('category') or not creating):
        out['category'] = parse_text(data.get('category'), 'category', 'Kategoriya', 128, required=True)
    if has('form') and (data.get('form') or not creating):
        out['form'] = parse_text(data.get('form'), 'form', 'Shakli', 64, required=True)
    if has('supplier_id'):
        sid = data.get('supplier_id') or None
        if sid:
            cur.execute("SELECT 1 FROM inventory_suppliers WHERE id = ?", (sid,))
            if not cur.fetchone():
                raise InventoryError("Yetkazib beruvchi topilmadi.", 'supplier_id')
        out['supplier_id'] = sid
    # Accounting-only fields.
    for fld, label in (('min_stock_level', 'Minimal qoldiq'), ('unit_price', 'Bemor narxi')):
        if has(fld) and data.get(fld) not in (None, ''):
            if not can_cost:
                raise Forbidden(f"{label}ni faqat buxgalter o'zgartira oladi.")
            if fld == 'min_stock_level':
                out[fld] = parse_qty(data[fld], fld, label, allow_zero=True)
            else:
                out[fld] = parse_money(data[fld], fld, label)
    # Fractions: a tablet is counted whole, a solution may be measured.
    frac = out.get('allow_fraction', (existing or {}).get('allow_fraction', 0))
    upp = out.get('units_per_package', (existing or {}).get('units_per_package', Decimal(1)))
    if not frac and not _is_whole(_dec(upp)):
        raise InventoryError("Kasr miqdorga ruxsat berilmagan mahsulotda qadoqdagi miqdor butun son bo'lishi kerak.",
                             'units_per_package')
    return out


def _find_duplicate_item(cur, name, strength, form, exclude_id=None):
    cur.execute("""SELECT id FROM medications_catalog
                   WHERE LOWER(name) = LOWER(?) AND COALESCE(LOWER(strength), '') = COALESCE(LOWER(?), '')
                     AND LOWER(form) = LOWER(?) AND (? IS NULL OR id <> ?) LIMIT 1""",
                (name, strength, form, exclude_id, exclude_id))
    return cur.fetchone()


def create_item(conn, data, actor=None, can_cost=False):
    ensure_ready(conn)
    cur = _cursor(conn)
    fields = _clean_item_fields(data, cur, None, can_cost, creating=True)
    fields.setdefault('category', ITEM_TYPE_LABELS.get(fields['item_type'], 'Boshqa'))
    fields.setdefault('form', fields['base_unit'])
    if 'min_stock_level' not in fields:
        fields['min_stock_level'] = default_min_stock(cur)
    fields.setdefault('unit_price', ZERO)
    dup = _find_duplicate_item(cur, fields['name'], fields.get('strength'), fields['form'])
    if dup:
        raise InventoryError("Bunday nom, doza va shakldagi mahsulot allaqachon mavjud.", 'name', 409)
    if fields.get('sku'):
        cur.execute("SELECT 1 FROM medications_catalog WHERE sku = ?", (fields['sku'],))
        if cur.fetchone():
            raise InventoryError("Bu artikul (SKU) boshqa mahsulotda ishlatilgan.", 'sku', 409)
    item_id = _gen_id(cur, 'medications_catalog', 'MED')
    cols = ['id'] + list(fields.keys())
    cur.execute(f"INSERT INTO medications_catalog ({', '.join(cols)}) "
                f"VALUES ({', '.join(['?'] * len(cols))})",
                [item_id] + list(fields.values()))
    refresh_alerts(conn, item_id)
    return _get_item_row(cur, item_id)


def update_item(conn, item_id, data, actor=None, can_cost=False):
    ensure_ready(conn)
    cur = _cursor(conn)
    cur.execute("SELECT * FROM medications_catalog WHERE id = ? FOR UPDATE", (item_id,))
    existing = cur.fetchone()
    if not existing:
        raise NotFound("Mahsulot topilmadi.")
    fields = _clean_item_fields(data, cur, existing, can_cost, creating=False)
    # An item with movements keeps its unit and its fraction rule: changing
    # them would silently change what every earlier quantity meant.
    cur.execute("SELECT COUNT(*) AS n FROM inventory_transactions WHERE item_id = ?", (item_id,))
    moved = int(cur.fetchone()['n']) > 0
    if moved and 'base_unit' in fields and fields['base_unit'] != existing['base_unit']:
        raise InventoryError("Harakatlar bo'lgan mahsulotning o'lchov birligini o'zgartirib bo'lmaydi.", 'base_unit')
    if ('allow_fraction' in fields and not fields['allow_fraction']
            and not _is_whole(_dec(existing['stock_quantity']))):
        raise InventoryError("Qoldiq kasr son: avval qoldiqni butun songa keltiring.", 'allow_fraction')
    if 'name' in fields or 'strength' in fields or 'form' in fields:
        dup = _find_duplicate_item(cur, fields.get('name', existing['name']),
                                   fields.get('strength', existing['strength']),
                                   fields.get('form', existing['form']), item_id)
        if dup:
            raise InventoryError("Bunday nom, doza va shakldagi mahsulot allaqachon mavjud.", 'name', 409)
    if fields.get('sku'):
        cur.execute("SELECT 1 FROM medications_catalog WHERE sku = ? AND id <> ?", (fields['sku'], item_id))
        if cur.fetchone():
            raise InventoryError("Bu artikul (SKU) boshqa mahsulotda ishlatilgan.", 'sku', 409)
    if fields:
        sets = ', '.join(f"{k} = ?" for k in fields)
        cur.execute(f"UPDATE medications_catalog SET {sets} WHERE id = ?",
                    list(fields.values()) + [item_id])
    refresh_alerts(conn, item_id)
    return _get_item_row(cur, item_id)


def set_threshold(conn, item_id, value, actor=None):
    ensure_ready(conn)
    cur = _cursor(conn)
    cur.execute("SELECT id FROM medications_catalog WHERE id = ? FOR UPDATE", (item_id,))
    if not cur.fetchone():
        raise NotFound("Mahsulot topilmadi.")
    level = parse_qty(value, 'min_stock_level', 'Minimal qoldiq', allow_zero=True)
    cur.execute("UPDATE medications_catalog SET min_stock_level = ? WHERE id = ?", (level, item_id))
    refresh_alerts(conn, item_id)
    return _get_item_row(cur, item_id)


def set_item_active(conn, item_id, active):
    ensure_ready(conn)
    cur = _cursor(conn)
    cur.execute("SELECT id FROM medications_catalog WHERE id = ? FOR UPDATE", (item_id,))
    if not cur.fetchone():
        raise NotFound("Mahsulot topilmadi.")
    cur.execute("UPDATE medications_catalog SET is_active = ? WHERE id = ?", (1 if active else 0, item_id))
    refresh_alerts(conn, item_id)
    return _get_item_row(cur, item_id)


def availability(conn, q=None, limit=30):
    """What a prescriber may see: name, unit, how much can be given. No costs."""
    cur = _cursor(conn)
    where, params = ["mc.is_active = 1"], []
    q = (q or '').strip()
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where.append("(mc.name LIKE ? OR mc.generic_name LIKE ?)")
        params += [like, like]
    items = _fetch_items(cur, 'WHERE ' + ' AND '.join(where), params, order='ORDER BY mc.name')
    out = []
    for i in items[:max(1, min(int(limit or 30), 100))]:
        row = {k: i[k] for k in ('id', 'name', 'generic_name', 'strength', 'form', 'item_type',
                                 'base_unit', 'allow_fraction')}
        row['available_quantity'] = i['available_quantity']
        row['stock_status'] = i['stock_status']
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

def list_suppliers(conn):
    cur = _cursor(conn)
    cur.execute("SELECT id, name, phone, address, notes, is_active, created_at "
                "FROM inventory_suppliers ORDER BY name")
    return cur.fetchall()


def create_supplier(conn, data, actor=None):
    ensure_ready(conn)
    cur = _cursor(conn)
    name = parse_text(data.get('name'), 'name', 'Yetkazib beruvchi nomi', 255, required=True)
    cur.execute("SELECT id FROM inventory_suppliers WHERE LOWER(name) = LOWER(?)", (name,))
    if cur.fetchone():
        raise InventoryError("Bunday yetkazib beruvchi allaqachon mavjud.", 'name', 409)
    sid = _gen_id(cur, 'inventory_suppliers', 'SUP')
    cur.execute("""INSERT INTO inventory_suppliers (id, name, phone, address, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (sid, name, parse_text(data.get('phone'), 'phone', 'Telefon', 64),
                 parse_text(data.get('address'), 'address', 'Manzil', 255),
                 parse_text(data.get('notes'), 'notes', 'Izoh', 2000)))
    cur.execute("SELECT * FROM inventory_suppliers WHERE id = ?", (sid,))
    return cur.fetchone()


def _find_or_create_supplier(cur, supplier_id, supplier_name):
    if supplier_id:
        cur.execute("SELECT id, name FROM inventory_suppliers WHERE id = ?", (supplier_id,))
        row = cur.fetchone()
        if not row:
            raise InventoryError("Yetkazib beruvchi topilmadi.", 'supplier_id')
        return row['id'], row['name']
    name = parse_text(supplier_name, 'supplier_name', 'Yetkazib beruvchi nomi', 255)
    if not name:
        return None, None
    cur.execute("SELECT id, name FROM inventory_suppliers WHERE LOWER(name) = LOWER(?)", (name,))
    row = cur.fetchone()
    if row:
        return row['id'], row['name']
    sid = _gen_id(cur, 'inventory_suppliers', 'SUP')
    cur.execute("INSERT INTO inventory_suppliers (id, name) VALUES (?, ?)", (sid, name))
    return sid, name


# ---------------------------------------------------------------------------
# Ledger and balance helpers
# ---------------------------------------------------------------------------

def _lock_item(cur, item_id):
    cur.execute("SELECT * FROM medications_catalog WHERE id = ? FOR UPDATE", (item_id,))
    row = cur.fetchone()
    if not row:
        raise NotFound("Mahsulot topilmadi.")
    return row


def _write_ledger(cur, txn_type, item_id, batch_id, qty_delta, balance_before, unit_cost,
                  actor_ref, **refs):
    """Append one ledger row and return its id."""
    qty_delta = _q(qty_delta)
    cur.execute("""
        INSERT INTO inventory_transactions
            (txn_type, item_id, batch_id, qty_delta, balance_before, balance_after,
             unit_cost, value_delta, source, operation_id, patient_id, prescription_id,
             consultation_id, admission_id, receipt_id, dispensing_id, supplier_id,
             accounting_transaction_id, performed_by, performed_by_staff_id, reason, notes,
             reversal_of, client_request_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (txn_type, item_id, batch_id, qty_delta, balance_before, _q(balance_before + qty_delta),
          _c(unit_cost), _m(qty_delta * _c(unit_cost)),
          refs.get('source'), refs.get('operation_id'), refs.get('patient_id'),
          refs.get('prescription_id'), refs.get('consultation_id'), refs.get('admission_id'),
          refs.get('receipt_id'), refs.get('dispensing_id'), refs.get('supplier_id'),
          refs.get('accounting_transaction_id'), actor_ref[0], actor_ref[1],
          refs.get('reason'), refs.get('notes'), refs.get('reversal_of'),
          refs.get('client_request_id')))
    return cur.lastrowid


def _set_balance(cur, item_id, new_balance, avg_cost=None, **extra):
    if _dec(new_balance) < 0:
        # The CHECK would refuse it anyway; say why in words and before any write
        # in the caller has been made visible.
        raise InventoryError("Ombor qoldig'i hisobi mos kelmayapti. Hisobotlar bo'limidagi "
                             "\"Solishtirish\" sahifasini tekshiring.", None, 409)
    sets, params = ["stock_quantity = ?"], [_q(new_balance)]
    if avg_cost is not None:
        sets.append("avg_unit_cost = ?")
        params.append(_c(avg_cost))
    for k, v in extra.items():
        sets.append(f"{k} = ?")
        params.append(v)
    cur.execute(f"UPDATE medications_catalog SET {', '.join(sets)} WHERE id = ?", params + [item_id])


def _usable_batches(cur, item_id, today, include_expired=False):
    """Lots in FEFO order, locked. Without expiry last (FIFO by received_at)."""
    clause = "" if include_expired else "AND (expiry_date IS NULL OR expiry_date >= ?)"
    params = [item_id] + ([] if include_expired else [today])
    cur.execute(f"""SELECT * FROM inventory_batches
                    WHERE item_id = ? AND remaining_qty > 0 {clause}
                    ORDER BY (expiry_date IS NULL), expiry_date, received_at, id FOR UPDATE""", params)
    return cur.fetchall()


def _quantity_for_item(value, item, field='quantity', label='Miqdor'):
    qty = parse_qty(value, field, label)
    if not int(item['allow_fraction']) and not _is_whole(qty):
        raise InventoryError(f"{item['name']} butun sonlarda hisoblanadi: kasr miqdor kiritib bo'lmaydi.", field)
    return qty


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

def _receipt_lines_in(cur, receipt_id):
    cur.execute("SELECT * FROM inventory_receipt_lines WHERE receipt_id = ? ORDER BY line_no", (receipt_id,))
    return cur.fetchall()


RECEIPT_COST_FIELDS = ('total_amount', 'payment_method', 'accounting_transaction_id',
                       'accounting_transaction_ref')
LINE_COST_FIELDS = ('package_price', 'unit_cost', 'line_total')


def get_receipt(conn, receipt_id, can_cost=False):
    cur = _cursor(conn)
    cur.execute("SELECT * FROM inventory_receipts WHERE id = ?", (receipt_id,))
    r = cur.fetchone()
    if not r:
        raise NotFound("Kirim hujjati topilmadi.")
    lines = _receipt_lines_in(cur, receipt_id)
    r['lines'] = lines
    if not can_cost:
        strip_costs(r, RECEIPT_COST_FIELDS)
        for ln in lines:
            strip_costs(ln, LINE_COST_FIELDS)
    return r


def list_receipts(conn, filters=None, can_cost=False):
    f = filters or {}
    cur = _cursor(conn)
    where, params = [], []
    if f.get('from'):
        where.append("r.receipt_date >= ?")
        params.append(f['from'])
    if f.get('to'):
        where.append("r.receipt_date <= ?")
        params.append(f['to'])
    if f.get('supplier_id'):
        where.append("r.supplier_id = ?")
        params.append(f['supplier_id'])
    if f.get('status'):
        where.append("r.status = ?")
        params.append(f['status'])
    clause = ('WHERE ' + ' AND '.join(where)) if where else ''
    limit = max(1, min(int(f.get('limit') or 100), 500))
    offset = max(0, int(f.get('offset') or 0))
    cur.execute(f"SELECT COUNT(*) AS n FROM inventory_receipts r {clause}", params)
    total = int(cur.fetchone()['n'])
    cur.execute(f"""SELECT r.*, (SELECT COUNT(*) FROM inventory_receipt_lines l WHERE l.receipt_id = r.id) AS line_count
                    FROM inventory_receipts r {clause}
                    ORDER BY r.receipt_date DESC, r.created_at DESC LIMIT ? OFFSET ?""",
                params + [limit, offset])
    rows = cur.fetchall()
    if not can_cost:
        for r in rows:
            strip_costs(r, RECEIPT_COST_FIELDS)
    return rows, total


def _prepare_line(cur, raw, line_no, receipt_date, today):
    """Validate one receipt line and work out base quantity and costs."""
    if not isinstance(raw, dict):
        raise InventoryError(f"{line_no}-qator noto'g'ri.", 'lines')
    where = f"{line_no}-qator: "
    try:
        item_id = raw.get('item_id')
        if not item_id and isinstance(raw.get('new_item'), dict):
            item = create_item_in_receipt(cur, raw['new_item'])
        else:
            if not item_id:
                raise InventoryError("Mahsulot tanlanmagan.", 'item_id')
            cur.execute("SELECT * FROM medications_catalog WHERE id = ?", (item_id,))
            item = cur.fetchone()
            if not item:
                raise InventoryError("Mahsulot topilmadi.", 'item_id')
        if not int(item['is_active']):
            raise InventoryError(f"{item['name']} faol emas: qabul qilib bo'lmaydi.", 'item_id')
        packages = parse_decimal(raw.get('packages'), 'packages', 'Qadoqlar soni', 3, ZERO, MAX_QTY)
        upp = raw.get('units_per_package')
        upp = _dec(item['units_per_package']) if upp in (None, '') else parse_decimal(
            upp, 'units_per_package', 'Qadoqdagi miqdor', 3, ZERO, MAX_QTY)
        qty = _q(packages * upp)
        if qty <= 0:
            raise InventoryError("Miqdor noldan katta bo'lishi kerak.", 'packages')
        if not int(item['allow_fraction']) and not _is_whole(qty):
            raise InventoryError(f"{item['name']} butun sonlarda hisoblanadi: {qty} dona chiqdi.", 'packages')
        price = parse_money(raw.get('package_price'), 'package_price', 'Qadoq narxi')
        expiry = parse_date(raw.get('expiry_date'), 'expiry_date', 'Yaroqlilik muddati')
        if int(item['track_expiry']) and not expiry:
            raise InventoryError(f"{item['name']} uchun yaroqlilik muddati kiritilishi shart.", 'expiry_date')
        if expiry and expiry < today:
            raise InventoryError(f"{item['name']}: muddati o'tgan mahsulotni qabul qilib bo'lmaydi.", 'expiry_date')
        batch_no = parse_text(raw.get('batch_no'), 'batch_no', 'Partiya raqami', 64)
        return {
            'item': item, 'item_id': item['id'], 'item_name': item['name'],
            'packages': _q(packages), 'units_per_package': _q(upp), 'quantity_base': qty,
            'package_price': price, 'unit_cost': _c(price / upp), 'line_total': _m(packages * price),
            'batch_no': batch_no, 'expiry_date': expiry,
        }
    except InventoryError as e:
        e.message = where + e.message
        e.args = (e.message,)
        raise


def create_item_in_receipt(cur, data):
    """An item created from inside a receipt (accounting's right, so costs are allowed)."""
    item = create_item(cur.conn, data, None, can_cost=True)
    cur.execute("SELECT * FROM medications_catalog WHERE id = ?", (item['id'],))
    return cur.fetchone()


def _find_by_client_id(cur, table, client_id, lock=False):
    cur.execute(f"SELECT id FROM {table} WHERE client_request_id = ?" + (" FOR UPDATE" if lock else ""),
                (client_id,))
    return cur.fetchone()


def _client_id(data, required=False):
    raw = data.get('client_request_id')
    if raw in (None, ''):
        if required:
            raise InventoryError("client_request_id majburiy (takroriy so'rovdan himoya).", 'client_request_id')
        return None
    s = str(raw).strip()
    if not re.match(r'^[A-Za-z0-9_-]{1,64}$', s):
        raise InventoryError("client_request_id faqat lotin harflari, raqamlar, '-' va '_' dan iborat bo'lishi kerak.",
                             'client_request_id')
    return s


def create_receipt(conn, data, actor=None, post=False, payment_method='cash', account_source_fn=None):
    """
    Create a draft receipt (post=True also posts it, in the same transaction).
    A repeated client_request_id returns the first receipt untouched.
    """
    ensure_ready(conn)
    cur = _cursor(conn)
    client_id = _client_id(data)
    if client_id:
        dup = _find_by_client_id(cur, 'inventory_receipts', client_id, lock=True)
        if dup:
            r = get_receipt(conn, dup['id'], can_cost=True)
            r['duplicate'] = True
            return r
    today = _today()
    receipt_date = parse_date(data.get('receipt_date'), 'receipt_date', 'Kirim sanasi') or today
    if receipt_date > today:
        raise InventoryError("Kirim sanasi kelajakda bo'lishi mumkin emas.", 'receipt_date')
    lines_in = data.get('lines')
    if not isinstance(lines_in, list) or not lines_in:
        raise InventoryError("Kamida bitta mahsulot qatori kiritilishi shart.", 'lines')
    if len(lines_in) > 200:
        raise InventoryError("Bitta hujjatda 200 tadan ortiq qator bo'lmaydi.", 'lines')
    sup_id, sup_name = _find_or_create_supplier(cur, data.get('supplier_id'), data.get('supplier_name'))
    invoice_number = parse_text(data.get('invoice_number'), 'invoice_number', 'Hisob-faktura raqami', 128)
    notes = parse_text(data.get('notes'), 'notes', 'Izoh', 2000)
    prepared = [_prepare_line(cur, raw, i + 1, receipt_date, today) for i, raw in enumerate(lines_in)]
    total = _m(sum((p['line_total'] for p in prepared), ZERO))
    username, staff_id = _actor_ref(cur, actor)
    rid = _gen_id(cur, 'inventory_receipts', 'RCP')
    cur.execute("""INSERT INTO inventory_receipts
                   (id, supplier_id, supplier_name, invoice_number, receipt_date, payment_method,
                    status, notes, total_amount, client_request_id, created_by, created_by_staff_id)
                   VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)""",
                (rid, sup_id, sup_name, invoice_number, receipt_date, payment_method,
                 notes, total, client_id, username, staff_id))
    for n, p in enumerate(prepared, start=1):
        batch_no = p['batch_no'] or f"{rid}-{n}"
        cur.execute("""INSERT INTO inventory_receipt_lines
                       (receipt_id, line_no, item_id, item_name, packages, units_per_package,
                        quantity_base, package_price, unit_cost, line_total, batch_no, expiry_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rid, n, p['item_id'], p['item_name'], p['packages'], p['units_per_package'],
                     p['quantity_base'], p['package_price'], p['unit_cost'], p['line_total'],
                     batch_no, p['expiry_date']))
    if post:
        return post_receipt(conn, rid, actor, account_source_fn)
    r = get_receipt(conn, rid, can_cost=True)
    r['duplicate'] = False
    return r


def post_receipt(conn, receipt_id, actor=None, account_source_fn=None):
    """
    Turn a draft into stock: lots, ledger, weighted-average cost, item balance,
    the accounting expense and alerts, all in the caller's one transaction.
    """
    ensure_ready(conn)
    cur = _cursor(conn)
    cur.execute("SELECT * FROM inventory_receipts WHERE id = ? FOR UPDATE", (receipt_id,))
    rec = cur.fetchone()
    if not rec:
        raise NotFound("Kirim hujjati topilmadi.")
    if rec['status'] != 'draft':
        names = {'posted': "allaqachon tasdiqlangan", 'reversed': "bekor qilingan (qaytarilgan)",
                 'cancelled': "bekor qilingan"}
        raise InventoryError(f"Kirim hujjati {names.get(rec['status'], rec['status'])}: qayta tasdiqlab bo'lmaydi.",
                             'status', 409)
    lines = _receipt_lines_in(cur, receipt_id)
    if not lines:
        raise InventoryError("Hujjatda qatorlar yo'q.", 'lines')
    today = _today()
    username, staff_id = _actor_ref(cur, actor)

    # Lock every item in id order, so two receipts naming the same items in a
    # different order cannot deadlock.
    items = {}
    for iid in sorted({ln['item_id'] for ln in lines}):
        items[iid] = _lock_item(cur, iid)
        if not int(items[iid]['is_active']):
            raise InventoryError(f"{items[iid]['name']} faol emas: qabul qilib bo'lmaydi.", 'item_id')
    balances = {iid: _dec(it['stock_quantity']) for iid, it in items.items()}
    avgs = {iid: _dec(it['avg_unit_cost']) for iid, it in items.items()}
    touched_last = {}
    for ln in lines:
        iid = ln['item_id']
        qty, cost = _dec(ln['quantity_base']), _dec(ln['unit_cost'])
        if ln['expiry_date'] and ln['expiry_date'] < today:
            raise InventoryError(f"{ln['item_name']}: muddati o'tgan mahsulotni qabul qilib bo'lmaydi.", 'expiry_date')
        cur.execute("""INSERT INTO inventory_batches
                       (item_id, batch_no, expiry_date, received_qty, remaining_qty, unit_cost,
                        source, receipt_id, receipt_line_id, supplier_id)
                       VALUES (?, ?, ?, ?, ?, ?, 'receipt', ?, ?, ?)""",
                    (iid, ln['batch_no'], ln['expiry_date'], qty, qty, cost,
                     receipt_id, ln['id'], rec['supplier_id']))
        batch_id = cur.lastrowid
        cur.execute("UPDATE inventory_receipt_lines SET batch_id = ? WHERE id = ?", (batch_id, ln['id']))
        before = balances[iid]
        new_avg = _c((before * avgs[iid] + qty * cost) / (before + qty))
        _write_ledger(cur, 'receipt', iid, batch_id, qty, before, cost, (username, staff_id),
                      source='receipt', operation_id=receipt_id, receipt_id=receipt_id,
                      supplier_id=rec['supplier_id'], reason=None)
        balances[iid] = before + qty
        avgs[iid] = new_avg
        touched_last[iid] = (ln['package_price'], cost)
    for iid in items:
        extra = {'last_package_price': touched_last[iid][0], 'last_unit_cost': touched_last[iid][1]}
        if rec['supplier_id']:
            extra['supplier_id'] = rec['supplier_id']
        _set_balance(cur, iid, balances[iid], avgs[iid], **extra)

    total = _m(sum((_dec(ln['line_total']) for ln in lines), ZERO))
    acc_id = None
    if total > 0:
        acc_id = _record_expense(cur, rec, lines, total, staff_id, account_source_fn)
    cur.execute("""UPDATE inventory_receipts SET status = 'posted', posted_at = ?, posted_by = ?,
                   total_amount = ?, accounting_transaction_id = ?, accounting_transaction_ref = ?
                   WHERE id = ?""",
                (_now(), username, total, acc_id, acc_id, receipt_id))
    for iid in items:
        refresh_alerts(conn, iid)
    r = get_receipt(conn, receipt_id, can_cost=True)
    r['duplicate'] = False
    return r


def _record_expense(cur, rec, lines, total, staff_id, account_source_fn):
    """The cash-desk expense for a posted receipt (category medication_purchase)."""
    method = rec['payment_method']
    source = account_source_fn(method) if account_source_fn else 'kassa'
    trx_id = _gen_id(cur, 'accounting_transactions', 'TRX-MED-2026')
    names = ', '.join(sorted({ln['item_name'] for ln in lines}))
    parts = [f"Ombor kirimi {rec['id']}: {names}"]
    if rec.get('supplier_name'):
        parts.append(f"Yetkazib beruvchi: {rec['supplier_name']}")
    if rec.get('invoice_number'):
        parts.append(f"Chek №: {rec['invoice_number']}")
    desc = '. '.join(parts)
    if len(desc) > 500:
        desc = desc[:497] + '...'
    cur.execute("""INSERT INTO accounting_transactions
                   (id, transaction_type, category, amount, payment_method, account_source,
                    description, transaction_date, recorded_by_staff_id)
                   VALUES (?, 'expense', 'medication_purchase', ?, ?, ?, ?, ?, ?)""",
                (trx_id, total, method, source, desc, rec['receipt_date'], staff_id))
    return trx_id


def cancel_receipt(conn, receipt_id, actor=None):
    ensure_ready(conn)
    cur = _cursor(conn)
    cur.execute("SELECT status FROM inventory_receipts WHERE id = ? FOR UPDATE", (receipt_id,))
    rec = cur.fetchone()
    if not rec:
        raise NotFound("Kirim hujjati topilmadi.")
    if rec['status'] != 'draft':
        raise InventoryError("Faqat qoralama hujjatni bekor qilish mumkin. Tasdiqlangan hujjat uchun "
                             "\"Qaytarish\" amalidan foydalaning.", 'status', 409)
    cur.execute("UPDATE inventory_receipts SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
                (_now(), receipt_id))
    return get_receipt(conn, receipt_id, can_cost=True)


def reverse_receipt(conn, receipt_id, reason, actor=None):
    """
    Undo a posted receipt: the received quantity leaves the shelf at its receipt
    cost, ledger rows are appended (never edited), the average cost is recomputed
    from what remains, and the accounting expense is voided. Refused when any of
    its stock was already used or written off.
    """
    ensure_ready(conn)
    cur = _cursor(conn)
    reason = parse_reason(reason)
    cur.execute("SELECT * FROM inventory_receipts WHERE id = ? FOR UPDATE", (receipt_id,))
    rec = cur.fetchone()
    if not rec:
        raise NotFound("Kirim hujjati topilmadi.")
    if rec['status'] != 'posted':
        raise InventoryError("Faqat tasdiqlangan kirim hujjatini qaytarish mumkin.", 'status', 409)
    username, staff_id = _actor_ref(cur, actor)
    lines = _receipt_lines_in(cur, receipt_id)
    items = {}
    for iid in sorted({ln['item_id'] for ln in lines}):
        items[iid] = _lock_item(cur, iid)
    batches = {}
    for ln in lines:
        cur.execute("SELECT * FROM inventory_batches WHERE id = ? FOR UPDATE", (ln['batch_id'],))
        b = cur.fetchone()
        if not b:
            raise InventoryError("Partiya topilmadi.", None, 409)
        if _dec(b['remaining_qty']) != _dec(b['received_qty']):
            raise InventoryError(
                f"{ln['item_name']}: bu kirimdagi mahsulotning bir qismi allaqachon ishlatilgan, "
                f"qaytarib bo'lmaydi. Qoldiq uchun tuzatish (korreksiya) kiriting.", 'status', 409)
        batches[ln['id']] = b
    balances = {iid: _dec(it['stock_quantity']) for iid, it in items.items()}
    avgs = {iid: _dec(it['avg_unit_cost']) for iid, it in items.items()}
    for ln in lines:
        iid, b = ln['item_id'], batches[ln['id']]
        qty, cost = _dec(ln['quantity_base']), _dec(b['unit_cost'])
        cur.execute("SELECT id FROM inventory_transactions WHERE txn_type = 'receipt' AND batch_id = ?",
                    (b['id'],))
        orig = cur.fetchone()
        before = balances[iid]
        value_before = before * avgs[iid]
        remaining = before - qty
        if remaining < 0:
            raise InventoryError("Ombor qoldig'i hisobi mos kelmayapti: qaytarib bo'lmaydi.", None, 409)
        cur.execute("UPDATE inventory_batches SET remaining_qty = 0 WHERE id = ?", (b['id'],))
        _write_ledger(cur, 'reversal', iid, b['id'], -qty, before, cost, (username, staff_id),
                      source='receipt_reversal', operation_id=receipt_id, receipt_id=receipt_id,
                      supplier_id=rec['supplier_id'], reason=reason,
                      reversal_of=orig['id'] if orig else None)
        balances[iid] = remaining
        if remaining > 0:
            avgs[iid] = _c(max((value_before - qty * cost) / remaining, ZERO))
    for iid in items:
        _set_balance(cur, iid, balances[iid], avgs[iid])
    cur.execute("""UPDATE inventory_receipts SET status = 'reversed', reversed_at = ?, reversed_by = ?,
                   reverse_reason = ? WHERE id = ?""", (_now(), username, reason, receipt_id))
    acc_id = rec['accounting_transaction_id']
    if acc_id:
        # The expense is voided (the purchase did not happen), as the old
        # DELETE of a medication purchase did. The receipt keeps the id in
        # accounting_transaction_ref and the reason, and audit_logs has the call.
        cur.execute("DELETE FROM accounting_transactions WHERE id = ?", (acc_id,))
    for iid in items:
        refresh_alerts(conn, iid)
    r = get_receipt(conn, receipt_id, can_cost=True)
    r['duplicate'] = False
    return r


# ---------------------------------------------------------------------------
# Dispensing
# ---------------------------------------------------------------------------

def _resolve_item_for_rx(cur, rx):
    """The stock item a prescription draws from, or None (same rules as the nurse round)."""
    import nursery
    row = nursery.resolve_stock_item(cur, rx.get('medication_id'), rx.get('medication_name'))
    return row['id'] if row else None


def _dispensed_so_far(cur, prescription_id):
    cur.execute("""SELECT COALESCE(SUM(quantity), 0) AS q FROM inventory_dispensings
                   WHERE prescription_id = ? AND status = 'completed'""", (prescription_id,))
    return _dec(cur.fetchone()['q'])


def _rx_state_error(status):
    return {
        'cancelled': "Retsept bekor qilingan: dori berib bo'lmaydi.",
        'completed': "Retsept yakunlangan: dori berib bo'lmaydi.",
        'held': "Retsept to'xtatib qo'yilgan: dori berib bo'lmaydi.",
    }.get(status, "Retsept faol emas: dori berib bo'lmaydi.")


DISPENSING_COST_FIELDS = ('unit_cost', 'total_cost')


def dispense(conn, data, actor=None, source='manual'):
    """
    Hand stock to a patient: FEFO across non-expired lots, one ledger row per lot,
    the dispensing and its lot list, all atomic. See the module docstring for the
    transaction contract and docs/WAREHOUSE_DESIGN.md for the rules.
    """
    ensure_ready(conn)
    cur = _cursor(conn)
    if source not in DISPENSING_SOURCES:
        raise InventoryError("Manba noto'g'ri.", 'source')
    client_id = _client_id(data, required=False)
    if client_id:
        dup = _find_by_client_id(cur, 'inventory_dispensings', client_id)
        if dup:
            d = get_dispensing(conn, dup['id'], can_cost=True)
            d['duplicate'] = True
            return d
    pid = parse_text(data.get('patient_id'), 'patient_id', 'Bemor', 64, required=True)
    rx_id = parse_text(data.get('prescription_id'), 'prescription_id', 'Retsept', 64)
    adm_id = parse_text(data.get('admission_id'), 'admission_id', 'Yotoq (admission)', 64)
    cons_id = parse_text(data.get('consultation_id'), 'consultation_id', 'Konsultatsiya', 64)
    notes = parse_text(data.get('notes'), 'notes', 'Izoh', 2000)

    cur.execute("SELECT id, full_name FROM patients WHERE id = ? OR patient_code = ?", (pid, pid))
    patient = cur.fetchone()
    if not patient:
        raise InventoryError("Bemor topilmadi.", 'patient_id')
    pid = patient['id']

    rx = None
    item_id = parse_text(data.get('item_id'), 'item_id', 'Mahsulot', 64)
    if rx_id:
        cur.execute("SELECT * FROM prescriptions WHERE id = ? FOR UPDATE", (rx_id,))
        rx = cur.fetchone()
        if not rx:
            raise InventoryError("Retsept topilmadi.", 'prescription_id')
        if rx['patient_id'] != pid:
            raise InventoryError("Retsept boshqa bemorga tegishli.", 'prescription_id')
        if rx['status'] != 'active':
            raise InventoryError(_rx_state_error(rx['status']), 'prescription_id')
        rx_item = _resolve_item_for_rx(cur, rx)
        if not rx_item:
            raise InventoryError("Retseptdagi dori ombor katalogida topilmadi. Avval buxgalter uni "
                                 "ombordagi mahsulotga bog'lashi kerak.", 'prescription_id')
        if item_id and item_id != rx_item:
            raise InventoryError("Tanlangan mahsulot retseptdagi dori bilan mos kelmaydi.", 'item_id')
        item_id = rx_item
        adm_id = adm_id or rx['admission_id']
    if not item_id:
        raise InventoryError("Mahsulot tanlanmagan.", 'item_id')
    if adm_id:
        cur.execute("SELECT patient_id FROM admissions WHERE id = ?", (adm_id,))
        a = cur.fetchone()
        if not a or a['patient_id'] != pid:
            raise InventoryError("Yotoq (admission) bu bemorga tegishli emas.", 'admission_id')
    if cons_id:
        cur.execute("SELECT patient_id FROM consultations WHERE id = ?", (cons_id,))
        c = cur.fetchone()
        if not c or c['patient_id'] != pid:
            raise InventoryError("Konsultatsiya bu bemorga tegishli emas.", 'consultation_id')

    item = _lock_item(cur, item_id)
    if client_id:
        # A second request with the same id that waited for the item lock: the
        # first one has committed by now. A locking read sees it (a plain read
        # would still show this transaction's older snapshot).
        dup = _find_by_client_id(cur, 'inventory_dispensings', client_id, lock=True)
        if dup:
            d = get_dispensing(conn, dup['id'], can_cost=True)
            d['duplicate'] = True
            return d
    if not int(item['is_active']):
        raise InventoryError(f"{item['name']} faol emas: berib bo'lmaydi.", 'item_id')
    # The screen route always records source 'manual' and so always needs the
    # doctor's order for a medicine. A bill line ('billing') has no prescription
    # to point at; the nurse's round ('nurse_round') carries its own.
    if item['item_type'] in PRESCRIPTION_TYPES and not rx and source == 'manual':
        raise InventoryError(f"{item['name']} faqat shifokor retsepti bo'yicha beriladi: retsept tanlang.",
                             'prescription_id')
    qty = _quantity_for_item(data.get('quantity'), item)

    if rx is not None and rx.get('quantity_prescribed') is not None:
        remaining = _dec(rx['quantity_prescribed']) - _dispensed_so_far(cur, rx_id)
        if qty > remaining:
            raise InventoryError(f"Retseptda qolgan miqdor: {max(remaining, ZERO)} {item['base_unit']}. "
                                 f"Bundan ko'p berib bo'lmaydi.", 'quantity')

    today = _today()
    batches = _usable_batches(cur, item_id, today)
    available = sum((_dec(b['remaining_qty']) for b in batches), ZERO)
    if qty > available:
        raise InventoryError(f"Omborda yetarli qoldiq yo'q. Mavjud (yaroqli): {_q(available)} {item['base_unit']}.",
                             'quantity')
    balance = _dec(item['stock_quantity'])
    if balance < qty:
        raise InventoryError("Ombor qoldig'i hisobi mos kelmayapti: berib bo'lmaydi. Administratorga murojaat qiling.",
                             None, 409)

    avg = _dec(item['avg_unit_cost'])
    username, staff_id = _actor_ref(cur, actor)
    did = _gen_id(cur, 'inventory_dispensings', 'DSP')
    doctor_name = None
    if rx and rx.get('doctor_id'):
        cur.execute("SELECT full_name FROM staff WHERE id = ?", (rx['doctor_id'],))
        row = cur.fetchone()
        doctor_name = row['full_name'] if row else None
    total_cost = _m(qty * avg)
    cur.execute("""
        INSERT INTO inventory_dispensings
            (id, client_request_id, patient_id, patient_name, prescription_id, consultation_id,
             admission_id, item_id, item_name, base_unit, quantity, unit_cost, total_cost,
             dosage, route, frequency, instructions, rx_doctor_id, rx_doctor_name, source,
             status, notes, dispensed_by, dispensed_by_staff_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)
    """, (did, client_id, pid, patient['full_name'], rx_id, cons_id, adm_id, item_id,
          item['name'], item['base_unit'], qty, avg, total_cost,
          rx['dosage'] if rx else None, rx['route'] if rx else None,
          rx['frequency'] if rx else None, rx['instructions'] if rx else None,
          rx['doctor_id'] if rx else None, doctor_name, source, notes, username, staff_id))
    left = qty
    for b in batches:
        if left <= 0:
            break
        take = min(_dec(b['remaining_qty']), left)
        cur.execute("UPDATE inventory_batches SET remaining_qty = ? WHERE id = ?",
                    (_q(_dec(b['remaining_qty']) - take), b['id']))
        txn = _write_ledger(cur, 'dispense', item_id, b['id'], -take, balance, avg,
                            (username, staff_id), source=source, operation_id=did,
                            patient_id=pid, prescription_id=rx_id, consultation_id=cons_id,
                            admission_id=adm_id, dispensing_id=did, notes=notes)
        cur.execute("""INSERT INTO inventory_dispensing_batches
                       (dispensing_id, batch_id, batch_no, expiry_date, quantity, unit_cost, txn_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (did, b['id'], b['batch_no'], b['expiry_date'], _q(take), _dec(b['unit_cost']), txn))
        balance -= take
        left -= take
    _set_balance(cur, item_id, balance)
    refresh_alerts(conn, item_id)
    d = get_dispensing(conn, did, can_cost=True)
    d['duplicate'] = False
    return d


def _attach_dispensing_batches(cur, rows):
    if not rows:
        return rows
    ids = [r['id'] for r in rows]
    marks = ','.join(['?'] * len(ids))
    cur.execute(f"""SELECT dispensing_id, batch_id, batch_no, expiry_date, quantity, unit_cost
                    FROM inventory_dispensing_batches WHERE dispensing_id IN ({marks}) ORDER BY id""", ids)
    by = {}
    for b in cur.fetchall():
        by.setdefault(b['dispensing_id'], []).append(b)
    for r in rows:
        r['batches'] = by.get(r['id'], [])
    return rows


def find_dispensing_by_client_id(conn, client_request_id):
    """The dispensing a client_request_id created, or None (for callers that undo their own work)."""
    cur = _cursor(conn)
    cur.execute("SELECT * FROM inventory_dispensings WHERE client_request_id = ?", (client_request_id,))
    return cur.fetchone()


def get_dispensing(conn, dispensing_id, can_cost=False):
    cur = _cursor(conn)
    cur.execute("SELECT * FROM inventory_dispensings WHERE id = ?", (dispensing_id,))
    r = cur.fetchone()
    if not r:
        raise NotFound("Dori berish yozuvi topilmadi.")
    _attach_dispensing_batches(cur, [r])
    if not can_cost:
        strip_costs(r, DISPENSING_COST_FIELDS)
        for b in r['batches']:
            b.pop('unit_cost', None)
    return r


def list_dispensings(conn, filters=None, can_cost=False):
    f = filters or {}
    cur = _cursor(conn)
    where, params = [], []
    for key, col in (('patient_id', 'patient_id'), ('item_id', 'item_id'),
                     ('prescription_id', 'prescription_id'), ('status', 'status')):
        if f.get(key):
            where.append(f"{col} = ?")
            params.append(f[key])
    if f.get('from'):
        where.append("created_at >= ?")
        params.append(f['from'])
    if f.get('to'):
        where.append("created_at < ?")
        params.append(f['to'] + _dt.timedelta(days=1))
    clause = ('WHERE ' + ' AND '.join(where)) if where else ''
    limit = max(1, min(int(f.get('limit') or 100), 500))
    offset = max(0, int(f.get('offset') or 0))
    cur.execute(f"SELECT COUNT(*) AS n FROM inventory_dispensings {clause}", params)
    total = int(cur.fetchone()['n'])
    cur.execute(f"""SELECT * FROM inventory_dispensings {clause}
                    ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""", params + [limit, offset])
    rows = cur.fetchall()
    _attach_dispensing_batches(cur, rows)
    if not can_cost:
        for r in rows:
            strip_costs(r, DISPENSING_COST_FIELDS)
            for b in r['batches']:
                b.pop('unit_cost', None)
    return rows, total


def reverse_dispensing(conn, dispensing_id, reason, actor=None):
    """Take a dispensing back: lots and balance restored, ledger gets reversal rows."""
    ensure_ready(conn)
    cur = _cursor(conn)
    reason = parse_reason(reason)
    cur.execute("SELECT * FROM inventory_dispensings WHERE id = ? FOR UPDATE", (dispensing_id,))
    d = cur.fetchone()
    if not d:
        raise NotFound("Dori berish yozuvi topilmadi.")
    if d['status'] != 'completed':
        raise InventoryError("Bu dori berish allaqachon qaytarilgan.", 'status', 409)
    item = _lock_item(cur, d['item_id'])
    username, staff_id = _actor_ref(cur, actor)
    cur.execute("SELECT * FROM inventory_dispensing_batches WHERE dispensing_id = ? ORDER BY id",
                (dispensing_id,))
    lots = cur.fetchall()
    balance = _dec(item['stock_quantity'])
    avg = _dec(item['avg_unit_cost'])
    for lot in lots:
        cur.execute("SELECT * FROM inventory_batches WHERE id = ? FOR UPDATE", (lot['batch_id'],))
        b = cur.fetchone()
        qty = _dec(lot['quantity'])
        if _dec(b['remaining_qty']) + qty > _dec(b['received_qty']):
            raise InventoryError("Partiya qoldig'i hisobi mos kelmayapti: qaytarib bo'lmaydi.", None, 409)
        cur.execute("UPDATE inventory_batches SET remaining_qty = ? WHERE id = ?",
                    (_q(_dec(b['remaining_qty']) + qty), b['id']))
        _write_ledger(cur, 'reversal', d['item_id'], b['id'], qty, balance, avg, (username, staff_id),
                      source='dispensing_reversal', operation_id=dispensing_id,
                      patient_id=d['patient_id'], prescription_id=d['prescription_id'],
                      consultation_id=d['consultation_id'], admission_id=d['admission_id'],
                      dispensing_id=dispensing_id, reason=reason, reversal_of=lot['txn_id'])
        balance += qty
    _set_balance(cur, d['item_id'], balance)
    cur.execute("""UPDATE inventory_dispensings SET status = 'reversed', reversed_at = ?, reversed_by = ?,
                   reverse_reason = ? WHERE id = ?""", (_now(), username, reason, dispensing_id))
    refresh_alerts(conn, d['item_id'])
    out = get_dispensing(conn, dispensing_id, can_cost=True)
    out['duplicate'] = False
    return out


def pending_prescriptions(conn, patient_id=None, limit=200):
    """Active prescriptions that map to a warehouse item, with prescribed / given / remaining."""
    ensure_ready(conn)
    cur = _cursor(conn)
    params = []
    where = "rx.status = 'active'"
    if patient_id:
        where += " AND (rx.patient_id = ? OR p.patient_code = ?)"
        params += [patient_id, patient_id]
    cur.execute(f"""SELECT rx.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                    FROM prescriptions rx JOIN patients p ON p.id = rx.patient_id
                    LEFT JOIN staff s ON s.id = rx.doctor_id
                    WHERE {where} ORDER BY rx.created_at DESC LIMIT ?""",
                params + [max(1, min(int(limit), 500))])
    rxs = cur.fetchall()
    if not rxs:
        return []
    # Resolve every name once.
    import nursery
    cur.execute("SELECT id, name FROM medications_catalog")
    by_name = {}
    for r in cur.fetchall():
        by_name.setdefault(nursery.alias_key(r['name']), r['id'])
    cur.execute("SELECT alias_key, medication_id FROM medication_aliases")
    by_alias = {r['alias_key']: r['medication_id'] for r in cur.fetchall()}
    today = _today()
    items = {i['id']: i for i in _fetch_items(cur, '', (), today)}
    ids = [r['id'] for r in rxs]
    marks = ','.join(['?'] * len(ids))
    cur.execute(f"""SELECT prescription_id, SUM(quantity) AS q FROM inventory_dispensings
                    WHERE status = 'completed' AND prescription_id IN ({marks}) GROUP BY prescription_id""", ids)
    given = {r['prescription_id']: _dec(r['q']) for r in cur.fetchall()}
    out = []
    for rx in rxs:
        iid = None
        if rx['medication_id'] and rx['medication_id'] in items:
            iid = rx['medication_id']
        else:
            key = nursery.alias_key(rx['medication_name'])
            iid = by_name.get(key) or by_alias.get(key)
        if not iid or iid not in items:
            continue
        it = items[iid]
        prescribed = rx['quantity_prescribed']
        done = given.get(rx['id'], ZERO)
        remaining = None if prescribed is None else _q(max(_dec(prescribed) - done, ZERO))
        if remaining is not None and remaining <= 0:
            continue
        out.append({
            'prescription_id': rx['id'], 'patient_id': rx['patient_id'], 'patient_name': rx['patient_name'],
            'patient_code': rx['patient_code'], 'admission_id': rx['admission_id'],
            'item_id': iid, 'item_name': it['name'], 'medication_name': rx['medication_name'],
            'base_unit': it['base_unit'], 'allow_fraction': it['allow_fraction'],
            'dosage': rx['dosage'], 'route': rx['route'], 'frequency': rx['frequency'],
            'duration_days': rx['duration_days'], 'instructions': rx['instructions'],
            'doctor_id': rx['doctor_id'], 'doctor_name': rx['doctor_name'],
            'quantity_prescribed': prescribed, 'quantity_unit': rx['quantity_unit'],
            'dispensed_quantity': _q(done), 'remaining_quantity': remaining,
            'available_quantity': it['available_quantity'], 'stock_status': it['stock_status'],
            'created_at': rx['created_at'],
        })
    return out


# ---------------------------------------------------------------------------
# Adjustments, write-offs, returns, reversal of a ledger row
# ---------------------------------------------------------------------------

def _ledger_group(cur, operation_id):
    cur.execute("SELECT * FROM inventory_transactions WHERE operation_id = ? ORDER BY id", (operation_id,))
    return cur.fetchall()


def adjust(conn, data, actor=None):
    """
    A stock correction, write-off, supplier return or patient return. The reason
    is mandatory; a repeated client_request_id returns the first result.
    """
    ensure_ready(conn)
    cur = _cursor(conn)
    client_id = _client_id(data, required=False)
    if client_id:
        dup = _find_by_client_id(cur, 'inventory_transactions', client_id)
        if dup:
            cur.execute("SELECT operation_id FROM inventory_transactions WHERE id = ?", (dup['id'],))
            op = cur.fetchone()['operation_id']
            return {'operation_id': op, 'transactions': _ledger_group(cur, op), 'duplicate': True}
    kind = str(data.get('kind') or '').strip().lower()
    if kind not in ADJUSTMENT_KINDS:
        raise InventoryError(f"Tur noto'g'ri. Ruxsat etilgan: {', '.join(ADJUSTMENT_KINDS)}.", 'kind')
    reason = parse_reason(data.get('reason'))
    item_id = parse_text(data.get('item_id'), 'item_id', 'Mahsulot', 64, required=True)
    item = _lock_item(cur, item_id)
    if client_id:
        dup = _find_by_client_id(cur, 'inventory_transactions', client_id, lock=True)
        if dup:
            cur.execute("SELECT operation_id FROM inventory_transactions WHERE id = ?", (dup['id'],))
            op = cur.fetchone()['operation_id']
            return {'operation_id': op, 'transactions': _ledger_group(cur, op), 'duplicate': True}
    qty = _quantity_for_item(data.get('quantity'), item)
    batch_id = data.get('batch_id')
    sup_id = data.get('supplier_id') or None
    patient_id = parse_text(data.get('patient_id'), 'patient_id', 'Bemor', 64)
    if sup_id:
        cur.execute("SELECT 1 FROM inventory_suppliers WHERE id = ?", (sup_id,))
        if not cur.fetchone():
            raise InventoryError("Yetkazib beruvchi topilmadi.", 'supplier_id')
    if patient_id:
        cur.execute("SELECT id FROM patients WHERE id = ? OR patient_code = ?", (patient_id, patient_id))
        p = cur.fetchone()
        if not p:
            raise InventoryError("Bemor topilmadi.", 'patient_id')
        patient_id = p['id']
    username, staff_id = _actor_ref(cur, actor)
    # Groups the ledger rows of this one operation (a decrease can span several lots).
    op_id = f"ADJ-{os.urandom(5).hex().upper()}"
    balance = _dec(item['stock_quantity'])
    avg = _dec(item['avg_unit_cost'])
    txn_type = ADJUSTMENT_KINDS[kind]
    refs = dict(source='adjustment', operation_id=op_id, reason=reason, supplier_id=sup_id,
                patient_id=patient_id, notes=parse_text(data.get('notes'), 'notes', 'Izoh', 2000))
    first = True

    def ledger(batch, delta, cost):
        nonlocal balance, first
        r = dict(refs)
        if first and client_id:
            r['client_request_id'] = client_id
        first = False
        _write_ledger(cur, txn_type, item_id, batch, delta, balance, cost, (username, staff_id), **r)
        balance += delta

    if kind in ('increase', 'patient_return'):
        expiry = parse_date(data.get('expiry_date'), 'expiry_date', 'Yaroqlilik muddati')
        if batch_id:
            cur.execute("SELECT * FROM inventory_batches WHERE id = ? AND item_id = ? FOR UPDATE",
                        (batch_id, item_id))
            b = cur.fetchone()
            if not b:
                raise InventoryError("Partiya topilmadi.", 'batch_id')
            if _dec(b['remaining_qty']) + qty > _dec(b['received_qty']):
                raise InventoryError("Partiyaga qaytarilayotgan miqdor qabul qilingan miqdordan oshib ketadi. "
                                     "Yangi partiya sifatida kiriting (partiyani tanlamang).", 'quantity')
            cur.execute("UPDATE inventory_batches SET remaining_qty = ? WHERE id = ?",
                        (_q(_dec(b['remaining_qty']) + qty), b['id']))
            ledger(b['id'], qty, _dec(b['unit_cost']))
        else:
            if int(item['track_expiry']) and not expiry:
                raise InventoryError("Bu mahsulot uchun yaroqlilik muddati kiritilishi shart.", 'expiry_date')
            if expiry and expiry < _today():
                raise InventoryError("Muddati o'tgan mahsulotni omborga qo'shib bo'lmaydi.", 'expiry_date')
            label = 'QAYTARISH' if kind == 'patient_return' else 'TUZATISH'
            cur.execute("""INSERT INTO inventory_batches
                           (item_id, batch_no, expiry_date, received_qty, remaining_qty, unit_cost, source)
                           VALUES (?, ?, ?, ?, ?, ?, 'adjustment')""",
                        (item_id, f"{label}-{_today():%Y%m%d}", expiry, qty, qty, avg))
            ledger(cur.lastrowid, qty, avg)
        _set_balance(cur, item_id, balance)
    else:
        # Decreasing kinds may take expired lots too (that is what a write-off is for).
        if batch_id:
            cur.execute("SELECT * FROM inventory_batches WHERE id = ? AND item_id = ? FOR UPDATE",
                        (batch_id, item_id))
            b = cur.fetchone()
            if not b:
                raise InventoryError("Partiya topilmadi.", 'batch_id')
            lots = [b]
        else:
            lots = _usable_batches(cur, item_id, _today(), include_expired=True)
        avail = sum((_dec(b['remaining_qty']) for b in lots), ZERO)
        if qty > avail:
            raise InventoryError(f"Omborda yetarli qoldiq yo'q. Mavjud: {_q(avail)} {item['base_unit']}.", 'quantity')
        if balance < qty:
            raise InventoryError("Ombor qoldig'i hisobi mos kelmayapti.", None, 409)
        left = qty
        for b in lots:
            if left <= 0:
                break
            take = min(_dec(b['remaining_qty']), left)
            cur.execute("UPDATE inventory_batches SET remaining_qty = ? WHERE id = ?",
                        (_q(_dec(b['remaining_qty']) - take), b['id']))
            ledger(b['id'], -take, avg)
            left -= take
        _set_balance(cur, item_id, balance)
    refresh_alerts(conn, item_id)
    return {'operation_id': op_id, 'transactions': _ledger_group(cur, op_id), 'duplicate': False}


_REVERSIBLE = ('adjustment_in', 'adjustment_out', 'supplier_return', 'patient_return', 'writeoff')


def reverse_transaction(conn, txn_id, reason, actor=None):
    """Reverse one adjustment-type ledger row, once. Receipts and dispensings have their own reversal."""
    ensure_ready(conn)
    cur = _cursor(conn)
    reason = parse_reason(reason)
    cur.execute("SELECT * FROM inventory_transactions WHERE id = ?", (txn_id,))
    t = cur.fetchone()
    if not t:
        raise NotFound("Harakat topilmadi.")
    if t['txn_type'] == 'dispense':
        raise InventoryError("Dori berishni \"Dori berishni qaytarish\" orqali bekor qiling.", 'txn_type')
    if t['txn_type'] == 'receipt':
        raise InventoryError("Kirimni \"Kirim hujjatini qaytarish\" orqali bekor qiling.", 'txn_type')
    if t['txn_type'] not in _REVERSIBLE:
        raise InventoryError("Bu harakatni qaytarib bo'lmaydi.", 'txn_type')
    item = _lock_item(cur, t['item_id'])
    cur.execute("SELECT id FROM inventory_transactions WHERE reversal_of = ? FOR UPDATE", (txn_id,))
    if cur.fetchone():
        raise InventoryError("Bu harakat allaqachon qaytarilgan.", 'status', 409)
    cur.execute("SELECT * FROM inventory_batches WHERE id = ? FOR UPDATE", (t['batch_id'],))
    b = cur.fetchone()
    delta = -_dec(t['qty_delta'])
    new_remaining = _dec(b['remaining_qty']) + delta
    if new_remaining < 0:
        raise InventoryError("Partiyada yetarli qoldiq yo'q: bu harakatni qaytarib bo'lmaydi "
                             "(mahsulot allaqachon ishlatilgan).", 'status', 409)
    if new_remaining > _dec(b['received_qty']):
        raise InventoryError("Partiya qoldig'i qabul qilingan miqdordan oshib ketadi.", 'status', 409)
    username, staff_id = _actor_ref(cur, actor)
    balance = _dec(item['stock_quantity'])
    cur.execute("UPDATE inventory_batches SET remaining_qty = ? WHERE id = ?", (_q(new_remaining), b['id']))
    _write_ledger(cur, 'reversal', t['item_id'], b['id'], delta, balance, _dec(t['unit_cost']),
                  (username, staff_id), source='transaction_reversal', operation_id=t['operation_id'],
                  patient_id=t['patient_id'], supplier_id=t['supplier_id'], reason=reason, reversal_of=txn_id)
    _set_balance(cur, t['item_id'], balance + delta)
    refresh_alerts(conn, t['item_id'])
    cur.execute("SELECT * FROM inventory_transactions WHERE reversal_of = ?", (txn_id,))
    return cur.fetchone()


def list_transactions(conn, filters=None, can_cost=False):
    f = filters or {}
    cur = _cursor(conn)
    where, params = [], []
    if f.get('item_id'):
        where.append("t.item_id = ?")
        params.append(f['item_id'])
    if f.get('type'):
        where.append("t.txn_type = ?")
        params.append(f['type'])
    if f.get('patient_id'):
        where.append("t.patient_id = ?")
        params.append(f['patient_id'])
    if f.get('from'):
        where.append("t.created_at >= ?")
        params.append(f['from'])
    if f.get('to'):
        where.append("t.created_at < ?")
        params.append(f['to'] + _dt.timedelta(days=1))
    clause = ('WHERE ' + ' AND '.join(where)) if where else ''
    limit = max(1, min(int(f.get('limit') or 100), 1000))
    offset = max(0, int(f.get('offset') or 0))
    cur.execute(f"SELECT COUNT(*) AS n FROM inventory_transactions t {clause}", params)
    total = int(cur.fetchone()['n'])
    cur.execute(f"""SELECT t.*, mc.name AS item_name, mc.base_unit, b.batch_no
                    FROM inventory_transactions t
                    JOIN medications_catalog mc ON mc.id = t.item_id
                    LEFT JOIN inventory_batches b ON b.id = t.batch_id
                    {clause} ORDER BY t.id DESC LIMIT ? OFFSET ?""", params + [limit, offset])
    rows = cur.fetchall()
    if not can_cost:
        for r in rows:
            _strip_txn(r)
    return rows, total


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def refresh_alerts(conn, item_id=None):
    """
    Bring inventory_alerts in line with the stock right now. Idempotent: a
    condition that already has an active alert gets no second one (the unique
    key makes a race harmless too), and a condition that no longer holds is
    resolved. Inactive items have no alerts.
    """
    cur = _cursor(conn)
    today = _today()
    days = expiry_warning_days(cur)
    where, params = '', []
    if item_id:
        where, params = 'WHERE mc.id = ?', [item_id]
    items = _fetch_items(cur, where, params, today)
    if not items:
        return {'created': 0, 'resolved': 0}
    ids = [i['id'] for i in items]
    marks = ','.join(['?'] * len(ids))
    cur.execute(f"""SELECT id, item_id, alert_type, batch_key FROM inventory_alerts
                    WHERE status = 'active' AND item_id IN ({marks})""", ids)
    active = {(r['item_id'], r['alert_type'], int(r['batch_key'])): r['id'] for r in cur.fetchall()}
    cur.execute(f"""SELECT id, item_id, batch_no, expiry_date, remaining_qty FROM inventory_batches
                    WHERE remaining_qty > 0 AND expiry_date IS NOT NULL AND expiry_date <= ?
                      AND item_id IN ({marks})""", [today + _dt.timedelta(days=days)] + ids)
    batches = cur.fetchall()
    desired = {}
    for it in items:
        if not it['is_active']:
            continue
        st = compute_status(it['available_quantity'], it['min_stock_level'])
        if st == 'out':
            desired[(it['id'], 'out_of_stock', 0)] = (
                f"{it['name']}: omborda qolmadi", it['available_quantity'], it['min_stock_level'], None, None)
        elif st == 'low':
            desired[(it['id'], 'low_stock', 0)] = (
                f"{it['name']}: qoldiq {it['available_quantity']} {it['base_unit']}, minimal {it['min_stock_level']}",
                it['available_quantity'], it['min_stock_level'], None, None)
    active_ids = {i['id'] for i in items if i['is_active']}
    names = {i['id']: i['name'] for i in items}
    for b in batches:
        if b['item_id'] not in active_ids:
            continue
        expired = b['expiry_date'] < today
        typ = 'expired' if expired else 'expiring_soon'
        msg = (f"{names[b['item_id']]} (partiya {b['batch_no']}): muddati {b['expiry_date']} da o'tgan"
               if expired else
               f"{names[b['item_id']]} (partiya {b['batch_no']}): muddati {b['expiry_date']} da tugaydi")
        desired[(b['item_id'], typ, int(b['id']))] = (msg, b['remaining_qty'], None, b['expiry_date'], b['id'])
    created = resolved = 0
    for key, (msg, qty, thr, exp, bid) in desired.items():
        if key in active:
            continue
        cur.execute("""INSERT IGNORE INTO inventory_alerts
                       (item_id, alert_type, batch_id, batch_key, status, active_marker, message,
                        quantity, threshold, expiry_date)
                       VALUES (?, ?, ?, ?, 'active', 1, ?, ?, ?, ?)""",
                    (key[0], key[1], bid, key[2], msg[:255], qty, thr, exp))
        created += cur.rowcount
    for key, aid in active.items():
        if key not in desired:
            cur.execute("""UPDATE inventory_alerts SET status = 'resolved', active_marker = NULL,
                           resolved_at = ? WHERE id = ? AND status = 'active'""", (_now(), aid))
            resolved += cur.rowcount
    return {'created': created, 'resolved': resolved}


def refresh_expiry_alerts(conn):
    """Startup / summary hook: expiry changes with the calendar, not with a movement."""
    result = refresh_alerts(conn)
    return result


def list_alerts(conn, status='active', limit=300):
    cur = _cursor(conn)
    where, params = '', []
    if status in ('active', 'resolved'):
        where, params = 'WHERE a.status = ?', [status]
    cur.execute(f"""SELECT a.*, mc.name AS item_name, mc.base_unit, b.batch_no
                    FROM inventory_alerts a JOIN medications_catalog mc ON mc.id = a.item_id
                    LEFT JOIN inventory_batches b ON b.id = a.batch_id
                    {where} ORDER BY a.status, FIELD(a.alert_type, 'out_of_stock', 'expired', 'low_stock',
                    'expiring_soon'), a.created_at DESC LIMIT ?""", params + [max(1, min(int(limit), 1000))])
    return cur.fetchall()


# ---------------------------------------------------------------------------
# Valuation, summary, reconciliation
# ---------------------------------------------------------------------------

def valuation(conn):
    """
    Stock value = quantity x weighted-average cost, per item, with the split
    total / expired / available. Returns {'total','expired','available','by_category','items'}.
    """
    cur = _cursor(conn)
    items = [i for i in _fetch_items(cur, '', (), None) if (i['available_quantity'] + i['expired_quantity']) > 0]
    total = sum((i['stock_value'] for i in items), ZERO)
    expired = sum((i['expired_value'] for i in items), ZERO)
    avail = sum((i['available_value'] for i in items), ZERO)
    by_cat = {}
    for i in items:
        c = by_cat.setdefault(i['category'], {'category': i['category'], 'items': 0, 'quantity': ZERO,
                                              'total_value': ZERO, 'expired_value': ZERO,
                                              'available_value': ZERO})
        c['items'] += 1
        c['quantity'] += i['available_quantity'] + i['expired_quantity']
        c['total_value'] += i['stock_value']
        c['expired_value'] += i['expired_value']
        c['available_value'] += i['available_value']
    return {'total_value': _m(total), 'expired_value': _m(expired), 'available_value': _m(avail),
            'by_category': sorted(by_cat.values(), key=lambda c: c['category'] or ''), 'items': items}


def summary(conn, can_cost=False, full=True):
    ensure_ready(conn)
    cur = _cursor(conn)
    try:
        refresh_alerts(conn)
        conn.commit()
    except Exception as e:
        print(f"[!] warehouse summary: alert refresh failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    everything = _fetch_items(cur, '', (), None)
    items = [i for i in everything if i['is_active']]
    units = {}
    for i in items:
        units[i['base_unit']] = units.get(i['base_unit'], ZERO) + _dec(i['stock_quantity'])
    out = {
        'items_total': len(items),
        'units_by_unit': [{'unit': u, 'qty': _q(q)} for u, q in sorted(units.items())],
        'low_stock_count': sum(1 for i in items if i['stock_status'] == 'low'),
        'out_of_stock_count': sum(1 for i in items if i['stock_status'] == 'out'),
        'expired_count': sum(1 for i in items if i['expired_quantity'] > 0),
        'expiring_count': sum(1 for i in items if i['expiring_quantity'] > 0),
        'settings': {'default_min_stock': default_min_stock(cur),
                     'expiry_warning_days': expiry_warning_days(cur)},
    }
    if can_cost:
        out['total_value'] = _m(sum((i['stock_value'] for i in everything), ZERO))
        out['expired_value'] = _m(sum((i['expired_value'] for i in everything), ZERO))
        out['available_value'] = _m(sum((i['available_value'] for i in everything), ZERO))
    if full:
        out['recent_receipts'] = list_receipts(conn, {'limit': 5, 'status': 'posted'}, can_cost)[0]
        out['recent_dispensings'] = list_dispensings(conn, {'limit': 8}, can_cost)[0]
    return out


def reconciliation(conn):
    """
    Item balance vs the sum of its lots vs the sum of its ledger. `ok` is true
    only when all three agree for every item; each mismatch lists the three
    numbers so the difference can be traced.
    """
    cur = _cursor(conn)
    cur.execute("""
        SELECT mc.id, mc.name, mc.base_unit, mc.stock_quantity,
               COALESCE((SELECT SUM(remaining_qty) FROM inventory_batches b WHERE b.item_id = mc.id), 0) AS batches_qty,
               COALESCE((SELECT SUM(qty_delta) FROM inventory_transactions t WHERE t.item_id = mc.id), 0) AS ledger_qty
        FROM medications_catalog mc ORDER BY mc.name""")
    rows = cur.fetchall()
    bad = []
    for r in rows:
        s, b, l = _dec(r['stock_quantity']), _dec(r['batches_qty']), _dec(r['ledger_qty'])
        if not (s == b == l):
            bad.append({'item_id': r['id'], 'name': r['name'], 'base_unit': r['base_unit'],
                        'stock_quantity': _q(s), 'batches_quantity': _q(b), 'ledger_quantity': _q(l),
                        'difference_batches': _q(s - b), 'difference_ledger': _q(s - l)})
    cur.execute("""SELECT COUNT(*) AS n FROM inventory_batches WHERE remaining_qty > received_qty OR remaining_qty < 0""")
    bad_batches = int(cur.fetchone()['n'])
    return {'ok': not bad and bad_batches == 0, 'items_checked': len(rows),
            'mismatches': bad, 'invalid_batches': bad_batches}


# ---------------------------------------------------------------------------
# Reports (rows + column list, so JSON and CSV come from one place)
# ---------------------------------------------------------------------------

REPORTS = ('stock', 'low-stock', 'out-of-stock', 'expiry', 'valuation', 'valuation-by-category',
           'receipts', 'dispensings', 'adjustments', 'movement', 'reconciliation')
COST_REPORTS = ('valuation', 'valuation-by-category')


def _col(key, label, cost=False):
    return {'key': key, 'label': label, 'cost': cost}


def report(conn, name, params=None, can_cost=False):
    """-> {'name','title','columns','rows','totals'}. Cost columns are dropped for non-cost roles."""
    p = params or {}
    if name not in REPORTS:
        raise NotFound("Hisobot topilmadi.")
    if name in COST_REPORTS and not can_cost:
        raise Forbidden("Bu hisobot faqat buxgalter va egasiga ochiq.")
    cur = _cursor(conn)
    today = _today()
    totals = {}
    if name in ('stock', 'low-stock', 'out-of-stock'):
        items = _fetch_items(cur, 'WHERE mc.is_active = 1', (), today)
        if name == 'low-stock':
            items = [i for i in items if i['stock_status'] == 'low']
        elif name == 'out-of-stock':
            items = [i for i in items if i['stock_status'] == 'out']
        cols = [_col('name', 'Nomi'), _col('category', 'Kategoriya'), _col('base_unit', 'Birlik'),
                _col('available_quantity', 'Mavjud'), _col('expired_quantity', "Muddati o'tgan"),
                _col('min_stock_level', 'Minimal'), _col('shortage', 'Yetishmovchilik'),
                _col('stock_status', 'Holat'), _col('nearest_expiry', 'Eng yaqin muddat'),
                _col('stock_value', 'Qiymati', True)]
        rows = items
    elif name == 'expiry':
        days = expiry_warning_days(cur)
        cur.execute("""SELECT mc.name, mc.base_unit, b.batch_no, b.expiry_date, b.remaining_qty
                       FROM inventory_batches b JOIN medications_catalog mc ON mc.id = b.item_id
                       WHERE b.remaining_qty > 0 AND b.expiry_date IS NOT NULL AND b.expiry_date <= ?
                       ORDER BY b.expiry_date, mc.name""", (today + _dt.timedelta(days=days),))
        rows = cur.fetchall()
        for r in rows:
            r['days_left'] = (r['expiry_date'] - today).days
            r['state'] = 'expired' if r['days_left'] < 0 else 'expiring'
        cols = [_col('name', 'Nomi'), _col('batch_no', 'Partiya'), _col('expiry_date', 'Muddati'),
                _col('days_left', 'Qolgan kun'), _col('remaining_qty', 'Qoldiq'),
                _col('base_unit', 'Birlik'), _col('state', 'Holat')]
    elif name == 'valuation':
        v = valuation(conn)
        rows = v['items']
        totals = {'total_value': v['total_value'], 'expired_value': v['expired_value'],
                  'available_value': v['available_value']}
        cols = [_col('name', 'Nomi'), _col('category', 'Kategoriya'), _col('base_unit', 'Birlik'),
                _col('available_quantity', 'Mavjud'), _col('expired_quantity', "Muddati o'tgan"),
                _col('avg_unit_cost', "O'rtacha tannarx", True), _col('stock_value', 'Jami qiymat', True),
                _col('expired_value', "Muddati o'tgan qiymati", True),
                _col('available_value', 'Yaroqli qiymat', True)]
    elif name == 'valuation-by-category':
        v = valuation(conn)
        rows = v['by_category']
        totals = {'total_value': v['total_value'], 'expired_value': v['expired_value'],
                  'available_value': v['available_value']}
        cols = [_col('category', 'Kategoriya'), _col('items', 'Mahsulotlar'), _col('quantity', 'Miqdor'),
                _col('total_value', 'Jami qiymat', True), _col('expired_value', "Muddati o'tgan", True),
                _col('available_value', 'Yaroqli', True)]
    elif name == 'receipts':
        rows, _total = list_receipts(conn, {'from': p.get('from'), 'to': p.get('to'),
                                            'supplier_id': p.get('supplier_id'), 'limit': 500}, True)
        cols = [_col('id', 'Hujjat'), _col('receipt_date', 'Sana'), _col('supplier_name', 'Yetkazib beruvchi'),
                _col('invoice_number', 'Hisob-faktura'), _col('status', 'Holat'),
                _col('line_count', 'Qatorlar'), _col('total_amount', 'Summa', True)]
        totals = {'total_amount': _m(sum((_dec(r['total_amount']) for r in rows if r['status'] == 'posted'), ZERO))}
    elif name == 'dispensings':
        rows, _t = list_dispensings(conn, {'from': p.get('from'), 'to': p.get('to'),
                                           'patient_id': p.get('patient_id'), 'item_id': p.get('item_id'),
                                           'limit': 500}, True)
        for r in rows:
            r['batch_list'] = ', '.join(f"{b['batch_no']}: {b['quantity']}" for b in r['batches'])
        cols = [_col('created_at', 'Vaqt'), _col('patient_name', 'Bemor'), _col('item_name', 'Mahsulot'),
                _col('quantity', 'Miqdor'), _col('base_unit', 'Birlik'), _col('batch_list', 'Partiyalar'),
                _col('dispensed_by', 'Bergan xodim'), _col('status', 'Holat'),
                _col('total_cost', 'Tannarxi', True)]
    elif name == 'adjustments':
        rows, _t = list_transactions(conn, {'from': p.get('from'), 'to': p.get('to'), 'limit': 1000}, True)
        rows = [r for r in rows if r['txn_type'] in ('adjustment_in', 'adjustment_out', 'writeoff',
                                                    'supplier_return', 'patient_return', 'reversal')]
        cols = [_col('created_at', 'Vaqt'), _col('txn_type', 'Tur'), _col('item_name', 'Mahsulot'),
                _col('batch_no', 'Partiya'), _col('qty_delta', "O'zgarish"), _col('reason', 'Sabab'),
                _col('performed_by', 'Xodim'), _col('value_delta', 'Qiymati', True)]
    elif name == 'movement':
        if not p.get('item_id'):
            raise InventoryError("Mahsulot (item_id) ko'rsatilishi shart.", 'item_id')
        rows, _t = list_transactions(conn, {'item_id': p['item_id'], 'from': p.get('from'),
                                            'to': p.get('to'), 'limit': 1000}, True)
        cols = [_col('created_at', 'Vaqt'), _col('txn_type', 'Tur'), _col('batch_no', 'Partiya'),
                _col('qty_delta', "O'zgarish"), _col('balance_before', 'Oldin'),
                _col('balance_after', 'Keyin'), _col('reason', 'Sabab'), _col('performed_by', 'Xodim'),
                _col('value_delta', 'Qiymati', True)]
    else:   # reconciliation
        rec = reconciliation(conn)
        rows = rec['mismatches']
        totals = {'ok': rec['ok'], 'items_checked': rec['items_checked']}
        cols = [_col('name', 'Nomi'), _col('stock_quantity', 'Qoldiq'),
                _col('batches_quantity', 'Partiyalar yig\'indisi'),
                _col('ledger_quantity', "Daftar yig'indisi")]
    if not can_cost:
        cols = [c for c in cols if not c['cost']]
        keep = {c['key'] for c in cols} | {'id', 'item_id'}
        rows = [{k: v for k, v in r.items() if k in keep} for r in rows]
        totals = {k: v for k, v in totals.items()
                  if k not in ('total_amount', 'total_value', 'expired_value', 'available_value')}
    return {'name': name, 'title': name, 'columns': cols, 'rows': rows, 'totals': totals}
