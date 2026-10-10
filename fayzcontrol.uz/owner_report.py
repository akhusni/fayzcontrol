"""
The owner's money report: what came in, from where, what went out, on what.

Every money movement already lands in accounting_transactions -- patient
payments through the payments trigger, everything else from the accounting
page -- so this reads that one ledger and only adds meaning to it:

- A patient payment is booked as one line "Bemor to'lovi". The owner asked
  where money comes from, so each payment is split over its invoice's items
  (bed days, consultation, medicine, tests, procedures) in proportion to
  what the invoice charged for them.
- Cash taken from the till to the bank (incasso) moves money between the
  clinic's own accounts. It is reported as a transfer, never as spending.
"""

import datetime as _dt
from collections import OrderedDict

import nursery


INCOME_LABELS = OrderedDict([
    ('bed_stay', "Statsionar (yotoq kunlari)"),
    ('consultation', "Konsultatsiya"),
    ('medication', "Dori-darmon (bemorga)"),
    ('lab_test', "Tahlillar"),
    ('procedure', "Muolajalar"),
    ('other', "Boshqa xizmatlar"),
    ('emergency_call', "Uyga chaqiruv (24/7)"),
    ('outpatient', "Ambulator qabul"),
    ('patient_other', "Bemor to'lovi (xizmat turi yozilmagan)"),
    ('other_income', "Boshqa kirimlar"),
])

EXPENSE_LABELS = OrderedDict([
    ('salary', "Maosh va smena to'lovlari"),
    ('medicine', "Dori-darmon xaridi"),
    ('food', "Bemorlar ovqati"),
    ('rent', "Bino ijarasi"),
    ('utilities', "Kommunal va aloqa"),
    ('equipment', "Jihozlar va sarf materiallari"),
    ('maintenance', "Xo'jalik va ta'mirlash"),
    ('refund', "Bemorlarga qaytarilgan pul"),
    ('other_expense', "Boshqa xarajatlar"),
])

# Stored category -> report group. Several spellings exist because the
# accounting page and the medicine-purchase form were written separately.
_INCOME_CATEGORY = {
    'patient_inpatient': 'bed_stay',
    'patient_outpatient': 'outpatient',
    'emergency_call': 'emergency_call',
}
_EXPENSE_CATEGORY = {
    'salary': 'salary',
    'medication_purchase': 'medicine',
    'pharmacy_restock': 'medicine',
    'nutrition': 'food',
    'food_catering': 'food',
    'rent': 'rent',
    'utilities': 'utilities',
    'equipment': 'equipment',
    'maintenance': 'maintenance',
    'Bemorga qaytarish (Refund)': 'refund',
}
TRANSFER_CATEGORIES = ('incasso',)

METHOD_LABELS = OrderedDict([
    ('cash', "Naqd pul"),
    ('card', "Karta (terminal)"),
    ('online', "Click / Payme"),
    ('bank', "Bank o'tkazmasi"),
])
_METHOD_GROUP = {
    'cash': 'cash', 'cash_register': 'cash',
    'terminal': 'card',
    'payme_click': 'online', 'card_transfer': 'online',
    'bank_wire': 'bank',
}

PATIENT_PAYMENT_CATEGORY = "Bemor to'lovi"
_ITEM_TYPES = ('bed_stay', 'consultation', 'medication', 'lab_test', 'procedure', 'other')


def _f(v):
    return float(v or 0)


def _invoice_shares(cur, invoice_ids):
    """invoice_id -> {group: share of the invoice}, from its charged items."""
    if not invoice_ids:
        return {}
    marks = ', '.join('?' for _ in invoice_ids)
    cur.execute(f"""
        SELECT invoice_id, item_type, SUM(total_amount) AS amount
        FROM invoice_items WHERE invoice_id IN ({marks})
        GROUP BY invoice_id, item_type
    """, tuple(invoice_ids))
    totals = {}
    for r in cur.fetchall():
        group = r['item_type'] if r['item_type'] in _ITEM_TYPES else 'other'
        totals.setdefault(r['invoice_id'], {})
        totals[r['invoice_id']][group] = totals[r['invoice_id']].get(group, 0.0) + _f(r['amount'])
    shares = {}
    for inv, parts in totals.items():
        whole = sum(parts.values())
        if whole > 0:
            shares[inv] = {g: v / whole for g, v in parts.items()}
    return shares


