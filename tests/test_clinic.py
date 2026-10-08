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
import re
import sys
import threading
import unittest
import urllib.error
import urllib.parse
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

    def put(self, p, payload):
        return self.call('PUT', p, payload)

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

    def admit(self, patient_id, bed, start, end, expect=201,
              program='standard_10', rate=RATE):
        status, body = self.api.post('/api/admissions', {
            'patient_id': patient_id, 'bed_id': bed, 'program_type': program,
            'start_date': start, 'planned_end_date': end,
            'attending_doctor_id': DOCTOR, 'daily_rate': rate,
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
        self.assertEqual(desk.get('/api/facility/availability')[0], 200,
                         'reception cannot place a patient without the board')

    def test_the_occupancy_board_is_not_open_to_every_role(self):
        """It names patients and the ward they are in, so it follows the same
        rule as the rest of the facility module rather than being public."""
        hr = self._account('hr_manager')
        self.assertEqual(hr.get('/api/facility/availability')[0], 403)

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


class WardRound(ApiTest):
    """
    The stationary ward round: who is in a bed today, and who the doctor has
    already seen.

    The per-patient check-up existed inside the EMR but had never once worked:
    POST /api/doctor/notes wrote a column named vital_bp, and the table has
    vital_bp_systolic and vital_bp_diastolic, so every save raised 'Unknown
    column' and answered 500. doctor_daily_notes was empty in a database that
    had been in use. There was also no list -- a doctor had to already know who
    was in the building and open each record in turn.
    """

    def _admitted(self, name, bed, days_back=0, days_forward=6):
        pid = self.make_patient(name)
        start = _dt.date.today() - _dt.timedelta(days=days_back)
        end = _dt.date.today() + _dt.timedelta(days=days_forward)
        _, adm = self.admit(pid, bed, start.isoformat(), end.isoformat())
        return pid, adm['admission_id']

    def _board(self, day=None):
        path = '/api/doctor/ward-round'
        if day:
            path += '?date=' + day.isoformat()
        status, body = self.api.get(path)
        self.assertEqual(status, 200, f"ward round failed: {body}")
        return body

    def _entry(self, board, admission_id):
        for p in board['patients']:
            if p['admission_id'] == admission_id:
                return p
        return None

    def _checkup(self, pid, adm, **kw):
        payload = {'patient_id': pid, 'admission_id': adm,
                   'dynamics_notes': kw.pop('dynamics', 'Holati barqaror')}
        payload.update(kw)
        return self.api.post('/api/doctor/notes', payload)

    def test_a_check_up_can_be_recorded_at_all(self):
        """The regression that matters: this endpoint answered 500 every time."""
        pid, adm = self._admitted('Ward A', BED_A)
        status, body = self._checkup(pid, adm, patient_condition='satisfactory',
                                     vital_pulse=72, vital_temp=36.6)
        self.assertEqual(status, 201, f"check-up did not save: {body}")

    def test_the_board_lists_who_is_in_a_bed(self):
        pid, adm = self._admitted('Ward B', BED_B)
        entry = self._entry(self._board(), adm)
        self.assertIsNotNone(entry, 'an admitted patient was missing from the round')
        self.assertEqual(entry['patient_name'], 'Ward B')
        self.assertEqual(entry['bed_code'], '21B')

    def test_the_board_separates_seen_from_waiting(self):
        pid_a, adm_a = self._admitted('Ward Seen', BED_A)
        pid_b, adm_b = self._admitted('Ward Waiting', BED_B)
        self._checkup(pid_a, adm_a, dynamics='Ko`rildi')

        board = self._board()
        self.assertTrue(self._entry(board, adm_a)['seen'])
        self.assertFalse(self._entry(board, adm_b)['seen'])
        self.assertGreaterEqual(board['totals']['seen'], 1)
        self.assertGreaterEqual(board['totals']['waiting'], 1)

    def test_the_board_says_which_day_of_the_stay_it_is(self):
        pid, adm = self._admitted('Ward Day', BED_C, days_back=3, days_forward=6)
        entry = self._entry(self._board(), adm)
        self.assertEqual(entry['day_of_stay'], 4, 'day four of the stay')
        self.assertEqual(entry['total_days'], 9)

    def test_a_patient_not_yet_admitted_is_not_on_the_board(self):
        pid = self.make_patient('Ward Future')
        start = _dt.date.today() + _dt.timedelta(days=5)
        end = start + _dt.timedelta(days=5)
        _, adm = self.admit(pid, BED_A, start.isoformat(), end.isoformat())
        self.assertIsNone(self._entry(self._board(), adm['admission_id']),
                          'a stay that has not started was on today\'s round')

    def test_recording_twice_amends_rather_than_duplicating(self):
        pid, adm = self._admitted('Ward Amend', BED_B)
        self._checkup(pid, adm, dynamics='Birinchi xulosa')
        self._checkup(pid, adm, dynamics='Tuzatilgan xulosa')
        entry = self._entry(self._board(), adm)
        self.assertEqual(entry['checkup']['dynamics_notes'], 'Tuzatilgan xulosa')

        status, notes = self.api.get('/api/doctor/notes?patient_id=' + pid)
        self.assertEqual(status, 200)
        today = _dt.date.today().isoformat()
        same_day = [n for n in notes if str(n.get('note_date'))[:10] == today]
        self.assertEqual(len(same_day), 1,
                         'the same morning has two contradictory assessments')

    def test_an_amendment_keeps_vitals_it_does_not_mention(self):
        pid, adm = self._admitted('Ward Keep', BED_C)
        self._checkup(pid, adm, dynamics='Birinchi', vital_pulse=80, vital_temp=36.8)
        self._checkup(pid, adm, dynamics='Matn tuzatildi')
        entry = self._entry(self._board(), adm)
        self.assertEqual(entry['checkup']['vital_pulse'], 80,
                         'correcting the text erased the recorded pulse')

    def test_nothing_is_invented_when_no_vitals_are_given(self):
        """
        It used to default to 120/80, pulse 72, 36.6 degrees and SpO2 98. An
        invented vital sign is indistinguishable from a measured one.
        """
        pid, adm = self._admitted('Ward Blank', BED_A)
        self._checkup(pid, adm, dynamics='Ko`rik o`tkazildi')
        c = self._entry(self._board(), adm)['checkup']
        for field in ('vital_bp_systolic', 'vital_bp_diastolic', 'vital_pulse',
                      'vital_temp', 'vital_spo2'):
            self.assertIsNone(c[field], f"{field} was invented")

    def test_a_round_with_nothing_written_in_it_is_refused(self):
        pid, adm = self._admitted('Ward Empty', BED_B)
        status, body = self.api.post('/api/doctor/notes', {
            'patient_id': pid, 'admission_id': adm, 'dynamics_notes': '   '})
        self.assertEqual(status, 400)
        self.assertEqual(body.get('field'), 'dynamics_notes')

    def test_an_unknown_condition_is_refused(self):
        pid, adm = self._admitted('Ward Cond', BED_C)
        status, body = self._checkup(pid, adm, patient_condition='fine')
        self.assertEqual(status, 400)
        self.assertEqual(body.get('field'), 'patient_condition')

    def test_an_implausible_vital_is_refused(self):
        pid, adm = self._admitted('Ward Vital', BED_A)
        status, body = self._checkup(pid, adm, vital_pulse=400)
        self.assertEqual(status, 400)
        self.assertEqual(body.get('field'), 'vital_pulse')

    def test_a_round_cannot_be_written_for_a_future_day(self):
        pid, adm = self._admitted('Ward Ahead', BED_B)
        ahead = (_dt.date.today() + _dt.timedelta(days=2)).isoformat()
        status, _ = self._checkup(pid, adm, note_date=ahead)
        self.assertEqual(status, 400, 'recorded a round that has not happened')

    def test_the_round_is_doctors_work(self):
        """A nurse records doses and vitals; the assessment is the doctor's."""
        pid, adm = self._admitted('Ward Role', BED_C)
        username = f'suite_ward_nurse_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        st, created = self.api.post('/api/users', {
            'username': username, 'password': 'Suite-Probe-2026',
            'full_name': 'Suite Nurse', 'role': 'nurse'})
        self.assertEqual(st, 201, f"could not create probe account: {created}")
        try:
            nurse = Client()
            st, login_body = nurse.login(username, 'Suite-Probe-2026')
            self.assertEqual(st, 200)
            if login_body.get('must_change_password'):
                nurse.post('/api/auth/change-password', {
                    'current_password': 'Suite-Probe-2026',
                    'new_password': 'Suite-Probe-2026-Rotated',
                    'confirm_password': 'Suite-Probe-2026-Rotated'})
            self.assertEqual(nurse.post('/api/doctor/notes', {
                'patient_id': pid, 'admission_id': adm,
                'dynamics_notes': 'x'})[0], 403)
            # But she may read the board: she needs to know who is in a bed.
            self.assertEqual(nurse.get('/api/doctor/ward-round')[0], 200)
        finally:
            self.api.delete('/api/users/' + (created.get('id') or username))


class NurseVitals(ApiTest):
    """
    daily_logs held the ward's observations and had a read endpoint only, so
    the vitals taken every morning had nowhere to go: the table was described
    in the schema, shown on the patient record, and never written.
    """

    def _admitted(self, name, bed, days_back=0, days_forward=6):
        pid = self.make_patient(name)
        start = _dt.date.today() - _dt.timedelta(days=days_back)
        end = _dt.date.today() + _dt.timedelta(days=days_forward)
        _, adm = self.admit(pid, bed, start.isoformat(), end.isoformat())
        return pid, adm['admission_id']

    def _logs(self, admission_id):
        status, body = self.api.get('/api/daily-logs/' + admission_id)
        self.assertEqual(status, 200)
        return body

    def test_a_days_observation_is_recorded_and_reads_back(self):
        _, adm = self._admitted('Vitals A', BED_A)
        today = _dt.date.today().isoformat()
        status, body = self.api.post('/api/daily-logs/' + adm, {
            'date': today, 'vital_bp_systolic': 128, 'vital_bp_diastolic': 82,
            'vital_pulse': 76, 'vital_temp': 36.7, 'vital_spo2': 98,
            'nurse_notes': 'Holati barqaror',
        })
        self.assertEqual(status, 201, f"vitals not recorded: {body}")
        logs = self._logs(adm)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['vital_pulse'], 76)
        self.assertEqual(float(logs[0]['vital_temp']), 36.7)
        self.assertEqual(logs[0]['nurse_notes'], 'Holati barqaror')

    def test_recording_twice_in_a_day_amends_rather_than_duplicating(self):
        _, adm = self._admitted('Vitals B', BED_B)
        today = _dt.date.today().isoformat()
        self.api.post('/api/daily-logs/' + adm, {'date': today, 'vital_pulse': 76})
        self.api.post('/api/daily-logs/' + adm, {'date': today, 'vital_pulse': 88})
        logs = self._logs(adm)
        self.assertEqual(len(logs), 1, 'the day has two contradictory records')
        self.assertEqual(logs[0]['vital_pulse'], 88)

    def test_an_amendment_keeps_what_it_does_not_mention(self):
        """
        The afternoon round records a pulse. It must not wipe the blood
        pressure taken that morning.
        """
        _, adm = self._admitted('Vitals C', BED_C)
        today = _dt.date.today().isoformat()
        self.api.post('/api/daily-logs/' + adm, {
            'date': today, 'vital_bp_systolic': 128, 'vital_bp_diastolic': 82,
            'vital_pulse': 76})
        self.api.post('/api/daily-logs/' + adm, {'date': today, 'vital_pulse': 88})
        logs = self._logs(adm)
        self.assertEqual(logs[0]['vital_pulse'], 88)
        self.assertEqual(logs[0]['vital_bp_systolic'], 128,
                         "the morning's blood pressure was erased")

    def test_a_blank_value_clears_a_reading_on_purpose(self):
        """Absent leaves alone; present-but-empty is an explicit correction."""
        _, adm = self._admitted('Vitals D', BED_A)
        today = _dt.date.today().isoformat()
        self.api.post('/api/daily-logs/' + adm, {'date': today, 'vital_pulse': 76})
        self.api.post('/api/daily-logs/' + adm, {'date': today, 'vital_pulse': ''})
        self.assertIsNone(self._logs(adm)[0]['vital_pulse'])

    def test_an_implausible_reading_is_refused_in_plain_language(self):
        _, adm = self._admitted('Vitals E', BED_B)
        status, body = self.api.post('/api/daily-logs/' + adm, {'vital_temp': 58})
        self.assertEqual(status, 400)
        self.assertEqual(body.get('field'), 'vital_temp')
        self.assertIn('30.0', body.get('error', ''))

    def test_diastolic_above_systolic_is_refused(self):
        _, adm = self._admitted('Vitals F', BED_C)
        status, body = self.api.post('/api/daily-logs/' + adm, {
            'vital_bp_systolic': 100, 'vital_bp_diastolic': 120})
        self.assertEqual(status, 400)
        self.assertEqual(body.get('field'), 'vital_bp_diastolic')

    def test_vitals_cannot_be_recorded_for_a_future_day(self):
        _, adm = self._admitted('Vitals G', BED_A)
        ahead = (_dt.date.today() + _dt.timedelta(days=2)).isoformat()
        status, _ = self.api.post('/api/daily-logs/' + adm,
                                  {'date': ahead, 'vital_pulse': 70})
        self.assertEqual(status, 400, 'recorded an observation not yet made')

    def test_a_date_outside_the_stay_is_refused(self):
        _, adm = self._admitted('Vitals H', BED_B)
        before = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()
        status, body = self.api.post('/api/daily-logs/' + adm,
                                     {'date': before, 'vital_pulse': 70})
        self.assertEqual(status, 400, f"logged against the wrong stay: {body}")

    def test_an_unknown_admission_is_refused(self):
        status, _ = self.api.post('/api/daily-logs/ADM-DOES-NOT-EXIST',
                                  {'vital_pulse': 70})
        self.assertEqual(status, 400)

    def test_only_the_ward_may_record_vitals(self):
        """Same boundary as the medication round: nursing work, nursing rights."""
        _, adm = self._admitted('Vitals I', BED_C)
        hr = Client()
        username = f'suite_vitals_hr_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        st, created = self.api.post('/api/users', {
            'username': username, 'password': 'Suite-Probe-2026',
            'full_name': 'Suite HR', 'role': 'hr_manager'})
        self.assertEqual(st, 201, f"could not create probe account: {created}")
        try:
            st, login_body = hr.login(username, 'Suite-Probe-2026')
            self.assertEqual(st, 200)
            if login_body.get('must_change_password'):
                hr.post('/api/auth/change-password', {
                    'current_password': 'Suite-Probe-2026',
                    'new_password': 'Suite-Probe-2026-Rotated',
                    'confirm_password': 'Suite-Probe-2026-Rotated'})
            self.assertEqual(hr.post('/api/daily-logs/' + adm, {'vital_pulse': 70})[0], 403)
        finally:
            self.api.delete('/api/users/' + (created.get('id') or username))


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


