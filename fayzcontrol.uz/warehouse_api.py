"""
Fayz Medical House — /api/warehouse HTTP routes.

The routes are plain functions over `inventory.py` so server.py keeps only a
thin hook. `handle()` returns (status, payload); the server writes it out. A
payload with a `_csv` key is a file download.

Authorization has two layers: permissions.authorize_api() has already decided
whether the caller may reach the route at all (module and verb). What stays
here is what the route table cannot say: which FIELDS a caller may see or
change (costs, patient price, threshold are accounting's), checked in the
handler so a hidden button in the page is never the only guard.
"""

import csv
import datetime as _dt
import io
import re
from decimal import Decimal

import inventory
import permissions
from inventory import InventoryError, NotFound, Forbidden

PREFIX = '/api/warehouse'


def _actor(user):
    user = user or {}
    return {'username': user.get('username'), 'staff_id': user.get('staff_id')}


def _first(query, key, default=None):
    vals = (query or {}).get(key)
    return vals[0] if vals else default


def _int(query, key, default, minimum=0, maximum=100000):
    raw = _first(query, key)
    if raw in (None, ''):
        return default
    # ASCII digits only: str.isdigit() and int() also accept characters such
    # as superscript two or fullwidth digits, and '1_000'.
    if not re.fullmatch(r'[0-9]{1,18}', str(raw).strip()):
        raise InventoryError(f"{key} butun son bo'lishi kerak.", key)
    return max(minimum, min(int(str(raw).strip()), maximum))


def _date_param(ctx, query, key, label):
    raw = _first(query, key)
    if raw in (None, ''):
        return None
    d, err = ctx['parse_date_param'](raw, default_today=False, field=label)
    if err:
        raise InventoryError(err, key)
    return d


def _err(e):
    payload = {'error': e.message}
    if e.field:
        payload['field'] = e.field
    return e.status, payload


def _csv_cell(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'ha' if v else "yo'q"
    if isinstance(v, Decimal):
        s = format(v.normalize(), 'f')
        return s
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat(sep=' ') if isinstance(v, _dt.datetime) else v.isoformat()
    s = str(v)
    # A cell that starts with = + - @ is executed as a formula by spreadsheet
    # programs; names and notes come from people, so neutralise them. A plain
    # negative number (days_left -3) is data, not a formula, and stays as is.
    if s and (s[0] in '=+@\t\r' or (s[0] == '-' and not re.fullmatch(r'-[0-9]+(\.[0-9]+)?', s))):
        s = "'" + s
    return s


def to_csv(columns, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c['label'] for c in columns])
    for r in rows:
        w.writerow([_csv_cell(r.get(c['key'])) for c in columns])
    # BOM so Excel reads the Uzbek apostrophes and Cyrillic as UTF-8.
    return '﻿' + buf.getvalue()


def _notify_for(conn, trx_id):
    """What the Telegram hook needs about a new expense, or None."""
    if not trx_id:
        return None
    cur = inventory._cursor(conn)
    cur.execute("""SELECT id, transaction_type, category, amount, payment_method, description,
                          transaction_date, recorded_by_staff_id
                   FROM accounting_transactions WHERE id = ?""", (trx_id,))
    r = cur.fetchone()
    if not r:
        return None
    return {'id': r['id'], 'transaction_type': r['transaction_type'], 'category': r['category'],
            'amount': float(r['amount']), 'payment_method': r['payment_method'],
            'description': r['description'], 'date': r['transaction_date'].isoformat(),
            'recorded_by_staff_id': r['recorded_by_staff_id']}


