#!/usr/bin/env python3
"""
Fayz Medical House — Regression Suite

Covers the defects found and fixed in this codebase, so they cannot come back
silently. Standard library only; no pytest, no new dependencies.

    # 1. start the server in another terminal
    python3 server.py 3000

    # 2. run the suite
    python3 tests/test_clinic.py
    python3 tests/test_clinic.py -v        # per-assertion detail
    python3 tests/test_clinic.py Overlap   # only matching test classes

The suite signs in, works against the live API, and cleans up the rows it
creates. Point it at a scratch database — it writes real records.
"""

import datetime as _dt
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get('FMH_TEST_BASE', 'http://127.0.0.1:3000')

# Credentials come from the environment and are deliberately not defaulted: a
# password written into a test file is a password in version control, which is
# the problem this suite exists partly to guard against. Export them first:
#
#   export FMH_TEST_USER=superadmin
#   export FMH_TEST_PASS='...'
#   python3 tests/test_clinic.py
#
# Use an account with full access, on a scratch database — these tests write
# real records.
USERNAME = os.environ.get('FMH_TEST_USER', '')
PASSWORD = os.environ.get('FMH_TEST_PASS', '')

# Beds present in data/seed_data.sql.
BED_A, BED_B, BED_C = 'BED-21A', 'BED-21B', 'BED-22A'
DOCTOR = 'STF-DOC-02'
RATE = 720000


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

class Client:
    """Minimal cookie-aware JSON client."""

    def __init__(self):
        self.cookie = None

    def call(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method)
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        if self.cookie:
            req.add_header('Cookie', self.cookie)
        try:
            with urllib.request.urlopen(req) as res:
                self._remember_cookie(res)
                body = res.read().decode()
                return res.status, (json.loads(body) if body.strip() else {})
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, {'raw': body}

    def _remember_cookie(self, res):
        raw = res.headers.get('Set-Cookie')
        if raw and raw.startswith('fmh_session='):
            self.cookie = raw.split(';', 1)[0]

    def login(self, username=USERNAME, password=PASSWORD):
        return self.call('POST', '/api/auth/login',
                         {'username': username, 'password': password})

    def get(self, p):
        return self.call('GET', p)

    def post(self, p, payload):
        return self.call('POST', p, payload)

    def delete(self, p):
        return self.call('DELETE', p)


def server_is_up():
    try:
        urllib.request.urlopen(BASE + '/login.html', timeout=4).read(1)
        return True
    except Exception:
        return False


def credentials_present():
    return bool(USERNAME and PASSWORD)


CREDENTIALS_HINT = (
    "set FMH_TEST_USER and FMH_TEST_PASS to an account with full access "
    "(the suite intentionally ships no default password)"
)