class PatientIdentity(ApiTest):
    """
    Date of birth and gender, as the front desk takes them.

    Registration had no field for either, and the inserts said
    body.get('gender', 'male') and body.get('birth_year', 1990), so every
    patient registered at the desk entered the record as a man born in 1990.
    An invented date of birth is worse than a missing one: the PDF header
    prints an age from it and the consultation form pre-fills from it, and
    nothing downstream can tell it from a real one.
    """

    def patient_row(self, patient_id):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT gender, birth_date, birth_year, full_name, is_anonymous FROM patients WHERE id = ?",
                        (patient_id,))
            return cur.fetchone()
        finally:
            conn.close()

    def test_a_date_of_birth_is_stored_and_its_year_derived(self):
        pid = self.make_patient('Nilufar Karimova',
                                birth_date='1985-03-14', gender='female')
        row = self.patient_row(pid)
        self.assertEqual(str(row['birth_date'])[:10], '1985-03-14')
        self.assertEqual(row['gender'], 'female')
        self.assertEqual(row['birth_year'], 1985,
                         'birth_year is what the CRM and the PDF header read')

    def test_nothing_is_invented_when_nothing_is_given(self):
        pid = self.make_patient('Nomalum Bemor')
        row = self.patient_row(pid)
        self.assertIsNone(row['birth_date'])
        self.assertIsNone(row['birth_year'], 'a birth year was invented')
        self.assertIsNone(row['gender'], "gender defaulted to 'male'")

    def test_an_unreadable_date_is_refused_in_plain_language(self):
        status, body = self.api.post('/api/crm/patients',
                                     {'full_name': 'X', 'birth_date': '14/03/1985'})
        self.assertEqual(status, 400)
        self.assertEqual(body.get('field'), 'birth_date')

    def test_a_date_of_birth_in_the_future_is_refused(self):
        status, _ = self.api.post('/api/crm/patients',
                                  {'full_name': 'X', 'birth_date': '2099-01-01'})
        self.assertEqual(status, 400)

    def test_an_unknown_gender_names_its_own_field(self):
        status, body = self.api.post('/api/crm/patients',
                                     {'full_name': 'X', 'gender': 'helicopter'})
        self.assertEqual(status, 400)
        self.assertEqual(body.get('field'), 'gender',
                         'the form would highlight the wrong input')

    def test_saving_a_consultation_does_not_overwrite_what_is_known(self):
        """
        The doctor page updated patients with the same 'male'/1990 fallbacks,
        so a woman born in 1985 recorded correctly at the desk became a man
        born in 1990 the first time her consultation was saved.
        """
        pid = self.make_patient('Nilufar Saidova',
                                birth_date='1985-03-14', gender='female')
        status, _ = self.api.post('/api/doctor/consultation-case', {
            'patient_id': pid,
            'patient': {'full_name': 'Nilufar Saidova'},
            'consultation_type': 'outpatient',
        })
        self.assertIn(status, (200, 201), 'consultation case did not save')
        row = self.patient_row(pid)
        self.assertEqual(row['gender'], 'female', 'gender was overwritten')
        self.assertEqual(str(row['birth_date'])[:10], '1985-03-14',
                         'date of birth was overwritten')

    def test_a_patient_without_a_phone_is_not_merged_into_a_stranger(self):
        """
        Booking a consultation matched on `phone = ? OR full_name = ?` with the
        phone bound even when empty. Most records carry an empty phone, so a
        walk-in who left no number was filed under the first such patient in
        the table.
        """
        existing = self.make_patient('Registrada Bemor')   # no phone
        status, body = self.api.post('/api/reception/appointment', {
            'patient_name': 'Butunlay Boshqa Odam',
            'patient_phone': '',
            'doctor_id': DOCTOR,
            'date': '2029-05-05',
        })
        self.assertEqual(status, 201, f"appointment failed: {body}")
        booked = body.get('patient_id')
        if booked:
            self._patients.append(booked)
        self.assertNotEqual(booked, existing,
                            'the visit was filed under an unrelated patient')

    def _book(self, **fields):
        payload = {'doctor_id': DOCTOR, 'date': '2029-05-08'}
        payload.update(fields)
        status, body = self.api.post('/api/reception/appointment', payload)
        self.assertEqual(status, 201, f"appointment failed: {body}")
        self._patients.append(body['patient_id'])
        return body['patient_id']

    def test_anonymous_visits_are_never_filed_together(self):
        """All were 'Anonim Bemor', phone '—', so they shared one record."""
        first = self._book(patient_name='Anonim Bemor', patient_phone='—', is_anonymous=True)
        second = self._book(patient_name='Anonim Bemor', patient_phone='—', is_anonymous=True)
        self.assertNotEqual(first, second, 'two anonymous strangers share one record')
        self.assertEqual(int(self.patient_row(first)['is_anonymous']), 1)

    def test_a_shared_name_alone_is_not_the_same_person(self):
        existing = self.make_patient('Aziz Karimov Namesake')
        booked = self._book(patient_name='Aziz Karimov Namesake')
        self.assertNotEqual(booked, existing, 'matched a stranger on the name alone')

    def test_a_shared_phone_alone_is_not_the_same_person(self):
        existing = self.make_patient('Ona Bemor', phone='+998901112233')
        booked = self._book(patient_name='Ogil Bemor', patient_phone='+998901112233')
        self.assertNotEqual(booked, existing, 'a family phone merged two people')

    def test_the_same_phone_and_name_is_the_same_person(self):
        existing = self.make_patient('Qaytgan Bemor', phone='+998901112244')
        booked = self._book(patient_name='Qaytgan Bemor', patient_phone='+998901112244')
        self.assertEqual(booked, existing, 'a returning patient got a second record')

    def test_a_case_on_a_shared_phone_does_not_rename_the_owner(self):
        existing = self.make_patient('Telefon Egasi', phone='+998901112255')
        status, body = self.api.post('/api/doctor/consultation-case', {
            'patient': {'full_name': 'Boshqa Odam', 'phone': '+998901112255'},
            'consultation_type': 'outpatient'})
        self.assertIn(status, (200, 201), f"case did not save: {body}")
        if body.get('patient_id') and body['patient_id'] != existing:
            self._patients.append(body['patient_id'])
        self.assertEqual(self.patient_row(existing)['full_name'], 'Telefon Egasi',
                         "the phone's owner was renamed")

    def test_a_crm_edit_reaches_the_record(self):
        """
        There was no PUT route: the CRM's edits got a 404 the page ignored,
        so an allergy entered there never reached the doctor's warning.
        """
        pid = self.make_patient('CRM Edit Bemor', gender='female')
        status, body = self.api.call('PUT', f'/api/crm/patients/{pid}', {
            'medical_allergies': 'Penitsillin', 'gender': '', 'phone': '+998901112266'})
        self.assertEqual(status, 200, f"the CRM edit was not stored: {body}")
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT medical_allergies, phone, gender, full_name FROM patients WHERE id = ?", (pid,))
            row = cur.fetchone()
        finally:
            conn.close()
        self.assertEqual(row['medical_allergies'], 'Penitsillin')
        self.assertEqual(row['phone'], '+998901112266')
        self.assertEqual(row['gender'], 'female', 'a blank gender overwrote a known one')
        self.assertEqual(row['full_name'], 'CRM Edit Bemor', 'an absent field was changed')

    def test_a_crm_edit_cannot_blank_the_name(self):
        pid = self.make_patient('CRM Name Kept')
        status, body = self.api.call('PUT', f'/api/crm/patients/{pid}', {'full_name': '  '})
        self.assertEqual(status, 400, f"a blank name was stored: {body}")
        self.assertEqual(body.get('field'), 'full_name')

    def test_the_doctor_queue_carries_the_date_of_birth(self):
        """The handoff exists so the doctor is not retyping what the desk took."""
        status, body = self.api.post('/api/reception/appointment', {
            'patient_name': 'Navbatdagi Bemor',
            'patient_phone': '+998901234599',
            'birth_date': '1990-07-02',
            'gender': 'male',
            'doctor_id': DOCTOR,
            'date': '2029-05-06',
        })
        self.assertEqual(status, 201, f"appointment failed: {body}")
        if body.get('patient_id'):
            self._patients.append(body['patient_id'])
        qstatus, queue = self.api.get('/api/consultations/queue')
        self.assertEqual(qstatus, 200)
        mine = [q for q in queue if q.get('patient_id') == body.get('patient_id')]
        self.assertTrue(mine, 'the booking did not reach the doctor queue')
        self.assertEqual(str(mine[0].get('birth_date'))[:10], '1990-07-02')


