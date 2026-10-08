"""
Monthly payroll, counted on the server from the saved duty roster.

The HR page used to work pay out in the browser from a rota it rebuilt on
every page load (so a shift HR changed by hand was gone after a refresh and
was never paid), and it added figures nobody had entered: 2 600 000 of
"inpatient bonus" for every doctor, a detox bonus of six procedures, and a
payslip that always said August 2026 and "paid". Each computer could show a
different total for the same person.

Pay is now base salary plus the shifts saved in data/duty_schedule.json
(the roster on the Duty page) times the listed duty tariffs. A day the roster
only suggests is not saved and earns nothing until HR saves it.
"""

import calendar
import re

# Uzbek personal income tax and the employee pension contribution, as the HR
# page has always deducted them.
INCOME_TAX_RATE = 0.12
PENSION_RATE = 0.001

# Roster field holding the staff id -> field holding the name -> tariff key.
DUTY_POSTS = (
    ('doctor_night_id', 'doctor_night', 'doctor_night'),
    ('nurse_primary_id', 'nurse_primary', 'nurse_24h'),
    # The HR rota's second-floor nurse ("2-Q").
    ('nurse_secondary_id', 'nurse_secondary', 'nurse_24h'),
    ('sanitar_primary_id', 'sanitar_primary', 'sanitar_24h'),
    # sanitar_secondary is the reserve ("Zaxira") on the Duty page, not a
    # worked shift, so it is not paid.
)

MONTH_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def _norm_name(name):
    name = re.sub(r'^\s*dr\.?\s+', '', str(name or ''), flags=re.I)
    # G'aniyeva, Gʻaniyeva and G‘aniyeva are one person.
    name = re.sub(r"['`ʻʼ‘’]", '', name)
    return ' '.join(name.lower().split())


def same_person(staff_name, roster_name):
    a, b = _norm_name(staff_name), _norm_name(roster_name)
    if not a or not b:
        return True
    return a == b or a.startswith(b) or b.startswith(a)


def build_payroll(month, staff_rows, shifts, tariffs):
    """
    Payroll for one month ('YYYY-MM').

    staff_rows: dicts with id, full_name, role, salary_base, is_active.
    shifts: roster days (only saved days; the file holds nothing else).
    tariffs: {'doctor_night': n, 'nurse_24h': n, 'sanitar_24h': n}.

    A shift that names an id missing from the staff list, or a name that does
    not match the staff record behind its id, is reported rather than paid to
    whoever holds that id: the roster file and the staff table were filled
    separately and do not always agree.
    """
    year, mon = int(month[:4]), int(month[5:7])
    month_shifts = [s for s in shifts
                    if isinstance(s, dict) and str(s.get('date') or '').startswith(month + '-')]

    by_id = {str(r['id']): r for r in staff_rows}
    counts = {}
    unlinked = {}
    mismatched = {}
    for sh in month_shifts:
        for id_field, name_field, tariff_key in DUTY_POSTS:
            sid = str(sh.get(id_field) or '').strip()
            name = str(sh.get(name_field) or '').strip()
            if not sid and not name:
                continue
            row = by_id.get(sid) if sid else None
            if row is None:
                key = (sid, name, tariff_key)
                unlinked[key] = unlinked.get(key, 0) + 1
                continue
            if not same_person(row.get('full_name'), name):
                key = (sid, name)
                mismatched[key] = mismatched.get(key, 0) + 1
                continue
            per = counts.setdefault(sid, {})
            per[tariff_key] = per.get(tariff_key, 0) + 1

    lines = []
    totals = {'base': 0.0, 'duty': 0.0, 'gross': 0.0, 'deductions': 0.0, 'net': 0.0}
    for row in staff_rows:
        sid = str(row['id'])
        duty_counts = counts.get(sid, {})
        active = bool(int(row.get('is_active') if row.get('is_active') is not None else 1))
        if not active and not duty_counts:
            continue
        base = float(row.get('salary_base') or 0)
        duty_pay = sum(float(tariffs.get(k) or 0) * n for k, n in duty_counts.items())
        gross = base + duty_pay
        income_tax = round(gross * INCOME_TAX_RATE)
        pension = round(gross * PENSION_RATE)
        net = gross - income_tax - pension
        lines.append({
            'staff_id': sid,
            'full_name': row.get('full_name') or '',
            'role': row.get('role') or '',
            'is_active': active,
            'base_salary': base,
            'duty_counts': duty_counts,
            'duty_shifts': sum(duty_counts.values()),
            'duty_pay': duty_pay,
            'gross': gross,
            'income_tax': income_tax,
            'pension': pension,
            'deductions': income_tax + pension,
            'net': net,
        })
        totals['base'] += base
        totals['duty'] += duty_pay
        totals['gross'] += gross
        totals['deductions'] += income_tax + pension
        totals['net'] += net

    return {
        'month': month,
        'days_in_month': calendar.monthrange(year, mon)[1],
        'saved_days': len({s.get('date') for s in month_shifts}),
        'tariffs': dict(tariffs),
        'rates': {'income_tax': INCOME_TAX_RATE, 'pension': PENSION_RATE},
        'staff': lines,
        'totals': totals,
        'unlinked_shifts': [
            {'staff_id': k[0], 'name': k[1], 'tariff': k[2], 'shifts': n}
            for k, n in sorted(unlinked.items())
        ],
        'name_mismatches': [
            {'staff_id': k[0], 'staff_name': by_id[k[0]].get('full_name') or '',
             'roster_name': k[1], 'shifts': n}
            for k, n in sorted(mismatched.items())
        ],
    }