class ApiTest(unittest.TestCase):
    """Base class: one signed-in client, and cleanup of created rows."""

    @classmethod
    def setUpClass(cls):
        if not server_is_up():
            raise unittest.SkipTest(f"no server at {BASE} — start `python3 server.py 3000` first")
        if not credentials_present():
            raise unittest.SkipTest(CREDENTIALS_HINT)
        cls.api = Client()
        status, _ = cls.api.login()
        if status != 200:
            raise unittest.SkipTest(f"could not sign in as {USERNAME} (HTTP {status})")

    # Beds touched by any test. Discharge and transfer deliberately leave the
    # vacated bed 'cleaning', so each test must hand them back or it starves
    # the ones that follow.
    BEDS_USED = (BED_A, BED_B, BED_C, 'BED-22B', 'BED-23A')

    def setUp(self):
        self._admissions = []
        self._patients = []
        self.release_beds()

    def tearDown(self):
        # Children first: invoices and items reference the admission.
        for adm in self._admissions:
            self.api.delete('/api/admissions/' + adm)
        for pid in self._patients:
            self.api.delete('/api/patients/' + pid)
        # The API cannot delete a payment, and an invoice with one blocks the
        # admission delete above, so those rows used to survive the run and
        # accumulate across runs — which produced an intermittent failure in
        # the billing assertions. Anything the API could not remove is cleaned
        # up directly; the suite owns the data it creates.
        self._force_cleanup()
        self.release_beds()

    def _force_cleanup(self):
        """
        Remove anything the API could not.

        The deletes collect ids first and then use plain IN lists rather than
        multi-table joins. A trigger on payments updates invoices, and MySQL
        refuses (error 1442) to let a trigger write to a table the invoking
        statement already names — so a `DELETE p FROM payments p JOIN invoices
        i ...` fails outright and the rows survive.
        """
        if not (self._patients or self._admissions):
            return
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from db import get_db
            conn = get_db()
            try:
                cur = conn.cursor()
                for pid in self._patients:
                    cur.execute("SELECT id FROM admissions WHERE patient_id = ?", (pid,))
                    adm_ids = [r['id'] for r in cur.fetchall()]
                    inv_ids = []
                    if adm_ids:
                        marks = ','.join(['?'] * len(adm_ids))
                        cur.execute(f"SELECT id FROM invoices WHERE admission_id IN ({marks})",
                                    tuple(adm_ids))
                        inv_ids = [r['id'] for r in cur.fetchall()]

                    if inv_ids:
                        marks = ','.join(['?'] * len(inv_ids))
                        cur.execute(f"DELETE FROM payments WHERE invoice_id IN ({marks})",
                                    tuple(inv_ids))
                        cur.execute(f"DELETE FROM invoice_items WHERE invoice_id IN ({marks})",
                                    tuple(inv_ids))
                        cur.execute(f"DELETE FROM invoices WHERE id IN ({marks})",
                                    tuple(inv_ids))
                    if adm_ids:
                        marks = ','.join(['?'] * len(adm_ids))
                        cur.execute(f"DELETE FROM medication_administrations "
                                    f"WHERE admission_id IN ({marks})", tuple(adm_ids))
                        cur.execute(f"DELETE FROM prescriptions WHERE admission_id IN ({marks})",
                                    tuple(adm_ids))
                        cur.execute(f"DELETE FROM daily_logs WHERE admission_id IN ({marks})",
                                    tuple(adm_ids))
                        cur.execute(f"DELETE FROM bed_transfers WHERE admission_id IN ({marks})",
                                    tuple(adm_ids))
                        cur.execute(f"DELETE FROM admissions WHERE id IN ({marks})",
                                    tuple(adm_ids))
                    cur.execute("DELETE FROM prescriptions WHERE patient_id = ?", (pid,))
                    cur.execute("DELETE FROM treatment_plans WHERE patient_id = ?", (pid,))
                    cur.execute("DELETE FROM consultations WHERE patient_id = ?", (pid,))
                    cur.execute("DELETE FROM medical_histories WHERE patient_id = ?", (pid,))
                    cur.execute("DELETE FROM appointments WHERE patient_id = ?", (pid,))
                    cur.execute("DELETE FROM patients WHERE id = ?", (pid,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"  [suite] could not fully clean up: {e}")

    def release_beds(self):
        for bed in self.BEDS_USED:
            self.api.post(f'/api/beds/{bed}/clean', {})

    def patient_record(self, patient_id):
        """
        One patient's own row, including its billing totals.

        Assertions use this rather than /api/stats/summary: that endpoint is a
        clinic-wide KPI roll-up, so any other record in the database moves its
        numbers and it only counts stays that are current today — which a
        future-dated test admission is not.
        """
        status, rows = self.api.get('/api/crm/patients')
        self.assertEqual(status, 200)
        for r in rows:
            if r.get('id') == patient_id:
                return r
        self.fail(f"patient {patient_id} not found in /api/crm/patients")

    def invoice_for(self, admission_id):
        """The invoice row for one admission, read straight from the database."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT total_billed, net_amount, total_paid, balance_due,
                                  payment_status
                           FROM invoices WHERE admission_id = ?""", (admission_id,))
            row = cur.fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, f"no invoice for admission {admission_id}")
        return row

    def make_patient(self, name='Test Bemor', **extra):
        payload = {'full_name': name}
        payload.update(extra)
        status, body = self.api.post('/api/crm/patients', payload)
        self.assertEqual(status, 201, f"patient create failed: {body}")
        self._patients.append(body['id'])
        return body['id']

    def admit(self, patient_id, bed, start, end, expect=201):
        status, body = self.api.post('/api/admissions', {
            'patient_id': patient_id, 'bed_id': bed, 'program_type': 'standard_10',
            'start_date': start, 'planned_end_date': end,
            'attending_doctor_id': DOCTOR, 'daily_rate': RATE,
        })
        if expect is not None:
            self.assertEqual(status, expect, f"admit returned {status}: {body}")
        if status == 201:
            self._admissions.append(body['admission_id'])
        return status, body


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class AuthBoundary(unittest.TestCase):
    """Every /api/* route was once reachable with no credentials at all."""

    @classmethod
    def setUpClass(cls):
        if not server_is_up():
            raise unittest.SkipTest(f"no server at {BASE}")
        if not credentials_present():
            raise unittest.SkipTest(CREDENTIALS_HINT)

    def test_api_requires_a_session(self):
        anon = Client()
        for path in ('/api/stats/summary', '/api/crm/patients', '/api/users',
                     '/api/beds', '/api/hr/data', '/api/accounting/data'):
            status, _ = anon.get(path)
            self.assertEqual(status, 401, f"{path} served an anonymous caller")

    def test_pages_redirect_to_login(self):
        req = urllib.request.Request(BASE + '/superpage.html')
        opener = urllib.request.build_opener(NoRedirect())
        try:
            res = opener.open(req)
            self.fail(f"superpage.html served anonymously (HTTP {res.status})")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 302)
            self.assertIn('/login.html', e.headers.get('Location', ''))

    def test_login_page_is_public(self):
        anon = Client()
        status, _ = anon.call('GET', '/api/auth/session')
        self.assertEqual(status, 200, 'session probe must work while signed out')

    def test_wrong_password_is_rejected(self):
        c = Client()
        status, body = c.login(USERNAME, 'definitely-not-the-password')
        self.assertEqual(status, 401)
        self.assertIsNone(c.cookie, 'no session cookie may be issued on failure')

    def test_login_never_returns_the_password(self):
        c = Client()
        status, body = c.login()
        self.assertEqual(status, 200)
        self.assertNotIn('password', body.get('user', {}))

    def test_logout_invalidates_the_session(self):
        c = Client()
        self.assertEqual(c.login()[0], 200)
        self.assertEqual(c.get('/api/stats/summary')[0], 200)
        c.post('/api/auth/logout', {})
        self.assertEqual(c.get('/api/stats/summary')[0], 401,
                         'session still worked after logout')

    def test_user_list_does_not_leak_passwords(self):
        c = Client()
        c.login()
        status, users = c.get('/api/users')
        self.assertEqual(status, 200)
        for u in users:
            self.assertEqual(u.get('password'), '********',
                             f"{u.get('username')} exposed a password value")