def handle(method, path, query, body, user, conn, ctx):
    """Dispatch one /api/warehouse request. Always returns (status, payload)."""
    # The same normalised path the permission check decided on.
    parts = permissions.warehouse_parts(path)
    if parts is None:
        return 404, {'error': "Yo'nalish topilmadi."}
    if method != 'GET' and not isinstance(body, dict):
        return 400, {'error': "So'rov formati noto'g'ri (JSON obyekt kutilgan)."}
    try:
        if method == 'GET':
            result = _get(parts, query, user, conn, ctx)
        else:
            try:
                result = _write(method, parts, body, user, conn, ctx)
                conn.commit()
            except Exception:
                # One request is one transaction: nothing of a failed operation
                # (stock, ledger, history) survives.
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            if isinstance(result[1], dict) and result[1].get('status') == 'posted' \
                    and not result[1].get('duplicate'):
                note = _notify_for(conn, result[1].get('accounting_transaction_id'))
                if note:
                    result[1]['_notify'] = note
        return result
    except InventoryError as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _get(parts, query, user, conn, ctx):
    can_cost = permissions.can_see_costs(user)
    head = parts[0] if parts else ''
    n = len(parts)
    has_wh = permissions.can(user, 'warehouse', 'read')

    if head in permissions.WAREHOUSE_PUBLIC_READS and n == 1 and not permissions.can_read_warehouse_public(user):
        raise Forbidden("Ombor ma'lumotini ko'rishga ruxsat yo'q.")

    if head == 'availability' and n == 1:
        return 200, {'items': inventory.availability(conn, _first(query, 'q'), _int(query, 'limit', 30, 1, 100))}

    if head == 'summary' and n == 1:
        # Expiry changes with the calendar: bring the alerts up to date first,
        # under the write lock (see inventory.refresh_alerts_if_due).
        inventory.refresh_alerts_if_due(conn, ctx.get('write_lock'))
        return 200, inventory.summary(conn, can_cost=can_cost, full=has_wh)

    if head == 'patients' and n == 1:
        return 200, {'patients': inventory.search_patients(conn, _first(query, 'q'), _int(query, 'limit', 20, 1, 50))}

    if head == 'settings' and n == 1:
        return 200, inventory.get_settings(conn)

    if head == 'items':
        if n == 1:
            status = _first(query, 'status')
            if status and status not in ('ok', 'low', 'out', 'expired', 'expiring'):
                raise InventoryError("Holat noto'g'ri. Ruxsat etilgan: ok, low, out, expired, expiring.", 'status')
            filters = {k: _first(query, k) for k in ('q', 'category', 'item_type', 'supplier_id',
                                                     'active', 'sort', 'dir')}
            filters.update({'status': status, 'limit': _int(query, 'limit', 100, 1, 500),
                            'offset': _int(query, 'offset', 0)})
            items, total = inventory.list_items(conn, filters, can_cost)
            return 200, {'items': items, 'total': total}
        if n == 2:
            return 200, inventory.get_item(conn, parts[1], can_cost)

    if head == 'suppliers' and n == 1:
        return 200, {'suppliers': inventory.list_suppliers(conn)}

    if head == 'receipts':
        if n == 1:
            filters = {'from': _date_param(ctx, query, 'from', 'Boshlanish sanasi'),
                       'to': _date_param(ctx, query, 'to', 'Tugash sanasi'),
                       'supplier_id': _first(query, 'supplier_id'), 'status': _first(query, 'status'),
                       'limit': _int(query, 'limit', 100, 1, 500), 'offset': _int(query, 'offset', 0)}
            rows, total = inventory.list_receipts(conn, filters, can_cost)
            return 200, {'receipts': rows, 'total': total}
        if n == 2:
            return 200, inventory.get_receipt(conn, parts[1], can_cost)

    if head == 'dispensings' and n == 1:
        filters = {'patient_id': _first(query, 'patient_id'), 'item_id': _first(query, 'item_id'),
                   'prescription_id': _first(query, 'prescription_id'), 'status': _first(query, 'status'),
                   'from': _date_param(ctx, query, 'from', 'Boshlanish sanasi'),
                   'to': _date_param(ctx, query, 'to', 'Tugash sanasi'),
                   'limit': _int(query, 'limit', 100, 1, 500), 'offset': _int(query, 'offset', 0)}
        rows, total = inventory.list_dispensings(conn, filters, can_cost)
        return 200, {'dispensings': rows, 'total': total}

    if head == 'prescriptions' and n == 2 and parts[1] == 'pending':
        return 200, {'prescriptions': inventory.pending_prescriptions(conn, _first(query, 'patient_id'))}

    if head == 'transactions' and n == 1:
        filters = {'item_id': _first(query, 'item_id'), 'type': _first(query, 'type'),
                   'patient_id': _first(query, 'patient_id'),
                   'from': _date_param(ctx, query, 'from', 'Boshlanish sanasi'),
                   'to': _date_param(ctx, query, 'to', 'Tugash sanasi'),
                   'limit': _int(query, 'limit', 100, 1, 1000), 'offset': _int(query, 'offset', 0)}
        rows, total = inventory.list_transactions(conn, filters, can_cost)
        return 200, {'transactions': rows, 'total': total}

    if head == 'alerts' and n == 1:
        inventory.refresh_alerts_if_due(conn, ctx.get('write_lock'))
        status = _first(query, 'status', 'active')
        if status not in ('active', 'resolved', 'all'):
            raise InventoryError("Holat noto'g'ri (active, resolved yoki all).", 'status')
        a_type = _first(query, 'type') or None
        if a_type and a_type not in inventory.ALERT_TYPES:
            raise InventoryError(f"Turi noto'g'ri. Ruxsat etilgan: {', '.join(inventory.ALERT_TYPES)}.", 'type')
        limit, offset = _int(query, 'limit', 100, 1, 500), _int(query, 'offset', 0)
        rows, total = inventory.list_alerts(conn, status, limit, offset, _first(query, 'item_id') or None, a_type)
        return 200, {'alerts': rows, 'total': total, 'limit': limit, 'offset': offset}

    if head == 'reconciliation' and n == 1:
        return 200, inventory.reconciliation(conn)

    if head == 'reports' and n == 2:
        params = {'from': _date_param(ctx, query, 'from', 'Boshlanish sanasi'),
                  'to': _date_param(ctx, query, 'to', 'Tugash sanasi'),
                  'item_id': _first(query, 'item_id'), 'supplier_id': _first(query, 'supplier_id'),
                  'patient_id': _first(query, 'patient_id')}
        if params['from'] and params['to'] and params['to'] < params['from']:
            raise InventoryError("Tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas.", 'to')
        fmt = (_first(query, 'format') or 'json').lower()
        if fmt not in ('json', 'csv'):
            raise InventoryError("Format noto'g'ri (json yoki csv).", 'format')
        if fmt == 'csv':
            # The export carries the whole range (up to MAX_EXPORT_ROWS); a
            # longer one is cut and says so in the X-Truncated header.
            rep = inventory.report(conn, parts[1], params, can_cost, limit=inventory.MAX_EXPORT_ROWS,
                                   offset=0, max_limit=inventory.MAX_EXPORT_ROWS)
            return 200, {'_csv': to_csv(rep['columns'], rep['rows']),
                         '_truncated': bool(rep['truncated']),
                         '_filename': f"ombor-{parts[1]}-{_dt.date.today().isoformat()}.csv"}
        rep = inventory.report(conn, parts[1], params, can_cost,
                               limit=_int(query, 'limit', 1000, 1, inventory.MAX_REPORT_ROWS),
                               offset=_int(query, 'offset', 0), max_limit=inventory.MAX_REPORT_ROWS)
        return 200, rep

    raise NotFound("Yo'nalish topilmadi.")


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _strip_item(item, can_cost):
    return item if can_cost else inventory.strip_costs(item, inventory.COST_ITEM_FIELDS)


