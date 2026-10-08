"""
Fayz Medical House — Audit Trail

The audit_logs table has existed in the schema since the beginning but nothing
ever wrote to it, so the system could not answer the question any medical
records system is eventually asked: who saw or changed this patient's record,
and when.

Every mutating request now leaves a row here, along with sign-in attempts and
refused access. Two constraints in the existing schema shape how:

  * performed_by_staff_id is a foreign key to staff(id), and not every login
    corresponds to a staff row (the superadmin account has none). The column
    holds a real staff id when one exists and NULL otherwise; the acting
    username is always recorded inside the JSON payload, so the trail never
    loses track of who acted.

  * action_type is CHECK-constrained to seven clinical values with nothing for
    authentication events. ensure_schema() widens that list in place, once, at
    startup.

Auditing must never break the request it is describing: every failure here is
swallowed and reported to the console.
"""

import os
import json
import datetime as _dt

# Clinical actions the original schema allowed.
CLINICAL_ACTIONS = {
    'CREATE', 'UPDATE', 'DELETE',
    'CHECK_IN', 'CHECK_OUT', 'TRANSFER', 'PAYMENT_RECEIVED',
}

# Added by ensure_schema() so sign-ins and refusals can be recorded too.
AUTH_ACTIONS = {
    'LOGIN', 'LOGIN_FAILED', 'LOGOUT', 'ACCESS_DENIED', 'PASSWORD_CHANGED',
}

ALL_ACTIONS = CLINICAL_ACTIONS | AUTH_ACTIONS

_schema_checked = False


def ensure_schema(conn):
    """
    Widen audit_logs.action_type to accept authentication events.

    Idempotent and safe to call on every start: it inspects the current CHECK
    clause and only rewrites it when an expected value is missing.
    """
    global _schema_checked
    if _schema_checked:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE
            FROM information_schema.CHECK_CONSTRAINTS cc
            JOIN information_schema.TABLE_CONSTRAINTS tc
              ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
             AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
            WHERE tc.TABLE_NAME = 'audit_logs' AND tc.TABLE_SCHEMA = DATABASE()
        """)
        rows = cur.fetchall() or []
        target = None
        for r in rows:
            clause = str(r['CHECK_CLAUSE'] if hasattr(r, 'keys') else r[1])
            if 'action_type' in clause:
                target = (r['CONSTRAINT_NAME'] if hasattr(r, 'keys') else r[0], clause)
                break

        if target and all(a in target[1] for a in AUTH_ACTIONS):
            _schema_checked = True
            return

        allowed = ', '.join(f"'{a}'" for a in sorted(ALL_ACTIONS))
        if target:
            cur.execute(f"ALTER TABLE audit_logs DROP CHECK {target[0]}")
        cur.execute(
            f"ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_chk_1 "
            f"CHECK (action_type IN ({allowed}))"
        )
        conn.commit()
        print("[✓] audit_logs.action_type widened to include authentication events.")
        _schema_checked = True
    except Exception as e:
        print(f"[!] Could not widen audit_logs.action_type ({e}). "
              f"Authentication events will not be recorded.")
        _schema_checked = True   # do not retry on every request


# How long the trail is kept. Two years by default -- generous, because this is
# a medical audit trail and how long it must be retained is a decision for the
# clinic and its regulator, not for this file. Set FMH_AUDIT_KEEP_DAYS to 0 to
# keep everything for ever.
KEEP_DAYS = int(os.environ.get('FMH_AUDIT_KEEP_DAYS', 730))

_index_checked = False


def ensure_index(conn):
    """
    Index audit_logs by time.

    The table had indexes on its primary key and on performed_by_staff_id and
    nothing else, so anything asking "what happened between these dates" --
    a retention sweep, or the viewer this still needs -- had to read every
    row. It reached 82,000 rows in a few days of testing.

    Idempotent; safe on every start.
    """
    global _index_checked
    if _index_checked:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) AS n FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'audit_logs'
              AND INDEX_NAME = 'idx_audit_timestamp'
        """)
        row = cur.fetchone()
        have = row['n'] if isinstance(row, dict) or hasattr(row, 'keys') else row[0]
        if not have:
            cur.execute("CREATE INDEX idx_audit_timestamp ON audit_logs (`timestamp`)")
            conn.commit()
            print("[✓] audit_logs indexed by timestamp.")
        _index_checked = True
    except Exception as e:
        print(f"[!] Could not index audit_logs by timestamp: {e}")
        _index_checked = True