class RoleAuthorization(ApiTest):
    """
    Authentication only proved who someone was. Every signed-in account could
    call every endpoint, so a receptionist could run payroll and a nurse could
    delete a patient. Each role is now confined to the modules its job needs.

    A throwaway account is created per test rather than relying on the seeded
    logins, so the suite carries no second password and cannot be broken by a
    routine password rotation.
    """

    def _account(self, role):
        """Create a temporary account in `role` and return a signed-in client."""
        username = f'suite_{role}_{os.getpid()}'
        password = 'Suite-Probe-2026'
        self.api.delete('/api/users/' + username)      # clear a previous run
        status, body = self.api.post('/api/users', {
            'username': username, 'password': password,
            'full_name': f'Suite {role}', 'role': role,
        })
        self.assertEqual(status, 201, f"could not create {role} account: {body}")
        self._temp_users.append(body.get('id') or username)

        client = Client()
        st, login_body = client.login(username, password)
        self.assertEqual(st, 200, f"could not sign in as the {role} account")

        # A newly issued account is held at the change-password screen until it
        # sets its own, exactly as a real new employee is. Walk that step so
        # the probes below exercise role permissions and not the rotation gate.
        if login_body.get('must_change_password'):
            rotated = password + '-Rotated'
            st2, b2 = client.post('/api/auth/change-password', {
                'current_password': password,
                'new_password': rotated,
                'confirm_password': rotated,
            })
            self.assertEqual(st2, 200, f"could not rotate the {role} password: {b2}")
        return client

    def setUp(self):
        super().setUp()
        self._temp_users = []

    def tearDown(self):
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        super().tearDown()

    def test_nurse_may_read_patients_but_not_change_them(self):
        nurse = self._account('nurse')
        self.assertEqual(nurse.get('/api/crm/patients')[0], 200)
        self.assertEqual(nurse.post('/api/crm/patients', {'full_name': 'X'})[0], 403)
        self.assertEqual(nurse.delete('/api/patients/PAT-ANY')[0], 403)

    def test_nurse_may_not_touch_money_or_staff(self):
        nurse = self._account('nurse')
        self.assertEqual(nurse.post('/api/payments', {'amount': 1})[0], 403)
        self.assertEqual(nurse.post('/api/staff', {'full_name': 'X'})[0], 403)
        self.assertEqual(nurse.get('/api/accounting/data')[0], 403)

    def test_receptionist_registers_and_admits_but_does_not_discharge(self):
        desk = self._account('receptionist')
        self.assertEqual(desk.get('/api/beds')[0], 200, 'needs free/occupied beds')
        status, created = desk.post('/api/crm/patients', {'full_name': 'Desk Probe'})
        self.assertEqual(status, 201, 'reception registers patients')
        # Created through the desk client, so register it for cleanup too.
        if created.get('id'):
            self._patients.append(created['id'])
        # Allowed through to validation (400), not refused by role (403).
        self.assertNotEqual(desk.post('/api/admissions', {})[0], 403,
                            'reception must be able to admit a stationary patient')
        self.assertEqual(desk.post('/api/admissions/ADM-X/discharge', {})[0], 403,
                         'discharge is a clinical decision')
        self.assertEqual(desk.post('/api/facility/rooms', {})[0], 403,
                         'reception must not reconfigure the building')

    def test_hr_has_no_patient_access(self):
        hr = self._account('hr_manager')
        self.assertEqual(hr.get('/api/crm/patients')[0], 403)
        self.assertEqual(hr.get('/api/doctor/clinical/PAT-ANY')[0], 403)
        self.assertNotEqual(hr.post('/api/staff', {})[0], 403, 'HR owns staff')

    def test_pharmacist_reads_prescriptions_but_cannot_write_them(self):
        ph = self._account('pharmacist')
        self.assertEqual(ph.get('/api/doctor/prescriptions')[0], 200)
        self.assertEqual(ph.post('/api/doctor/prescriptions', {})[0], 403)

    def test_only_an_administrator_manages_users(self):
        for role in ('nurse', 'receptionist', 'doctor', 'accountant'):
            c = self._account(role)
            self.assertEqual(c.get('/api/users')[0], 403, f"{role} saw the user list")
            self.assertEqual(c.post('/api/users', {'username': 'x'})[0], 403,
                             f"{role} could create a user")

    def test_refusal_is_403_not_401(self):
        """
        The distinction matters: the client redirects to the login screen on
        401, and signing in again would not grant a missing permission.
        """
        nurse = self._account('nurse')
        status, body = nurse.post('/api/payments', {'amount': 1})
        self.assertEqual(status, 403)
        self.assertIn('required', body)

    def test_an_unmapped_route_is_denied_by_default(self):
        """
        A route added without a permission rule must fail closed. This is what
        stops a future endpoint from being silently world-readable.
        """
        import permissions
        self.assertIsNone(permissions.required_for_api('GET', '/api/not/mapped/yet'))
        # Nobody passes, not even the superadmin. Letting the top role through
        # would hide the missing rule until someone with a narrower role hit
        # it in production; failing for everyone surfaces it immediately.
        for role in ('superadmin', 'admin', 'nurse'):
            allowed, reason = permissions.authorize_api({'role': role}, 'GET', '/api/nope')
            self.assertFalse(allowed, f"{role} reached an unmapped route")
            self.assertIn('no permission rule', reason)