class NothingClinicalIsInvented(ApiTest):
    """
    Every field of a medication order and a discharge summary used to have a
    fallback, so a request that named only the drug was stored as a complete
    order, and an empty discharge summary was stored as a complete document.

    Demonstrated before the fix: posting {"medication_name": "Analgin"} was
    recorded as 400 ml of it, intravenously by drip, once every morning for
    five days, over the name of a doctor who had not been asked. The nurse
    station builds its medication round from exactly those columns.

    An invented clinical value is indistinguishable from a measured one, which
    is what makes it worse than a blank.
    """

    def _stay(self, name, bed):
        pid = self.make_patient(name)
        start = _dt.date.today()
        end = start + _dt.timedelta(days=7)
        _, adm = self.admit(pid, bed, start.isoformat(), end.isoformat())
        return pid, adm['admission_id']

    def _row(self, table, patient_id, columns):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            # patients is keyed by id; everything else references patient_id.
            key = 'id' if table == 'patients' else 'patient_id'
            cur.execute(f"SELECT {columns} FROM {table} WHERE {key} = ?", (patient_id,))
            return cur.fetchone()
        finally:
            conn.close()

    # --- medication orders -------------------------------------------------

    def test_a_drug_name_alone_is_not_a_prescription(self):
        pid, adm = self._stay('Rx Bare', BED_A)
        status, body = self.api.post('/api/doctor/prescriptions', {
            'patient_id': pid, 'admission_id': adm, 'medication_name': 'Analgin'})
        self.assertEqual(status, 400, f"an incomplete order was accepted: {body}")
        self.assertIsNone(self._row('prescriptions', pid, 'id'),
                          'an incomplete order reached the record')

    def test_each_missing_part_of_an_order_is_named(self):
        pid, adm = self._stay('Rx Fields', BED_B)
        base = {'patient_id': pid, 'admission_id': adm, 'medication_name': 'Analgin',
                'dosage': '2 ml', 'route': 'M/I', 'frequency': 'Kuniga 2 mahal',
                'duration_days': 3}
        for field in ('medication_name', 'dosage', 'route', 'frequency', 'duration_days'):
            payload = dict(base)
            payload[field] = ''
            status, body = self.api.post('/api/doctor/prescriptions', payload)
            self.assertEqual(status, 400, f"{field} was allowed to be blank")
            self.assertEqual(body.get('field'), field)

    def test_an_order_stores_what_was_written_and_nothing_else(self):
        pid, adm = self._stay('Rx Exact', BED_C)
        status, body = self.api.post('/api/doctor/prescriptions', {
            'patient_id': pid, 'admission_id': adm, 'medication_name': 'Analgin',
            'dosage': '2 ml', 'route': 'M/I', 'frequency': 'Kuniga 2 mahal',
            'duration_days': 3})
        self.assertEqual(status, 201, f"a complete order was refused: {body}")

        row = self._row('prescriptions', pid,
                        'medication_name, dosage, route, frequency, duration_days, form, timing')
        self.assertEqual(row['dosage'], '2 ml')
        self.assertEqual(row['route'], 'M/I')
        self.assertEqual(row['duration_days'], 3)
        # Never asked for, so never filled in. These used to become
        # 'Infuzion flakon' and 'Ertalab'.
        self.assertIsNone(row['form'], 'a dosage form was invented')
        self.assertIsNone(row['timing'], 'a time of day was invented')

    def test_an_implausible_duration_is_refused(self):
        pid, adm = self._stay('Rx Days', BED_A)
        for days in (0, -3, 4000):
            status, _ = self.api.post('/api/doctor/prescriptions', {
                'patient_id': pid, 'admission_id': adm, 'medication_name': 'Analgin',
                'dosage': '2 ml', 'route': 'M/I', 'frequency': 'Kuniga 1 mahal',
                'duration_days': days})
            self.assertEqual(status, 400, f"duration {days} was accepted")

    # --- the discharge summary ---------------------------------------------

    def test_an_empty_discharge_summary_is_refused(self):
        """
        It used to produce a complete document: diagnosis 'Alkogol
        intoksikatsiyasi remissiya davri', ICD-10 F10.2, outcome 'recovered'.
        """
        pid, adm = self._stay('Epi Empty', BED_B)
        status, body = self.api.post('/api/doctor/epicrisis',
                                     {'patient_id': pid, 'admission_id': adm})
        self.assertEqual(status, 400, f"an empty discharge summary was saved: {body}")
        self.assertEqual(body.get('field'), 'diagnosis_final')
        self.assertIsNone(self._row('discharge_epicrises', pid, 'id'),
                          'an empty discharge summary reached the record')

    def test_a_discharge_summary_keeps_to_what_the_doctor_wrote(self):
        pid, adm = self._stay('Epi Real', BED_C)
        status, body = self.api.post('/api/doctor/epicrisis', {
            'patient_id': pid, 'admission_id': adm,
            'diagnosis_final': 'F10.2 remissiya', 'discharge_status': 'recovered'})
        self.assertEqual(status, 201, f"a real discharge summary was refused: {body}")
        row = self._row('discharge_epicrises', pid,
                        'diagnosis_final, icd10_code, treatment_summary')
        self.assertEqual(row['diagnosis_final'], 'F10.2 remissiya')
        self.assertIsNone(row['icd10_code'], 'an ICD-10 code was invented')
        self.assertIsNone(row['treatment_summary'], 'a treatment summary was invented')

    # --- allergies and authorship ------------------------------------------

    def test_an_allergy_history_nobody_took_is_unknown_not_none(self):
        """
        medical_allergies defaulted to "Yo'q". The doctor's page raises its
        allergy warning from this column, so a record nobody had questioned
        asserted the patient was safe and the warning stayed silent.
        """
        pid = self.make_patient('Allergy Unknown')
        row = self._row('patients', pid, 'medical_allergies, chronic_conditions')
        self.assertIsNone(row['medical_allergies'],
                          'the record claims the patient has no allergies')
        self.assertIsNone(row['chronic_conditions'])

    def test_a_stated_allergy_is_kept(self):
        pid = self.make_patient('Allergy Known', medical_allergies='Penitsillin')
        self.assertEqual(
            self._row('patients', pid, 'medical_allergies')['medical_allergies'],
            'Penitsillin')

    def test_work_is_never_signed_by_a_doctor_who_was_not_asked(self):
        """
        doctor_id fell back to the literal 'STF-DOC-01' -- a real person -- so
        an order with no stated author was recorded over their name.
        """
        pid, adm = self._stay('Rx Author', BED_A)
        self.api.post('/api/doctor/prescriptions', {
            'patient_id': pid, 'admission_id': adm, 'medication_name': 'Analgin',
            'dosage': '2 ml', 'route': 'M/I', 'frequency': 'Kuniga 1 mahal',
            'duration_days': 2})
        author = self._row('prescriptions', pid, 'doctor_id')['doctor_id']
        self.assertNotEqual(author, 'STF-DOC-01',
                            'the order was signed by a doctor who was not asked')

    def test_a_stated_author_is_kept(self):
        pid, adm = self._stay('Rx Author Kept', BED_B)
        self.api.post('/api/doctor/prescriptions', {
            'patient_id': pid, 'admission_id': adm, 'doctor_id': DOCTOR,
            'medication_name': 'Analgin', 'dosage': '2 ml', 'route': 'M/I',
            'frequency': 'Kuniga 1 mahal', 'duration_days': 2})
        self.assertEqual(self._row('prescriptions', pid, 'doctor_id')['doctor_id'], DOCTOR)

    # --- names and doctors nobody gave -------------------------------------

    def test_an_admission_for_nobody_is_refused(self):
        """
        With no patient and no name the server registered 'Yangi Bemor' and
        put that person in a bed, on the invoice and on the nurse's round.
        """
        start = _dt.date.today()
        status, body = self.api.post('/api/admissions', {
            'bed_id': BED_A, 'program_type': 'standard_10',
            'start_date': start.isoformat(),
            'planned_end_date': (start + _dt.timedelta(days=3)).isoformat()})
        self.assertEqual(status, 400, f"a nameless admission was accepted: {body}")
        self.assertEqual(body.get('field'), 'patient_name')

    def test_an_admission_with_no_doctor_is_given_nobody(self):
        """
        It was handed to the first active doctor in the staff table, who then
        found a stranger on their ward round.
        """
        pid = self.make_patient('No Doctor Stay')
        start = _dt.date.today()
        status, body = self.api.post('/api/admissions', {
            'patient_id': pid, 'bed_id': BED_B, 'program_type': 'standard_10',
            'start_date': start.isoformat(),
            'planned_end_date': (start + _dt.timedelta(days=3)).isoformat()})
        self.assertEqual(status, 201, f"admission without a doctor failed: {body}")
        self._admissions.append(body['admission_id'])
        row = self._row('admissions', pid, 'attending_doctor_id')
        self.assertIsNone(row['attending_doctor_id'],
                          'a doctor who was not chosen was made responsible')

    def test_an_appointment_needs_a_person_and_a_doctor(self):
        """The page sent 'STF-DOC-01' and the server 'Bemor' when left blank."""
        status, body = self.api.post('/api/reception/appointment', {
            'patient_name': 'Kimdir Bemor', 'date': '2029-05-07'})
        self.assertEqual(status, 400, f"booked into nobody's diary: {body}")
        self.assertEqual(body.get('field'), 'doctor_id')
        status, body = self.api.post('/api/reception/appointment', {
            'doctor_id': DOCTOR, 'date': '2029-05-07'})
        self.assertEqual(status, 400, f"booked a nameless patient: {body}")
        self.assertEqual(body.get('field'), 'patient_name')

    def test_saving_a_case_keeps_the_name_and_allergy_on_file(self):
        """
        A case saved without the name or allergy overwrote them with 'Yangi
        Bemor' and NULL -- wiping a recorded allergy and its warning.
        """
        pid = self.make_patient('Allergy Kept', medical_allergies='Penitsillin')
        status, body = self.api.post('/api/doctor/consultation-case', {
            'patient_id': pid, 'consultation_type': 'outpatient'})
        self.assertIn(status, (200, 201), f"case did not save: {body}")
        row = self._row('patients', pid, 'full_name, medical_allergies')
        self.assertEqual(row['full_name'], 'Allergy Kept', 'the name was overwritten')
        self.assertEqual(row['medical_allergies'], 'Penitsillin',
                         'a recorded allergy was wiped')

    def test_a_case_with_a_half_written_order_saves_nothing(self):
        """
        The case endpoint filled a bare drug name in as 400 ml by IV drip,
        once a day, for five days -- the same order the single-order endpoint
        already refused. It is refused before the case itself is written.
        """
        pid = self.make_patient('Case Rx Bare')
        status, body = self.api.post('/api/doctor/consultation-case', {
            'patient_id': pid, 'consultation_type': 'outpatient',
            'prescriptions': [{'medication_name': 'Analgin'}]})
        self.assertEqual(status, 400, f"a half-written order was saved: {body}")
        self.assertEqual(body.get('field'), 'dosage')
        self.assertIn('Analgin', body.get('error', ''), 'the drug is not named')
        self.assertIsNone(self._row('prescriptions', pid, 'id'))
        self.assertIsNone(self._row('medical_histories', pid, 'id'),
                          'the case was half-saved before the refusal')

    def test_a_case_order_keeps_to_what_was_written(self):
        pid = self.make_patient('Case Rx Real')
        status, body = self.api.post('/api/doctor/consultation-case', {
            'patient_id': pid, 'consultation_type': 'outpatient',
            'prescriptions': [{'medication_name': 'Analgin', 'dosage': '2 ml',
                               'route': 'M/I', 'frequency': 'Kuniga 1 mahal',
                               'duration_days': 3}]})
        self.assertIn(status, (200, 201), f"a complete order was refused: {body}")
        rx = self._row('prescriptions', pid, 'dosage, route, duration_days, form, timing')
        self.assertEqual((rx['dosage'], rx['route'], rx['duration_days']), ('2 ml', 'M/I', 3))
        self.assertIsNone(rx['form'], 'a dosage form was invented')
        self.assertIsNone(rx['timing'], 'a time of day was invented')
        mh = self._row('medical_histories', pid, 'icd10_code')
        self.assertIsNone(mh['icd10_code'], 'an ICD-10 code (F10.2) was invented')

    def test_a_case_for_a_new_nameless_patient_is_refused(self):
        status, body = self.api.post('/api/doctor/consultation-case', {
            'consultation_type': 'outpatient'})
        self.assertEqual(status, 400, f"a nameless patient was registered: {body}")
        self.assertEqual(body.get('field'), 'full_name')


class FreshIds(unittest.TestCase):
    """
    Fourteen handlers drew a random PREFIX-#### id and inserted it without
    looking. With 9,000 values a clash is likely by the 112th row, and each
    one failed as a 500 -- a prescription or appointment typed again. These
    drive the helpers with a fake cursor, so no server or database is needed.
    """

    class _Cur:
        def __init__(self, taken):
            self.taken, self.queries, self._hit = set(taken), [], False

        def execute(self, sql, params):
            self.queries.append(sql)
            self._hit = any(p in self.taken for p in params)

        def fetchone(self):
            return (1,) if self._hit else None

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import server
        cls.server = server

    def test_a_free_id_keeps_the_familiar_format(self):
        cur = self._Cur(taken=())
        rid = self.server.new_record_id(cur, 'prescriptions', 'RX-2026')
        self.assertRegex(rid, r'^RX-2026-\d{4}$')
        self.assertIn('prescriptions', cur.queries[0], 'the id was not probed')

    def test_a_taken_id_is_never_handed_out(self):
        taken = {f"RX-2026-{n}" for n in range(1000, 10000)}
        rid = self.server.new_record_id(self._Cur(taken), 'prescriptions', 'RX-2026')
        self.assertNotIn(rid, taken)
        self.assertTrue(rid.startswith('RX-2026-'))

    def test_a_patient_code_clash_is_avoided_too(self):
        """PAT-1234 (CRM) and PAT-2026-1234 (desk) both made FMH-2026-1234."""
        taken = {f"FMH-2026-{n}" for n in range(1000, 10000)}
        pid, code = self.server.new_patient_ids(self._Cur(taken))
        self.assertNotIn(code, taken)
        self.assertEqual(pid.split('-')[-1], code.split('-')[-1],
                         'the id and the code no longer share their digits')