def prune(conn, keep_days=None):
    """
    Drop entries older than the retention window. Returns how many went.

    Deleted in batches so a first run against a table that has never been
    pruned cannot hold a single enormous transaction open while the clinic is
    working.
    """
    keep = KEEP_DAYS if keep_days is None else int(keep_days)
    if keep <= 0:
        return 0
    ensure_index(conn)
    cur = conn.cursor()
    removed = 0
    while True:
        cur.execute("""
            DELETE FROM audit_logs
            WHERE `timestamp` < DATE_SUB(NOW(), INTERVAL ? DAY)
            LIMIT 5000
        """, (keep,))
        n = cur.rowcount or 0
        conn.commit()
        removed += n
        if n < 5000:
            break
    return removed


def _staff_id_for(user):
    """
    The staff row this account maps to, or None.

    performed_by_staff_id is a foreign key, so an id that does not exist in
    staff would fail the insert. Accounts without a staff_id (the superadmin)
    record NULL and rely on the username in the payload.
    """
    if not user:
        return None
    sid = user.get('staff_id')
    return sid or None


REDACTED = '[yashirilgan]'


def _is_secret_key(key):
    k = str(key).lower()
    return 'password' in k or k in ('token', 'secret', 'api_key')


def redact(data):
    """
    A copy of `data` with every secret string replaced by REDACTED.

    Only string values are masked, so a flag such as must_change_password
    (a boolean) still tells the reader what happened.
    """
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if _is_secret_key(k) and isinstance(v, str):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data


def scrub_secrets(conn):
    """
    Mask passwords already written into the trail, before redact() existed.

    Idempotent: rows are re-read and only those still holding a clear-text
    secret are rewritten. Returns how many rows changed. Only the secret
    values change; who, what and when stay exactly as recorded.
    """
    cur = conn.cursor()
    changed = 0
    for column in ('new_data_json', 'old_data_json'):
        # The LIKE narrows a full-table read to the few rows that mention a
        # password key at all; the JSON is then checked properly in Python.
        cur.execute(f"SELECT id, {column} AS doc FROM audit_logs "
                    f"WHERE CAST({column} AS CHAR) LIKE '%password%'")
        rows = cur.fetchall() or []
        for r in rows:
            raw = r['doc'] if hasattr(r, 'keys') else r[1]
            try:
                doc = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            except Exception:
                continue
            clean = redact(doc)
            if clean != doc:
                cur.execute(f"UPDATE audit_logs SET {column} = ? WHERE id = ?",
                            (json.dumps(clean, ensure_ascii=False, default=str),
                             r['id'] if hasattr(r, 'keys') else r[0]))
                changed += 1
        conn.commit()
    return changed


def record(conn, entity_name, entity_id, action_type,
           user=None, old_data=None, new_data=None, ip_address=None, note=None):
    """
    Append one row to the audit trail.

    Never raises: a failure to audit is reported but does not fail the action
    being audited.
    """
    if action_type not in ALL_ACTIONS:
        # Keep the trail honest rather than silently mislabelling.
        print(f"[!] Refusing to audit unknown action_type {action_type!r}")
        return
    try:
        # The generic write hook passes the whole request body, and the user
        # console's body carried the password an administrator typed: 2,414
        # rows of the local trail held one in clear text. Secrets are masked
        # here, at the one place every row goes through.
        new_data = redact(new_data)
        old_data = redact(old_data)
        payload_new = dict(new_data) if isinstance(new_data, dict) else ({} if new_data is None else {'value': new_data})
        # The acting identity always travels with the row, even when the
        # foreign key has to be NULL.
        payload_new['_actor'] = (user or {}).get('username') or 'anonymous'
        payload_new['_actor_role'] = (user or {}).get('role') or 'none'
        if note:
            payload_new['_note'] = note

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_logs
                (entity_name, entity_id, action_type, old_data_json, new_data_json,
                 performed_by_staff_id, ip_address, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(entity_name)[:64],
            str(entity_id)[:64],
            action_type,
            json.dumps(old_data, ensure_ascii=False, default=str) if old_data else None,
            json.dumps(payload_new, ensure_ascii=False, default=str),
            _staff_id_for(user),
            (ip_address or '')[:64] or None,
            _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        ))
        conn.commit()
    except Exception as e:
        print(f"[!] Audit write failed ({entity_name}/{entity_id}/{action_type}): {e}")


# ---------------------------------------------------------------------------
# Mapping requests onto audit entries
# ---------------------------------------------------------------------------