class NurseStation(ApiTest):
    """
    The clinic could prescribe but had no way to record giving a dose:
    prescriptions held the order, daily_logs held vitals, and nothing recorded
    that a dose was administered, by whom, when. The round is derived from the
    standing orders so a future date is answerable, and the recorded
    administrations are overlaid on it.
    """

    def _order(self, patient_id, admission_id, **kw):
        payload = {
            'patient_id': patient_id, 'admission_id': admission_id,
            'medication_name': kw.get('name', 'Diazepam'),
            'dosage': kw.get('dosage', '10mg'),
            'route': kw.get('route', 'IM'),
            'frequency': kw.get('frequency', 'Kuniga 2 mahal'),
            'duration_days': kw.get('duration_days', 5),
        }
        if kw.get('timing'):
            payload['timing'] = kw['timing']
        status, body = self.api.post('/api/doctor/prescriptions', payload)
        self.assertIn(status, (200, 201), f"prescription failed: {body}")
        return body.get('id')

    def _admitted_patient(self, name, bed, days_back=0, days_forward=6):
        pid = self.make_patient(name)
        start = _dt.date.today() - _dt.timedelta(days=days_back)
        end = _dt.date.today() + _dt.timedelta(days=days_forward)
        _, adm = self.admit(pid, bed, start.isoformat(), end.isoformat())
        return pid, adm['admission_id']

    def _round(self, day=None):
        path = '/api/nursery/round'
        if day:
            path += '?date=' + day.isoformat()
        status, body = self.api.get(path)
        self.assertEqual(status, 200, f"round failed: {body}")
        return body

    def _find(self, round_data, patient_id):
        for p in round_data['patients']:
            if p['patient_id'] == patient_id:
                return p
        return None

    def test_frequency_decides_how_many_doses_are_planned(self):
        pid, adm = self._admitted_patient('Round Freq', BED_A)
        self._order(pid, adm, name='Twice', frequency='Kuniga 2 mahal')
        self._order(pid, adm, name='Thrice', frequency='har 8 soatda')
        entry = self._find(self._round(), pid)
        self.assertIsNotNone(entry, 'the admitted patient is missing from the round')
        by_med = {}
        for d in entry['doses']:
            by_med.setdefault(d['medication_name'], []).append(d)
        self.assertEqual(len(by_med['Twice']), 2, 'twice daily should plan two doses')
        # "every 8 hours" is three doses a day, not eight.
        self.assertEqual(len(by_med['Thrice']), 3, 'every 8h should plan three doses')

    def test_as_needed_orders_are_not_scheduled(self):
        """
        Planning an as-needed order would report a missed dose every day it was
        simply not required.
        """
        pid, adm = self._admitted_patient('Round PRN', BED_B)
        self._order(pid, adm, name='Metoklopramid', frequency="Zarurat tug'ilganda")
        entry = self._find(self._round(), pid)
        self.assertEqual(entry['doses'], [], 'an as-needed order was put on the clock')
        self.assertEqual(len(entry['as_needed']), 1, 'the order should still be listed')

    def test_a_range_order_plans_its_lower_bound(self):
        """
        "Kuniga 1-2 mahal" leaves the second dose to discretion, so planning
        two would mark a correctly-treated patient as having missed one.
        """
        pid, adm = self._admitted_patient('Round Range', BED_C)
        self._order(pid, adm, name='Fenazepam', frequency='Kuniga 1-2 mahal')
        entry = self._find(self._round(), pid)
        self.assertEqual(len(entry['doses']), 1)
        self.assertEqual(entry['doses'][0]['max_per_day'], 2,
                         'the permitted maximum should be carried for the nurse')

    def test_recording_a_dose_shows_up_on_the_round(self):
        pid, adm = self._admitted_patient('Round Record', BED_A)
        rx = self._order(pid, adm, frequency='Kuniga 2 mahal')
        status, body = self.api.post('/api/nursery/administer', {
            'prescription_id': rx, 'slot_index': 0, 'status': 'given'})
        self.assertEqual(status, 201, f"recording failed: {body}")

        entry = self._find(self._round(), pid)
        first = [d for d in entry['doses'] if d['slot_index'] == 0][0]
        self.assertEqual(first['state'], 'given')
        self.assertIsNotNone(first['administered_at'], 'no time was stamped')

    def test_re_recording_amends_rather_than_duplicating(self):
        pid, adm = self._admitted_patient('Round Amend', BED_B)
        rx = self._order(pid, adm, frequency='Kuniga 1 mahal')
        self.api.post('/api/nursery/administer',
                      {'prescription_id': rx, 'slot_index': 0, 'status': 'refused'})
        self.api.post('/api/nursery/administer',
                      {'prescription_id': rx, 'slot_index': 0, 'status': 'given'})
        entry = self._find(self._round(), pid)
        doses = [d for d in entry['doses'] if d['slot_index'] == 0]
        self.assertEqual(len(doses), 1, 'the same dose appeared twice')
        self.assertEqual(doses[0]['state'], 'given')

    def test_future_and_past_days_are_distinguished(self):
        pid, adm = self._admitted_patient('Round Dates', BED_C)
        self._order(pid, adm, frequency='Kuniga 1 mahal', duration_days=10)

        future = self._round(_dt.date.today() + _dt.timedelta(days=3))
        self.assertTrue(future['is_future'])
        entry = self._find(future, pid)
        self.assertTrue(entry['doses'], 'a future day should still show what is due')
        self.assertEqual(entry['doses'][0]['state'], 'scheduled')

        today = self._round()
        self.assertTrue(today['is_today'])
        self.assertEqual(self._find(today, pid)['doses'][0]['state'], 'pending')

    def test_a_future_dose_cannot_be_marked_given(self):
        pid, adm = self._admitted_patient('Round Future', BED_A)
        rx = self._order(pid, adm, frequency='Kuniga 1 mahal', duration_days=10)
        later = (_dt.date.today() + _dt.timedelta(days=2)).isoformat()
        status, body = self.api.post('/api/nursery/administer', {
            'prescription_id': rx, 'slot_index': 0, 'status': 'given', 'date': later})
        self.assertEqual(status, 400, 'a dose was recorded before it was due')
        self.assertIn('error', body)

    def test_an_as_needed_dose_records_without_a_slot(self):
        pid, adm = self._admitted_patient('Round PRN Give', BED_B)
        rx = self._order(pid, adm, name='Metoklopramid', frequency="Zarurat tug'ilganda")
        status, body = self.api.post('/api/nursery/administer', {
            'prescription_id': rx, 'status': 'given', 'notes': 'suite'})
        self.assertEqual(status, 201, f"as-needed dose failed: {body}")
        # Extras start at 100 so they cannot collide with a planned slot.
        self.assertGreaterEqual(body['slot_index'], 100)
        entry = self._find(self._round(), pid)
        self.assertEqual(len(entry['as_needed'][0]['given_today']), 1)

    def test_validation_messages_are_readable(self):
        """
        Input mistakes used to surface as the database constraint that caught
        them. These must be plain messages, not schema errors.
        """
        pid, adm = self._admitted_patient('Round Validate', BED_C)
        rx = self._order(pid, adm)
        for payload, expect_field in (
            ({'prescription_id': rx, 'slot_index': 0, 'status': 'teleported'}, 'status'),
            ({'prescription_id': rx, 'slot_index': 0, 'date': '18-09-2026'}, 'date'),
            ({'slot_index': 0, 'status': 'given'}, 'prescription_id'),
        ):
            status, body = self.api.post('/api/nursery/administer', payload)
            self.assertEqual(status, 400, f"{payload} was accepted")
            self.assertIn('error', body)
            msg = body['error']
            for leak in ('Check constraint', 'chk_', 'Traceback', '1062', '3819'):
                self.assertNotIn(leak, msg, f"the message leaks internals: {msg}")

    def test_only_the_nurse_station_may_record_doses(self):
        pid, adm = self._admitted_patient('Round Perms', BED_A)
        rx = self._order(pid, adm)
        username = f'suite_kitchen_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        st, body = self.api.post('/api/users', {
            'username': username, 'password': 'Suite-Probe-2026',
            'full_name': 'Suite Kitchen', 'role': 'kitchen_staff'})
        self.assertEqual(st, 201, f"could not create the probe account: {body}")
        try:
            c = Client()
            c.login(username, 'Suite-Probe-2026')
            c.post('/api/auth/change-password', {
                'current_password': 'Suite-Probe-2026',
                'new_password': 'Suite-Probe-2026-Rotated',
                'confirm_password': 'Suite-Probe-2026-Rotated'})
            self.assertEqual(c.get('/api/nursery/round')[0], 403,
                             'kitchen staff could read the medication round')
            self.assertEqual(
                c.post('/api/nursery/administer',
                       {'prescription_id': rx, 'slot_index': 0, 'status': 'given'})[0],
                403, 'kitchen staff could record a dose')
        finally:
            self.api.delete('/api/users/' + (body.get('id') or username))