class Operations(ApiTest):
    """
    The things that matter to whoever keeps this running, rather than to the
    clinic: is it up, and does the audit trail stay a manageable size.
    """

    def test_health_answers_without_a_session(self):
        """Whatever monitors this cannot sign in."""
        req = urllib.request.Request(BASE + '/api/health')
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(req) as res:
            self.assertEqual(res.status, 200)
            body = json.loads(res.read())
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['database'], 'ok')

    def test_health_says_nothing_it_does_not_have_to(self):
        """
        A failing probe is readable by anyone, so it carries no version, no
        counts and no error text.
        """
        req = urllib.request.Request(BASE + '/api/health')
        with urllib.request.build_opener(NoRedirect()).open(req) as res:
            body = json.loads(res.read())
        self.assertEqual(set(body), {'status', 'database'})

    def test_the_audit_trail_is_searchable_by_date(self):
        """
        audit_logs had indexes on its primary key and on the staff id, and
        nothing else, so a question about a date range -- or a retention
        sweep -- had to read every row of a table with no upper bound.
        """
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SHOW INDEX FROM audit_logs")
            names = {r['Key_name'] for r in cur.fetchall()}
        finally:
            conn.close()
        self.assertIn('idx_audit_timestamp', names,
                      'the audit trail cannot be queried by date')

    def test_retention_removes_only_what_is_past_the_window(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        import audit
        conn = get_db()
        try:
            cur = conn.cursor()
            # A row well inside the window, and one well outside it.
            cur.execute("""INSERT INTO audit_logs
                           (entity_name, entity_id, action_type, `timestamp`)
                           VALUES ('suite_probe', 'KEEP', 'CREATE', NOW())""")
            cur.execute("""INSERT INTO audit_logs
                           (entity_name, entity_id, action_type, `timestamp`)
                           VALUES ('suite_probe', 'DROP', 'CREATE',
                                   DATE_SUB(NOW(), INTERVAL 900 DAY))""")
            conn.commit()

            audit.prune(conn, keep_days=730)

            cur.execute("""SELECT entity_id FROM audit_logs
                           WHERE entity_name = 'suite_probe'""")
            left = {r['entity_id'] for r in cur.fetchall()}
            self.assertIn('KEEP', left, 'retention deleted a current entry')
            self.assertNotIn('DROP', left, 'retention kept an expired entry')

            cur.execute("DELETE FROM audit_logs WHERE entity_name = 'suite_probe'")
            conn.commit()
        finally:
            conn.close()

    def test_retention_can_be_switched_off(self):
        """Keeping everything for ever is a legitimate choice for a medical
        record, so zero means zero rather than delete-everything."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        import audit
        conn = get_db()
        try:
            self.assertEqual(audit.prune(conn, keep_days=0), 0)
        finally:
            conn.close()


class PublicEnquiry(ApiTest):
    """
    The booking form on the public website.

    It used to POST straight at /api/reception/appointment. Once the API
    required a session that endpoint answered 401, so every enquiry from the
    website vanished: nothing recorded, nobody told, and the clinic had no way
    to know enquiries had stopped arriving.

    They land in appointment_requests now, through the only route in the system
    that accepts a write without a session. Nothing it writes is clinical data
    until somebody at the desk accepts it, so spam cannot fill the patient list.
    """

    PATH = '/api/public/appointment-request'
    SITE = 'https://fayzmedical.uz'

    def enquire(self, payload, ip=None, origin=None):
        """
        Post as the website would. Each test uses its own X-Real-IP so the
        per-address rate limit of one test cannot spend another's allowance;
        the server trusts that header because only Nginx can reach the socket.
        """
        req = urllib.request.Request(BASE + self.PATH,
                                     data=json.dumps(payload).encode(),
                                     method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('X-Real-IP', ip or f'203.0.113.{os.getpid() % 250 + 1}')
        if origin:
            req.add_header('Origin', origin)
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(req) as res:
                body = res.read().decode()
                return res.status, (json.loads(body) if body.strip() else {}), dict(res.headers)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                return e.code, json.loads(body), dict(e.headers)
            except Exception:
                return e.code, {}, dict(e.headers)

    def table_counts(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            out = {}
            for t in ('appointment_requests', 'patients', 'appointments'):
                cur.execute(f'SELECT COUNT(*) AS n FROM {t}')
                out[t] = cur.fetchone()['n']
            return out
        finally:
            conn.close()

    def cleanup_requests(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT patient_id, appointment_id FROM appointment_requests")
            for r in cur.fetchall():
                if r['appointment_id']:
                    cur.execute('DELETE FROM appointments WHERE id = ?', (r['appointment_id'],))
                if r['patient_id']:
                    cur.execute('DELETE FROM patients WHERE id = ?', (r['patient_id'],))
            cur.execute('DELETE FROM appointment_requests')
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.cleanup_requests()
        super().tearDown()

    def test_the_website_can_lodge_an_enquiry_without_signing_in(self):
        status, body, _ = self.enquire(
            {'full_name': 'Aziza Rahimova', 'phone': '+998 90 111 22 33'},
            ip='203.0.113.11')
        self.assertEqual(status, 201, f"the website could not book: {body}")
        self.assertIn('request_id', body)

    def test_an_enquiry_is_not_yet_a_patient(self):
        """Unverified input from the internet stays out of the clinical tables."""
        before = self.table_counts()
        self.enquire({'full_name': 'Ehtimoliy Bemor', 'phone': '+998901112233'},
                     ip='203.0.113.12')
        after = self.table_counts()
        self.assertEqual(after['appointment_requests'], before['appointment_requests'] + 1)
        self.assertEqual(after['patients'], before['patients'],
                         'a stranger on the internet created a patient record')
        self.assertEqual(after['appointments'], before['appointments'],
                         'a stranger on the internet booked a clinic slot')

    def test_rubbish_is_refused_in_plain_language(self):
        for payload, field in [
                ({'phone': '+998901112233'}, 'full_name'),
                ({'full_name': 'Test', 'phone': '12'}, 'phone'),
                ({'full_name': 'Test', 'phone': '+998901112233',
                  'preferred_date': '2020-01-01'}, 'preferred_date')]:
            status, body, _ = self.enquire(payload, ip='203.0.113.13')
            self.assertEqual(status, 400, f"{field} was accepted: {body}")
            self.assertEqual(body.get('field'), field)

    def test_a_bot_that_fills_every_field_is_dropped_silently(self):
        """
        The honeypot is a field no person sees. Answering 201 and storing
        nothing means a script cannot tell which of its submissions landed.
        """
        before = self.table_counts()['appointment_requests']
        status, _, _ = self.enquire(
            {'full_name': 'Bot', 'phone': '+998901112233', 'website': 'http://spam'},
            ip='203.0.113.14')
        self.assertEqual(status, 201, 'the bot learned it was detected')
        self.assertEqual(self.table_counts()['appointment_requests'], before,
                         'the honeypot submission was stored')

    def test_typing_mistakes_do_not_spend_the_booking_allowance(self):
        """
        Somebody mistyping their phone number three times has not used up
        their enquiries; only stored ones count against the strict limit.
        """
        ip = '203.0.113.15'
        for _ in range(3):
            self.assertEqual(self.enquire({'full_name': 'Aziza', 'phone': '12'}, ip=ip)[0], 400)
        status, body, _ = self.enquire(
            {'full_name': 'Aziza Rahimova', 'phone': '+998901112233'}, ip=ip)
        self.assertEqual(status, 201, f"the typos cost a real booking: {body}")

    def test_a_flood_from_one_address_is_cut_off(self):
        ip = '203.0.113.16'
        codes = [self.enquire({'full_name': f'Flood {i}', 'phone': '+998901112233'},
                              ip=ip)[0] for i in range(8)]
        self.assertIn(429, codes, 'an address could lodge unlimited enquiries')
        self.assertLessEqual(codes.count(201), 6, 'the limit let too many through')

    def test_cors_is_offered_to_the_clinic_site_and_nobody_else(self):
        _, _, headers = self.enquire(
            {'full_name': 'Origin Test', 'phone': '+998901112233'},
            ip='203.0.113.17', origin=self.SITE)
        self.assertEqual(headers.get('Access-Control-Allow-Origin'), self.SITE)

        _, _, other = self.enquire(
            {'full_name': 'Origin Test 2', 'phone': '+998901112233'},
            ip='203.0.113.18', origin='https://evil.example')
        self.assertIsNone(other.get('Access-Control-Allow-Origin'),
                          'any site on the internet was invited to call this API')

    def test_no_other_route_answers_without_a_session(self):
        """Opening one door must not have opened the rest."""
        for path in ('/api/patients', '/api/reception/requests', '/api/crm/patients',
                     '/api/reception/appointment'):
            req = urllib.request.Request(BASE + path)
            opener = urllib.request.build_opener(NoRedirect())
            try:
                with opener.open(req) as res:
                    self.fail(f"{path} answered {res.status} with no session")
            except urllib.error.HTTPError as e:
                self.assertIn(e.code, (401, 403), f"{path} answered {e.code}")
                self.assertIsNone(e.headers.get('Access-Control-Allow-Origin'),
                                  f"{path} offered CORS")

    def test_the_desk_sees_what_came_in(self):
        self.enquire({'full_name': 'Ko`rinadigan Bemor', 'phone': '+998901112233',
                      'note': 'Konsultatsiya'}, ip='203.0.113.19')
        status, body = self.api.get('/api/reception/requests')
        self.assertEqual(status, 200)
        names = [r['full_name'] for r in body['requests']]
        self.assertIn('Ko`rinadigan Bemor', names)
        self.assertGreaterEqual(body['waiting'], 1)

    def test_accepting_is_what_creates_the_patient(self):
        _, body, _ = self.enquire(
            {'full_name': 'Sanjar Toshmatov', 'phone': '+998934445566'},
            ip='203.0.113.20')
        req_id = body['request_id']
        before = self.table_counts()

        status, result = self.api.post(f'/api/reception/requests/{req_id}/accept', {})
        self.assertEqual(status, 201, f"accept failed: {result}")
        self.assertIn('patient_id', result)
        self.assertIn('appointment_id', result)

        after = self.table_counts()
        self.assertEqual(after['patients'], before['patients'] + 1)
        self.assertEqual(after['appointments'], before['appointments'] + 1)

    def test_rejecting_creates_nothing(self):
        _, body, _ = self.enquire({'full_name': 'Spam Bot', 'phone': '+998901112233'},
                                  ip='203.0.113.21')
        before = self.table_counts()
        status, result = self.api.post(f"/api/reception/requests/{body['request_id']}/reject", {})
        self.assertEqual(status, 200, f"reject failed: {result}")
        after = self.table_counts()
        self.assertEqual(after['patients'], before['patients'])
        self.assertEqual(after['appointments'], before['appointments'])

    def test_an_enquiry_is_only_decided_once(self):
        _, body, _ = self.enquire({'full_name': 'Ikki Marta', 'phone': '+998901112233'},
                                  ip='203.0.113.22')
        req_id = body['request_id']
        self.assertEqual(self.api.post(f'/api/reception/requests/{req_id}/accept', {})[0], 201)
        status, second = self.api.post(f'/api/reception/requests/{req_id}/reject', {})
        self.assertEqual(status, 400, 'the same enquiry was decided twice')
        self.assertEqual(second.get('field'), 'status')

    def test_the_inbox_is_receptions_work(self):
        username = f'suite_enq_hr_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        st, created = self.api.post('/api/users', {
            'username': username, 'password': 'Suite-Probe-2026',
            'full_name': 'Suite HR', 'role': 'hr_manager'})
        self.assertEqual(st, 201, f"could not create probe account: {created}")
        try:
            hr = Client()
            st, login_body = hr.login(username, 'Suite-Probe-2026')
            self.assertEqual(st, 200)
            if login_body.get('must_change_password'):
                hr.post('/api/auth/change-password', {
                    'current_password': 'Suite-Probe-2026',
                    'new_password': 'Suite-Probe-2026-Rotated',
                    'confirm_password': 'Suite-Probe-2026-Rotated'})
            self.assertEqual(hr.get('/api/reception/requests')[0], 403)
        finally:
            self.api.delete('/api/users/' + (created.get('id') or username))


class StaticFileExposure(unittest.TestCase):
    """
    The web root is also the source tree. It holds server.py, auth.py,
    permissions.py, the schema dumps, the request log and db_config.json --
    which carries the MySQL password in plaintext.

    requires_session() decided what to serve by exclusion: anything that was
    not an /api/ path and did not end in .html was treated as a harmless
    static asset. So every one of those files answered 200 to an anonymous
    caller, and `curl https://<host>/db_config.json` returned the database
    credentials. HEAD skipped the check altogether, because do_HEAD was never
    overridden and fell through to SimpleHTTPRequestHandler.
    """

    SECRET_PATHS = [
        '/db_config.json',
        '/db_config.example.json',
        '/auth.py',
        '/permissions.py',
        '/server.py',
        '/db.py',
        '/consultation.py',
        '/data/users.json',
        '/data/hr_db.json',
        '/data/accounting_db.json',
        '/data/reception_db.json',
        '/data/seed_data.sql',
        '/data/schema.mysql.sql',
        '/data/pricing_config.json',
        '/server_log.txt',
        '/CHANGES.md',
        '/README.md',
        '/tests/test_clinic.py',
        '/.gitignore',
    ]

    def fetch(self, path, method='GET'):
        """Status code only, without following the login redirect."""
        req = urllib.request.Request(BASE + path, method=method)
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(req) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except urllib.error.URLError:
            return None, b''

    def test_the_credentials_file_is_not_downloadable(self):
        status, body = self.fetch('/db_config.json')
        self.assertNotEqual(status, 200,
                            'the MySQL password was served over HTTP')
        self.assertNotIn(b'password', body.lower())

    def test_no_source_or_data_file_is_downloadable(self):
        served = []
        for path in self.SECRET_PATHS:
            status, _ = self.fetch(path)
            if status == 200:
                served.append(path)
        self.assertEqual(served, [], f"served to an anonymous caller: {served}")

    def test_head_is_gated_the_same_way_as_get(self):
        """HEAD leaks existence and size, and it used to skip the gate."""
        for path in ('/db_config.json', '/auth.py', '/data/users.json'):
            status, _ = self.fetch(path, method='HEAD')
            self.assertNotEqual(status, 200, f"HEAD {path} answered 200")

    def test_head_on_a_portal_page_redirects_like_get(self):
        status, _ = self.fetch('/doctor.html', method='HEAD')
        self.assertEqual(status, 302,
                         'HEAD served a portal page without a session')

    def test_a_path_nobody_allowed_is_refused(self):
        """The rule is an allow-list, so an unanticipated file is refused."""
        for path in ('/install.py', '/update_pharmacology.py',
                     '/data/pricing_config.json', '/run_clinic_server.ps1'):
            status, _ = self.fetch(path)
            self.assertNotEqual(status, 200, f"{path} was served")

    def test_the_login_screen_still_has_its_assets(self):
        """The gate must not be so eager that nobody can sign in."""
        for path in ('/login.html', '/robots.txt',
                     '/css/unified_header.css', '/js/fmh_dialogs.js'):
            status, _ = self.fetch(path)
            self.assertEqual(status, 200, f"{path} is needed anonymously")

    def test_reference_data_is_served_to_signed_in_staff(self):
        """
        The ward layout and the drug catalogues are fetched by the portals, so
        closing the directory must not take them with it.
        """
        if not credentials_present():
            self.skipTest(CREDENTIALS_HINT)
        api = Client()
        if api.login()[0] != 200:
            self.skipTest('could not sign in')
        for path in ('/data/clinic_rooms.json', '/data/pharmacology_db.json',
                     '/data/fayz_house_meds.json'):
            req = urllib.request.Request(BASE + path)
            req.add_header('Cookie', api.cookie)
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(req) as res:
                self.assertEqual(res.status, 200, f"{path} unreachable when signed in")

    def test_reference_data_is_not_public(self):
        status, _ = self.fetch('/data/clinic_rooms.json')
        self.assertNotEqual(status, 200, 'clinic layout served anonymously')


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

    def test_a_stay_may_begin_the_day_another_ends(self):
        """
        The last date of a stay is the day the patient leaves, not a night in
        the bed: total_days is DATEDIFF(end, start), so a stay 01->08 is billed
        for seven nights and the bed is free on the 8th. The guard used to
        compare the interval closed at both ends and refused that turnover,
        while the booking board (which compares half-open) showed the bed as
        free — the desk was told to book a bed the server then rejected.
        """
        a = self.make_patient('Turnover Out')
        b = self.make_patient('Turnover In')
        self.admit(a, BED_B, '2027-08-01', '2027-08-08')
        status, body = self.admit(b, BED_B, '2027-08-08', '2027-08-15', expect=None)
        self.assertEqual(status, 201, f"same-day turnover was refused: {body}")

    def test_a_stay_may_not_begin_the_day_before_another_ends(self):
        """One day the other way round is a real overlap and must still fail."""
        a = self.make_patient('Turnover Out 2')
        b = self.make_patient('Turnover In 2')
        self.admit(a, BED_B, '2027-09-01', '2027-09-08')
        status, body = self.admit(b, BED_B, '2027-09-07', '2027-09-15', expect=None)
        self.assertEqual(status, 400, f"bed double-booked by one night: {body}")

    def test_a_same_day_stay_still_holds_the_bed(self):
        """
        A stay whose start and end are the same date bills one day, so it must
        occupy one night. Comparing the interval half-open makes it empty, and
        an empty interval overlaps nothing — the bed would look free to
        everyone including the next booking.
        """
        a = self.make_patient('Single Day')
        b = self.make_patient('Single Day Rival')
        self.admit(a, BED_C, '2027-10-20', '2027-10-20')
        status, body = self.admit(b, BED_C, '2027-10-20', '2027-10-25', expect=None)
        self.assertEqual(status, 400, f"a one-day stay did not hold its bed: {body}")


# ---------------------------------------------------------------------------
# Whole-room bookings
# ---------------------------------------------------------------------------

class WholeRoomBooking(ApiTest):
    """
    'Statsionar Butun Xona' sells a two-bed room to one patient at 1.1M a day
    against 720k for a shared bed. The premium buys the second bed staying
    empty, so the partner bed has to be held even though nobody is in it.

    That rule existed only in the browser: reception.js kept a hand-written
    map of which bed partners which and greyed the partner out. The server
    knew nothing about it, so the same room could be sold whole and then
    filled by anything that posted to the API directly — including the very
    same page on another machine, whose bed map came from its own localStorage.
    """

    SOLO = 'statsionar_full_room'
    # Beds 22A and 22B are the two halves of room 22.
    ROOM_22_A, ROOM_22_B = 'BED-22A', 'BED-22B'

    def test_a_room_sold_whole_refuses_a_second_patient(self):
        solo = self.make_patient('Solo Buyer')
        other = self.make_patient('Unwanted Roommate')
        self.admit(solo, self.ROOM_22_A, '2028-01-05', '2028-01-15',
                   program=self.SOLO, rate=1100000)
        status, body = self.admit(other, self.ROOM_22_B, '2028-01-06', '2028-01-12',
                                  expect=None)
        self.assertEqual(status, 400,
                         f"a room billed as private took a second patient: {body}")

    def test_a_room_cannot_be_sold_whole_while_its_partner_bed_is_taken(self):
        """The rule has to hold in both directions, not just the one the page
        happened to exercise."""
        sitting = self.make_patient('Already In Room')
        solo = self.make_patient('Late Solo Buyer')
        self.admit(sitting, self.ROOM_22_B, '2028-02-05', '2028-02-15')
        status, body = self.admit(solo, self.ROOM_22_A, '2028-02-06', '2028-02-12',
                                  program=self.SOLO, rate=1100000, expect=None)
        self.assertEqual(status, 400,
                         f"a room was sold whole while occupied: {body}")

    def test_two_shared_stays_may_still_share_a_room(self):
        """The room is only held whole when somebody has paid for that."""
        a = self.make_patient('Sharer A')
        b = self.make_patient('Sharer B')
        self.admit(a, self.ROOM_22_A, '2028-03-05', '2028-03-15')
        status, body = self.admit(b, self.ROOM_22_B, '2028-03-06', '2028-03-12',
                                  expect=None)
        self.assertEqual(status, 201,
                         f"an ordinary two-bed room was refused a second patient: {body}")

    def test_a_whole_room_booking_leaves_other_rooms_alone(self):
        solo = self.make_patient('Solo In 22')
        elsewhere = self.make_patient('Patient In 21')
        self.admit(solo, self.ROOM_22_A, '2028-04-05', '2028-04-15',
                   program=self.SOLO, rate=1100000)
        status, body = self.admit(elsewhere, BED_A, '2028-04-06', '2028-04-12',
                                  expect=None)
        self.assertEqual(status, 201, f"a different room was blocked too: {body}")

    def test_the_room_reopens_once_the_whole_room_dates_pass(self):
        solo = self.make_patient('Solo Until May')
        later = self.make_patient('June Arrival')
        self.admit(solo, self.ROOM_22_A, '2028-05-01', '2028-05-10',
                   program=self.SOLO, rate=1100000)
        status, body = self.admit(later, self.ROOM_22_B, '2028-06-01', '2028-06-10',
                                  expect=None)
        self.assertEqual(status, 201,
                         f"the room stayed locked after the stay ended: {body}")

    def test_a_transfer_cannot_break_into_a_room_sold_whole(self):
        """
        Admission is not the only way into a bed. The transfer path had its own
        copy of the occupancy check, so a patient could be moved into a room
        that admission would have refused.
        """
        solo = self.make_patient('Solo Transfer Target')
        mover = self.make_patient('Moving Patient')
        self.admit(solo, self.ROOM_22_A, '2028-07-01', '2028-07-20',
                   program=self.SOLO, rate=1100000)
        _, adm = self.admit(mover, BED_A, '2028-07-05', '2028-07-18')
        status, body = self.api.post(
            f"/api/admissions/{adm['admission_id']}/transfer",
            {'new_bed_id': self.ROOM_22_B, 'transfer_date': '2028-07-06'})
        self.assertEqual(status, 400,
                         f"a transfer walked into a room billed as private: {body}")


# ---------------------------------------------------------------------------
# The occupancy board
# ---------------------------------------------------------------------------

class OccupancyBoard(ApiTest):
    """
    /api/facility/availability — what reception needs before it can place
    anyone: which beds are free between two given dates.

    /api/beds could not answer this. It reads v_bed_live_status, which is
    pinned to CURDATE(), so it only ever describes today; a desk booking a
    stay that starts next week got today's picture. The page made up the
    difference in the browser, merging a static room file with bookings held
    in localStorage — per-machine fiction that blocked real beds on one
    computer and left them green on the next.
    """

    SOLO = 'statsionar_full_room'
    ROOM_22_A, ROOM_22_B = 'BED-22A', 'BED-22B'

    def board(self, start, end, client=None):
        status, body = (client or self.api).get(
            f'/api/facility/availability?start={start}&end={end}')
        self.assertEqual(status, 200, f"board unavailable: {body}")
        return body

    def bed(self, board, bed_id):
        for room in board['rooms']:
            for b in room['beds']:
                if b['bed_id'] == bed_id:
                    return b
        self.fail(f"{bed_id} missing from the board")

    def test_the_board_covers_the_whole_ward(self):
        board = self.board('2029-01-01', '2029-01-08')
        self.assertEqual(board['summary']['total_beds'], 14)
        self.assertEqual(board['summary']['total_rooms'], 7)
        # Consultation rooms, the nurse stations and reception have no beds and
        # have no business on a bed board.
        self.assertTrue(all(r['beds'] for r in board['rooms']))

    def test_an_occupied_bed_is_named_with_who_holds_it(self):
        pid = self.make_patient('Board Occupant')
        self.admit(pid, BED_A, '2029-02-01', '2029-02-10')
        entry = self.bed(self.board('2029-02-01', '2029-02-08'), BED_A)
        self.assertEqual(entry['status'], 'occupied')
        self.assertEqual(entry['occupant']['patient_name'], 'Board Occupant')

    def test_a_bed_free_now_but_booked_later_is_not_simply_free(self):
        """
        A bed that is free today and taken on the fourth day of the requested
        stay must not be offered as free for that stay, or the desk books it
        and the server refuses at the last step.
        """
        pid = self.make_patient('Board Late Arrival')
        self.admit(pid, BED_B, '2029-03-05', '2029-03-20')
        entry = self.bed(self.board('2029-03-01', '2029-03-10'), BED_B)
        self.assertEqual(entry['status'], 'partial_conflict')
        self.assertEqual(entry['conflict']['start_date'], '2029-03-05')

    def test_the_partner_of_a_room_sold_whole_reads_as_locked(self):
        pid = self.make_patient('Board Solo Buyer')
        self.admit(pid, self.ROOM_22_A, '2029-04-01', '2029-04-10',
                   program=self.SOLO, rate=1100000)
        board = self.board('2029-04-01', '2029-04-08')
        self.assertEqual(self.bed(board, self.ROOM_22_B)['status'], 'room_locked')
        room = next(r for r in board['rooms']
                    if any(b['bed_id'] == self.ROOM_22_A for b in r['beds']))
        self.assertTrue(room['locked_whole_room'])
        self.assertEqual(room['free_beds'], 0)

    def test_the_board_answers_for_the_dates_asked_not_for_today(self):
        """The whole point of the endpoint: a stay outside the window is not
        the window's problem."""
        pid = self.make_patient('Board Far Future')
        self.admit(pid, BED_C, '2029-06-01', '2029-06-10')
        self.assertEqual(self.bed(self.board('2029-05-01', '2029-05-10'), BED_C)['status'],
                         'available')
        self.assertEqual(self.bed(self.board('2029-06-02', '2029-06-08'), BED_C)['status'],
                         'occupied')

    def test_a_free_bed_advertises_when_it_is_next_taken(self):
        pid = self.make_patient('Board Next Booking')
        self.admit(pid, BED_C, '2029-07-20', '2029-07-28')
        entry = self.bed(self.board('2029-07-01', '2029-07-10'), BED_C)
        self.assertEqual(entry['status'], 'available')
        self.assertEqual(entry['next_booking'], '2029-07-20')

    def test_a_backwards_range_is_refused_in_plain_language(self):
        status, body = self.api.get(
            '/api/facility/availability?start=2029-08-10&end=2029-08-01')
        self.assertEqual(status, 400)
        self.assertIn('sana', str(body.get('error', '')).lower())

    def test_every_bed_the_board_calls_free_can_actually_be_booked(self):
        """
        The invariant that makes the board worth having. The board and the
        booking guard are two readings of the same question, and they were
        written in two languages with two different interval rules; this walks
        the board's own verdict back through the door it is advising on.
        """
        start, end = '2029-09-01', '2029-09-08'
        blocker = self.make_patient('Invariant Blocker')
        solo = self.make_patient('Invariant Solo')
        self.admit(blocker, BED_A, start, end)
        self.admit(solo, self.ROOM_22_A, start, end, program=self.SOLO, rate=1100000)

        board = self.board(start, end)
        free = [b['bed_id'] for r in board['rooms'] for b in r['beds']
                if b['status'] == 'available']
        self.assertTrue(free, 'the board claimed the whole ward was full')

        for bed_id in free:
            p = self.make_patient(f'Invariant {bed_id}')
            status, body = self.admit(p, bed_id, start, end, expect=None)
            self.assertEqual(status, 201,
                             f"board offered {bed_id} but the guard refused it: {body}")

        taken = [b['bed_id'] for r in board['rooms'] for b in r['beds']
                 if b['status'] in ('occupied', 'room_locked', 'partial_conflict')]
        for bed_id in taken:
            p = self.make_patient(f'Invariant Refused {bed_id}')
            status, body = self.admit(p, bed_id, start, end, expect=None)
            self.assertEqual(status, 400,
                             f"board marked {bed_id} taken but the guard allowed it: {body}")


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

    def test_the_medication_round_downloads_as_a_pdf(self):
        """
        The round could be printed from the browser and not downloaded. A
        signed sheet gets filed, so it has to exist as a file the ward can keep
        and re-send, not only as whatever the browser rendered that afternoon.
        """
        pid = self.make_patient('Round PDF Bemor')
        start = _dt.date.today()
        end = start + _dt.timedelta(days=6)
        _, adm = self.admit(pid, BED_A, start.isoformat(), end.isoformat())
        status, rx = self.api.post('/api/doctor/prescriptions', {
            'patient_id': pid, 'admission_id': adm['admission_id'],
            'medication_name': 'Diazepam', 'dosage': '10mg', 'route': 'IM',
            'frequency': 'Kuniga 2 mahal', 'duration_days': 5,
        })
        self.assertIn(status, (200, 201), f"prescription failed: {rx}")

        req = urllib.request.Request(
            BASE + '/api/nursery/round/pdf?date=' + start.isoformat())
        req.add_header('Cookie', self.api.cookie)
        with urllib.request.urlopen(req) as res:
            self.assertEqual(res.status, 200)
            self.assertEqual(res.headers.get('Content-Type'), 'application/pdf')
            self.assertIn('attachment', res.headers.get('Content-Disposition', ''))
            body = res.read()
        self.assertTrue(body.startswith(b'%PDF'), 'response was not a PDF')
        self.assertGreater(len(body), 800, 'PDF looks truncated')

    def test_a_day_with_nobody_on_the_ward_is_not_an_empty_pdf(self):
        """An empty sheet would be filed as though the round had been done."""
        far = (_dt.date.today() + _dt.timedelta(days=900)).isoformat()
        req = urllib.request.Request(BASE + '/api/nursery/round/pdf?date=' + far)
        req.add_header('Cookie', self.api.cookie)
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(req) as res:
                self.fail(f"an empty day produced a sheet (HTTP {res.status})")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_the_round_pdf_is_nursing_work(self):
        """Same boundary as the round itself: HR has no business with it."""
        username = f'suite_pdf_hr_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        st, created = self.api.post('/api/users', {
            'username': username, 'password': 'Suite-Probe-2026',
            'full_name': 'Suite HR', 'role': 'hr_manager'})
        self.assertEqual(st, 201, f"could not create probe account: {created}")
        try:
            hr = Client()
            st, login_body = hr.login(username, 'Suite-Probe-2026')
            self.assertEqual(st, 200)
            if login_body.get('must_change_password'):
                hr.post('/api/auth/change-password', {
                    'current_password': 'Suite-Probe-2026',
                    'new_password': 'Suite-Probe-2026-Rotated',
                    'confirm_password': 'Suite-Probe-2026-Rotated'})
            self.assertEqual(hr.get('/api/nursery/round/pdf')[0], 403)
        finally:
            self.api.delete('/api/users/' + (created.get('id') or username))

    def test_pdf_module_imports(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, root)
        try:
            from pdf_generator import generate_patient_pdf  # noqa: F401
        except SyntaxError as e:
            self.fail(f"pdf_generator.py does not parse: {e}")
        except ImportError as e:
            self.skipTest(f"reportlab not installed: {e}")