# Which entity a mutating path is about, longest prefix wins. Used to give the
# trail a meaningful entity_name instead of the raw URL.
_ENTITY_BY_PREFIX = [
    ('/api/doctor/prescriptions', 'prescriptions'),
    ('/api/doctor/consultation-case', 'consultation'),
    ('/api/doctor/anamnesis', 'medical_histories'),
    ('/api/doctor/epicrisis', 'discharge_epicrises'),
    ('/api/doctor/notes', 'doctor_daily_notes'),
    ('/api/daily-logs', 'daily_logs'),
    ('/api/accounting/transaction', 'accounting_transactions'),
    ('/api/reception/appointment', 'appointments'),
    ('/api/reception/call-log', 'call_logs'),
    ('/api/facility/rooms', 'rooms'),
    ('/api/facility/beds', 'beds'),
    ('/api/settings/pricing', 'pricing_config'),
    ('/api/crm/patients', 'patients'),
    ('/api/crm/payments', 'payments'),
    ('/api/accounting/medication-purchases', 'medication_purchases'),
    ('/api/accounting/medicine-links', 'medication_aliases'),
    ('/api/accounting/invoice-items', 'invoice_items'),
    ('/api/accounting/transaction', 'accounting_transactions'),
    ('/api/admissions', 'admissions'),
    ('/api/payments', 'payments'),
    ('/api/patients', 'patients'),
    ('/api/beds', 'beds'),
    ('/api/staff', 'staff'),
    ('/api/hr/staff', 'staff'),
    ('/api/hr/attendance', 'staff_attendance'),
    ('/api/users', 'users'),
]


def entity_for_path(path):
    best = None
    for prefix, entity in _ENTITY_BY_PREFIX:
        if path.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, entity)
    return best[1] if best else 'api'


def action_for(method, path):
    """
    Translate an HTTP verb into one of the schema's action types, preferring a
    clinically meaningful label where the path says what happened.
    """
    if '/discharge' in path:
        return 'CHECK_OUT'
    if '/transfer' in path:
        return 'TRANSFER'
    if path.endswith('/reactivate'):
        return 'UPDATE'
    # An administrator issuing a new one-time password. Without this it was
    # labelled CREATE, as if a new account had been made.
    if path.endswith('/reset-password'):
        return 'PASSWORD_CHANGED'
    if path.startswith('/api/admissions') and method == 'POST':
        return 'CHECK_IN'
    if path.rstrip('/').endswith('/payments') or '/payments' in path:
        return 'PAYMENT_RECEIVED' if method == 'POST' else 'UPDATE'
    return {'POST': 'CREATE', 'PUT': 'UPDATE', 'DELETE': 'DELETE'}.get(method, 'UPDATE')


def entity_id_from(path, body, response_body):
    """
    Best-effort identifier for the audited row: an id the response reported, an
    id in the request, or the trailing path segment.
    """
    for source in (response_body, body):
        if isinstance(source, dict):
            for key in ('id', 'admission_id', 'patient_id', 'payment_id', 'staff_id'):
                if source.get(key):
                    return str(source[key])
    tail = path.rstrip('/').rsplit('/', 1)[-1]
    return tail or path


# ---------------------------------------------------------------------------
# Reading the trail (GET /api/audit)
#
# The trail was written for a year with no way to read it short of a MySQL
# prompt, so "who changed this bill" could not be answered by the clinic.
# ---------------------------------------------------------------------------

MAX_PAGE = 200
_ENTITY_CHARS = set('abcdefghijklmnopqrstuvwxyz0123456789_')


def _like_escape(text):
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _summary(new_doc, old_doc):
    """A one-line description of a row for the table, secrets masked."""
    parts = []
    doc = redact(new_doc) if isinstance(new_doc, dict) else {}
    if doc.get('_note'):
        parts.append(str(doc['_note']))
    for k, v in doc.items():
        if str(k).startswith('_'):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, default=str)
        v = str(v)
        if len(v) > 40:
            v = v[:39] + '…'
        parts.append(f'{k}: {v}')
    text = '; '.join(parts)
    if old_doc:
        text = (text + ' ' if text else '') + "(eski qiymat saqlangan)"
    return text[:240]