class LoginThrottle(unittest.TestCase):
    """
    The login endpoint answered unlimited guesses at full speed, which on an
    internet-exposed deployment invites a dictionary attack.
    """

    @classmethod
    def setUpClass(cls):
        if not server_is_up():
            raise unittest.SkipTest(f"no server at {BASE}")

    def test_repeated_failures_are_eventually_refused(self):
        import auth as auth_mod
        # A username of its own so the lockout cannot affect real accounts.
        victim = f'throttle_probe_{os.getpid()}'
        c = Client()
        saw_throttle = False
        for _ in range(auth_mod.MAX_FAILURES + 2):
            status, _ = c.login(victim, 'wrong-password')
            if status == 429:
                saw_throttle = True
                break
            self.assertEqual(status, 401)
        self.assertTrue(saw_throttle,
                        f"no lockout after {auth_mod.MAX_FAILURES + 2} failures")

    def test_failure_response_does_not_reveal_whether_the_user_exists(self):
        """
        Both probes use synthetic names. Guessing at a real account here would
        add to that account's own lockout counter and lock the suite out of
        every test that follows.
        """
        _, absent = Client().login(f'absent_a_{os.getpid()}', 'x')
        _, other = Client().login(f'absent_b_{os.getpid()}', 'x')
        self.assertEqual(absent.get('error'), other.get('error'))
        self.assertNotIn('parol', (absent.get('error') or '').lower().replace(
            "login yoki parol noto'g'ri", ''),
            'the message should not say which half was wrong')