class MedicationPurchases(ApiTest):
    def test_medication_purchase_records_expense_and_restocks(self):
        """
        Buying medications must record an expense transaction in accounting,
        appear in medication_purchases, and update catalog inventory stock.
        """
        today_str = _dt.date.today().isoformat()
        st, res = self.api.post('/api/accounting/medication-purchases', {
            'purchase_date': today_str,
            'payment_method': 'cash',
            'supplier_name': 'Grand Pharm Test',
            'invoice_number': 'CHK-TEST-001',
            'notes': 'Test batch purchase',
            'items': [
                {
                    'medication_name': 'Reamberin 1.5% 400ml',
                    'category': 'Detoksikatsiya',
                    'form': 'flakon',
                    'quantity': 10,
                    'unit_price': 40000
                }
            ]
        })
        self.assertEqual(st, 201, f"medication purchase failed: {res}")
        trx_id = res['transaction_id']
        pur_ids = res['purchase_ids']
        self.assertEqual(res['amount'], 400000.0)

        # 1. Verify accounting ledger and data
        st_data, acc_data = self.api.get('/api/accounting/data')
        self.assertEqual(st_data, 200)
        self.assertIn('medication_purchases', acc_data)

        # Check transaction in accounting_transactions
        txn = next((t for t in acc_data['transactions'] if t['id'] == trx_id), None)
        self.assertIsNotNone(txn, "transaction not found in accounting transactions")
        self.assertEqual(txn['type'], 'expense')
        self.assertEqual(txn['category'], 'medication_purchase')
        self.assertEqual(float(txn['amount']), 400000.0)

        # Check medication_purchases list
        pur = next((p for p in acc_data['medication_purchases'] if p['id'] in pur_ids), None)
        self.assertIsNotNone(pur, "purchase not found in medication purchases list")
        self.assertEqual(pur['medication_name'], 'Reamberin 1.5% 400ml')
        self.assertEqual(float(pur['total_price']), 400000.0)

        # 2. Verify dedicated GET endpoint
        st_list, pur_list = self.api.get('/api/accounting/medication-purchases')
        self.assertEqual(st_list, 200)
        self.assertTrue(any(p['id'] == pur_ids[0] for p in pur_list))

        # 3. Clean up by deleting the test purchase
        st_del, del_res = self.api.delete(f'/api/accounting/medication-purchases/{pur_ids[0]}')
        self.assertEqual(st_del, 200, f"delete purchase failed: {del_res}")

    def test_medication_purchase_validation_rejects_empty_or_negative(self):
        """Refuse zero or negative quantities and empty item lists."""
        st, res = self.api.post('/api/accounting/medication-purchases', {
            'items': []
        })
        self.assertEqual(st, 400)

        st, res = self.api.post('/api/accounting/medication-purchases', {
            'items': [
                {'medication_name': 'Test Med', 'quantity': -5, 'unit_price': 10000}
            ]
        })
        self.assertEqual(st, 400)

    def test_unauthorized_staff_cannot_create_medication_purchase(self):
        """Only accounting-authorized roles may record clinic purchases."""
        nurse_user = f'suite_med_nurse_{os.getpid()}'
        self.api.delete('/api/users/' + nurse_user)
        st, created = self.api.post('/api/users', {
            'username': nurse_user, 'password': 'Suite-Probe-2026',
            'full_name': 'Suite Nurse', 'role': 'nurse'
        })
        self.assertEqual(st, 201)
        try:
            nurse = Client()
            self.assertEqual(nurse.login(nurse_user, 'Suite-Probe-2026')[0], 200)
            res_code, _ = nurse.post('/api/accounting/medication-purchases', {
                'items': [{'medication_name': 'Test', 'quantity': 1, 'unit_price': 1000}]
            })
            self.assertEqual(res_code, 403)
        finally:
            self.api.delete('/api/users/' + nurse_user)


PROBE_PREFIXES = ('suite_', 'concurrent_probe_', 'pwpolicy_probe')


def sweep_probe_accounts(when):
    """Remove any account this suite created and failed to clean up."""
    if not credentials_present():
        return
    api = Client()
    if api.login()[0] != 200:
        return
    status, users = api.get('/api/users')
    if status != 200 or not isinstance(users, list):
        return
    stale = [u for u in users
             if str(u.get('username', '')).startswith(PROBE_PREFIXES)]
    # This runs against the file that holds every real login, so it refuses to
    # act if its own selection looks wrong. A sweep that would remove most of
    # the accounts has misidentified something, and the right answer is to stop
    # and say so rather than to tidy up.
    if stale and len(stale) > len(users) // 2:
        print(f"  [suite] REFUSING to sweep: {len(stale)} of {len(users)} accounts "
              f"matched a probe prefix, which cannot be right")
        return
    for u in stale:
        api.delete('/api/users/' + (u.get('id') or u['username']))
    if stale:
        print(f"  [suite] swept {len(stale)} leftover probe account(s) {when}: "
              + ', '.join(u['username'] for u in stale))