def _patients_for_invoices(cur, invoice_ids):
    if not invoice_ids:
        return {}
    marks = ', '.join('?' for _ in invoice_ids)
    cur.execute(f"""
        SELECT i.id AS invoice_id, p.full_name, p.patient_code
        FROM invoices i
        LEFT JOIN admissions a ON a.id = i.admission_id
        LEFT JOIN appointments ap ON ap.id = i.appointment_id
        JOIN patients p ON p.id = COALESCE(a.patient_id, ap.patient_id)
        WHERE i.id IN ({marks})
    """, tuple(invoice_ids))
    return {r['invoice_id']: (r['full_name'] or r['patient_code']) for r in cur.fetchall()}


def _ledger(cur, start, end):
    cur.execute("""
        SELECT id, transaction_type, category, amount, payment_method,
               related_invoice_id, description, transaction_date, created_at
        FROM accounting_transactions
        WHERE transaction_date BETWEEN ? AND ?
        ORDER BY transaction_date DESC, created_at DESC
    """, (start.isoformat(), end.isoformat()))
    return [dict(r) for r in cur.fetchall()]


def _period_totals(cur, start, end):
    """Income and expense for a period, transfers excluded, in one query."""
    marks = ', '.join('?' for _ in TRANSFER_CATEGORIES)
    cur.execute(f"""
        SELECT transaction_type, COALESCE(SUM(amount), 0) AS total
        FROM accounting_transactions
        WHERE transaction_date BETWEEN ? AND ? AND category NOT IN ({marks})
        GROUP BY transaction_type
    """, (start.isoformat(), end.isoformat()) + TRANSFER_CATEGORIES)
    sums = {r['transaction_type']: _f(r['total']) for r in cur.fetchall()}
    return sums.get('income', 0.0), sums.get('expense', 0.0)


def _totals(rows):
    income = sum(_f(r['amount']) for r in rows if r['transaction_type'] == 'income'
                 and r['category'] not in TRANSFER_CATEGORIES)
    expense = sum(_f(r['amount']) for r in rows if r['transaction_type'] == 'expense'
                  and r['category'] not in TRANSFER_CATEGORIES)
    return income, expense