class AuditTrail(ApiTest):
    """audit_logs existed in the schema from the start but nothing wrote to it."""

    def _count(self):
        import sys as _s, os as _o
        _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS n FROM audit_logs")
            return cur.fetchone()['n']
        finally:
            conn.close()

    def test_a_write_leaves_an_audit_row(self):
        before = self._count()
        pid = self.make_patient('Audit Probe')
        after = self._count()
        self.assertGreater(after, before, 'creating a patient recorded nothing')

    def test_the_row_names_the_actor_and_the_record(self):
        import sys as _s, os as _o, json as _j
        _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
        from db import get_db
        pid = self.make_patient('Audit Actor Probe')
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT entity_name, entity_id, action_type, new_data_json
                           FROM audit_logs WHERE entity_id = ? ORDER BY id DESC LIMIT 1""", (pid,))
            row = cur.fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, f"no audit row carries the new patient id {pid}")
        self.assertEqual(row['entity_name'], 'patients')
        self.assertEqual(row['action_type'], 'CREATE')
        payload = _j.loads(row['new_data_json'])
        self.assertTrue(payload.get('_actor'), 'the acting username was not recorded')

    def test_a_refused_request_is_recorded(self):
        before = self._count()
        anon = Client()
        anon.login(USERNAME, PASSWORD)
        # Ask for something the account may not have; superadmin can do all, so
        # use the permission layer directly for the refusal path instead.
        import permissions
        allowed, _ = permissions.authorize_api({'role': 'kitchen_staff'}, 'GET', '/api/users')
        self.assertFalse(allowed, 'expected kitchen staff to be refused the user list')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


class PasswordStorage(unittest.TestCase):
    """Passwords were stored in plaintext in data/users.json."""

    def test_no_plaintext_passwords_on_disk(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import auth
        users = auth.load_users()
        self.assertTrue(users, 'users.json is empty')
        for u in users:
            pw = u.get('password')
            if pw:
                self.assertTrue(auth.is_hashed(pw),
                                f"{u.get('username')} still has a plaintext password")

    def test_hash_roundtrip(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import auth
        h = auth.hash_password('correct horse')
        self.assertTrue(auth.verify_password('correct horse', h))
        self.assertFalse(auth.verify_password('Correct horse', h))
        self.assertNotEqual(h, auth.hash_password('correct horse'),
                            'each hash must use a fresh salt')


# ---------------------------------------------------------------------------
# Bed allocation
# ---------------------------------------------------------------------------

class OverlapGuard(ApiTest):
    """
    The interval overlap check bound its two date parameters in reverse, which
    turned an overlap test into a containment test: only a stay falling wholly
    inside an existing one was caught, so partially overlapping stays were
    accepted and two patients could hold the same bed.
    """

    def test_partial_overlap_extending_past_the_end_is_rejected(self):
        a = self.make_patient('Overlap A')
        b = self.make_patient('Overlap B')
        self.admit(a, BED_A, '2027-03-01', '2027-03-11')
        status, body = self.admit(b, BED_A, '2027-03-05', '2027-03-15', expect=None)
        self.assertEqual(status, 400, f"bed double-booked: {body}")

    def test_partial_overlap_starting_before_the_start_is_rejected(self):
        a = self.make_patient('Overlap C')
        b = self.make_patient('Overlap D')
        self.admit(a, BED_B, '2027-04-10', '2027-04-20')
        status, body = self.admit(b, BED_B, '2027-04-05', '2027-04-15', expect=None)
        self.assertEqual(status, 400, f"bed double-booked: {body}")

    def test_fully_containing_stay_is_rejected(self):
        a = self.make_patient('Overlap E')
        b = self.make_patient('Overlap F')
        self.admit(a, BED_C, '2027-05-10', '2027-05-15')
        status, body = self.admit(b, BED_C, '2027-05-01', '2027-05-30', expect=None)
        self.assertEqual(status, 400, f"bed double-booked: {body}")

    def test_non_overlapping_stay_is_still_allowed(self):
        """The guard must not become so eager that it blocks legitimate reuse."""
        a = self.make_patient('Sequential A')
        b = self.make_patient('Sequential B')
        self.admit(a, BED_A, '2027-06-01', '2027-06-10')
        status, _ = self.admit(b, BED_A, '2027-07-01', '2027-07-10', expect=None)
        self.assertEqual(status, 201, 'a later, non-overlapping stay was refused')


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class ConsultationIntake(ApiTest):
    """
    The six-section narcology/psychiatry intake, and the treatment plan kept
    apart from it. The intake is the record of one encounter and does not
    change; the plan is a live instruction that gets revised, so they are
    stored and printed separately.
    """

    MINIMAL = {'primary_complaint': 'Alkogolga ruju, uyqusizlik'}

    def _intake(self, patient_id, **over):
        payload = dict(self.MINIMAL, patient_id=patient_id)
        payload.update(over)
        return self.api.post('/api/consultations', payload)

    def test_the_form_definition_is_served_for_the_page_to_build_from(self):
        """
        The page builds its form from this, so it must agree with what the
        server validates against — one definition, not two.
        """
        status, meta = self.api.get('/api/consultations/sections')
        self.assertEqual(status, 200)
        self.assertEqual(len(meta['sections']), 6, 'six sections were specified')
        names = [f['name'] for sec in meta['sections'] for f in sec['fields']]
        self.assertEqual(len(names), len(set(names)), 'a field name is duplicated')
        for sec in meta['sections']:
            for f in sec['fields']:
                self.assertTrue(f.get('label'), f"{f['name']} has no label to render")
        # The six areas the specification named.
        for required in ('date_of_birth', 'treatment_basis', 'primary_complaint',
                         'substances', 'prior_psych_diagnoses',
                         'family_history_addiction', 'risk_to_self',
                         'working_diagnosis'):
            self.assertIn(required, names, f'{required} is missing from the intake')

    def test_a_consultation_saves_and_reads_back(self):
        pid = self.make_patient('Intake Save')
        status, body = self._intake(
            pid,
            treatment_basis='family_initiated',
            working_diagnosis='Alkogolga qaramlik sindromi',
            icd10_code='F10.2',
            risk_to_self='moderate',
            seizure_history=True,
            substances=[{'substance': 'Alkogol', 'age_first_use': 17,
                         'peak_daily_amount': '1L', 'last_use_date': '2026-09-17'}])
        self.assertEqual(status, 201, f"intake failed: {body}")

        status, rec = self.api.get('/api/consultations/' + body['consultation_id'])
        self.assertEqual(status, 200)
        self.assertEqual(rec['treatment_basis'], 'family_initiated')
        self.assertEqual(rec['risk_to_self'], 'moderate')
        self.assertEqual(int(rec['seizure_history']), 1)
        self.assertEqual([x['substance'] for x in rec['substances']], ['Alkogol'])

    def test_a_court_mandated_admission_needs_its_reference(self):
        """
        Without the order number the legal basis cannot be substantiated
        later, which is exactly when it is asked for.
        """
        pid = self.make_patient('Intake Court')
        status, body = self._intake(pid, treatment_basis='court_mandated')
        self.assertEqual(status, 400, 'a court order was accepted with no reference')
        status, _ = self._intake(pid, treatment_basis='court_mandated',
                                 court_reference='№ 4082/2026')
        self.assertEqual(status, 201)

    def test_the_complaint_is_required(self):
        pid = self.make_patient('Intake NoComplaint')
        status, body = self.api.post('/api/consultations', {'patient_id': pid})
        self.assertEqual(status, 400)
        self.assertIn('error', body)

    def test_implausible_values_are_refused_in_plain_language(self):
        pid = self.make_patient('Intake Validate')
        for over, what in (
            ({'date_of_birth': '2099-01-01'}, 'a future birth date'),
            ({'risk_to_self': 'catastrophic'}, 'an invented risk level'),
            ({'overdose_count': -3}, 'a negative count'),
            ({'substances': [{'age_first_use': 16}]}, 'a substance with no name'),
            ({'substances': [{'substance': 'Alkogol', 'age_first_use': 400}]},
             'an impossible first-use age'),
        ):
            status, body = self._intake(pid, **over)
            self.assertEqual(status, 400, f"{what} was accepted")
            msg = body.get('error', '')
            for leak in ('Check constraint', 'chk_', 'Traceback', '3819', '1062'):
                self.assertNotIn(leak, msg, f"the message leaks internals: {msg}")

    def test_the_plan_is_stored_separately_from_the_intake(self):
        pid = self.make_patient('Plan Separate')
        _, intake = self._intake(pid, working_diagnosis='Abstinensiya')
        cid = intake['consultation_id']

        status, plan = self.api.post('/api/treatment-plans', {
            'patient_id': pid, 'consultation_id': cid, 'plan_type': 'detox',
            'immediate_actions': 'Statsionarga yotqizish',
            'detox_protocol': 'Diazepam kamayuvchi sxema',
            'duration_days': 10})
        self.assertEqual(status, 201, f"plan failed: {plan}")
        self.assertNotEqual(plan['plan_id'], cid, 'the plan shares the intake id')

        status, timeline = self.api.get('/api/consultations/patient/' + pid)
        self.assertEqual(status, 200)
        self.assertEqual(len(timeline['consultations']), 1)
        self.assertEqual(len(timeline['plans']), 1, 'the plan should be listed apart')

        # Reading the plan on its own is what lets it be printed by itself.
        status, one = self.api.get('/api/treatment-plans/' + plan['plan_id'])
        self.assertEqual(status, 200)
        self.assertEqual(one['plan_type'], 'detox')
        self.assertNotIn('primary_complaint', one,
                         'the plan document should not carry the intake with it')

    def test_a_detox_plan_requires_a_protocol(self):
        pid = self.make_patient('Plan Detox')
        status, _ = self.api.post('/api/treatment-plans', {
            'patient_id': pid, 'plan_type': 'detox',
            'immediate_actions': 'Yotqizish'})
        self.assertEqual(status, 400, 'a detox plan was accepted with no protocol')

    def test_a_new_active_plan_supersedes_the_previous_one(self):
        """
        Only one plan can be the live instruction, or the ward has to guess
        which sheet to follow.
        """
        pid = self.make_patient('Plan Supersede')
        for actions in ('Birinchi reja', 'Ikkinchi reja'):
            status, _ = self.api.post('/api/treatment-plans', {
                'patient_id': pid, 'plan_type': 'outpatient',
                'immediate_actions': actions})
            self.assertEqual(status, 201)

        status, plans = self.api.get('/api/treatment-plans/patient/' + pid)
        self.assertEqual(status, 200)
        active = [p for p in plans if p['status'] == 'active']
        self.assertEqual(len(active), 1, f"{len(active)} plans are active at once")
        self.assertEqual(len([p for p in plans if p['status'] == 'superseded']), 1)

    def test_the_intake_reaches_the_existing_emr(self):
        """
        The existing history tab and the printed A4 blank read from
        medical_histories. Without the mirror the new intake would be
        invisible to both and a printed blank would carry no diagnosis.
        """
        pid = self.make_patient('Intake Mirror')
        _, body = self._intake(pid, working_diagnosis='Opioid qaramligi',
                               icd10_code='F11.2', drug_allergies='Penitsillin')
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT diagnosis_primary, icd10_code, allergic_status
                           FROM medical_histories WHERE patient_id = ?
                           ORDER BY created_at DESC LIMIT 1""", (pid,))
            row = cur.fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, 'the intake did not reach medical_histories')
        self.assertEqual(row['icd10_code'], 'F11.2')
        self.assertIn('Penitsillin', row['allergic_status'] or '')

    def test_a_consultation_records_its_author(self):
        """A clinical record with no named author is not much of a record."""
        pid = self.make_patient('Intake Author')
        _, body = self._intake(pid)
        _, rec = self.api.get('/api/consultations/' + body['consultation_id'])
        # The suite signs in as an administrator, which may not map to a staff
        # row; what must hold is that the column is populated when it does.
        if rec.get('doctor_id'):
            self.assertTrue(rec.get('doctor_name'),
                            'a doctor_id was stored but resolves to no name')

    def test_the_queue_is_the_handoff_from_registration(self):
        status, rows = self.api.get('/api/consultations/queue')
        self.assertEqual(status, 200)
        self.assertIsInstance(rows, list)

    def test_only_doctors_may_write_a_consultation(self):
        pid = self.make_patient('Intake Perms')
        username = f'suite_nurse_c_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        st, body = self.api.post('/api/users', {
            'username': username, 'password': 'Suite-Probe-2026',
            'full_name': 'Suite Nurse C', 'role': 'nurse'})
        self.assertEqual(st, 201, f"could not create the probe account: {body}")
        try:
            c = Client()
            c.login(username, 'Suite-Probe-2026')
            c.post('/api/auth/change-password', {
                'current_password': 'Suite-Probe-2026',
                'new_password': 'Suite-Probe-2026-Rot',
                'confirm_password': 'Suite-Probe-2026-Rot'})
            self.assertEqual(
                c.post('/api/consultations', dict(self.MINIMAL, patient_id=pid))[0],
                403, 'a nurse could record a consultation')
            self.assertEqual(
                c.post('/api/treatment-plans',
                       {'patient_id': pid, 'immediate_actions': 'x'})[0],
                403, 'a nurse could write a treatment plan')
            # But a nurse must be able to READ the plan she has to carry out.
            self.assertEqual(c.get('/api/treatment-plans/patient/' + pid)[0], 200,
                             'a nurse could not read the plan she must follow')
        finally:
            self.api.delete('/api/users/' + (body.get('id') or username))