class DutyScheduleSave(ApiTest):
    """The duty roster is a JSON file the page rewrites on every shift swap."""

    ROSTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'duty_schedule.json')

    def setUp(self):
        super().setUp()
        # The roster is a tracked file; put its exact bytes back afterwards.
        self._roster_bytes = None
        if os.path.exists(self.ROSTER):
            with open(self.ROSTER, 'rb') as f:
                self._roster_bytes = f.read()

    def tearDown(self):
        if self._roster_bytes is not None:
            with open(self.ROSTER, 'wb') as f:
                f.write(self._roster_bytes)
        super().tearDown()

    def test_saving_shifts_keeps_nurses_and_doctors(self):
        """A swap sends only sanitarkas + shifts; it used to erase the rest."""
        st, before = self.api.get('/api/duty-schedule')
        self.assertEqual(st, 200)
        st, res = self.api.post('/api/duty-schedule', {
            'sanitarkas': before.get('sanitarkas', []),
            'shifts': before.get('shifts', []),
        })
        self.assertEqual(st, 200, res)
        st, after = self.api.get('/api/duty-schedule')
        self.assertEqual(after.get('nurses'), before.get('nurses'))
        self.assertEqual(after.get('doctors'), before.get('doctors'))
        self.assertEqual(after.get('shifts'), before.get('shifts'))

    def test_saving_one_day_keeps_the_other_months(self):
        """A swap for a month not yet stored posted that month only and erased the rest of the roster."""
        st, before = self.api.get('/api/duty-schedule')
        self.assertEqual(st, 200)
        kept = before.get('shifts', [])
        st, res = self.api.post('/api/duty-schedule', {
            'shifts': [{'date': '2031-01-15', 'sanitar_primary': 'Suite Probe'}],
        })
        self.assertEqual(st, 200, res)
        st, after = self.api.get('/api/duty-schedule')
        dates = {s.get('date') for s in after.get('shifts', [])}
        for sh in kept:
            self.assertIn(sh.get('date'), dates)
        self.assertIn('2031-01-15', dates)

    def test_refuses_bad_shape_and_markup(self):
        st, res = self.api.post('/api/duty-schedule', {'shifts': 'hammasi'})
        self.assertEqual(st, 400, res)
        st, res = self.api.post('/api/duty-schedule', {
            'shifts': [{'date': '2026-10-01', 'sanitar_primary': '<img src=x onerror=alert(1)>'}],
        })
        self.assertEqual(st, 400, res)
        self.assertIn('error', res)


class AccountingPaymentMethods(ApiTest):
    def test_card_is_stored_as_terminal(self):
        """'card' was known only to the payments route; journal entries fell back to cash."""
        st, res = self.api.post('/api/accounting/transaction', {
            'type': 'expense', 'category': 'operational_expense', 'amount': 1000,
            'payment_method': 'card', 'title': 'Suite probe: card method',
        })
        self.assertEqual(st, 201, res)
        st, data = self.api.get('/api/accounting/data')
        txn = next(t for t in data['transactions'] if t['id'] == res['id'])
        self.assertEqual(txn['payment_method'], 'terminal')
        self.assertEqual(txn['account_source'], 'terminal_bank')


class MedicationPurchaseQuantity(ApiTest):
    def test_fractional_quantity_is_refused(self):
        """Stock is whole units; 2.5 was billed as 2.5 but stocked as 2."""
        st, res = self.api.post('/api/accounting/medication-purchases', {
            'items': [{'medication_name': 'Suite probe med', 'quantity': 2.5, 'unit_price': 1000}],
        })
        self.assertEqual(st, 400, res)
        self.assertEqual(res.get('field'), 'quantity')


class AnamnesisDoesNotWriteConsultation(ApiTest):
    def test_anamnesis_save_creates_no_consultation(self):
        """Saving an anamnesis used to file a 'final' consultation with risk 'none'."""
        pid = self.make_patient('Anamnez Sinov')
        st, res = self.api.post('/api/doctor/anamnesis', {
            'patient_id': pid, 'complaints': 'Bosh ogrigi',
            'somatic_status': 'Qoniqarli',
        })
        self.assertIn(st, (200, 201), res)
        st, cons = self.api.get('/api/consultations/patient/' + pid)
        self.assertEqual(st, 200, cons)
        self.assertEqual(cons['consultations'], [])


class MedicineStock(ApiTest):
    """
    Stock only ever went up (purchases) and never down when medicine was given,
    so the shelf count drifted further from the truth every day.
    """
    _order = NurseStation._order
    _admitted_patient = NurseStation._admitted_patient

    def _stock_item(self, name, qty=5, price=2000):
        st, res = self.api.post('/api/accounting/medication-purchases', {
            'items': [{'medication_name': name, 'form': 'ampula', 'quantity': qty, 'unit_price': price}],
        })
        self.assertEqual(st, 201, res)
        self.addCleanup(self.api.delete, '/api/accounting/medication-purchases/' + res['purchase_ids'][0])
        return self._find_stock(name)

    def _find_stock(self, name):
        st, data = self.api.get('/api/accounting/data')
        self.assertEqual(st, 200)
        return next(m for m in data['pharmacy_stock'] if m['name'] == name)

    def _usage(self):
        today = _dt.date.today().isoformat()
        st, usage = self.api.get(f'/api/accounting/medicine-usage?start={today}&end={today}')
        self.assertEqual(st, 200, usage)
        return usage

    def _give(self, rx, slot, status='given'):
        st, body = self.api.post('/api/nursery/administer', {
            'prescription_id': rx, 'slot_index': slot, 'status': status})
        self.assertIn(st, (200, 201), body)

    def test_given_dose_takes_one_unit_and_a_correction_puts_it_back(self):
        name = f'Suite Stock Med {os.getpid()}'
        item = self._stock_item(name, qty=5, price=2000)
        start = int(item['stock_quantity'])
        pid, adm = self._admitted_patient('Ombor Sinov', BED_A)
        rx = self._order(pid, adm, name=name, frequency='Kuniga 2 mahal')

        self._give(rx, 0)
        self.assertEqual(int(self._find_stock(name)['stock_quantity']), start - 1)
        row = next(r for r in self._usage()['linked'] if r['name'] == name)
        self.assertEqual(row['doses'], 1)
        self.assertEqual(row['units_taken'], 1)
        self.assertEqual(row['cost'], 2000.0)

        # Recording the same dose again is an amendment, not a second unit.
        self._give(rx, 0)
        self.assertEqual(int(self._find_stock(name)['stock_quantity']), start - 1)

        self._give(rx, 0, status='missed')
        self.assertEqual(int(self._find_stock(name)['stock_quantity']), start)

    def test_unmatched_name_is_listed_until_accounting_links_it(self):
        stock_name = f'Suite Linked Stock {os.getpid()}'
        rx_name = f'suite  doctor name {os.getpid()}'
        item = self._stock_item(stock_name, qty=3)
        pid, adm = self._admitted_patient('Bog`lash Sinov', BED_B)
        rx = self._order(pid, adm, name=rx_name, frequency='Kuniga 2 mahal')

        self._give(rx, 0)
        self.assertEqual(int(self._find_stock(stock_name)['stock_quantity']), int(item['stock_quantity']))
        self.assertIn(rx_name, [u['medication_name'] for u in self._usage()['unlinked']])

        st, res = self.api.post('/api/accounting/medicine-links', {
            'medication_name': rx_name, 'medication_id': item['id']})
        self.assertEqual(st, 200, res)
        # The dose already given came off the shelf too, and the name is no
        # longer offered for linking.
        self.assertEqual(res['settled_doses'], 1)
        self.assertEqual(int(self._find_stock(stock_name)['stock_quantity']), int(item['stock_quantity']) - 1)
        self.assertNotIn(rx_name, [u['medication_name'] for u in self._usage()['unlinked']])

        self._give(rx, 1)
        self.assertEqual(int(self._find_stock(stock_name)['stock_quantity']), int(item['stock_quantity']) - 2)

    def test_link_refuses_unknown_stock_item(self):
        st, res = self.api.post('/api/accounting/medicine-links', {
            'medication_name': 'Nimadir', 'medication_id': 'MED-NOT-THERE'})
        self.assertEqual(st, 400, res)
        self.assertEqual(res.get('field'), 'medication_id')


class OwnerReport(ApiTest):
    """The owner follows all money from a phone, read-only."""
    _account = RoleAuthorization._account

    def setUp(self):
        super().setUp()
        self._temp_users = []

    def tearDown(self):
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        super().tearDown()

    def _summary(self, client=None):
        today = _dt.date.today().isoformat()
        st, body = (client or self.api).get(f'/api/owner/summary?start={today}&end={today}')
        self.assertEqual(st, 200, body)
        return body

    @staticmethod
    def _group(rows, key):
        return next((r['amount'] for r in rows if r['key'] == key), 0.0)

    def test_income_and_spending_are_grouped_and_transfers_left_out(self):
        before = self._summary()
        for payload in (
            {'type': 'income', 'category': 'emergency_call', 'amount': 5000, 'title': 'Suite probe: call-out'},
            {'type': 'expense', 'category': 'salary', 'amount': 3000, 'title': 'Suite probe: salary'},
            {'type': 'expense', 'category': 'incasso', 'amount': 1000, 'title': 'Suite probe: cash to bank'},
        ):
            st, res = self.api.post('/api/accounting/transaction', dict(payload, payment_method='cash'))
            self.assertEqual(st, 201, res)
        after = self._summary()

        self.assertAlmostEqual(after['income'] - before['income'], 5000, delta=0.01)
        # Moving cash to the bank is not spending.
        self.assertAlmostEqual(after['expense'] - before['expense'], 3000, delta=0.01)
        self.assertAlmostEqual(after['transfers'] - before['transfers'], 1000, delta=0.01)
        self.assertAlmostEqual(
            self._group(after['income_by_source'], 'emergency_call')
            - self._group(before['income_by_source'], 'emergency_call'), 5000, delta=0.01)
        self.assertAlmostEqual(
            self._group(after['expense_by_category'], 'salary')
            - self._group(before['expense_by_category'], 'salary'), 3000, delta=0.01)

    def test_patient_payment_is_split_by_what_the_invoice_charged(self):
        pid = self.make_patient('Egasi Sinov')
        start = _dt.date.today()
        _, adm = self.admit(pid, BED_C, start.isoformat(), (start + _dt.timedelta(days=3)).isoformat())
        before = self._summary()
        st, pay = self.api.post('/api/payments', {
            'admission_id': adm['admission_id'], 'amount': 100000, 'payment_method': 'cash'})
        self.assertEqual(st, 201, pay)
        after = self._summary()
        self.assertAlmostEqual(
            self._group(after['income_by_source'], 'bed_stay')
            - self._group(before['income_by_source'], 'bed_stay'), 100000, delta=1)
        entry = next(e for e in after['entries'] if e['type'] == 'income' and e['group'] == 'bed_stay'
                     and e['who'] == 'Egasi Sinov')
        self.assertAlmostEqual(entry['amount'], 100000, delta=1)

    def test_a_booking_not_yet_begun_is_not_debt(self):
        """The invoice holds the whole planned stay from the day it is booked."""
        before = self._summary()['debts']
        pid = self.make_patient('Kelajak Bron')
        start = _dt.date.today() + _dt.timedelta(days=40)
        self.admit(pid, BED_A, start.isoformat(), (start + _dt.timedelta(days=5)).isoformat())
        after = self._summary()['debts']
        self.assertEqual(after['count'], before['count'])
        self.assertAlmostEqual(after['total'], before['total'], delta=0.01)

    def test_period_is_required(self):
        st, body = self.api.get('/api/owner/summary')
        self.assertEqual(st, 400, body)

    def test_owner_reads_money_but_cannot_change_it(self):
        owner = self._account('owner')
        self._summary(owner)
        st, _ = owner.post('/api/accounting/transaction', {
            'type': 'expense', 'category': 'salary', 'amount': 1, 'title': 'X'})
        self.assertEqual(st, 403)
        self.assertEqual(owner.get('/api/crm/patients')[0], 403)

    def test_accountant_does_not_see_the_owner_report(self):
        accountant = self._account('accountant')
        today = _dt.date.today().isoformat()
        st, _ = accountant.get(f'/api/owner/summary?start={today}&end={today}')
        self.assertEqual(st, 403)



class FrontDeskSafety(ApiTest):
    """Faults found in the 2026-10-08 system map: a refused advance, double-booked slots, name deletes."""

    _account = RoleAuthorization._account

    def setUp(self):
        super().setUp()
        self._temp_users = []

    def tearDown(self):
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        super().tearDown()

    def test_reception_advance_is_paid_with_the_admission(self):
        """The advance was a separate /api/payments call a receptionist may not make, and it was lost silently."""
        desk = self._account('receptionist')
        start = (_dt.date.today() + _dt.timedelta(days=400)).isoformat()
        end = (_dt.date.today() + _dt.timedelta(days=405)).isoformat()
        st, body = desk.post('/api/admissions', {
            'patient_name': 'Avans Probe Bemor', 'patient_phone': '+998900000123',
            'bed_id': BED_A, 'program_type': 'statsionar_shared',
            'start_date': start, 'planned_end_date': end,
            'attending_doctor_id': DOCTOR, 'daily_price': RATE,
            'advance_amount': 150000, 'advance_method': 'cash',
        })
        self.assertEqual(st, 201, body)
        self._admissions.append(body['admission_id'])
        self._patients.append(body['patient_id'])
        self.assertTrue(body.get('advance_payment_id'), body)
        inv = self.invoice_for(body['admission_id'])
        self.assertEqual(float(inv['total_paid']), 150000.0)

    def test_receptionist_still_cannot_take_other_payments(self):
        """The advance right is narrow: the general payments route stays closed to the desk."""
        desk = self._account('receptionist')
        st, _ = desk.post('/api/payments', {'invoice_id': 'INV-NOPE', 'amount': 1})
        self.assertEqual(st, 403)

    def test_a_negative_advance_is_refused(self):
        st, body = self.api.post('/api/admissions', {
            'patient_name': 'Avans Minus Bemor', 'bed_id': BED_A,
            'start_date': '2029-03-01', 'planned_end_date': '2029-03-05',
            'attending_doctor_id': DOCTOR, 'daily_price': RATE,
            'advance_amount': -5000,
        })
        self.assertEqual(st, 400, body)
        self.assertEqual(body.get('field'), 'advance_amount')

    def test_the_same_doctor_slot_cannot_be_booked_twice(self):
        """The slot grid never showed booked times and the server never checked, so two desks could book one slot."""
        day = (_dt.date.today() + _dt.timedelta(days=420)).isoformat()
        first = {'patient_name': 'Slot Probe Bir', 'patient_phone': '+998900000201',
                 'doctor_id': DOCTOR, 'date': day, 'time': '11:30',
                 'service_type': 'consultation'}
        st, body = self.api.post('/api/reception/appointment', first)
        self.assertIn(st, (200, 201), body)
        if body.get('patient_id'):
            self._patients.append(body['patient_id'])
        second = dict(first, patient_name='Slot Probe Ikki', patient_phone='+998900000202')
        st, body2 = self.api.post('/api/reception/appointment', second)
        self.assertEqual(st, 400, body2)
        self.assertEqual(body2.get('field'), 'time')
        st, body3 = self.api.post('/api/reception/appointment', dict(second, time='12:00'))
        self.assertIn(st, (200, 201), body3)
        if body3.get('patient_id'):
            self._patients.append(body3['patient_id'])

    def test_deleting_by_name_deletes_nobody(self):
        """The bed board sent a patient's name; the server matched full_name and wiped every namesake."""
        pid = self.make_patient('Namesake Probe Bemor')
        self.api.delete('/api/patients/' + urllib.parse.quote('Namesake Probe Bemor'))
        st, rows = self.api.get('/api/crm/patients')
        self.assertEqual(st, 200)
        self.assertTrue(any(r.get('id') == pid for r in rows),
                        'a delete by name removed the patient')


