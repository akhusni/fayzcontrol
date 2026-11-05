"""
Fayz Medical House — Owner Private Accounting & Bookkeeping Engine

Confidential and restricted solely to the clinic owner (role: owner) and superadmin.
Tracks all private cash flow, expense destinations, income sources, reasons,
and accurate timestamps. Completely isolated from staff accounting unless explicitly
marked 'is_clinic_account' by the owner.
"""

import datetime as _dt
import re
from collections import OrderedDict

_schema_checked = False

PAYMENT_METHODS = OrderedDict([
    ('cash', "Naqd pul"),
    ('card', "Plastik karta"),
    ('bank', "Bank o'tkazmasi"),
    ('online', "Click / Payme")
])

# Mapping to accounting_transactions check constraint
METHOD_MAP_TO_ACC = {
    'cash': 'cash',
    'card': 'terminal',
    'bank': 'bank_wire',
    'online': 'payme_click'
}


def _acc_source_for(acc_method):
    if acc_method in ('cash', 'cash_register'):
        return 'kassa'
    if acc_method == 'terminal':
        return 'terminal_bank'
    return 'main_bank_account'


def ensure_schema(conn):
    """
    Ensure the owner_accounting_transactions table exists with is_clinic_account column.
    Idempotent and safe across MySQL 8.0 and SQLite environments.
    """
    global _schema_checked
    if _schema_checked:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS owner_accounting_transactions (
                id VARCHAR(64) PRIMARY KEY,
                transaction_type VARCHAR(16) NOT NULL,
                amount DECIMAL(15,2) NOT NULL,
                category VARCHAR(128) NOT NULL,
                destination_or_source VARCHAR(255) NOT NULL,
                reason TEXT NOT NULL,
                payment_method VARCHAR(32) NOT NULL DEFAULT 'cash',
                transaction_time DATETIME NOT NULL,
                is_clinic_account TINYINT(1) NOT NULL DEFAULT 0,
                linked_accounting_trx_id VARCHAR(128) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                recorded_by_user VARCHAR(64) NULL,
                notes TEXT NULL
            );
        """)
        # Schema migration check for is_clinic_account & linked_accounting_trx_id
        try:
            cur.execute("SELECT is_clinic_account FROM owner_accounting_transactions LIMIT 1")
        except Exception:
            try:
                cur.execute("ALTER TABLE owner_accounting_transactions ADD COLUMN is_clinic_account TINYINT(1) NOT NULL DEFAULT 0")
                cur.execute("ALTER TABLE owner_accounting_transactions ADD COLUMN linked_accounting_trx_id VARCHAR(128) NULL")
                conn.commit()
            except Exception:
                pass

        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_owner_atx_time ON owner_accounting_transactions (transaction_time);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_owner_atx_type ON owner_accounting_transactions (transaction_type);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_owner_atx_clinic ON owner_accounting_transactions (is_clinic_account);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_owner_atx_created ON owner_accounting_transactions (created_at);")
        except Exception:
            pass
        conn.commit()
        _schema_checked = True
    except Exception as e:
        print(f"[!] Could not create owner_accounting_transactions table: {e}")


def generate_owner_trx_id(cur):
    """Generate sequential unique ID: OWN-YYYYMMDD-XXXX."""
    today_str = _dt.date.today().strftime('%Y%m%d')
    prefix = f"OWN-{today_str}"
    cur.execute(
        "SELECT id FROM owner_accounting_transactions WHERE id LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefix}-%",)
    )
    row = cur.fetchone()
    if row:
        val = row['id'] if isinstance(row, dict) else row[0]
        try:
            num = int(str(val).split('-')[-1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    return f"{prefix}-{num:04d}"


def generate_accounting_trx_id(cur):
    """Generate unique ID for accounting_transactions: TRX-OWN-YYYY-XXXX."""
    prefix = f"TRX-OWN-{_dt.date.today().year}"
    cur.execute(
        "SELECT id FROM accounting_transactions WHERE id LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefix}-%",)
    )
    row = cur.fetchone()
    if row:
        val = row['id'] if isinstance(row, dict) else row[0]
        try:
            num = int(str(val).split('-')[-1]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    return f"{prefix}-{num:04d}"


def _format_dt(val):
    if val is None:
        return ""
    if hasattr(val, 'strftime'):
        return val.strftime('%Y-%m-%d %H:%M:%S')
    s = str(val).strip()
    return s[:19]


def get_transaction_by_id(conn, trx_id):
    """Fetch a single transaction as a normalized dict."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, transaction_type, amount, category, destination_or_source,
               reason, payment_method, transaction_time, is_clinic_account,
               linked_accounting_trx_id, created_at, recorded_by_user, notes
        FROM owner_accounting_transactions
        WHERE id = ?
    """, (trx_id,))
    row = cur.fetchone()
    if not row:
        return None
    r = dict(row)
    r['amount'] = float(r['amount'] or 0.0)
    r['is_clinic_account'] = bool(r.get('is_clinic_account'))
    r['transaction_time'] = _format_dt(r.get('transaction_time'))
    r['created_at'] = _format_dt(r.get('created_at'))
    r['payment_method_label'] = PAYMENT_METHODS.get(r.get('payment_method'), r.get('payment_method'))
    return r


def create_transaction(conn, data, actor_username='owner'):
    """
    Record an income or expense transaction with timestamp, destination/source, and reason.
    If 'is_clinic_account' is True, synchronizes into clinic's accounting_transactions as well.
    Returns: (record_dict, error_message, field_name)
    """
    txn_type = (data.get('transaction_type') or data.get('type') or '').strip().lower()
    if txn_type not in ('income', 'expense'):
        return None, "Operatsiya turi noto'g'ri (faqat 'income' yoki 'expense' bo'lishi mumkin).", 'transaction_type'

    try:
        raw_amt = str(data.get('amount') or '').replace(' ', '').replace(',', '.')
        amount = round(float(raw_amt), 2)
    except (ValueError, TypeError):
        amount = 0.0

    if amount <= 0:
        return None, "Summa 0 dan katta bo'lishi kerak.", 'amount'

    dest = (data.get('destination_or_source') or data.get('destination') or data.get('source') or '').strip()
    if not dest:
        err_msg = "Chiqim qayerga sarflangani kiritilishi shart." if txn_type == 'expense' else "Kirim qayerdan/qayerga kelgani kiritilishi shart."
        return None, err_msg, 'destination_or_source'

    reason = (data.get('reason') or data.get('description') or '').strip()
    if not reason:
        return None, "Amaliyot nega bo'lgani (sababi / to'liq izoh) kiritilishi shart.", 'reason'

    method = (data.get('payment_method') or 'cash').strip().lower()
    if method not in PAYMENT_METHODS:
        method = 'cash'

    category = (data.get('category') or '').strip()
    if not category:
        category = dest[:128]

    # Parse provided timestamp or default to now
    time_raw = (data.get('transaction_time') or data.get('timestamp') or '').strip()
    txn_time = None
    if time_raw:
        clean_time = time_raw.replace('T', ' ')
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                txn_time = _dt.datetime.strptime(clean_time[:19], fmt)
                break
            except ValueError:
                pass
    if txn_time is None:
        txn_time = _dt.datetime.now()

    notes = (data.get('notes') or '').strip() or None
    is_clinic_acc = 1 if data.get('is_clinic_account') in (True, 1, '1', 'true', 'True') else 0

    cur = conn.cursor()
    trx_id = generate_owner_trx_id(cur)
    linked_acc_id = None

    # If marked "klinika hisobidan", book into main accounting_transactions
    if is_clinic_acc:
        linked_acc_id = generate_accounting_trx_id(cur)
        acc_method = METHOD_MAP_TO_ACC.get(method, 'cash')
        acc_source = _acc_source_for(acc_method)
        acc_category = category if category in ('operational_expense', 'salary', 'maintenance', 'equipment', 'rent', 'utilities', 'food', 'other_expense', 'other_income') else ('operational_expense' if txn_type == 'expense' else 'other_income')
        acc_desc = f"Klinika hisobidan (Egasi): {dest} — {reason}"
        if len(acc_desc) > 500:
            acc_desc = acc_desc[:497] + '...'

        cur.execute("""
            INSERT INTO accounting_transactions
            (id, transaction_type, category, amount, payment_method, account_source,
             description, transaction_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            linked_acc_id, txn_type, acc_category, amount, acc_method, acc_source,
            acc_desc, txn_time.strftime('%Y-%m-%d'), txn_time.strftime('%Y-%m-%d %H:%M:%S')
        ))

    cur.execute("""
        INSERT INTO owner_accounting_transactions
        (id, transaction_type, amount, category, destination_or_source, reason,
         payment_method, transaction_time, is_clinic_account, linked_accounting_trx_id,
         recorded_by_user, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trx_id, txn_type, amount, category, dest, reason,
        method, txn_time.strftime('%Y-%m-%d %H:%M:%S'), is_clinic_acc, linked_acc_id,
        actor_username, notes
    ))
    conn.commit()

    return get_transaction_by_id(conn, trx_id), None, None


def update_transaction(conn, trx_id, data):
    """
    Update an existing transaction record and sync changes to accounting_transactions if linked.
    Returns: (record_dict, error_message, status_code)
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, transaction_type, amount, category, destination_or_source,
               reason, payment_method, transaction_time, is_clinic_account,
               linked_accounting_trx_id
        FROM owner_accounting_transactions
        WHERE id = ?
    """, (trx_id,))
    existing = cur.fetchone()
    if not existing:
        return None, "Bunday amaliyot topilmadi.", 404

    ex = dict(existing)
    updates = []
    params = []

    # Amount
    amt = ex['amount']
    if 'amount' in data:
        try:
            raw_amt = str(data['amount']).replace(' ', '').replace(',', '.')
            amt = round(float(raw_amt), 2)
            if amt <= 0:
                return None, "Summa 0 dan katta bo'lishi kerak.", 400
            updates.append("amount = ?")
            params.append(amt)
        except (ValueError, TypeError):
            return None, "Summa noto'g'ri kiritildi.", 400

    # Type
    tt = ex['transaction_type']
    if 'transaction_type' in data:
        tt = str(data['transaction_type']).strip().lower()
        if tt not in ('income', 'expense'):
            return None, "Operatsiya turi noto'g'ri.", 400
        updates.append("transaction_type = ?")
        params.append(tt)

    # Destination / Source
    dest = ex['destination_or_source']
    if 'destination_or_source' in data:
        dest = str(data['destination_or_source']).strip()
        if not dest:
            return None, "Qayerga / Qayerdan maydoni to'ldirilishi shart.", 400
        updates.append("destination_or_source = ?")
        params.append(dest)

    # Reason
    reason = ex['reason']
    if 'reason' in data:
        reason = str(data['reason']).strip()
        if not reason:
            return None, "Nega bo'lgani (sababi) kiritilishi shart.", 400
        updates.append("reason = ?")
        params.append(reason)

    # Method
    pm = ex['payment_method']
    if 'payment_method' in data:
        raw_pm = str(data['payment_method']).strip().lower()
        if raw_pm in PAYMENT_METHODS:
            pm = raw_pm
            updates.append("payment_method = ?")
            params.append(pm)

    # Category
    cat = ex['category']
    if 'category' in data:
        c = str(data['category']).strip()
        if c:
            cat = c[:128]
            updates.append("category = ?")
            params.append(cat)

    if 'notes' in data:
        notes = str(data['notes']).strip()
        updates.append("notes = ?")
        params.append(notes or None)

    # Timestamp
    txn_time_str = _format_dt(ex['transaction_time'])
    if 'transaction_time' in data:
        time_raw = str(data['transaction_time']).strip().replace('T', ' ')
        txn_time = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                txn_time = _dt.datetime.strptime(time_raw[:19], fmt)
                break
            except ValueError:
                pass
        if txn_time:
            txn_time_str = txn_time.strftime('%Y-%m-%d %H:%M:%S')
            updates.append("transaction_time = ?")
            params.append(txn_time_str)

    # Clinic account flag handling
    was_clinic = bool(ex.get('is_clinic_account'))
    linked_acc_id = ex.get('linked_accounting_trx_id')
    is_clinic = was_clinic

    if 'is_clinic_account' in data:
        is_clinic = bool(data['is_clinic_account'])
        if is_clinic != was_clinic:
            updates.append("is_clinic_account = ?")
            params.append(1 if is_clinic else 0)

    # Synchronize linked accounting_transactions
    if was_clinic and not is_clinic:
        # User unchecked "klinika hisobidan" -> delete from accounting_transactions
        if linked_acc_id:
            cur.execute("DELETE FROM accounting_transactions WHERE id = ?", (linked_acc_id,))
        updates.append("linked_accounting_trx_id = ?")
        params.append(None)
    elif not was_clinic and is_clinic:
        # User checked "klinika hisobidan" -> create new in accounting_transactions
        new_linked_id = generate_accounting_trx_id(cur)
        acc_method = METHOD_MAP_TO_ACC.get(pm, 'cash')
        acc_source = _acc_source_for(acc_method)
        acc_category = cat if cat in ('operational_expense', 'salary', 'maintenance', 'equipment', 'rent', 'utilities', 'food', 'other_expense', 'other_income') else ('operational_expense' if tt == 'expense' else 'other_income')
        acc_desc = f"Klinika hisobidan (Egasi): {dest} — {reason}"
        if len(acc_desc) > 500:
            acc_desc = acc_desc[:497] + '...'

        cur.execute("""
            INSERT INTO accounting_transactions
            (id, transaction_type, category, amount, payment_method, account_source,
             description, transaction_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_linked_id, tt, acc_category, amt, acc_method, acc_source,
            acc_desc, txn_time_str[:10], txn_time_str
        ))
        updates.append("linked_accounting_trx_id = ?")
        params.append(new_linked_id)
    elif is_clinic and linked_acc_id:
        # Already linked, update details in accounting_transactions
        acc_method = METHOD_MAP_TO_ACC.get(pm, 'cash')
        acc_source = _acc_source_for(acc_method)
        acc_category = cat if cat in ('operational_expense', 'salary', 'maintenance', 'equipment', 'rent', 'utilities', 'food', 'other_expense', 'other_income') else ('operational_expense' if tt == 'expense' else 'other_income')
        acc_desc = f"Klinika hisobidan (Egasi): {dest} — {reason}"
        if len(acc_desc) > 500:
            acc_desc = acc_desc[:497] + '...'

        cur.execute("""
            UPDATE accounting_transactions
            SET transaction_type = ?, amount = ?, category = ?, payment_method = ?,
                account_source = ?, description = ?, transaction_date = ?
            WHERE id = ?
        """, (
            tt, amt, acc_category, acc_method, acc_source, acc_desc, txn_time_str[:10], linked_acc_id
        ))

    if updates:
        params.append(trx_id)
        cur.execute(f"UPDATE owner_accounting_transactions SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()

    return get_transaction_by_id(conn, trx_id), None, 200


def delete_transaction(conn, trx_id):
    """
    Delete a transaction. Also cleans up linked accounting_transactions row if present.
    Returns: (success_bool, error_message, status_code)
    """
    cur = conn.cursor()
    cur.execute("SELECT id, linked_accounting_trx_id FROM owner_accounting_transactions WHERE id = ?", (trx_id,))
    row = cur.fetchone()
    if not row:
        return False, "Bunday amaliyot topilmadi.", 404

    r = dict(row)
    linked_acc_id = r.get('linked_accounting_trx_id')
    if linked_acc_id:
        cur.execute("DELETE FROM accounting_transactions WHERE id = ?", (linked_acc_id,))

    cur.execute("DELETE FROM owner_accounting_transactions WHERE id = ?", (trx_id,))
    conn.commit()
    return True, None, 200


def list_transactions(conn, start=None, end=None, txn_type=None, search=None,
                      payment_method=None, clinic_scope=None, limit=100, offset=0):
    """
    List owner transactions with flexible filters and comprehensive financial summary.
    clinic_scope: 'all' | 'clinic' (only clinic accounts) | 'private' (only private owner)
    """
    ensure_schema(conn)
    cur = conn.cursor()

    where_clauses = []
    params = []

    if start:
        where_clauses.append("transaction_time >= ?")
        params.append(f"{start} 00:00:00")
    if end:
        where_clauses.append("transaction_time <= ?")
        params.append(f"{end} 23:59:59")
    if txn_type and txn_type in ('income', 'expense'):
        where_clauses.append("transaction_type = ?")
        params.append(txn_type)
    if payment_method and payment_method in PAYMENT_METHODS:
        where_clauses.append("payment_method = ?")
        params.append(payment_method)
    if clinic_scope == 'clinic':
        where_clauses.append("is_clinic_account = 1")
    elif clinic_scope == 'private':
        where_clauses.append("is_clinic_account = 0")

    if search:
        s = f"%{search.strip()}%"
        where_clauses.append(
            "(destination_or_source LIKE ? OR reason LIKE ? OR category LIKE ? OR notes LIKE ? OR id LIKE ?)"
        )
        params.extend([s, s, s, s, s])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # 1. Total filtered count
    cur.execute(f"SELECT COUNT(*) AS total_count FROM owner_accounting_transactions {where_sql}", tuple(params))
    c_row = cur.fetchone()
    total_count = c_row['total_count'] if isinstance(c_row, dict) else c_row[0]

    # 2. Filtered list
    try:
        limit_val = max(1, min(int(limit), 500))
    except (ValueError, TypeError):
        limit_val = 100
    try:
        offset_val = max(0, int(offset))
    except (ValueError, TypeError):
        offset_val = 0

    query_params = list(params) + [limit_val, offset_val]
    cur.execute(f"""
        SELECT id, transaction_type, amount, category, destination_or_source,
               reason, payment_method, transaction_time, is_clinic_account,
               linked_accounting_trx_id, created_at, recorded_by_user, notes
        FROM owner_accounting_transactions
        {where_sql}
        ORDER BY transaction_time DESC, created_at DESC
        LIMIT ? OFFSET ?
    """, tuple(query_params))

    raw_rows = cur.fetchall()
    transactions = []
    for row in raw_rows:
        r = dict(row)
        r['amount'] = float(r['amount'] or 0.0)
        r['is_clinic_account'] = bool(r.get('is_clinic_account'))
        r['transaction_time'] = _format_dt(r.get('transaction_time'))
        r['created_at'] = _format_dt(r.get('created_at'))
        r['payment_method_label'] = PAYMENT_METHODS.get(r.get('payment_method'), r.get('payment_method'))
        transactions.append(r)

    # 3. Financial Summary for the filtered range
    cur.execute(f"""
        SELECT transaction_type,
               COALESCE(SUM(amount), 0.0) AS total_amount,
               COUNT(*) AS cnt
        FROM owner_accounting_transactions
        {where_sql}
        GROUP BY transaction_type
    """, tuple(params))
    sum_rows = cur.fetchall()

    filtered_income = 0.0
    filtered_expense = 0.0
    income_count = 0
    expense_count = 0
    for sr in sum_rows:
        srd = dict(sr)
        tt = srd['transaction_type']
        amt = float(srd['total_amount'] or 0.0)
        cnt = int(srd['cnt'] or 0)
        if tt == 'income':
            filtered_income = amt
            income_count = cnt
        elif tt == 'expense':
            filtered_expense = amt
            expense_count = cnt

    # 4. Overall all-time summary (unfiltered by date)
    cur.execute("""
        SELECT transaction_type,
               COALESCE(SUM(amount), 0.0) AS total_amount,
               COUNT(*) AS cnt
        FROM owner_accounting_transactions
        GROUP BY transaction_type
    """)
    all_time_rows = cur.fetchall()
    all_time_income = 0.0
    all_time_expense = 0.0
    for ar in all_time_rows:
        ard = dict(ar)
        tt = ard['transaction_type']
        amt = float(ard['total_amount'] or 0.0)
        if tt == 'income':
            all_time_income = amt
        elif tt == 'expense':
            all_time_expense = amt

    # 5. Today's turnover
    today_str = _dt.date.today().isoformat()
    cur.execute("""
        SELECT transaction_type, COALESCE(SUM(amount), 0.0) AS total_amount
        FROM owner_accounting_transactions
        WHERE transaction_time >= ? AND transaction_time <= ?
        GROUP BY transaction_type
    """, (f"{today_str} 00:00:00", f"{today_str} 23:59:59"))
    today_rows = cur.fetchall()
    today_income = 0.0
    today_expense = 0.0
    for tr in today_rows:
        trd = dict(tr)
        if trd['transaction_type'] == 'income':
            today_income = float(trd['total_amount'] or 0.0)
        elif trd['transaction_type'] == 'expense':
            today_expense = float(trd['total_amount'] or 0.0)

    # 6. Distinct categories for autocomplete
    cur.execute("SELECT DISTINCT destination_or_source FROM owner_accounting_transactions ORDER BY destination_or_source ASC LIMIT 100")
    categories = [r['destination_or_source'] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

    return {
        'transactions': transactions,
        'total_count': total_count,
        'limit': limit_val,
        'offset': offset_val,
        'summary': {
            'period_income': round(filtered_income, 2),
            'period_expense': round(filtered_expense, 2),
            'period_balance': round(filtered_income - filtered_expense, 2),
            'income_count': income_count,
            'expense_count': expense_count,
            'all_time_income': round(all_time_income, 2),
            'all_time_expense': round(all_time_expense, 2),
            'all_time_balance': round(all_time_income - all_time_expense, 2),
            'today_income': round(today_income, 2),
            'today_expense': round(today_expense, 2),
        },
        'categories': categories
    }