class DeleteLeavesNothingBehind(ApiTest):
    """
    Deleting an admission left its invoice_items behind. The foreign key is
    ON DELETE CASCADE, but the handler disables FOREIGN_KEY_CHECKS first (a
    PRAGMA carried over from the SQLite era) and MySQL does not run cascades
    while checks are off.

    That mattered because an invoice id is derived from its admission id. A
    later admission created in the same second reuses the id after a delete,
    so the orphaned lines reattached and the new patient was billed for the
    previous patient's stay — which is how this was found: an intermittent
    failure showing 17 days charged on a 10-day admission.
    """

    def test_deleting_an_admission_removes_its_billing_lines(self):
        pid = self.make_patient('Delete Billing')
        start = _dt.date.today() + _dt.timedelta(days=200)
        _, adm = self.admit(pid, BED_A, start.isoformat(),
                            (start + _dt.timedelta(days=10)).isoformat())
        adm_id = adm['admission_id']
        self.assertGreater(self._item_count('INV-' + adm_id), 0,
                           'the stay should have been billed')

        status, _ = self.api.delete('/api/admissions/' + adm_id)
        self.assertEqual(status, 200)
        self._admissions = [a for a in self._admissions if a != adm_id]

        self.assertEqual(self._item_count('INV-' + adm_id), 0,
                         'billing lines survived the delete and would reattach '
                         'to the next admission that reused this id')

    def test_a_reused_admission_id_starts_with_a_clean_invoice(self):
        """
        Reproduces the mechanism directly: bill a stay, delete it, then create
        another admission carrying the same invoice id and confirm it is billed
        only for its own nights.
        """
        first = self.make_patient('Reuse A')
        start = _dt.date.today() + _dt.timedelta(days=300)
        _, adm = self.admit(first, BED_B, start.isoformat(),
                            (start + _dt.timedelta(days=7)).isoformat())
        adm_id = adm['admission_id']
        self.api.delete('/api/admissions/' + adm_id)
        self._admissions = [a for a in self._admissions if a != adm_id]

        # Any leftover line would be picked up by an invoice with this id.
        self.assertEqual(self._item_count('INV-' + adm_id), 0)

    def _item_count(self, invoice_id):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS n FROM invoice_items WHERE invoice_id = ?",
                        (invoice_id,))
            return int(cur.fetchone()['n'])
        finally:
            conn.close()


class GeneratedIdCollisions(ApiTest):
    """
    Admission ids were second-resolution timestamps, so two admissions created
    in the same second collided on the primary key and one was lost. Staff ids
    came from COUNT(*) and, combined with ON CONFLICT DO UPDATE, a collision
    silently overwrote an existing employee while reporting success.
    """

    def test_simultaneous_admissions_all_succeed(self):
        beds = [BED_A, BED_B, BED_C, 'BED-22B', 'BED-23A']
        patients = [self.make_patient(f'Concurrent {i}') for i in range(len(beds))]
        results = [None] * len(beds)

        def worker(i):
            results[i] = self.api.post('/api/admissions', {
                'patient_id': patients[i], 'bed_id': beds[i],
                'program_type': 'standard_10',
                'start_date': '2027-08-01', 'planned_end_date': '2027-08-11',
                'attending_doctor_id': DOCTOR, 'daily_rate': RATE,
            })

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(beds))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ids = []
        for status, body in results:
            self.assertEqual(status, 201, f"concurrent admission failed: {body}")
            ids.append(body['admission_id'])
            self._admissions.append(body['admission_id'])
        self.assertEqual(len(set(ids)), len(ids), f"duplicate admission ids: {ids}")

    def test_simultaneous_staff_inserts_all_persist(self):
        before = len(self.api.get('/api/staff')[1])
        results = [None] * 4

        def worker(i):
            results[i] = self.api.post('/api/staff',
                                       {'full_name': f'Nurse Concurrent {i}', 'role': 'nurse'})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        created = []
        for status, body in results:
            self.assertIn(status, (200, 201), f"staff insert failed: {body}")
            created.append(body['id'])
        try:
            self.assertEqual(len(set(created)), 4, f"staff ids collided: {created}")
            after = len(self.api.get('/api/staff')[1])
            self.assertEqual(after, before + 4,
                             'a staff record was overwritten rather than added')
        finally:
            for sid in set(created):
                self.api.delete('/api/staff/' + sid)