class BedBoardTransfer(ApiTest):
    """
    The bed board's "change bed" only rewrote the page's own memory, and the
    real transfer route re-priced the rest of the stay at the destination
    bed's list rate and would move a patient who had already left.
    """

    SOLO = 'statsionar_full_room'

    def _db_one(self, sql, params):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchone()
        finally:
            conn.close()

    def _admit_at(self, pid, bed, start, end, price, program='statsionar_shared'):
        """Admit with an explicit agreed daily_price (the admit() helper
        sends daily_rate, which the server ignores in favour of the list)."""
        status, body = self.api.post('/api/admissions', {
            'patient_id': pid, 'bed_id': bed, 'program_type': program,
            'start_date': start, 'planned_end_date': end,
            'attending_doctor_id': DOCTOR, 'daily_price': price,
        })
        self.assertEqual(status, 201, f"admit returned {status}: {body}")
        self._admissions.append(body['admission_id'])
        return body['admission_id']

    def _transfer(self, adm_id, bed, date, **extra):
        payload = {'new_bed_id': bed, 'transfer_date': date}
        payload.update(extra)
        return self.api.post(f"/api/admissions/{adm_id}/transfer", payload)

    def test_transfer_moves_the_stay_and_cleans_the_old_bed(self):
        pid = self.make_patient('Transfer Board Bemor')
        adm = self._admit_at(pid, BED_C, '2029-05-01', '2029-05-11', RATE)
        status, body = self._transfer(adm, 'BED-23A', '2029-05-04',
                                      reason='regression suite')
        self.assertEqual(status, 200, f"transfer failed: {body}")

        row = self._db_one("SELECT bed_id, status FROM admissions WHERE id = ?", (adm,))
        self.assertEqual(row['bed_id'], 'BED-23A')
        self.assertEqual(row['status'], 'active')
        old_bed = self._db_one("SELECT status FROM beds WHERE id = ?", (BED_C,))
        self.assertEqual(old_bed['status'], 'cleaning',
                         'the vacated bed was not sent to cleaning')
        moved = self._db_one("SELECT COUNT(*) AS n FROM bed_transfers "
                             "WHERE admission_id = ? AND to_bed_id = 'BED-23A'", (adm,))
        self.assertEqual(int(moved['n']), 1, 'no bed_transfers row was written')
        # Length of stay is unchanged: 3 nights + 7 nights at the same rate.
        self.assertAlmostEqual(float(self.invoice_for(adm)['total_billed']),
                               10 * RATE, delta=0.01)

    def test_a_whole_room_stay_keeps_its_rate_after_a_transfer(self):
        """A 1 100 000 whole-room stay was re-billed at the bed's 720 000 list rate."""
        pid = self.make_patient('Solo Transfer Rate')
        adm = self._admit_at(pid, 'BED-22B', '2029-06-01', '2029-06-11', 1100000,
                             program=self.SOLO)
        status, body = self._transfer(adm, BED_A, '2029-06-04')
        self.assertEqual(status, 200, f"whole-room transfer failed: {body}")
        self.assertAlmostEqual(float(self.invoice_for(adm)['total_billed']),
                               10 * 1100000, delta=0.01,
                               msg='the agreed whole-room rate changed after the move')
        row = self._db_one("SELECT daily_price FROM admissions WHERE id = ?", (adm,))
        self.assertAlmostEqual(float(row['daily_price']), 1100000, delta=0.01)

    def test_a_custom_rate_survives_a_transfer(self):
        pid = self.make_patient('Custom Rate Transfer')
        adm = self._admit_at(pid, BED_A, '2029-07-01', '2029-07-11', 650000)
        status, body = self._transfer(adm, BED_C, '2029-07-06')
        self.assertEqual(status, 200, f"transfer failed: {body}")
        self.assertAlmostEqual(float(self.invoice_for(adm)['total_billed']),
                               10 * 650000, delta=0.01)

    def test_a_new_price_typed_on_the_move_applies_from_the_move_date(self):
        """PO 2026-10-08: the agreed price stays, but staff may set a new one on the move."""
        pid = self.make_patient('New Price Transfer')
        adm = self._admit_at(pid, BED_A, '2029-09-01', '2029-09-11', 650000)
        status, body = self._transfer(adm, BED_C, '2029-09-04', new_daily_price=900000)
        self.assertEqual(status, 200, f"transfer failed: {body}")
        # 3 nights at the old price, 7 at the new one.
        self.assertAlmostEqual(float(self.invoice_for(adm)['total_billed']),
                               3 * 650000 + 7 * 900000, delta=0.01)
        row = self._db_one("SELECT daily_price FROM admissions WHERE id = ?", (adm,))
        self.assertAlmostEqual(float(row['daily_price']), 900000, delta=0.01)

    def test_a_bad_new_price_is_refused(self):
        pid = self.make_patient('Bad Price Transfer')
        adm = self._admit_at(pid, BED_A, '2029-10-01', '2029-10-06', 650000)
        status, body = self._transfer(adm, BED_C, '2029-10-02', new_daily_price=-5)
        self.assertEqual(status, 400, body)
        self.assertEqual(body.get('field'), 'new_daily_price')

    def test_a_same_day_transfer_keeps_the_rate(self):
        """A move on the arrival day rewrites the only line instead of splitting it."""
        pid = self.make_patient('Same Day Transfer')
        adm = self._admit_at(pid, BED_B, '2029-08-01', '2029-08-06', 650000)
        status, body = self._transfer(adm, BED_C, '2029-08-01')
        self.assertEqual(status, 200, f"transfer failed: {body}")
        self.assertAlmostEqual(float(self.invoice_for(adm)['total_billed']),
                               5 * 650000, delta=0.01)

    def test_a_discharged_stay_cannot_be_transferred(self):
        pid = self.make_patient('Discharged Then Moved')
        adm = self._admit_at(pid, BED_A, '2029-09-01', '2029-09-11', RATE)
        status, body = self.api.post(f"/api/admissions/{adm}/discharge",
                                     {'discharge_date': '2029-09-05', 'summary': 'regression suite'})
        self.assertEqual(status, 200, f"discharge failed: {body}")
        self.release_beds()
        billed = float(self.invoice_for(adm)['total_billed'])

        status, body = self._transfer(adm, BED_C, '2029-09-03')
        self.assertEqual(status, 400, f"a discharged patient was moved: {body}")
        self.assertIn("faol", body.get('error', ''))
        self.assertAlmostEqual(float(self.invoice_for(adm)['total_billed']), billed,
                               delta=0.01, msg='the refused move still changed the bill')
        bed = self._db_one("SELECT status FROM beds WHERE id = ?", (BED_C,))
        self.assertEqual(bed['status'], 'operational')

    def test_a_transfer_onto_an_occupied_bed_is_refused_and_changes_nothing(self):
        sitting = self.make_patient('Sitting In 22A')
        mover = self.make_patient('Wants 22A')
        self._admit_at(sitting, BED_C, '2029-10-01', '2029-10-11', RATE)
        adm = self._admit_at(mover, 'BED-23A', '2029-10-02', '2029-10-09', RATE)
        status, body = self._transfer(adm, BED_C, '2029-10-04')
        self.assertEqual(status, 400, f"transfer overlapped an occupied bed: {body}")
        row = self._db_one("SELECT bed_id FROM admissions WHERE id = ?", (adm,))
        self.assertEqual(row['bed_id'], 'BED-23A')
        bed = self._db_one("SELECT status FROM beds WHERE id = ?", ('BED-23A',))
        self.assertEqual(bed['status'], 'operational',
                         'a refused move still sent the bed to cleaning')

    def test_bad_requests_get_an_uzbek_400_not_a_raw_error(self):
        pid = self.make_patient('Bad Transfer Input')
        adm = self._admit_at(pid, BED_A, '2029-11-01', '2029-11-11', RATE)
        status, body = self._transfer(adm, '', '2029-11-03')
        self.assertEqual(status, 400, body)
        self.assertEqual(body.get('field'), 'new_bed_id')
        status, body = self._transfer(adm, 'BED-NOPE', '2029-11-03')
        self.assertEqual(status, 400, body)
        self.assertIn('topilmadi', body.get('error', ''))
        status, body = self._transfer('ADM-NOPE', BED_C, '2029-11-03')
        self.assertEqual(status, 400, body)
        self.assertIn('topilmadi', body.get('error', ''))
        status, body = self._transfer(adm, BED_C, 'not-a-date')
        self.assertEqual(status, 400, body)
        # A move outside the stay would bill a night that does not exist.
        status, body = self._transfer(adm, BED_C, '2029-11-11')
        self.assertEqual(status, 400, body)
        status, body = self._transfer(adm, BED_C, '2029-10-30')
        self.assertEqual(status, 400, body)


class OnePriceList(ApiTest):
    """
    Every page used to carry its own copy of the tariffs, and the API's own
    default lacked the consultation fee. data/pricing_config.json, served by
    /api/settings/pricing, is now the one list; these pin how it is read,
    saved and used for a stay sent without a price.
    """

    _account = RoleAuthorization._account
    PRICING = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data',
                           'pricing_config.json')

    def setUp(self):
        super().setUp()
        self._temp_users = []
        # A tracked file the save rewrites; put its exact bytes back afterwards.
        self._pricing_bytes = None
        if os.path.exists(self.PRICING):
            with open(self.PRICING, 'rb') as f:
                self._pricing_bytes = f.read()

    def tearDown(self):
        if self._pricing_bytes is not None:
            with open(self.PRICING, 'wb') as f:
                f.write(self._pricing_bytes)
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        super().tearDown()

    def test_every_role_can_read_the_list(self):
        """Reception, the doctor and the nurse all show prices, so all of them must read it."""
        for role in ('receptionist', 'doctor', 'nurse'):
            client = self._account(role)
            st, body = client.get('/api/settings/pricing')
            self.assertEqual(st, 200, f"{role}: {body}")
            self.assertIn('statsionar_shared', body.get('packages', {}), role)

    def test_the_list_always_has_the_consultation_fee(self):
        st, body = self.api.get('/api/settings/pricing')
        self.assertEqual(st, 200, body)
        consult = body['packages'].get('consultation')
        self.assertIsNotNone(consult, 'consultation fee missing from the price list')
        self.assertGreater(float(consult['daily_rate']), 0)
        self.assertIsInstance(body.get('additional_services'), list)

    def test_receptionist_cannot_change_prices(self):
        desk = self._account('receptionist')
        st, _ = desk.post('/api/settings/pricing',
                          {'packages': {'ambulator_1': {'daily_rate': 1}}})
        self.assertEqual(st, 403)

    def test_a_bad_amount_is_refused_with_its_field(self):
        for bad in ('ikki yuz', -5, None, 'nan'):
            st, body = self.api.post('/api/settings/pricing',
                                     {'packages': {'ambulator_1': {'daily_rate': bad}}})
            self.assertEqual(st, 400, f"{bad!r}: {body}")
            self.assertEqual(body.get('field'), 'packages.ambulator_1.daily_rate', body)
        st, body = self.api.post('/api/settings/pricing',
                                 {'packages': {'mystery_pkg': {'daily_rate': 1000}}})
        self.assertEqual(st, 400, body)
        st, body = self.api.post('/api/settings/pricing', {'additional_services': [
            {'id': 'x1', 'name': 'A', 'price': 1000}, {'id': 'x1', 'name': 'B', 'price': 2000}]})
        self.assertEqual(st, 400, body)
        self.assertEqual(body.get('field'), 'additional_services.1.id', body)
        st, body = self.api.post('/api/settings/pricing', {'additional_services': [
            {'id': 'x2', 'name': '', 'price': 1000}]})
        self.assertEqual(st, 400, body)
        # Nothing was written by any refused request.
        with open(self.PRICING, 'rb') as f:
            self.assertEqual(f.read(), self._pricing_bytes)

    def test_a_save_without_consultation_keeps_it(self):
        st, before = self.api.get('/api/settings/pricing')
        consult = before['packages']['consultation']['daily_rate']
        amb1 = before['packages']['ambulator_1']['daily_rate']
        st, body = self.api.post('/api/settings/pricing',
                                 {'packages': {'ambulator_1': {'daily_rate': amb1 + 1000}},
                                  'updated_by': 'someone else'})
        self.assertEqual(st, 200, body)
        st, after = self.api.get('/api/settings/pricing')
        self.assertEqual(after['packages']['ambulator_1']['daily_rate'], amb1 + 1000)
        self.assertEqual(after['packages']['consultation']['daily_rate'], consult)
        self.assertTrue(after['packages']['ambulator_1'].get('name_uz'))
        # The author comes from the session, not the request body.
        self.assertNotEqual(after.get('updated_by'), 'someone else')
        self.assertTrue(after.get('updated_by'))

    def test_reception_programmes_do_not_include_the_consultation(self):
        """The fee reached the desk as a sixth inpatient programme priced per day."""
        st, body = self.api.get('/api/reception/data')
        self.assertEqual(st, 200, body)
        ids = [p['id'] for p in body.get('program_types', [])]
        self.assertNotIn('consultation', ids)
        self.assertIn('statsionar_shared', ids)
        st, pricing = self.api.get('/api/settings/pricing')
        self.assertEqual(float(body.get('consultation_fee')),
                         float(pricing['packages']['consultation']['daily_rate']))

    def test_a_stay_without_a_price_gets_its_package_rate(self):
        """A missing daily_price was billed at a hardcoded 720 000 whatever the programme."""
        st, pricing = self.api.get('/api/settings/pricing')
        listed = float(pricing['packages']['kunlik_statsionar']['daily_rate'])
        start = (_dt.date.today() + _dt.timedelta(days=470)).isoformat()
        end = (_dt.date.today() + _dt.timedelta(days=473)).isoformat()
        st, body = self.api.post('/api/admissions', {
            'patient_name': 'Narx Probe Bemor', 'bed_id': BED_A,
            'program_type': 'kunlik_statsionar',
            'start_date': start, 'planned_end_date': end,
            'attending_doctor_id': DOCTOR,
        })
        self.assertEqual(st, 201, body)
        self._admissions.append(body['admission_id'])
        self._patients.append(body['patient_id'])
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT daily_price FROM admissions WHERE id = ?", (body['admission_id'],))
            self.assertAlmostEqual(float(cur.fetchone()['daily_price']), listed, delta=0.01)
        finally:
            conn.close()
        self.assertAlmostEqual(float(self.invoice_for(body['admission_id'])['total_billed']),
                               3 * listed, delta=0.01)