def parse_search(query):
    """
    Read GET /api/audit filters from a parsed query string.
    Returns (filters, None) or (None, (message, field)).
    """
    def one(name):
        v = query.get(name, [''])[0]
        return (v or '').strip()

    f = {}
    for name, label in (('from', "Boshlanish sanasi"), ('to', "Tugash sanasi")):
        raw = one(name)
        if raw:
            try:
                f[name] = _dt.date.fromisoformat(raw[:10])
            except ValueError:
                return None, (f"{label} noto'g'ri. Format: YYYY-MM-DD.", name)
    if f.get('from') and f.get('to') and f['to'] < f['from']:
        return None, ("Tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas.", 'to')

    user = one('user').lower()
    if len(user) > 64:
        return None, ("Foydalanuvchi logini juda uzun.", 'user')
    if user:
        f['user'] = user

    entity = one('entity').lower()
    if entity:
        if len(entity) > 64 or not set(entity) <= _ENTITY_CHARS:
            return None, ("Bo'lim (jadval) nomi noto'g'ri.", 'entity')
        f['entity'] = entity

    action = one('action').upper()
    if action:
        if action not in ALL_ACTIONS:
            return None, ("Amal turi noto'g'ri.", 'action')
        f['action'] = action

    q = one('q')
    if len(q) > 100:
        return None, ("Qidiruv matni 100 belgidan oshmasin.", 'q')
    if q:
        f['q'] = q

    for name, default, low, high in (('limit', 50, 1, MAX_PAGE), ('offset', 0, 0, 10_000_000)):
        raw = one(name)
        if not raw:
            f[name] = default
            continue
        try:
            n = int(raw)
        except ValueError:
            return None, (f"'{name}' butun son bo'lishi kerak.", name)
        if n < low or n > high:
            return None, (f"'{name}' {low}..{high} oralig'ida bo'lishi kerak.", name)
        f[name] = n
    f['facets'] = one('facets') in ('1', 'true', 'yes')
    return f, None


def search(conn, f):
    """Run a filtered, paged read of the trail. `f` comes from parse_search."""
    ensure_index(conn)
    where, params = [], []
    if f.get('from'):
        where.append("`timestamp` >= ?")
        params.append(f['from'].isoformat() + ' 00:00:00')
    if f.get('to'):
        where.append("`timestamp` < ?")
        params.append((f['to'] + _dt.timedelta(days=1)).isoformat() + ' 00:00:00')
    if f.get('user'):
        where.append("JSON_UNQUOTE(JSON_EXTRACT(new_data_json, '$._actor')) = ?")
        params.append(f['user'])
    if f.get('entity'):
        where.append("entity_name = ?")
        params.append(f['entity'])
    if f.get('action'):
        where.append("action_type = ?")
        params.append(f['action'])
    if f.get('q'):
        pat = '%' + _like_escape(f['q']) + '%'
        where.append("(entity_id LIKE ? OR ip_address LIKE ? "
                     "OR CAST(new_data_json AS CHAR) LIKE ?)")
        params.extend([pat, pat, pat])
    clause = (' WHERE ' + ' AND '.join(where)) if where else ''

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM audit_logs" + clause, tuple(params))
    row = cur.fetchone()
    total = int(row['n'] if hasattr(row, 'keys') else row[0])

    cur.execute("SELECT id, `timestamp`, entity_name, entity_id, action_type, "
                "new_data_json, old_data_json, performed_by_staff_id, ip_address "
                "FROM audit_logs" + clause + " ORDER BY id DESC LIMIT ? OFFSET ?",
                tuple(params) + (f['limit'], f['offset']))
    out = []
    for r in cur.fetchall() or []:
        def load(raw):
            if raw in (None, ''):
                return None
            try:
                return json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            except Exception:
                return None
        new_doc = load(r['new_data_json'])
        old_doc = load(r['old_data_json'])
        nd = new_doc if isinstance(new_doc, dict) else {}
        ts = r['timestamp']
        out.append({
            'id': r['id'],
            'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S') if hasattr(ts, 'strftime') else str(ts),
            'actor': nd.get('_actor') or '',
            'actor_role': nd.get('_actor_role') or '',
            'action': r['action_type'],
            'entity': r['entity_name'],
            'entity_id': r['entity_id'],
            'staff_id': r['performed_by_staff_id'],
            'ip': r['ip_address'] or '',
            'summary': _summary(new_doc, old_doc),
        })
    result = {'rows': out, 'total': total, 'limit': f['limit'], 'offset': f['offset']}
    if f.get('facets'):
        cur.execute("SELECT DISTINCT entity_name FROM audit_logs ORDER BY entity_name")
        result['entities'] = [(x['entity_name'] if hasattr(x, 'keys') else x[0])
                              for x in cur.fetchall() or []]
        result['actions'] = sorted(ALL_ACTIONS)
    return result