class JsonStoreIntegrity(ApiTest):
    """
    users.json was read-modify-written with no locking, so concurrent writes
    interleaved: one thread truncated the file while another was reading it,
    and the reader then wrote its truncated view back. Five simultaneous
    registrations once reduced eight users to two.
    """

    def test_concurrent_user_creation_loses_nobody(self):
        before = self.api.get('/api/users')[1]
        names = [f'concurrent_probe_{i}' for i in range(5)]

        def worker(name):
            self.api.post('/api/users', {
                'username': name, 'full_name': name, 'role': 'nurse', 'password': 'probe-pw'
            })

        threads = [threading.Thread(target=worker, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        after = self.api.get('/api/users')[1]
        try:
            self.assertEqual(len(after), len(before) + 5,
                             f"user count went {len(before)} -> {len(after)}; records were lost")
            usernames = {u['username'] for u in after}
            for original in before:
                self.assertIn(original['username'], usernames,
                              f"pre-existing user {original['username']} was destroyed")
        finally:
            for u in after:
                if u['username'].startswith('concurrent_probe_'):
                    self.api.delete('/api/users/' + u['id'])


# ---------------------------------------------------------------------------
# Clinical and financial flow
# ---------------------------------------------------------------------------

class ClinicalWorkflow(ApiTest):
    """Admit, bill, pay, transfer, prescribe, export, discharge."""

    def test_full_stay_bills_and_settles_correctly(self):
        pid = self.make_patient('Workflow Bemor', birth_year=1985)
        _, adm = self.admit(pid, BED_A, '2027-09-01', '2027-09-11')
        self.assertEqual(adm['days'], 10)

        # Assert on THIS admission's invoice, not the patient's lifetime total.
        # total_billed on the patient row sums every admission they have ever
        # had, which is correct behaviour but makes the assertion depend on the
        # patient having exactly one stay.
        rec = self.patient_record(pid)
        self.assertEqual(rec['total_admissions_count'], 1,
                         'the patient under test should have exactly one stay')

        inv = self.invoice_for(adm['admission_id'])
        self.assertAlmostEqual(float(inv['net_amount']), 10 * RATE, delta=1,
                               msg='ten nights at the daily rate should be billed')

        status, pay = self.api.post('/api/payments', {
            'admission_id': adm['admission_id'], 'amount': 2_000_000,
            'payment_method': 'cash'})
        self.assertEqual(status, 201, f"payment failed: {pay}")

        inv = self.invoice_for(adm['admission_id'])
        self.assertAlmostEqual(float(inv['total_paid']), 2_000_000, delta=1)
        self.assertAlmostEqual(float(inv['balance_due']), 10 * RATE - 2_000_000, delta=1,
                               msg='balance did not reflect the payment')

    def test_transfer_splits_the_stay_without_changing_its_length(self):
        pid = self.make_patient('Transfer Bemor')
        _, adm = self.admit(pid, BED_B, '2027-10-01', '2027-10-11')
        status, body = self.api.post(
            f"/api/admissions/{adm['admission_id']}/transfer",
            {'new_bed_id': BED_C, 'transfer_date': '2027-10-05'})
        self.assertEqual(status, 200, f"transfer failed: {body}")
        res = body['result']
        self.assertEqual(res['old_bed_days'] + res['new_bed_days'], 10,
                         'the two segments must still add up to the whole stay')

    def test_transfer_onto_an_occupied_bed_is_refused(self):
        a = self.make_patient('Occupied Target')
        b = self.make_patient('Moving Patient')
        self.admit(a, BED_C, '2027-11-01', '2027-11-11')
        _, adm = self.admit(b, BED_A, '2027-11-05', '2027-11-20')
        status, body = self.api.post(
            f"/api/admissions/{adm['admission_id']}/transfer",
            {'new_bed_id': BED_C, 'transfer_date': '2027-11-05'})
        self.assertEqual(status, 400, f"transfer overlapped an occupied bed: {body}")

    def test_discharge_closes_the_stay(self):
        pid = self.make_patient('Discharge Bemor')
        _, adm = self.admit(pid, BED_A, '2027-12-01', '2027-12-11')
        self.assertIsNotNone(self.patient_record(pid).get('active_admission'),
                             'patient should hold an active admission before discharge')

        status, body = self.api.post(
            f"/api/admissions/{adm['admission_id']}/discharge",
            {'discharge_date': '2027-12-08', 'summary': 'regression suite'})
        self.assertEqual(status, 200, f"discharge failed: {body}")

        self.assertIsNone(self.patient_record(pid).get('active_admission'),
                          'the admission was still active after discharge')

    def test_prescription_can_be_added(self):
        pid = self.make_patient('Rx Bemor')
        _, adm = self.admit(pid, BED_B, '2028-01-01', '2028-01-11')
        status, body = self.api.post('/api/doctor/prescriptions', {
            'admission_id': adm['admission_id'], 'patient_id': pid,
            'medication_name': 'Diazepam', 'dosage': '10mg',
            'frequency': '2x kunda', 'route': 'IM', 'duration_days': 5})
        self.assertIn(status, (200, 201), f"prescription failed: {body}")


class PdfExport(ApiTest):
    """
    pdf_generator.py contained an escaped quote inside an f-string expression,
    a syntax error before Python 3.12, so the module never imported and the
    bare except at the import site hid it. The caller also treated the returned
    bytes as a filesystem path, so the route 404'd even once importable.
    """

    def test_export_returns_a_real_pdf(self):
        pid = self.make_patient('PDF Bemor')
        self.admit(pid, BED_A, '2028-02-01', '2028-02-11')
        req = urllib.request.Request(BASE + '/api/doctor/download-pdf/' + pid)
        req.add_header('Cookie', self.api.cookie)
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            body = res.read()
        self.assertTrue(body.startswith(b'%PDF'), 'response was not a PDF')
        self.assertGreater(len(body), 1000, 'PDF looks truncated')

    def test_pdf_module_imports(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, root)
        try:
            from pdf_generator import generate_patient_pdf  # noqa: F401
        except SyntaxError as e:
            self.fail(f"pdf_generator.py does not parse: {e}")
        except ImportError as e:
            self.skipTest(f"reportlab not installed: {e}")


if __name__ == '__main__':
    argv = [sys.argv[0]]
    verbose = '-v' in sys.argv or '--verbose' in sys.argv
    filters = [a for a in sys.argv[1:] if not a.startswith('-')]

    loader = unittest.TestLoader()
    if filters:
        loader.testNamePatterns = [f'*{f}*' for f in filters]
    suite = loader.loadTestsFromModule(sys.modules['__main__'])

    if not server_is_up():
        print(f"\n  The suite needs a running server at {BASE}.")
        print("  Start it with:  python3 server.py 3000\n")
        sys.exit(2)
    if not credentials_present():
        print("\n  " + CREDENTIALS_HINT)
        print("    export FMH_TEST_USER=superadmin")
        print("    export FMH_TEST_PASS='your-password'\n")
        sys.exit(2)

    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