def summary(conn, start, end):
    """Everything the owner page shows for [start, end] (dates, inclusive)."""
    cur = conn.cursor()
    rows = _ledger(cur, start, end)

    days = (end - start).days + 1
    prev_end = start - _dt.timedelta(days=1)
    prev_start = prev_end - _dt.timedelta(days=days - 1)
    prev_income, prev_expense = _period_totals(cur, prev_start, prev_end)

    invoice_ids = sorted({r['related_invoice_id'] for r in rows if r['related_invoice_id']})
    shares = _invoice_shares(cur, invoice_ids)
    who = _patients_for_invoices(cur, invoice_ids)

    income_groups = {k: {'amount': 0.0, 'count': 0} for k in INCOME_LABELS}
    expense_groups = {k: {'amount': 0.0, 'count': 0} for k in EXPENSE_LABELS}
    methods = {k: {'income': 0.0, 'expense': 0.0} for k in METHOD_LABELS}
    daily = OrderedDict()
    d = start
    while d <= end:
        daily[d.isoformat()] = {'income': 0.0, 'expense': 0.0}
        d += _dt.timedelta(days=1)
    entries = []
    transfers = 0.0

    for r in rows:
        amount = _f(r['amount'])
        day = r['transaction_date'].isoformat() if hasattr(r['transaction_date'], 'isoformat') else str(r['transaction_date'])[:10]
        method = _METHOD_GROUP.get(r['payment_method'], 'cash')
        base = {
            'id': r['id'],
            'date': day,
            'method': method,
            'description': r['description'] or '',
            'who': who.get(r['related_invoice_id']),
            'total': amount,
        }
        if r['category'] in TRANSFER_CATEGORIES:
            transfers += amount
            entries.append(dict(base, type='transfer', group='transfer', amount=amount))
            continue

        if r['transaction_type'] == 'income':
            methods[method]['income'] += amount
            daily.setdefault(day, {'income': 0.0, 'expense': 0.0})['income'] += amount
            if r['category'] == PATIENT_PAYMENT_CATEGORY:
                parts = shares.get(r['related_invoice_id']) or {'patient_other': 1.0}
            else:
                parts = {_INCOME_CATEGORY.get(r['category'], 'other_income'): 1.0}
            for group, share in parts.items():
                part = round(amount * share, 2)
                income_groups[group]['amount'] += part
                income_groups[group]['count'] += 1
                entries.append(dict(base, type='income', group=group, amount=part))
        else:
            methods[method]['expense'] += amount
            daily.setdefault(day, {'income': 0.0, 'expense': 0.0})['expense'] += amount
            group = _EXPENSE_CATEGORY.get(r['category'], 'other_expense')
            expense_groups[group]['amount'] += amount
            expense_groups[group]['count'] += 1
            entries.append(dict(base, type='expense', group=group, amount=amount))

    income, expense = _totals(rows)

    def _listed(groups, labels):
        out = [{'key': k, 'label': labels[k], 'amount': round(v['amount'], 2), 'count': v['count']}
               for k, v in groups.items() if v['count']]
        return sorted(out, key=lambda x: -x['amount'])

    # An invoice is raised for the whole planned stay at booking, so a stay
    # that has not begun is not money anyone owes yet. Only stays that have
    # started count; their figure is still the full stay's unpaid balance.
    # A desk visit (consultation, outpatient course) is billed on its day.
    cur.execute("""
        SELECT i.id AS invoice_id, i.balance_due, p.full_name, p.patient_code,
               COALESCE(a.start_date, ap.appointment_date) AS start_date
        FROM invoices i
        LEFT JOIN admissions a ON a.id = i.admission_id
        LEFT JOIN appointments ap ON ap.id = i.appointment_id
        JOIN patients p ON p.id = COALESCE(a.patient_id, ap.patient_id)
        WHERE i.balance_due > 0 AND i.payment_status IN ('unpaid', 'partial')
          AND COALESCE(a.start_date, ap.appointment_date) <= CURDATE()
        ORDER BY i.balance_due DESC
    """)
    debt_rows = [dict(r) for r in cur.fetchall()]

    usage = nursery.medicine_usage(conn, start.isoformat(), end.isoformat())

    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat(), 'days': days},
        'previous': {
            'start': prev_start.isoformat(), 'end': prev_end.isoformat(),
            'income': round(prev_income, 2), 'expense': round(prev_expense, 2),
            'net': round(prev_income - prev_expense, 2),
        },
        'income': round(income, 2),
        'expense': round(expense, 2),
        'net': round(income - expense, 2),
        'transfers': round(transfers, 2),
        'income_by_source': _listed(income_groups, INCOME_LABELS),
        'expense_by_category': _listed(expense_groups, EXPENSE_LABELS),
        'by_method': [{'key': k, 'label': METHOD_LABELS[k],
                       'income': round(v['income'], 2), 'expense': round(v['expense'], 2)}
                      for k, v in methods.items() if v['income'] or v['expense']],
        'daily': [{'date': k, 'income': round(v['income'], 2), 'expense': round(v['expense'], 2)}
                  for k, v in daily.items()],
        'debts': {
            'total': round(sum(_f(r['balance_due']) for r in debt_rows), 2),
            'count': len(debt_rows),
            'top': [{'invoice_id': r['invoice_id'],
                     'who': r['full_name'] or r['patient_code'],
                     'amount': round(_f(r['balance_due']), 2),
                     'since': r['start_date'].isoformat() if hasattr(r['start_date'], 'isoformat') else r['start_date']}
                    for r in debt_rows[:8]],
        },
        'medicine_used': {
            'cost': usage['total_cost'],
            'doses': usage['total_doses'],
            'top': [{'name': r['name'], 'doses': r['doses'], 'cost': r['cost'],
                     'left': r['available_quantity'], 'low': r['low']}
                    for r in usage['linked'][:6]],
        },
        'entries': entries[:600],
        'entries_truncated': len(entries) > 600,
    }