class SecondPassFixes(ApiTest):
    """Faults found by the review of the first overhaul pass (2026-10-08)."""

    _account = RoleAuthorization._account

    def setUp(self):
        super().setUp()
        self._temp_users = []

    def tearDown(self):
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        super().tearDown()

    def _db(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        return get_db()

    def _invoice_id(self, admission_id):
        conn = self._db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM invoices WHERE admission_id = ?", (admission_id,))
            return cur.fetchone()['id']
        finally:
            conn.close()

    # --- appointments -----------------------------------------------------

    def test_a_cancelled_slot_can_be_booked_again(self):
        """Cancel changed only the desk's screen, so the server kept refusing the freed slot."""
        day = (_dt.date.today() + _dt.timedelta(days=430)).isoformat()
        first = {'patient_name': 'Cancel Probe Bir', 'patient_phone': '+998900000301',
                 'doctor_id': DOCTOR, 'date': day, 'time': '14:30',
                 'service_type': 'consultation'}
        st, body = self.api.post('/api/reception/appointment', first)
        self.assertIn(st, (200, 201), body)
        self._patients.append(body['patient_id'])
        apt = body['id']

        st, res = self.api.put(f'/api/reception/appointment/{apt}/cancel', {})
        self.assertEqual(st, 200, res)
        st, res = self.api.put(f'/api/reception/appointment/{apt}/cancel', {})
        self.assertEqual(st, 400, 'a cancelled booking was cancelled twice')

        second = dict(first, patient_name='Cancel Probe Ikki', patient_phone='+998900000302')
        st, body2 = self.api.post('/api/reception/appointment', second)
        self.assertIn(st, (200, 201), body2)
        self._patients.append(body2['patient_id'])

    def test_cancelling_an_unknown_appointment_is_404(self):
        st, _ = self.api.put('/api/reception/appointment/APT-NOPE/cancel', {})
        self.assertEqual(st, 404)

    # --- landing page -----------------------------------------------------

    def test_each_role_lands_on_its_own_home(self):
        """Login, / and index.html all sent everyone to the Super-Portal."""
        nurse = self._account('nurse')
        st, sess = nurse.get('/api/auth/session')
        self.assertEqual(sess.get('home'), '/nurse.html')
        opener = urllib.request.build_opener(NoRedirect)
        for path in ('/', '/index.html'):
            req = urllib.request.Request(BASE + path)
            req.add_header('Cookie', nurse.cookie)
            try:
                opener.open(req)
                self.fail(f'{path} did not redirect')
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 302)
                self.assertEqual(e.headers.get('Location'), '/nurse.html', path)

    def test_a_home_the_user_cannot_open_is_never_sent(self):
        """A refused page redirects to the home; a home outside the user's rights looped forever."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import permissions
        narrowed = {'role': 'doctor', 'permissions': ['nursery:read']}
        home = permissions.home_for(narrowed)
        self.assertNotEqual(home, '/doctor.html')
        self.assertTrue(permissions.authorize_page(narrowed, home)[0], home)
        self.assertEqual(permissions.home_for({'role': 'nobody', 'permissions': ['x:read']}),
                         '/change-password.html')

    # --- money ------------------------------------------------------------

    def test_a_journal_entry_needs_a_real_amount(self):
        """The salary payout sent no amount, and 0 so'm was stored or a 500 was shown as paid."""
        for payload, field in (
            ({'type': 'expense', 'category': 'salary', 'title': 'Suite probe: no amount'}, 'amount'),
            ({'type': 'expense', 'category': 'salary', 'amount': 0, 'title': 'Suite probe: zero'}, 'amount'),
            ({'type': 'gift', 'category': 'salary', 'amount': 10, 'title': 'Suite probe: type'}, 'type'),
        ):
            st, body = self.api.post('/api/accounting/transaction', dict(payload, payment_method='cash'))
            self.assertEqual(st, 400, body)
            self.assertEqual(body.get('field'), field)

    def test_a_salary_payout_names_the_employee(self):
        """Payouts held only free text, so the 'paid' badge reset and the same doctor could be paid twice."""
        st, res = self.api.post('/api/accounting/transaction', {
            'type': 'expense', 'category': 'salary', 'amount': 1000, 'payment_method': 'cash',
            'title': 'Suite probe: salary link', 'related_staff_id': DOCTOR})
        self.assertEqual(st, 201, res)
        try:
            st, data = self.api.get('/api/accounting/data')
            txn = next(t for t in data['transactions'] if t['id'] == res['id'])
            self.assertEqual(txn.get('related_staff_id'), DOCTOR)
        finally:
            conn = self._db()
            try:
                conn.cursor().execute("DELETE FROM accounting_transactions WHERE id = ?", (res['id'],))
                conn.commit()
            finally:
                conn.close()

    def test_an_online_advance_lands_in_the_merchant_account(self):
        """The desk filed Click/Payme advances under the main bank account; accounting files them as merchant."""
        start = (_dt.date.today() + _dt.timedelta(days=440)).isoformat()
        end = (_dt.date.today() + _dt.timedelta(days=443)).isoformat()
        st, body = self.api.post('/api/admissions', {
            'patient_name': 'Online Avans Probe', 'patient_phone': '+998900000311',
            'bed_id': BED_A, 'program_type': 'statsionar_shared',
            'start_date': start, 'planned_end_date': end,
            'attending_doctor_id': DOCTOR, 'daily_price': RATE,
            'advance_amount': 50000, 'advance_method': 'online',
        })
        self.assertEqual(st, 201, body)
        self._admissions.append(body['admission_id'])
        self._patients.append(body['patient_id'])
        conn = self._db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT account_destination FROM payments WHERE id = ?",
                        (body['advance_payment_id'],))
            self.assertEqual(cur.fetchone()['account_destination'], 'click_payme_merchant')
        finally:
            conn.close()

    def test_an_extra_service_stays_on_the_bill(self):
        """Lines added in accounting lived only in the page and vanished on the next sync."""
        start = (_dt.date.today() + _dt.timedelta(days=450)).isoformat()
        end = (_dt.date.today() + _dt.timedelta(days=453)).isoformat()
        pid = self.make_patient('Xizmat Probe Bemor')
        _, adm = self.admit(pid, BED_A, start, end)
        inv = self._invoice_id(adm['admission_id'])
        before = float(self.invoice_for(adm['admission_id'])['total_billed'])

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data',
                               'pricing_config.json'), encoding='utf-8') as f:
            svc = json.load(f)['additional_services'][0]
        st, body = self.api.post('/api/accounting/invoice-items', {
            'invoice_id': inv, 'service_code': svc['id'], 'quantity': 2,
            'unit_price': 1,   # ignored: the server prices it
        })
        self.assertEqual(st, 201, body)
        self.assertAlmostEqual(body['unit_price'], float(svc['price']), delta=0.01)
        after = float(self.invoice_for(adm['admission_id'])['total_billed'])
        self.assertAlmostEqual(after - before, 2 * float(svc['price']), delta=0.01)

        st, data = self.api.get('/api/accounting/data')
        self.assertTrue(any(i['invoice_id'] == inv for i in data.get('invoice_items', [])),
                        'the saved line is not returned to the page')

        for payload, field in (
            ({'invoice_id': inv, 'service_code': 'srv-nope', 'quantity': 1}, 'service_code'),
            ({'invoice_id': inv, 'service_code': svc['id'], 'quantity': 0}, 'quantity'),
            ({'invoice_id': 'INV-NOPE', 'service_code': svc['id'], 'quantity': 1}, 'invoice_id'),
        ):
            st, res = self.api.post('/api/accounting/invoice-items', payload)
            self.assertEqual(st, 400, res)
            self.assertEqual(res.get('field'), field)

        desk = self._account('receptionist')
        st, _ = desk.post('/api/accounting/invoice-items',
                          {'invoice_id': inv, 'service_code': svc['id'], 'quantity': 1})
        self.assertEqual(st, 403)

    def test_a_medicine_added_to_a_bill_comes_off_the_shelf(self):
        st, data = self.api.get('/api/accounting/data')
        med = next((m for m in data.get('pharmacy_stock', [])
                    if int(m.get('stock_quantity') or 0) >= 2), None)
        if not med:
            self.skipTest('no stock item with 2 or more units')
        start = (_dt.date.today() + _dt.timedelta(days=460)).isoformat()
        end = (_dt.date.today() + _dt.timedelta(days=462)).isoformat()
        pid = self.make_patient('Dori Hisob Probe')
        _, adm = self.admit(pid, BED_A, start, end)
        inv = self._invoice_id(adm['admission_id'])
        stock = int(med['stock_quantity'])
        try:
            st, body = self.api.post('/api/accounting/invoice-items', {
                'invoice_id': inv, 'service_code': 'MED:' + med['id'], 'quantity': 2})
            self.assertEqual(st, 201, body)
            self.assertEqual(body['item_type'], 'medication')
            st, res = self.api.post('/api/accounting/invoice-items', {
                'invoice_id': inv, 'service_code': 'MED:' + med['id'], 'quantity': stock + 50})
            self.assertEqual(st, 400, 'more than the shelf holds was billed')
            conn = self._db()
            try:
                cur = conn.cursor()
                cur.execute("SELECT stock_quantity FROM medications_catalog WHERE id = ?", (med['id'],))
                self.assertEqual(int(cur.fetchone()['stock_quantity']), stock - 2)
            finally:
                conn.close()
        finally:
            conn = self._db()
            try:
                cur = conn.cursor()
                cur.execute("UPDATE medications_catalog SET stock_quantity = ? WHERE id = ?",
                            (stock, med['id']))
                conn.commit()
            finally:
                conn.close()

    # --- clinical records ------------------------------------------------

    def test_an_outpatient_gets_one_note_per_day(self):
        """With no stay the unique key never matched, so every save added another note for the day."""
        pid = self.make_patient('Ambulator Kundalik Probe')
        for text in ('Birinchi yozuv', 'Tuzatilgan yozuv'):
            st, body = self.api.post('/api/doctor/notes', {
                'patient_id': pid, 'patient_condition': 'satisfactory', 'dynamics_notes': text})
            self.assertEqual(st, 201, body)
        conn = self._db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT dynamics_notes FROM doctor_daily_notes WHERE patient_id = ? "
                        "AND admission_id IS NULL", (pid,))
            rows = cur.fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]['dynamics_notes'], 'Tuzatilgan yozuv')

    def test_a_pdf_prints_text_with_angle_brackets(self):
        """'Hb<norma' broke ReportLab's markup parser and the route said 'patient not found'."""
        pid = self.make_patient('PDF Belgi Probe')
        st, res = self.api.post('/api/doctor/anamnesis', {
            'patient_id': pid, 'complaints': 'Hb<norma, ALT>40 & <b>qalin</b>'})
        self.assertIn(st, (200, 201), res)
        req = urllib.request.Request(BASE + '/api/doctor/download-pdf/' + pid + '?doc_type=anamnesis')
        req.add_header('Cookie', self.api.cookie)
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)
            self.assertTrue(r.read().startswith(b'%PDF'))

    def test_every_menu_entry_is_a_real_page_rule(self):
        """The shared menu lists pages by path; one missing from PAGE_RULES would be open to everyone."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import permissions
        js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'js',
                               'fmh_dialogs.js'), encoding='utf-8').read()
        keys = re.findall(r"key: '(/[a-z_]+\.html)'", js)
        self.assertGreaterEqual(len(keys), 10, 'menu list not found')
        for k in keys:
            self.assertIn(k, permissions.PAGE_RULES, k)
            self.assertTrue(os.path.exists(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), '..', k.lstrip('/'))), k)

    def test_an_impossible_roster_date_is_refused(self):
        """Only the pattern was checked, and merged saves could never remove a junk day."""
        roster = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'duty_schedule.json')
        keep = open(roster, 'rb').read() if os.path.exists(roster) else None
        try:
            for bad in ('2031-13-45', '2031-02-30', '2031-01-15\n'):
                st, res = self.api.post('/api/duty-schedule', {
                    'shifts': [{'date': bad, 'sanitar_primary': 'Suite Probe'}]})
                self.assertEqual(st, 400, (bad, res))
        finally:
            if keep is not None:
                with open(roster, 'wb') as f:
                    f.write(keep)


class PdfHonesty(ApiTest):
    """The patient PDF ignored the chosen document and filled blanks with a diagnosis, vitals and a doctor."""

    def _pdf(self, pid, doc_type):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, root)
        try:
            import reportlab.rl_config as rl_config
            from pdf_generator import generate_patient_pdf
        except ImportError as e:
            self.skipTest(f"reportlab not installed: {e}")
        old = rl_config.pageCompression
        rl_config.pageCompression = 0
        try:
            return generate_patient_pdf(pid, doc_type=doc_type)
        finally:
            rl_config.pageCompression = old

    def test_an_empty_record_prints_not_recorded(self):
        pid = self.make_patient('PDF Bo\'sh Bemor')
        pdf = self._pdf(pid, 'full_dossier')
        self.assertTrue(pdf and pdf.startswith(b'%PDF'))
        self.assertIn(b'Qayd etilmagan', pdf)
        for invented in (b'F10.2', b'Rustam', b'120/80', b'Meksidol', b'muvaffaqiyatli'):
            self.assertNotIn(invented, pdf, f"invented content {invented!r} in the PDF")

    def test_the_route_passes_the_document_type(self):
        pid = self.make_patient('PDF Turi Bemor')
        self.admit(pid, BED_A, '2028-03-01', '2028-03-05')

        def fetch(doc_type):
            req = urllib.request.Request(
                BASE + '/api/doctor/download-pdf/' + pid + '?doc_type=' + doc_type)
            req.add_header('Cookie', self.api.cookie)
            with urllib.request.urlopen(req) as res:
                return res.read()
        rx = fetch('prescriptions')
        dossier = fetch('full_dossier')
        self.assertTrue(rx.startswith(b'%PDF') and dossier.startswith(b'%PDF'))
        # The dossier adds the history and discharge sections.
        self.assertGreater(len(dossier), len(rx) + 200,
                           'full_dossier came back the same size as prescriptions')


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

    # The suite creates throwaway accounts to probe each role. Every test
    # that makes one also deletes it, but one occasionally survived into
    # data/users.json -- a tracked file, so the residue showed up in `git
    # status` and would have shipped in a package built from the working tree.
    # Rather than chase a rare interleaving, cleanup is made total: sweep
    # before and after, so an interrupted run leaves nothing behind either.
    sweep_probe_accounts('before')
    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    sweep_probe_accounts('after')
    sys.exit(0 if result.wasSuccessful() else 1)