def _bool_field(body, key):
    """A real JSON boolean. Absent is False. A string such as "false" is refused
    (a client that sends it by mistake would otherwise post a draft receipt)."""
    v = body.get(key)
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    raise InventoryError(f"{key} true yoki false bo'lishi kerak.", key)


def _payment_method(body, ctx):
    """The payment method as the books know it; an unknown one is refused, not turned into cash."""
    raw = body.get('payment_method')
    if raw in (None, ''):
        return 'cash'
    if not isinstance(raw, str):
        raise InventoryError("To'lov usuli noto'g'ri.", 'payment_method')
    key = raw.strip().lower()
    aliases = ctx.get('payment_method_aliases') or {}
    if key not in aliases and key not in inventory.PAYMENT_METHODS:
        raise InventoryError("To'lov usuli noto'g'ri. Ruxsat etilgan: " + ', '.join(inventory.PAYMENT_METHODS) + ".",
                             'payment_method')
    return ctx['normalize_payment_method'](key)


def _write(method, parts, body, user, conn, ctx):
    actor = _actor(user)
    can_cost = permissions.can_see_costs(user)
    can_cost_write = permissions.can(user, 'accounting', 'write')
    head = parts[0] if parts else ''
    n = len(parts)

    # Defence in depth: the route table already asked for accounting:write on
    # these, but the handler must not depend on a path being spelled the way
    # the table expected.
    if permissions.warehouse_is_money_route(method, parts) and not can_cost_write:
        raise Forbidden("Bu amal faqat buxgalteriya uchun.")

    if method == 'POST' and head == 'items':
        if n == 1:
            item = inventory.create_item(conn, body, actor, can_cost=can_cost_write)
            return 201, _strip_item(item, can_cost)
        if n == 3 and parts[2] in ('deactivate', 'activate'):
            item = inventory.set_item_active(conn, parts[1], parts[2] == 'activate')
            return 200, _strip_item(item, can_cost)

    if method == 'PUT' and head == 'items' and n == 2:
        item = inventory.update_item(conn, parts[1], body, actor, can_cost=can_cost_write)
        return 200, _strip_item(item, can_cost)

    if method == 'PUT' and head == 'items' and n == 3 and parts[2] == 'threshold':
        item = inventory.set_threshold(conn, parts[1], body.get('min_stock_level'), actor)
        return 200, _strip_item(item, can_cost)

    if method == 'POST' and head == 'suppliers' and n == 1:
        return 201, inventory.create_supplier(conn, body, actor)

    if method == 'POST' and head == 'receipts':
        src = ctx['account_source_for']
        if n == 1:
            post = _bool_field(body, 'post')
            r = inventory.create_receipt(conn, body, actor, post=post,
                                         payment_method=_payment_method(body, ctx),
                                         account_source_fn=src)
            return (200 if r.get('duplicate') else 201), r
        if n == 3 and parts[2] == 'post':
            return 200, inventory.post_receipt(conn, parts[1], actor, src)
        if n == 3 and parts[2] == 'cancel':
            return 200, inventory.cancel_receipt(conn, parts[1], actor)
        if n == 3 and parts[2] == 'reverse':
            return 200, inventory.reverse_receipt(conn, parts[1], body.get('reason'), actor)

    if method == 'POST' and head == 'dispense' and n == 1:
        # The HTTP route always records source 'manual': 'nurse_round' and
        # 'billing' are for the service calls made by those code paths.
        if body.get('client_request_id') in (None, ''):
            raise InventoryError("client_request_id majburiy (takroriy so'rovdan himoya).", 'client_request_id')
        d = inventory.dispense(conn, body, actor, source='manual')
        if not can_cost:
            inventory.strip_costs(d, inventory.DISPENSING_COST_FIELDS)
            for b in d['batches']:
                b.pop('unit_cost', None)
        return (200 if d.get('duplicate') else 201), d

    if method == 'POST' and head == 'dispensings' and n == 3 and parts[2] == 'reverse':
        d = inventory.reverse_dispensing(conn, parts[1], body.get('reason'), actor)
        if not can_cost:
            inventory.strip_costs(d, inventory.DISPENSING_COST_FIELDS)
            for b in d['batches']:
                b.pop('unit_cost', None)
        return 200, d

    if method == 'POST' and head == 'adjustments' and n == 1:
        if body.get('client_request_id') in (None, ''):
            raise InventoryError("client_request_id majburiy (takroriy so'rovdan himoya).", 'client_request_id')
        res = inventory.adjust(conn, body, actor)
        res['id'] = res['operation_id']
        if not can_cost:
            for t in res['transactions']:
                inventory._strip_txn(t)
        return (200 if res.get('duplicate') else 201), res

    if method == 'POST' and head == 'transactions' and n == 3 and parts[2] == 'reverse':
        t = inventory.reverse_transaction(conn, inventory.parse_int_id(parts[1], 'id', 'Harakat raqami') or -1,
                                          body.get('reason'), actor)
        if not can_cost:
            inventory._strip_txn(t)
        return 200, t

    raise NotFound("Yo'nalish topilmadi.")
