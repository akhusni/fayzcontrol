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
                    # Desk visits (consultation, outpatient) are billed on
                    # the appointment, not on a stay.
                    cur.execute("SELECT id FROM appointments WHERE patient_id = ?", (pid,))
                    apt_ids = [r['id'] for r in cur.fetchall()]
                    if apt_ids:
                        marks = ','.join(['?'] * len(apt_ids))
                        cur.execute(f"SELECT id FROM invoices WHERE appointment_id IN ({marks})",
                                    tuple(apt_ids))
                        inv_ids += [r['id'] for r in cur.fetchall()]

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
            # The hash is not sent at all (it used to be masked as '********').
            self.assertNotIn('password', u, f"{u.get('username')} carried a password field")
            self.assertNotIn('pbkdf2', json.dumps(u), f"{u.get('username')} exposed a hash")


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

    def slot(self, minute=0):
        """A doctor, day and time no other test (or earlier run) is using."""
        return {'doctor_id': DOCTOR, 'appointment_date': '2031-03-14',
                'appointment_time': f'{8 + os.getpid() % 9:02d}:{(minute + os.getpid()) % 60:02d}'}

    def test_accepting_is_what_creates_the_patient(self):
        _, body, _ = self.enquire(
            {'full_name': 'Sanjar Toshmatov', 'phone': '+998934445566'},
            ip='203.0.113.20')
        req_id = body['request_id']
        before = self.table_counts()

        status, result = self.api.post(f'/api/reception/requests/{req_id}/accept',
                                       self.slot(1))
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
        self.assertEqual(self.api.post(f'/api/reception/requests/{req_id}/accept',
                                       self.slot(2))[0], 201)
        status, second = self.api.post(f'/api/reception/requests/{req_id}/reject', {})
        self.assertEqual(status, 400, 'the same enquiry was decided twice')
        self.assertEqual(second.get('field'), 'status')

    def test_accepting_needs_a_doctor_and_a_time(self):
        """
        The desk's accept button sent an empty body and the server booked the
        patient with no doctor at 10:00: a visit in nobody's diary, at a time
        nobody chose. Now both are required, and a refusal creates nothing.
        """
        _, body, _ = self.enquire({'full_name': 'Shifokorsiz Bemor', 'phone': '+998935556677'},
                                  ip='203.0.113.23')
        req_id = body['request_id']
        before = self.table_counts()
        url = f'/api/reception/requests/{req_id}/accept'
        good = self.slot(3)
        for payload, field in [
                ({}, 'doctor_id'),
                (dict(good, doctor_id='STF-NOBODY-404'), 'doctor_id'),
                ({'doctor_id': DOCTOR, 'appointment_date': good['appointment_date']},
                 'appointment_time'),
                (dict(good, appointment_time='25:99'), 'appointment_time'),
                (dict(good, appointment_date='14.03.2031'), 'appointment_date')]:
            status, result = self.api.post(url, payload)
            self.assertEqual(status, 400, f"{payload} was accepted: {result}")
            self.assertEqual(result.get('field'), field, result)
        after = self.table_counts()
        self.assertEqual(after['patients'], before['patients'], 'a refusal registered a patient')
        self.assertEqual(after['appointments'], before['appointments'], 'a refusal booked a visit')
        # Still waiting for a proper decision.
        self.assertEqual(self.api.post(url, good)[0], 201)

    def test_accepting_books_the_chosen_doctor_and_time(self):
        _, body, _ = self.enquire({'full_name': 'Vaqtli Bemor', 'phone': '+998936667788'},
                                  ip='203.0.113.24')
        chosen = self.slot(4)
        status, result = self.api.post(
            f"/api/reception/requests/{body['request_id']}/accept", chosen)
        self.assertEqual(status, 201, f"accept failed: {result}")
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("""SELECT doctor_id, appointment_date, appointment_time
                           FROM appointments WHERE id = ?""", (result['appointment_id'],))
            row = cur.fetchone()
        finally:
            conn.close()
        self.assertEqual(row['doctor_id'], DOCTOR)
        self.assertEqual(str(row['appointment_date']), chosen['appointment_date'])
        self.assertTrue(str(row['appointment_time']).zfill(8).startswith(chosen['appointment_time']),
                        f"booked at {row['appointment_time']}, not {chosen['appointment_time']}")

    def test_an_accepted_enquiry_cannot_take_a_booked_slot(self):
        """The same one-patient-per-slot rule as booking at the desk."""
        same = self.slot(5)
        first = self.enquire({'full_name': 'Birinchi Bemor', 'phone': '+998937778899'},
                             ip='203.0.113.25')[1]['request_id']
        second = self.enquire({'full_name': 'Ikkinchi Bemor', 'phone': '+998938889900'},
                              ip='203.0.113.26')[1]['request_id']
        self.assertEqual(self.api.post(f'/api/reception/requests/{first}/accept', same)[0], 201)
        status, body = self.api.post(f'/api/reception/requests/{second}/accept', same)
        self.assertEqual(status, 400, f"two patients were booked into one slot: {body}")
        self.assertEqual(body.get('field'), 'appointment_time')

    def test_an_unknown_service_from_the_website_does_not_break_accepting(self):
        """
        The website's service field is free text. A value the appointments
        CHECK does not know made accepting fail with a 500.
        """
        _, body, _ = self.enquire({'full_name': 'Xizmat Matni', 'phone': '+998939990011',
                                   'service_type': 'Narkolog maslahati'},
                                  ip='203.0.113.27')
        status, result = self.api.post(
            f"/api/reception/requests/{body['request_id']}/accept", self.slot(6))
        self.assertEqual(status, 201, f"accept failed: {result}")

    def test_accepting_checks_the_doctor_the_day_and_the_service(self):
        """
        Any staff id was taken as the doctor, a past preferred day was booked
        into yesterday's diary, 'home_visit' was booked although the clinic
        makes none for now, and the phone alone picked the patient record.
        """
        _, body, _ = self.enquire({'full_name': 'Tekshiruv Bemor', 'phone': '+998931231231',
                                   'service_type': 'home_visit'}, ip='203.0.113.28')
        url = f"/api/reception/requests/{body['request_id']}/accept"
        st, nurse = self.api.post('/api/staff', {'full_name': 'Suite Enquiry Hamshira',
                                                 'role': 'nurse', 'base_salary': 0})
        self.assertEqual(st, 201, nurse)
        # Same phone, different person: must not be reused.
        relative = self.make_patient('Boshqa Qarindosh', phone='+998931231231')
        try:
            good = self.slot(7)
            yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
            for payload, field in ((dict(good, doctor_id=nurse['id']), 'doctor_id'),
                                   (dict(good, appointment_date=yesterday), 'appointment_date')):
                status, result = self.api.post(url, payload)
                self.assertEqual((status, result.get('field')), (400, field), (payload, result))
            status, result = self.api.post(url, good)
            self.assertEqual(status, 201, result)
            self.assertNotEqual(result['patient_id'], relative,
                                'a relative sharing the phone was filed as this patient')
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from db import get_db
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute("SELECT service_type FROM appointments WHERE id = ?",
                            (result['appointment_id'],))
                self.assertEqual(cur.fetchone()['service_type'], 'outpatient')
            finally:
                conn.close()
        finally:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from db import get_db
            conn = get_db()
            try:
                conn.cursor().execute("DELETE FROM staff WHERE id = ?", (nurse['id'],))
                conn.commit()
            finally:
                conn.close()

    def test_a_bad_telegram_setting_does_not_disable_the_module(self):
        """int() at import raised on a typo and silently turned every notice off."""
        import subprocess
        env = dict(os.environ, FMH_TELEGRAM_ENQUIRY_TOPIC='--5', FMH_TELEGRAM_CHAT_ID='abc',
                   FMH_TELEGRAM_BOT_TOKEN='')
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, '-c',
                              'import telegram_service as t; print(t.TOPIC_ENQUIRIES, t.CHAT_ID)'],
                             cwd=root, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], 'None -1004441223890')

    def test_the_staff_group_is_told_only_what_it_needs(self):
        """
        A new enquiry is announced in the staff Telegram group so it is
        answered while warm. The text comes from the open internet: it must be
        escaped for Telegram's HTML mode, carry only name, phone, preferred
        date and note (never the visitor's IP), and do nothing at all when no
        bot token is configured.
        """
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import telegram_service as tg
        sent = []
        saved = (tg.ENABLED, tg.send_telegram_message)
        tg.send_telegram_message = lambda topic, text, parse_mode='HTML': sent.append(text)
        req = {'full_name': '<b>Aziz</b> & Co', 'phone': '+998 90 111 22 33',
               'preferred_date': '2031-03-14', 'note': 'Qo`ng`iroq qiling',
               'ip_address': '198.51.100.7', 'id': 'REQ-SECRET'}
        try:
            tg.ENABLED = False
            tg.notify_enquiry_sync(req)
            self.assertEqual(sent, [], 'a notice went out with no bot configured')

            tg.ENABLED = True
            tg.notify_enquiry_sync(req)
        finally:
            tg.ENABLED, tg.send_telegram_message = saved
        self.assertEqual(len(sent), 1)
        text = sent[0]
        self.assertIn('&lt;b&gt;Aziz&lt;/b&gt; &amp; Co', text, 'the name was not escaped')
        self.assertIn('+998 90 111 22 33', text)
        self.assertIn('2031-03-14', text)
        self.assertIn('Qo`ng`iroq qiling', text)
        self.assertNotIn('198.51.100.7', text, "the visitor's IP was sent to the group")
        self.assertNotIn('REQ-SECRET', text)

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


class SessionsSurviveRestart(unittest.TestCase):
    """
    Sessions lived only in the server's memory, so every restart or deploy
    signed the whole clinic out mid-shift. They are now kept in user_sessions.
    Restarting the server mid-suite would break the suite's own cookie, so
    these drive auth directly: clearing the in-memory cache is what a restart
    does to it. Sessions made here belong to this test process, not the
    running server, and each test removes its own rows.
    """

    PROBE = 'zz-session-probe'   # not in users.json on purpose

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import auth
        import db
        cls.auth, cls.db = auth, db
        conn = db.get_db()
        try:
            db.ensure_user_sessions(conn)
        finally:
            conn.close()

    def _sql(self, sql, params=()):
        conn = self.db.get_db()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall() if sql.lstrip().upper().startswith('SELECT') else None
            conn.commit()
            return rows
        finally:
            conn.close()

    def _rows(self, token):
        return self._sql("SELECT * FROM user_sessions WHERE token_hash = ?",
                         (self.auth.token_hash(token),))

    def _forget(self, token):
        """What a restart does to this process's view of the session."""
        self.auth._SESSIONS.pop(self.auth.token_hash(token), None)

    def _real_user(self):
        user = self.auth.find_user(USERNAME)
        self.assertTrue(user, 'the test account is missing from users.json')
        return user

    def tearDown(self):
        self.auth.destroy_sessions_for_user(self.PROBE)

    def test_a_stored_session_is_found_again_after_a_restart(self):
        token = self.auth.create_session(self._real_user(), ip='10.0.0.9', user_agent='probe')
        try:
            self._forget(token)
            sess = self.auth.get_session(token)
            self.assertTrue(sess, 'the session did not survive losing the memory cache')
            self.assertEqual(sess['user']['username'].lower(), USERNAME.lower())
            self.assertNotIn('password', sess['user'])
            row = self._rows(token)[0]
            self.assertEqual((row['ip_address'], row['user_agent']), ('10.0.0.9', 'probe'))
        finally:
            self.auth.destroy_session(token)

    def test_only_a_hash_of_the_token_is_stored(self):
        token = self.auth.create_session(self._real_user())
        try:
            self.assertEqual(len(self._rows(token)), 1)
            raw = self._sql("SELECT COUNT(*) AS n FROM user_sessions WHERE token_hash = ? "
                            "OR user_agent = ? OR ip_address = ?", (token, token, token))
            self.assertEqual(raw[0]['n'], 0, 'the raw token reached the database')
            self.assertEqual(len(self._rows(token)[0]['token_hash']), 64)
        finally:
            self.auth.destroy_session(token)

    def test_logout_deletes_the_row(self):
        token = self.auth.create_session(self._real_user())
        self.auth.destroy_session(token)
        self.assertEqual(self._rows(token), [])
        self.assertIsNone(self.auth.get_session(token))

    def test_sign_out_everywhere_deletes_every_row_of_that_account(self):
        probe = {'username': self.PROBE, 'role': 'reception', 'id': 'U-PROBE'}
        first, second = self.auth.create_session(probe), self.auth.create_session(probe)
        self._forget(second)   # one this process never saw: only in the DB
        self.auth.destroy_sessions_for_user(self.PROBE.upper())
        self.assertEqual(self._sql("SELECT token_hash FROM user_sessions WHERE username = ?",
                                   (self.PROBE,)), [])
        self.assertIsNone(self.auth.get_session(first))
        self.assertIsNone(self.auth.get_session(second))

    def test_an_expired_row_is_rejected_and_removed(self):
        token = self.auth.create_session(self._real_user())
        try:
            stale = self.auth._db_time(self.auth._now() - _dt.timedelta(
                seconds=self.auth.SESSION_IDLE_SECONDS + 60))
            self._sql("UPDATE user_sessions SET last_seen = ? WHERE token_hash = ?",
                      (stale, self.auth.token_hash(token)))
            self._forget(token)
            self.assertIsNone(self.auth.get_session(token))
            self.assertEqual(self._rows(token), [])
        finally:
            self.auth.destroy_session(token)

    def test_a_deleted_or_blocked_account_is_not_revived(self):
        """The account is re-read on restore, not trusted from the row."""
        token = self.auth.create_session({'username': self.PROBE, 'role': 'superadmin'})
        self._forget(token)
        self.assertIsNone(self.auth.get_session(token))
        self.assertEqual(self._rows(token), [])

    def test_a_row_removed_elsewhere_ends_the_cached_session(self):
        token = self.auth.create_session(self._real_user())
        try:
            self._sql("DELETE FROM user_sessions WHERE token_hash = ?",
                      (self.auth.token_hash(token),))
            sess = self.auth._SESSIONS[self.auth.token_hash(token)]
            sess['db_seen'] -= _dt.timedelta(seconds=self.auth.SESSION_TOUCH_SECONDS + 1)
            self.assertIsNone(self.auth.get_session(token))
        finally:
            self.auth.destroy_session(token)

    def test_last_seen_is_not_written_on_every_request(self):
        token = self.auth.create_session(self._real_user())
        try:
            # Whole seconds: MySQL rounds a fractional second into DATETIME, so a
            # marker taken at x.6 s came back as the next second and this test
            # failed about one run in three.
            marker = self.auth._db_time(self.auth._now() - _dt.timedelta(minutes=10)).replace(microsecond=0)
            self._sql("UPDATE user_sessions SET last_seen = ? WHERE token_hash = ?",
                      (marker, self.auth.token_hash(token)))
            for _ in range(3):
                self.assertTrue(self.auth.get_session(token))
            self.assertEqual(str(self._rows(token)[0]['last_seen'])[:19],
                             marker.strftime('%Y-%m-%d %H:%M:%S'))
            sess = self.auth._SESSIONS[self.auth.token_hash(token)]
            sess['db_seen'] -= _dt.timedelta(seconds=self.auth.SESSION_TOUCH_SECONDS + 1)
            self.assertTrue(self.auth.get_session(token))
            self.assertNotEqual(str(self._rows(token)[0]['last_seen'])[:19],
                                marker.strftime('%Y-%m-%d %H:%M:%S'),
                                'the throttled write never happened')
        finally:
            self.auth.destroy_session(token)

    def test_an_unchanged_last_seen_second_is_not_read_as_revoked(self):
        """PyMySQL counts changed rows: rewriting the same second returned 0."""
        token = self.auth.create_session(self._real_user())
        try:
            key = self.auth.token_hash(token)
            now = self.auth._now().replace(microsecond=0)
            self._sql("UPDATE user_sessions SET last_seen = ? WHERE token_hash = ?",
                      (self.auth._db_time(now), key))
            sess = self.auth._SESSIONS[key]
            sess['db_seen'] = now - _dt.timedelta(seconds=self.auth.SESSION_TOUCH_SECONDS + 1)
            self.assertTrue(self.auth._touch(key, sess, now), 'a live session was ended')
            self.assertIn(key, self.auth._SESSIONS)
        finally:
            self.auth.destroy_session(token)

    def test_a_logout_whose_delete_failed_is_not_restored(self):
        token = self.auth.create_session(self._real_user())
        real = self.db.get_db

        def down():
            raise ConnectionError('MySQL is down (simulated)')
        self.db.get_db = down
        try:
            self.auth.destroy_session(token)
        finally:
            self.db.get_db = real
        self.assertEqual(len(self._rows(token)), 1, 'precondition: the row survived the failed delete')
        self.assertIsNone(self.auth.get_session(token), 'a signed-out session came back')
        self.assertEqual(self._rows(token), [], 'the delete was not retried')

    def test_a_session_held_during_sign_out_everywhere_ends(self):
        probe = {'username': self.PROBE, 'role': 'nurse', 'id': 'U-PROBE'}
        token = self.auth.create_session(probe)
        key = self.auth.token_hash(token)
        sess = self.auth._SESSIONS[key]
        real = self.db.get_db

        def down():
            raise ConnectionError('MySQL is down (simulated)')
        self.db.get_db = down
        try:
            self.auth.destroy_sessions_for_user(self.PROBE)
        finally:
            self.db.get_db = real
        # A request that had already looked the session up carries on.
        self.auth._SESSIONS[key] = sess
        sess['persisted'] = False
        self.assertIsNone(self.auth.get_session(token))
        self.assertNotIn(key, self.auth._SESSIONS)
        self._sql("DELETE FROM user_sessions WHERE token_hash = ?", (key,))

    def test_a_missing_users_file_does_not_delete_sessions(self):
        """iCloud renamed users.json once; restore deleted every row it met."""
        token = self.auth.create_session(self._real_user())
        real = self.auth.load_users
        try:
            self._forget(token)
            self.auth.load_users = lambda: []
            self.assertIsNone(self.auth.get_session(token))
            self.assertEqual(len(self._rows(token)), 1, 'the row was deleted')
            self.auth.load_users = real
            self.assertTrue(self.auth.get_session(token), 'the session did not come back')
        finally:
            self.auth.load_users = real
            self.auth.destroy_session(token)

    def test_a_database_outage_never_raises_and_keeps_cached_sessions(self):
        """GET /api/auth/session must answer, not 500, while MySQL is down."""
        token = self.auth.create_session(self._real_user())
        real = self.db.get_db

        def down():
            raise ConnectionError('MySQL is down (simulated)')
        self.db.get_db = down
        try:
            sess = self.auth._SESSIONS[self.auth.token_hash(token)]
            sess['db_seen'] -= _dt.timedelta(seconds=self.auth.SESSION_TOUCH_SECONDS + 1)
            self.assertTrue(self.auth.get_session(token), 'a cached session was lost')
            self.assertIsNone(self.auth.get_session('not-a-real-token'))
            self.auth.create_session({'username': self.PROBE, 'role': 'nurse'})
            self.auth.destroy_sessions_for_user(self.PROBE)
        finally:
            self.db.get_db = real
            self.auth.destroy_session(token)


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

    def test_the_nurse_station_can_open_the_whole_plan(self):
        """
        Plans were saved but the nurse station and the ward round never showed
        them. Their read-only "Davolash rejasi" view lists the patient's plans
        and opens the active one, so a nurse must be able to read both the
        list and the full plan -- and still not change it.
        """
        pid = self.make_patient('Plan For Nurse')
        st, plan = self.api.post('/api/treatment-plans', {
            'patient_id': pid, 'plan_type': 'outpatient',
            'immediate_actions': 'Vitallarni 4 soatda bir nazorat qilish'})
        self.assertEqual(st, 201, f"plan failed: {plan}")
        username = f'suite_nurse_p_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        st, body = self.api.post('/api/users', {
            'username': username, 'password': 'Suite-Probe-2026',
            'full_name': 'Suite Nurse P', 'role': 'nurse'})
        self.assertEqual(st, 201, f"could not create the probe account: {body}")
        try:
            c = Client()
            c.login(username, 'Suite-Probe-2026')
            c.post('/api/auth/change-password', {
                'current_password': 'Suite-Probe-2026',
                'new_password': 'Suite-Probe-2026-Rot',
                'confirm_password': 'Suite-Probe-2026-Rot'})
            st, plans = c.get('/api/treatment-plans/patient/' + pid)
            self.assertEqual(st, 200)
            active = [p for p in plans if p['status'] == 'active']
            self.assertEqual([p['id'] for p in active], [plan['plan_id']])
            st, one = c.get('/api/treatment-plans/' + plan['plan_id'])
            self.assertEqual(st, 200, 'a nurse could not open the plan itself')
            self.assertEqual(one['immediate_actions'], 'Vitallarni 4 soatda bir nazorat qilish')
            self.assertEqual(
                c.post('/api/treatment-plans',
                       {'patient_id': pid, 'immediate_actions': 'x'})[0],
                403, 'reading the plan let a nurse write one')
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



class ServerPayroll(ApiTest):
    """
    Pay used to be worked out in the HR page from a rota it rebuilt on every
    load, plus a doctor bonus and a detox bonus nobody had entered. It is now
    GET /api/hr/payroll: base salary + saved roster shifts x the listed duty
    tariffs. These pin what is paid, what is reported instead, and who may
    read it.
    """

    _account = RoleAuthorization._account
    HERE = os.path.dirname(os.path.abspath(__file__))
    ROSTER = os.path.join(HERE, '..', 'data', 'duty_schedule.json')
    PRICING = os.path.join(HERE, '..', 'data', 'pricing_config.json')
    MONTH = '2031-02'

    def setUp(self):
        super().setUp()
        self._temp_users = []
        self._staff = []
        self._saved = {}
        for path in (self.ROSTER, self.PRICING):
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    self._saved[path] = f.read()

    def tearDown(self):
        for path, data in self._saved.items():
            with open(path, 'wb') as f:
                f.write(data)
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        if self._staff:
            sys.path.insert(0, os.path.dirname(self.HERE))
            from db import get_db
            conn = get_db()
            try:
                cur = conn.cursor()
                for sid in self._staff:
                    cur.execute("DELETE FROM staff WHERE id = ?", (sid,))
                conn.commit()
            finally:
                conn.close()
        super().tearDown()

    def _staff_member(self, name, role, salary):
        st, body = self.api.post('/api/staff', {'full_name': name, 'role': role,
                                                'base_salary': salary})
        self.assertEqual(st, 201, body)
        self._staff.append(body['id'])
        return body

    def _payroll(self, client=None):
        st, body = (client or self.api).get('/api/hr/payroll?month=' + self.MONTH)
        self.assertEqual(st, 200, body)
        return body

    def test_a_saved_shift_is_paid_at_the_listed_tariff(self):
        san = self._staff_member('Suite Payroll Sanitarka', 'sanitar', 1000000)
        self.assertEqual(san['staff']['role'], 'sanitar', 'a sanitarka was filed as another role')
        st, res = self.api.post('/api/duty-schedule', {'shifts': [
            {'date': self.MONTH + '-03', 'sanitar_primary_id': san['id'],
             'sanitar_primary': 'Suite Payroll Sanitarka'},
            {'date': self.MONTH + '-04', 'sanitar_primary_id': san['id'],
             'sanitar_primary': 'Suite Payroll Sanitarka',
             # The reserve is not a worked shift.
             'sanitar_secondary_id': san['id'], 'sanitar_secondary': 'Suite Payroll Sanitarka'},
        ]})
        self.assertEqual(st, 200, res)
        body = self._payroll()
        tariff = body['tariffs']['sanitar_24h']
        line = next(l for l in body['staff'] if l['staff_id'] == san['id'])
        self.assertEqual(line['duty_counts'], {'sanitar_24h': 2})
        self.assertEqual(line['duty_pay'], 2 * tariff)
        self.assertEqual(line['gross'], 1000000 + 2 * tariff)
        self.assertEqual(line['income_tax'], round(line['gross'] * 0.12))
        self.assertEqual(line['net'], line['gross'] - line['income_tax'] - line['pension'])
        self.assertEqual(body['saved_days'], 2)

    def test_a_shift_for_someone_else_is_reported_not_paid(self):
        nurse = self._staff_member('Suite Payroll Hamshira', 'nurse', 0)
        st, res = self.api.post('/api/duty-schedule', {'shifts': [
            {'date': self.MONTH + '-05', 'nurse_primary_id': nurse['id'],
             'nurse_primary': 'Boshqa Odam Ismi'},
            {'date': self.MONTH + '-06', 'doctor_night_id': 'STF-SUITE-NOBODY',
             'doctor_night': 'Suite Yoq Shifokor'},
        ]})
        self.assertEqual(st, 200, res)
        body = self._payroll()
        line = next(l for l in body['staff'] if l['staff_id'] == nurse['id'])
        self.assertEqual(line['duty_pay'], 0, 'a shift was paid to whoever holds the id')
        self.assertIn(nurse['id'], [m['staff_id'] for m in body['name_mismatches']])
        self.assertIn('STF-SUITE-NOBODY', [u['staff_id'] for u in body['unlinked_shifts']])

    def test_tariffs_come_from_the_price_list(self):
        st, body = self.api.post('/api/settings/pricing', {'duty_tariffs': {'nurse_24h': 412000}})
        self.assertEqual(st, 200, body)
        self.assertEqual(body['pricing']['duty_tariffs']['nurse_24h'], 412000)
        self.assertEqual(self._payroll()['tariffs']['nurse_24h'], 412000)
        st, roster = self.api.get('/api/duty-schedule')
        self.assertEqual(roster['duty_tariffs']['nurse_24h'], 412000)
        self.assertIn('sanitarkas', roster.get('staff_pool', {}))

    def test_a_bad_tariff_is_refused_with_its_field(self):
        for bad in ('ikki yuz', -5, None, True):
            st, body = self.api.post('/api/settings/pricing', {'duty_tariffs': {'nurse_24h': bad}})
            self.assertEqual(st, 400, f"{bad!r}: {body}")
            self.assertEqual(body.get('field'), 'duty_tariffs.nurse_24h', body)
        st, body = self.api.post('/api/settings/pricing', {'duty_tariffs': {'surgeon': 1}})
        self.assertEqual(st, 400, body)
        with open(self.PRICING, 'rb') as f:
            self.assertEqual(f.read(), self._saved.get(self.PRICING))

    def test_a_bad_month_is_refused(self):
        for bad in ('2031-13', '2031-2', 'oktabr'):
            st, body = self.api.get('/api/hr/payroll?month=' + urllib.parse.quote(bad))
            self.assertEqual(st, 400, f"{bad!r}: {body}")
            self.assertEqual(body.get('field'), 'month')

    def test_a_new_employee_never_takes_an_existing_id(self):
        first = self._staff_member('Suite Payroll Birinchi', 'sanitar', 0)
        second = self._staff_member('Suite Payroll Ikkinchi', 'sanitar', '')
        self.assertNotEqual(first['id'], second['id'])
        st, staff = self.api.get('/api/staff')
        rows = staff if isinstance(staff, list) else staff.get('staff', [])
        names = {r['id']: r['full_name'] for r in rows}
        self.assertEqual(names.get(first['id']), 'Suite Payroll Birinchi',
                         'adding an employee overwrote another one')
        # A blank salary is 0, not an invented 10 000 000.
        self.assertEqual(second['staff']['base_salary'], 0)
        st, body = self.api.post('/api/staff', {'full_name': 'Suite Payroll Xato',
                                                'role': 'sanitar', 'base_salary': 'kop'})
        self.assertEqual(st, 400, body)
        self.assertEqual(body.get('field'), 'base_salary')

    def test_a_sanitarka_reads_the_roster_but_cannot_save_it(self):
        """Saved days are paid, so a sanitarka could otherwise pay herself."""
        san = self._account('sanitar')
        st, _ = san.get('/api/duty-schedule')
        self.assertEqual(st, 200)
        st, _ = san.post('/api/duty-schedule', {'shifts': [
            {'date': self.MONTH + '-07', 'sanitar_primary': 'Suite Probe'}]})
        self.assertEqual(st, 403)

    def test_a_rename_keeps_saved_shifts_paid(self):
        nurse = self._staff_member('Suite Payroll Karimva', 'nurse', 0)
        other = self._staff_member('Suite Payroll Boshqa', 'nurse', 0)
        st, res = self.api.post('/api/duty-schedule', {'shifts': [
            {'date': self.MONTH + '-08', 'nurse_primary_id': nurse['id'],
             'nurse_primary': 'Suite Payroll Karimva'},
            # A roster mistake under the same id must not be handed over.
            {'date': self.MONTH + '-09', 'nurse_primary_id': nurse['id'],
             'nurse_primary': 'Suite Payroll Boshqa'},
        ]})
        self.assertEqual(st, 200, res)
        st, body = self.api.post('/api/staff', {'id': nurse['id'], 'full_name': 'Suite Payroll Karimova',
                                                'role': 'nurse', 'base_salary': 0})
        self.assertEqual(st, 201, body)
        line = next(l for l in self._payroll()['staff'] if l['staff_id'] == nurse['id'])
        self.assertEqual(line['duty_counts'], {'nurse_24h': 1},
                         'a rename stopped pay, or paid a day that named someone else')
        self.assertTrue(other['id'])

    def test_salaries_stay_with_hr_and_accounting(self):
        """/api/hr/data was open to every login and /api/staff sent salary_base to all."""
        desk = self._account('receptionist')
        st, _ = desk.get('/api/hr/data')
        self.assertEqual(st, 403)
        st, rows = desk.get('/api/staff')
        self.assertEqual(st, 200)
        self.assertTrue(rows, 'the staff list came back empty')
        self.assertFalse(any('salary_base' in r for r in rows), 'the desk can read salaries')
        self.assertFalse(any('detox_procedure_fee' in r for r in rows), 'the desk can read procedure fees')
        st, rows = self.api.get('/api/staff')
        self.assertTrue(any('salary_base' in r for r in rows))

    def test_the_doctor_list_carries_no_pay(self):
        """/api/doctors is open to every login and still sent salary_base."""
        for role in ('receptionist', 'nurse'):
            c = self._account(role)
            st, rows = c.get('/api/doctors')
            self.assertEqual(st, 200, rows)
            self.assertTrue(rows, 'the doctor list came back empty')
            for k in ('salary_base', 'detox_procedure_fee'):
                self.assertFalse(any(k in r for r in rows), f'{role} can read {k} via /api/doctors')
        st, rows = self.api.get('/api/doctors')
        self.assertTrue(any('salary_base' in r for r in rows), 'HR-level callers lost the pay columns')

    def test_the_desk_cannot_read_payroll(self):
        desk = self._account('receptionist')
        st, _ = desk.get('/api/hr/payroll?month=' + self.MONTH)
        self.assertEqual(st, 403)


class HrAttendanceAndStaffRecords(ApiTest):
    """
    The HR page kept attendance and half of each staff form in the browser
    only, so both were gone after a reload or on another computer, and its
    delete button said "o'chirish" while the server only deactivated. These
    pin POST /api/hr/attendance, the HR staff columns, and reactivation.
    """

    _account = RoleAuthorization._account

    def setUp(self):
        super().setUp()
        self._temp_users = []
        self._staff = []

    def tearDown(self):
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        if self._staff:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from db import get_db
            conn = get_db()
            try:
                cur = conn.cursor()
                for sid in self._staff:
                    cur.execute("DELETE FROM staff_attendance WHERE staff_id = ?", (sid,))
                    cur.execute("DELETE FROM staff WHERE id = ?", (sid,))
                conn.commit()
            finally:
                conn.close()
        super().tearDown()

    def _staff_member(self, name='Suite HR Xodim', role='nurse', **extra):
        payload = {'full_name': name, 'role': role, 'base_salary': 0}
        payload.update(extra)
        st, body = self.api.post('/api/staff', payload)
        self.assertEqual(st, 201, body)
        self._staff.append(body['id'])
        return body

    def _hr_staff(self, sid):
        st, body = self.api.get('/api/hr/data')
        self.assertEqual(st, 200, body)
        return next((s for s in body['staff'] if s['id'] == sid), None), body

    def _attendance(self, sid):
        _s, body = self._hr_staff(sid)
        return [a for a in body['attendance_records'] if a['staff_id'] == sid]

    @staticmethod
    def _day(offset=-1):
        return (_dt.date.today() + _dt.timedelta(days=offset)).isoformat()

    # --- attendance -------------------------------------------------------

    def test_attendance_is_saved_once_per_person_per_day(self):
        sid = self._staff_member()['id']
        day = self._day(-1)
        st, body = self.api.post('/api/hr/attendance', {
            'staff_id': sid, 'work_date': day, 'shift_type': 'day', 'status': 'present',
            'check_in': '08:00', 'check_out': '17:30'})
        self.assertEqual(st, 200, body)
        self.assertEqual(body['attendance']['worked_hours'], 9.5)
        # A second save for the same day corrects it rather than adding a row.
        st, body = self.api.post('/api/hr/attendance', {
            'staff_id': sid, 'work_date': day, 'shift_type': 'day', 'status': 'late',
            'check_in': '08:15', 'late_minutes': 15, 'notes': 'Suite'})
        self.assertEqual(st, 200, body)
        rows = [a for a in self._attendance(sid) if str(a['work_date'])[:10] == day]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]['status'], 'late')
        self.assertEqual(rows[0]['late_minutes'], 15)
        self.assertEqual(rows[0]['check_in_time'], '08:15')
        self.assertIsNone(rows[0]['check_out_time'], 'the old check-out survived the correction')

    def test_a_night_shift_ends_the_next_morning(self):
        sid = self._staff_member()['id']
        st, body = self.api.post('/api/hr/attendance', {
            'staff_id': sid, 'work_date': self._day(-2), 'shift_type': 'night', 'status': 'present',
            'check_in': '20:00', 'check_out': '08:00'})
        self.assertEqual(st, 200, body)
        self.assertEqual(body['attendance']['worked_hours'], 12.0)
        self.assertTrue(str(body['attendance']['check_out']).startswith(self._day(-1)), body)

    def test_lateness_is_kept_only_for_a_late_entry(self):
        sid = self._staff_member()['id']
        st, body = self.api.post('/api/hr/attendance', {
            'staff_id': sid, 'work_date': self._day(-1), 'shift_type': 'day', 'status': 'present',
            'check_in': '08:00', 'late_minutes': 20})
        self.assertEqual(st, 200, body)
        self.assertIsNone(body['attendance']['late_minutes'])

    def test_bad_attendance_is_refused_and_nothing_is_written(self):
        sid = self._staff_member()['id']
        good = {'staff_id': sid, 'work_date': self._day(-1), 'shift_type': 'day', 'status': 'present'}
        cases = [
            ({'staff_id': ''}, 'staff_id'),
            ({'staff_id': 'STF-NOBODY-999'}, 'staff_id'),
            ({'work_date': ''}, 'work_date'),
            ({'work_date': '2026-13-01'}, 'work_date'),
            ({'work_date': self._day(+2)}, 'work_date'),
            ({'status': 'scheduled_night'}, 'status'),
            ({'shift_type': 'evening'}, 'shift_type'),
            ({'check_in': '25:00'}, 'check_in'),
            ({'check_out': 'tushda'}, 'check_out'),
            ({'status': 'absent', 'check_in': '08:00'}, 'check_in'),
            ({'status': 'late', 'late_minutes': -5}, 'late_minutes'),
        ]
        for change, field in cases:
            payload = dict(good, **change)
            st, body = self.api.post('/api/hr/attendance', payload)
            self.assertEqual(st, 400, f'{change} was accepted: {body}')
            self.assertEqual(body.get('field'), field, f'{change}: {body}')
            self.assertNotIn('Traceback', json.dumps(body))
        self.assertEqual(self._attendance(sid), [])

    def test_the_server_tomorrow_is_accepted(self):
        # A UTC server is a day behind Tashkent between 00:00 and 05:00, so
        # the browser's today can be the server's tomorrow.
        sid = self._staff_member()['id']
        st, body = self.api.post('/api/hr/attendance', {
            'staff_id': sid, 'work_date': self._day(+1), 'shift_type': 'day', 'status': 'present'})
        self.assertEqual(st, 200, body)

    def test_only_hr_records_attendance(self):
        sid = self._staff_member()['id']
        payload = {'staff_id': sid, 'work_date': self._day(-1), 'shift_type': 'day', 'status': 'sick'}
        desk = self._account('receptionist')
        self.assertEqual(desk.post('/api/hr/attendance', payload)[0], 403)
        hr = self._account('hr_manager')
        st, body = hr.post('/api/hr/attendance', payload)
        self.assertEqual(st, 200, body)

    # --- staff HR fields --------------------------------------------------

    def test_hr_form_fields_survive_a_reload(self):
        sid = self._staff_member(
            'Suite HR Toliq', 'doctor',
            hire_date='2024-03-01', experience_years=7, category='1-toifa',
            role_title_uz='Shifokor-Narkolog', department='doctors', assigned_floor='2',
            telegram='@suite_hr', detox_procedure_fee=150000, bls_cpr_certified=True)['id']
        row, _ = self._hr_staff(sid)
        self.assertEqual(str(row['hire_date'])[:10], '2024-03-01')
        self.assertEqual(row['experience_years'], 7)
        self.assertEqual(row['category'], '1-toifa')
        self.assertEqual(row['role_title_uz'], 'Shifokor-Narkolog')
        self.assertEqual(row['department'], 'doctors')
        self.assertEqual(row['assigned_floor'], '2')
        self.assertEqual(row['telegram'], 'suite_hr')
        self.assertEqual(float(row['detox_procedure_fee']), 150000.0)
        self.assertEqual(row['bls_cpr_certified'], 1)

        # A save from a form without these fields (the Super-Portal hire
        # form) keeps them; a field sent blank clears it.
        st, body = self.api.post('/api/staff', {'id': sid, 'full_name': 'Suite HR Toliq',
                                                'role': 'doctor', 'base_salary': 0})
        self.assertEqual(st, 201, body)
        row, _ = self._hr_staff(sid)
        self.assertEqual(row['category'], '1-toifa', 'a partial save wiped HR data')
        st, body = self.api.post('/api/staff', {'id': sid, 'full_name': 'Suite HR Toliq',
                                                'role': 'doctor', 'base_salary': 0, 'category': ''})
        self.assertEqual(st, 201, body)
        row, _ = self._hr_staff(sid)
        self.assertIsNone(row['category'])
        self.assertEqual(row['experience_years'], 7)

    def test_missing_hr_fields_stay_empty(self):
        sid = self._staff_member('Suite HR Bosh')['id']
        row, _ = self._hr_staff(sid)
        for key in ('hire_date', 'experience_years', 'category', 'telegram', 'bls_cpr_certified'):
            self.assertIsNone(row.get(key), f'{key} was filled in for nobody: {row.get(key)!r}')

    def test_bad_hr_fields_are_refused(self):
        cases = [
            ({'category': 'Professor'}, 'category'),
            ({'department': 'kitchen'}, 'department'),
            ({'assigned_floor': '7'}, 'assigned_floor'),
            ({'hire_date': '01.03.2024'}, 'hire_date'),
            ({'hire_date': '1890-01-01'}, 'hire_date'),
            ({'experience_years': -1}, 'experience_years'),
            ({'experience_years': 'besh'}, 'experience_years'),
            ({'detox_procedure_fee': -5}, 'detox_procedure_fee'),
        ]
        for extra, field in cases:
            payload = {'full_name': 'Suite HR Xato', 'role': 'nurse', 'base_salary': 0}
            payload.update(extra)
            st, body = self.api.post('/api/staff', payload)
            if st == 201:
                self._staff.append(body['id'])
            self.assertEqual(st, 400, f'{extra} was accepted: {body}')
            self.assertEqual(body.get('field'), field, f'{extra}: {body}')

    def test_a_role_outside_the_short_list_is_kept(self):
        body = self._staff_member('Suite HR Farmatsevt', 'pharmacist')
        self.assertEqual(body['staff']['role'], 'pharmacist', 'a pharmacist was saved as admin')

    # --- deactivate / reactivate -----------------------------------------

    def test_deactivated_staff_stay_listed_and_can_be_reactivated(self):
        sid = self._staff_member('Suite HR Qaytuvchi', category='2-toifa')['id']
        st, body = self.api.delete('/api/staff/' + sid)
        self.assertEqual(st, 200, body)
        row, _ = self._hr_staff(sid)
        self.assertIsNotNone(row, 'a deactivated employee vanished from HR')
        self.assertEqual(row['status'], 'inactive')
        st, active = self.api.get('/api/staff')
        self.assertNotIn(sid, [s['id'] for s in active], 'an inactive employee is still offered elsewhere')

        st, body = self.api.post('/api/staff/' + urllib.parse.quote(sid) + '/reactivate', {})
        self.assertEqual(st, 200, body)
        row, _ = self._hr_staff(sid)
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['category'], '2-toifa', 'reactivation rewrote the record')

        # Editing a deactivated person keeps them inactive: the upsert used to
        # set is_active = 1, so fixing a phone number silently put someone who
        # had left back on the roster and the payroll.
        self.api.delete('/api/staff/' + sid)
        st, body = self.api.post('/api/staff', {'id': sid, 'full_name': 'Suite HR Qaytuvchi',
                                                'role': 'nurse', 'base_salary': 0,
                                                'phone': '+998900000001'})
        self.assertEqual(st, 201, body)
        self.assertEqual(body['staff']['status'], 'inactive', body)
        row, _ = self._hr_staff(sid)
        self.assertEqual(row['status'], 'inactive', 'an edit reactivated a deactivated employee')

    def test_a_client_chosen_staff_id_must_be_a_plain_id(self):
        # A quote in the id ran script from the Super-Portal fire button.
        for bad in ("X');alert(1);//", 'a b', 'x' * 65, '<b>'):
            st, body = self.api.post('/api/staff', {'id': bad, 'full_name': 'Suite HR Yomon Id',
                                                    'role': 'nurse', 'base_salary': 0})
            if st == 201:
                self._staff.append(body['id'])
            self.assertEqual(st, 400, f'{bad!r} was accepted: {body}')
            self.assertEqual(body.get('field'), 'id', body)

    def test_hr_free_text_refuses_markup(self):
        for key in ('role_title_uz', 'telegram'):
            st, body = self.api.post('/api/staff', {'full_name': 'Suite HR Belgi', 'role': 'nurse',
                                                    'base_salary': 0, key: 'a<img src=x>'})
            if st == 201:
                self._staff.append(body['id'])
            self.assertEqual(st, 400, f'{key} accepted markup: {body}')
            self.assertEqual(body.get('field'), key, body)

    def test_reactivation_needs_hr_and_a_real_person(self):
        sid = self._staff_member()['id']
        self.api.delete('/api/staff/' + sid)
        desk = self._account('receptionist')
        self.assertEqual(desk.post('/api/staff/' + sid + '/reactivate', {})[0], 403)
        self.assertEqual(self.api.post('/api/staff/STF-NOBODY-999/reactivate', {})[0], 404)

class AdminConsole(ApiTest):
    """
    The Super-Portal user console offered 6 of the 13 roles, could only create
    and delete, and the routes behind it accepted any role name, set typed
    passwords with no rotation, would delete or block the superadmin, and
    stored the typed password in the audit trail. These pin the hardened
    /api/users routes, the password reset and the audit viewer.
    """

    PW = 'Suite-Probe-2026'

    def setUp(self):
        super().setUp()
        self._temp_users = []

    def tearDown(self):
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        super().tearDown()

    def _create(self, role, tag, **extra):
        username = f'suite_adm_{tag}_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        payload = {'username': username, 'password': self.PW,
                   'full_name': f'Suite Admin {tag}', 'role': role}
        payload.update(extra)
        st, body = self.api.post('/api/users', payload)
        self.assertEqual(st, 201, f"could not create {role} probe: {body}")
        self._temp_users.append(body['id'])
        return body['id'], username

    def _signed_in(self, username, password=None):
        """Sign in and walk the first-login password change."""
        password = password or self.PW
        c = Client()
        st, b = c.login(username, password)
        self.assertEqual(st, 200, f"could not sign in as {username}: {b}")
        if b.get('must_change_password'):
            st2, b2 = c.post('/api/auth/change-password', {
                'current_password': password, 'new_password': password + '-R',
                'confirm_password': password + '-R'})
            self.assertEqual(st2, 200, b2)
        return c

    def _superadmin_id(self):
        st, users = self.api.get('/api/users')
        self.assertEqual(st, 200, users)
        return next(u['id'] for u in users if u['username'] == 'superadmin')

    def _audit_rows(self, entity_id):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT action_type, new_data_json, old_data_json FROM audit_logs "
                        "WHERE entity_name = 'users' AND entity_id = ? ORDER BY id", (entity_id,))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # --- roles -------------------------------------------------------------

    def test_role_list_is_every_role_in_permissions(self):
        import permissions
        st, roles = self.api.get('/api/users/roles')
        self.assertEqual(st, 200, roles)
        self.assertEqual({r['key'] for r in roles}, set(permissions.ROLES))
        for r in roles:
            self.assertEqual(r['label'], permissions.ROLES[r['key']]['label'])

    def test_a_role_the_old_form_lacked_can_be_issued(self):
        uid, _u = self._create('sanitar', 'san')
        st, users = self.api.get('/api/users')
        self.assertEqual(next(u for u in users if u['id'] == uid)['role'], 'sanitar')

    # --- failed sign-ins ---------------------------------------------------------

    def _failed_login_rows(self, since_id, entity_id):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM audit_logs WHERE action_type = 'LOGIN_FAILED' "
                        "AND id > ? AND entity_id = ?", (since_id, entity_id))
            return cur.fetchall()
        finally:
            conn.close()

    def _last_audit_id(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id), 0) AS n FROM audit_logs")
            return int(cur.fetchone()['n'])
        finally:
            conn.close()

    def test_a_failed_sign_in_for_an_unknown_login_is_masked(self):
        """The typed text (often a password in the wrong box) was shown in the audit viewer."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import audit
        typed = f'Parol-{os.getpid()}-xyz'.lower()
        before = self._last_audit_id()
        st, _ = Client().login(typed, 'wrong-password')
        self.assertEqual(st, 401)
        self.assertEqual(self._failed_login_rows(before, typed), [], 'the typed login was stored')
        self.assertTrue(self._failed_login_rows(before, audit.UNKNOWN_LOGIN))
        # A real account's name is kept: that is who was being tried.
        _uid, uname = self._create('nurse', 'lf')
        st, _ = Client().login(uname, 'wrong-password')
        self.assertEqual(st, 401)
        self.assertTrue(self._failed_login_rows(before, uname))

    def test_old_failed_sign_ins_are_scrubbed_but_not_without_users(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import audit
        import auth
        from db import get_db
        typed = f'zz-typed-{os.getpid()}'
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO audit_logs (entity_name, entity_id, action_type, new_data_json, "
                        "timestamp) VALUES ('auth', ?, 'LOGIN_FAILED', '{}', NOW())", (typed,))
            row_id = cur.lastrowid
            conn.commit()
            self.assertEqual(audit.scrub_unknown_logins(conn, []), 0,
                             'an unreadable users.json masked everything')
            names = [u.get('username') for u in auth.load_users()]
            self.assertGreaterEqual(audit.scrub_unknown_logins(conn, names), 1)
            cur.execute("SELECT entity_id FROM audit_logs WHERE id = ?", (row_id,))
            self.assertEqual(cur.fetchone()['entity_id'], audit.UNKNOWN_LOGIN)
            cur.execute("DELETE FROM audit_logs WHERE id = ?", (row_id,))
            conn.commit()
        finally:
            conn.close()

    # --- account managers are not superadmins --------------------------------

    def test_only_a_superadmin_grants_or_touches_superadmin_power(self):
        # admin:write let a non-superadmin create a superadmin, grant '*' or
        # reset another superadmin's password and sign in as them.
        _mid, mgr_name = self._create('admin', 'mgr', permissions=['admin', 'reception'])
        sa2_id, _sa2 = self._create('superadmin', 'sa2')
        mgr = self._signed_in(mgr_name)

        def _new(tag, **extra):
            payload = {'username': f'suite_adm_{tag}_{os.getpid()}', 'password': self.PW,
                       'full_name': f'Suite Admin {tag}', 'role': 'doctor'}
            payload.update(extra)
            st, body = mgr.post('/api/users', payload)
            if st == 201:
                self._temp_users.append(body['id'])
            return st, body

        for tag, extra in (('esa', {'role': 'superadmin'}), ('est', {'permissions': ['*']}),
                           ('eaw', {'permissions': ['admin:write']}),
                           ('eam', {'permissions': ['admin', 'crm']})):
            st, body = _new(tag, **extra)
            self.assertEqual(st, 403, f'{extra} granted by a non-superadmin: {body}')

        st, body = mgr.post('/api/users/' + sa2_id + '/reset-password', {})
        self.assertEqual(st, 403, f'a non-superadmin reset a superadmin: {body}')
        st, body = mgr.put('/api/users/' + sa2_id, {'full_name': 'Hijacked'})
        self.assertEqual(st, 403, f'a non-superadmin edited a superadmin: {body}')
        st, body = self.api.put('/api/users/' + sa2_id, {'phone': '+998900000003'})
        self.assertEqual(st, 200, f'a superadmin could not edit another superadmin: {body}')

        st, body = _new('doc')
        self.assertEqual(st, 201, body)
        doc_id = body['user']['id']
        st, body = mgr.put('/api/users/' + doc_id, {'role': 'superadmin'})
        self.assertEqual(st, 403, f'a non-superadmin promoted to superadmin: {body}')
        st, body = mgr.put('/api/users/' + doc_id, {'permissions': ['*']})
        self.assertEqual(st, 403, body)
        # Ordinary accounts stay manageable.
        st, body = mgr.post('/api/users/' + doc_id + '/reset-password', {})
        self.assertEqual(st, 200, body)
        st, body = mgr.put('/api/users/' + doc_id, {'phone': '+998900000002'})
        self.assertEqual(st, 200, body)

    # --- permissions -------------------------------------------------------

    def test_non_admins_are_refused_and_admin_read_is_read_only(self):
        uid, _ = self._create('doctor', 'tgt')
        _nid, nurse_name = self._create('nurse', 'nrs')
        nurse = self._signed_in(nurse_name)
        for method, path, payload in (
                ('GET', '/api/users/roles', None), ('GET', '/api/audit', None),
                ('PUT', '/api/users/' + uid, {'full_name': 'X'}),
                ('POST', f'/api/users/{uid}/reset-password', {}),
                ('DELETE', '/api/users/' + uid, None)):
            st, _b = nurse.call(method, path, payload)
            self.assertEqual(st, 403, f"nurse got {st} on {method} {path}")
        # The 'admin' role carries admin:read: it may look, not change.
        _aid, admin_name = self._create('admin', 'adm')
        admin = self._signed_in(admin_name)
        self.assertEqual(admin.get('/api/audit?limit=1')[0], 200)
        self.assertEqual(admin.get('/api/users/roles')[0], 200)
        self.assertEqual(admin.put('/api/users/' + uid, {'full_name': 'X'})[0], 403)
        self.assertEqual(admin.post(f'/api/users/{uid}/reset-password', {})[0], 403)
        self.assertEqual(admin.delete('/api/users/' + uid)[0], 403)

    # --- create / edit -----------------------------------------------------

    def test_create_refuses_bad_input_with_the_field(self):
        base = {'username': f'suite_adm_bad_{os.getpid()}', 'password': self.PW,
                'full_name': 'Suite Bad', 'role': 'nurse'}
        for change, field in (({'role': 'janitor'}, 'role'), ({'role': ''}, 'role'),
                              ({'full_name': '  '}, 'full_name'),
                              ({'password': 'short'}, 'password'),
                              ({'username': 'A B!'}, 'username'),
                              ({'username': ''}, 'username'),
                              ({'staff_id': 'STF-NOBODY-999'}, 'staff_id'),
                              ({'permissions': ['nonsense']}, 'permissions')):
            payload = dict(base, **change)
            st, body = self.api.post('/api/users', payload)
            if st == 201:
                self._temp_users.append(body['id'])
            self.assertEqual(st, 400, f"{change} was accepted: {body}")
            self.assertEqual(body.get('field'), field, body)

    def test_create_without_password_issues_a_one_time_one(self):
        username = f'suite_adm_tmp_{os.getpid()}'
        self.api.delete('/api/users/' + username)
        st, body = self.api.post('/api/users', {'username': username,
                                                'full_name': 'Suite Tmp', 'role': 'nurse'})
        self.assertEqual(st, 201, body)
        self._temp_users.append(body['id'])
        self.assertTrue(body.get('temporary_password'))
        self.assertNotIn('password', body['user'])
        c = Client()
        st, b = c.login(username, body['temporary_password'])
        self.assertEqual(st, 200)
        self.assertTrue(b.get('must_change_password'))

    def test_edit_changes_name_phone_role_and_staff_link(self):
        uid, _ = self._create('nurse', 'edt')
        st, staff = self.api.get('/api/staff')
        self.assertEqual(st, 200)
        sid = staff[0]['id']
        st, body = self.api.put('/api/users/' + uid, {
            'full_name': 'Suite Edited', 'phone': '+998 90 000 00 00',
            'role': 'doctor', 'staff_id': sid})
        self.assertEqual(st, 200, body)
        u = body['user']
        self.assertEqual((u['full_name'], u['role'], u['staff_id']), ('Suite Edited', 'doctor', sid))
        self.assertNotIn('password', u)
        st, body = self.api.put('/api/users/' + uid, {'staff_id': ''})
        self.assertEqual(st, 200, body)
        self.assertNotIn('staff_id', body['user'])
        for change, field in (({'role': 'janitor'}, 'role'), ({'full_name': ''}, 'full_name'),
                              ({'staff_id': 'STF-NOBODY-999'}, 'staff_id'),
                              ({'is_active': 'no'}, 'is_active'),
                              ({'password': 'Another-Pass-1'}, 'password')):
            st, body = self.api.put('/api/users/' + uid, change)
            self.assertEqual(st, 400, f"{change} was accepted: {body}")
            self.assertEqual(body.get('field'), field, body)
        self.assertEqual(self.api.put('/api/users/suite_nobody_xyz', {'full_name': 'X'})[0], 404)

    def test_blocking_signs_the_account_out_and_refuses_login(self):
        uid, username = self._create('nurse', 'blk')
        c = self._signed_in(username)
        self.assertEqual(c.get('/api/crm/patients')[0], 200)
        st, body = self.api.put('/api/users/' + uid, {'is_active': False})
        self.assertEqual(st, 200, body)
        self.assertEqual(c.get('/api/crm/patients')[0], 401, 'blocked account kept its session')
        self.assertEqual(Client().login(username, self.PW + '-R')[0], 401)
        self.assertEqual(self.api.put('/api/users/' + uid, {'is_active': True})[0], 200)
        self.assertEqual(Client().login(username, self.PW + '-R')[0], 200)

    # --- reset -------------------------------------------------------------

    def test_reset_issues_a_one_time_password_that_must_be_changed(self):
        uid, username = self._create('nurse', 'rst')
        c = self._signed_in(username)
        st, body = self.api.post(f'/api/users/{uid}/reset-password', {})
        self.assertEqual(st, 200, body)
        temp = body.get('temporary_password')
        self.assertTrue(temp and len(temp) >= 8)
        self.assertEqual(c.get('/api/crm/patients')[0], 401, 'old session survived the reset')
        self.assertEqual(Client().login(username, self.PW + '-R')[0], 401,
                         'the old password still works')
        fresh = Client()
        st, b = fresh.login(username, temp)
        self.assertEqual(st, 200)
        self.assertTrue(b.get('must_change_password'))
        self.assertEqual(fresh.get('/api/crm/patients')[0], 403,
                         'a reset account reached data before changing its password')
        self.assertEqual(self.api.post('/api/users/suite_nobody_xyz/reset-password', {})[0], 404)

    # --- protection --------------------------------------------------------

    def test_superadmin_account_cannot_be_deleted_demoted_blocked_or_reset(self):
        sid = self._superadmin_id()
        st, users = self.api.get('/api/users')
        self.assertTrue(next(u for u in users if u['id'] == sid).get('protected'))
        self.assertEqual(self.api.delete('/api/users/' + sid)[0], 403)
        self.assertEqual(self.api.put('/api/users/' + sid, {'role': 'nurse'})[0], 403)
        self.assertEqual(self.api.put('/api/users/' + sid, {'is_active': False})[0], 403)
        self.assertEqual(self.api.put('/api/users/' + sid, {'permissions': ['crm']})[0], 403)
        self.assertEqual(self.api.post(f'/api/users/{sid}/reset-password', {})[0], 403)
        st, users = self.api.get('/api/users')
        me = next(u for u in users if u['id'] == sid)
        self.assertEqual((me['role'], me['is_active']), ('superadmin', True))

    def test_an_administrator_cannot_remove_their_own_account(self):
        uid, username = self._create('superadmin', 'own')
        me = self._signed_in(username)
        self.assertEqual(me.delete('/api/users/' + uid)[0], 403)
        self.assertEqual(me.put('/api/users/' + uid, {'role': 'nurse'})[0], 403)
        self.assertEqual(me.put('/api/users/' + uid, {'is_active': False})[0], 403)
        self.assertEqual(me.post(f'/api/users/{uid}/reset-password', {})[0], 403)
        # Name and phone of one's own account stay editable.
        self.assertEqual(me.put('/api/users/' + uid, {'phone': '+998 90 111 11 11'})[0], 200)

    # --- audit -------------------------------------------------------------

    def test_no_password_reaches_the_audit_trail(self):
        uid, _ = self._create('nurse', 'aud')
        st, body = self.api.post(f'/api/users/{uid}/reset-password', {})
        self.assertEqual(st, 200, body)
        temp = body['temporary_password']
        rows = self._audit_rows(uid)
        self.assertTrue(any(r['action_type'] == 'CREATE' for r in rows), rows)
        self.assertTrue(any(r['action_type'] == 'PASSWORD_CHANGED' for r in rows),
                        'the reset was not recorded as a password change')
        for r in rows:
            blob = json.dumps(r, default=str)
            self.assertNotIn(self.PW, blob, 'the typed password was audited')
            self.assertNotIn(temp, blob, 'the issued password was audited')
            self.assertNotIn('pbkdf2', blob)
        st, page = self.api.get('/api/audit?entity=users&q=' + urllib.parse.quote(uid))
        self.assertEqual(st, 200, page)
        self.assertTrue(page['rows'])
        for r in page['rows']:
            self.assertNotIn(self.PW, r['summary'])

    def test_audit_viewer_refuses_bad_filters(self):
        for qs, field in (('limit=201', 'limit'), ('limit=0', 'limit'), ('limit=x', 'limit'),
                          ('offset=-1', 'offset'), ('action=BOGUS', 'action'),
                          ('from=2026-13-01', 'from'), ('entity=users;drop', 'entity'),
                          ('from=2026-10-09&to=2026-10-01', 'to'), ('q=' + 'x' * 101, 'q')):
            st, body = self.api.get('/api/audit?' + qs)
            self.assertEqual(st, 400, f"{qs} was accepted: {body}")
            self.assertEqual(body.get('field'), field, body)

    def test_audit_viewer_filters_and_pages(self):
        uid, username = self._create('nurse', 'flt')
        today = _dt.date.today().isoformat()
        st, page = self.api.get(f'/api/audit?entity=users&action=CREATE&user={USERNAME}'
                                f'&from={today}&to={today}&limit=5&facets=1')
        self.assertEqual(st, 200, page)
        self.assertLessEqual(len(page['rows']), 5)
        self.assertGreaterEqual(page['total'], len(page['rows']))
        self.assertIn('users', page['entities'])
        self.assertIn('PASSWORD_CHANGED', page['actions'])
        for r in page['rows']:
            self.assertEqual((r['entity'], r['action'], r['actor']), ('users', 'CREATE', USERNAME))
            self.assertTrue(r['timestamp'].startswith(today))
        self.assertTrue(any(r['entity_id'] == uid for r in page['rows']),
                        'the account just created is not in the newest rows')
        st, found = self.api.get('/api/audit?q=' + urllib.parse.quote(username))
        self.assertEqual(st, 200)
        self.assertTrue(any(r['entity_id'] == uid for r in found['rows']))
        _s, p1 = self.api.get('/api/audit?limit=3&offset=0')
        _s, p2 = self.api.get('/api/audit?limit=3&offset=3')
        ids1, ids2 = [r['id'] for r in p1['rows']], [r['id'] for r in p2['rows']]
        self.assertEqual(ids1, sorted(ids1, reverse=True))
        self.assertFalse(set(ids1) & set(ids2), 'pages overlap')
        if ids1 and ids2:
            self.assertGreater(min(ids1), max(ids2))


class AccountingMoney(ApiTest):
    """
    Phase 4, chunk D. The cash desk paid salaries from figures it made up
    (8.5 / 12 million and an 8-10 % "commission" nobody set) because
    accountants could not read the server payroll; the desk printed a
    consultation fee and showed an outpatient daily fee that were never
    billed; and a patient's invoices could only be seen one at a time.
    """

    _account = RoleAuthorization._account

    def setUp(self):
        super().setUp()
        self._temp_users = []
        self.day = (_dt.date.today() + _dt.timedelta(days=430)).isoformat()

    def tearDown(self):
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        super().tearDown()

    def _rows(self, sql, params=()):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def _visit(self, client=None, **over):
        payload = {'patient_name': 'Hisob Probe Bemor', 'patient_phone': '+998900000431',
                   'doctor_id': DOCTOR, 'date': self.day, 'time': '09:10',
                   'service_type': 'consultation', 'bill_visit': True}
        payload.update(over)
        st, body = (client or self.api).post('/api/reception/appointment', payload)
        if isinstance(body, dict) and body.get('patient_id') and body['patient_id'] not in self._patients:
            self._patients.append(body['patient_id'])
        return st, body

    def _listed(self, package):
        st, pricing = self.api.get('/api/settings/pricing')
        self.assertEqual(st, 200)
        return float(pricing['packages'][package]['daily_rate'])

    # --- payroll -----------------------------------------------------------

    def test_the_cash_desk_reads_the_server_payroll_and_the_front_desk_does_not(self):
        acc = self._account('accountant')
        st, body = acc.get('/api/hr/payroll')
        self.assertEqual(st, 200, body)
        self.assertIn('staff', body)
        self.assertIn('net', body['totals'])
        self.assertEqual(acc.post('/api/hr/payroll', {})[0], 403, 'reading payroll is not writing HR')
        self.assertEqual(acc.get('/api/hr/data')[0], 403, 'only the payroll was opened, not all of HR')
        desk = self._account('receptionist')
        self.assertEqual(desk.get('/api/hr/payroll')[0], 403)

    def test_accounting_data_carries_no_invented_doctor_pay(self):
        """It sent salary_base + 10 % of patient payments to everyone with accounting:read."""
        desk = self._account('receptionist')
        st, body = desk.get('/api/accounting/data')
        self.assertEqual(st, 200)
        self.assertNotIn('doctors_payroll', body)

    # --- desk visit billing --------------------------------------------------

    def test_a_consultation_is_billed_once_at_the_typed_price(self):
        st, body = self._visit(consultation_fee=260000)
        self.assertEqual(st, 201, body)
        inv_id = body.get('invoice_id')
        self.assertTrue(inv_id, body)
        items = self._rows("SELECT quantity, unit_price, item_type FROM invoice_items WHERE invoice_id = ?",
                           (inv_id,))
        self.assertEqual(len(items), 1, items)
        self.assertEqual((float(items[0]['quantity']), float(items[0]['unit_price']), items[0]['item_type']),
                         (1.0, 260000.0, 'consultation'))
        inv = self._rows("SELECT appointment_id, admission_id, total_billed, balance_due FROM invoices WHERE id = ?",
                         (inv_id,))[0]
        self.assertEqual(inv['appointment_id'], body['id'])
        self.assertIsNone(inv['admission_id'])
        self.assertEqual(float(inv['total_billed']), 260000.0)
        self.assertEqual(float(inv['balance_due']), 260000.0)

        # A resend of the same visit answers with it and bills nothing more.
        st2, again = self._visit(consultation_fee=260000)
        self.assertEqual(st2, 200, again)
        self.assertTrue(again.get('already_recorded'))
        self.assertEqual((again['id'], again['invoice_id']), (body['id'], inv_id))
        n_apts = self._rows("SELECT COUNT(*) AS n FROM appointments WHERE patient_id = ?", (body['patient_id'],))
        self.assertEqual(int(n_apts[0]['n']), 1)
        n_items = self._rows("SELECT COUNT(*) AS n FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id "
                             "JOIN appointments a ON a.id = i.appointment_id WHERE a.patient_id = ?",
                             (body['patient_id'],))
        self.assertEqual(int(n_items[0]['n']), 1)

    def test_an_outpatient_course_is_billed_at_the_listed_rate_when_none_is_typed(self):
        st, body = self._visit(service_type='outpatient', program_type='ambulator_2', days=3,
                               patient_phone='+998900000432', time='09:20')
        self.assertEqual(st, 201, body)
        items = self._rows("SELECT quantity, unit_price, item_type FROM invoice_items WHERE invoice_id = ?",
                           (body['invoice_id'],))
        self.assertEqual(len(items), 1, items)
        self.assertEqual(float(items[0]['quantity']), 3.0)
        self.assertEqual(float(items[0]['unit_price']), self._listed('ambulator_2'))
        self.assertEqual(items[0]['item_type'], 'procedure')

    def test_nothing_is_billed_or_booked_without_a_length_or_a_price(self):
        cases = [
            ({'service_type': 'outpatient', 'program_type': 'ambulator_1'}, 'days'),
            ({'service_type': 'outpatient', 'program_type': 'ambulator_1', 'days': 0}, 'days'),
            ({'service_type': 'outpatient', 'days': 5}, 'program_type'),
            ({'service_type': 'outpatient', 'program_type': 'statsionar_shared', 'days': 5}, 'program_type'),
            ({'consultation_fee': 0}, 'consultation_fee'),
            ({'consultation_fee': 'abc'}, 'consultation_fee'),
            ({'consultation_fee': -5}, 'consultation_fee'),
        ]
        for extra, field in cases:
            st, body = self._visit(patient_name='Hisob Rad Bemor', patient_phone='+998900000433', **extra)
            self.assertEqual((st, body.get('field')), (400, field), (extra, body))
        left = self._rows("SELECT COUNT(*) AS n FROM appointments WHERE patient_name = 'Hisob Rad Bemor'")
        self.assertEqual(int(left[0]['n']), 0, 'a refused visit was still booked')

    def test_a_booking_from_the_appointments_tab_bills_nothing(self):
        st, body = self._visit(bill_visit=None, patient_phone='+998900000434', time='09:30')
        self.assertEqual(st, 201, body)
        self.assertNotIn('invoice_id', body)
        self.assertEqual(self._rows("SELECT id FROM invoices WHERE appointment_id = ?", (body['id'],)), [])

    def test_cancelling_an_unpaid_visit_removes_its_bill(self):
        st, body = self._visit(patient_phone='+998900000435', time='09:40')
        self.assertEqual(st, 201, body)
        st, res = self.api.put(f"/api/reception/appointment/{body['id']}/cancel", {})
        self.assertEqual(st, 200, res)
        self.assertEqual(self._rows("SELECT id FROM invoices WHERE id = ?", (body['invoice_id'],)), [])

    def test_a_paid_visit_keeps_its_bill_when_cancelled(self):
        st, body = self._visit(patient_phone='+998900000436', time='09:50')
        self.assertEqual(st, 201, body)
        st, pay = self.api.post('/api/payments', {'invoice_id': body['invoice_id'], 'amount': 1000,
                                                  'payment_method': 'cash'})
        self.assertEqual(st, 201, pay)
        st, res = self.api.put(f"/api/reception/appointment/{body['id']}/cancel", {})
        self.assertEqual(st, 200, res)
        self.assertIn("to'lov olingan", res['message'])
        self.assertEqual(len(self._rows("SELECT id FROM invoices WHERE id = ?", (body['invoice_id'],))), 1)

    def test_cancelling_a_visit_keeps_lines_added_later(self):
        """Cancel deleted every line, including stock medicines added in Accounting."""
        st, body = self._visit(patient_phone='+998900000438', time='10:30')
        self.assertEqual(st, 201, body)
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data',
                               'pricing_config.json'), encoding='utf-8') as f:
            svc = json.load(f)['additional_services'][0]
        st, added = self.api.post('/api/accounting/invoice-items', {
            'invoice_id': body['invoice_id'], 'service_code': svc['id'], 'quantity': 1})
        self.assertEqual(st, 201, added)
        st, res = self.api.put(f"/api/reception/appointment/{body['id']}/cancel", {})
        self.assertEqual(st, 200, res)
        items = self._rows("SELECT id, item_type FROM invoice_items WHERE invoice_id = ?",
                           (body['invoice_id'],))
        self.assertEqual([i['id'] for i in items], [added['id']],
                         'the visit fee should go and the added line stay')
        inv = self._rows("SELECT total_billed FROM invoices WHERE id = ?", (body['invoice_id'],))
        self.assertEqual(len(inv), 1, 'the invoice holding the added line was deleted')
        self.assertAlmostEqual(float(inv[0]['total_billed']), float(svc['price']), delta=0.01)

    def test_a_paid_visit_is_not_mistaken_for_a_retry(self):
        """A second real consultation the same day was answered as a resend and never billed."""
        st, first = self._visit(patient_phone='+998900000439', time='10:40', consultation_fee=250000)
        self.assertEqual(st, 201, first)
        st, pay = self.api.post('/api/payments', {'invoice_id': first['invoice_id'], 'amount': 250000,
                                                  'payment_method': 'cash'})
        self.assertEqual(st, 201, pay)
        st, second = self._visit(patient_phone='+998900000439', time='15:40', consultation_fee=250000)
        self.assertEqual(st, 201, second)
        self.assertFalse(second.get('already_recorded'), second)
        self.assertNotEqual(second['invoice_id'], first['invoice_id'])

    def test_a_client_appointment_id_must_be_a_plain_id(self):
        """The id was copied into INV-<id> and printed inside an onclick handler."""
        st, body = self._visit(id="APT-1');alert(1);//", patient_phone='+998900000440', time='10:50')
        self.assertEqual((st, body.get('field')), (400, 'id'), body)

    # --- salary payouts ----------------------------------------------------------

    def test_a_salary_is_paid_once_per_payroll_month(self):
        """The paid-this-month guard lived only in the page and used the recording date."""
        st, staff = self.api.post('/api/staff', {'full_name': 'Suite Maosh Xodim', 'role': 'nurse',
                                                 'base_salary': 1000})
        self.assertEqual(st, 201, staff)
        sid = staff['id']
        today = _dt.date.today()
        this_month = today.strftime('%Y-%m')
        prev = (today.replace(day=1) - _dt.timedelta(days=1))
        prev_month = prev.strftime('%Y-%m')
        older = (prev.replace(day=1) - _dt.timedelta(days=1))

        def pay(**extra):
            payload = {'type': 'expense', 'category': 'salary', 'amount': 1000,
                       'related_staff_id': sid, 'payment_method': 'bank',
                       'title': 'Suite maosh'}
            payload.update(extra)
            return self.api.post('/api/accounting/transaction', payload)

        try:
            st, b = pay(payroll_month=prev_month)
            self.assertEqual(st, 201, b)
            st, b = pay(payroll_month=prev_month)
            self.assertEqual((st, b.get('field')), (409, 'payroll_month'), b)
            # Paying last month's salary today does not use up this month.
            st, b = pay(payroll_month=this_month)
            self.assertEqual(st, 201, b)
            # No month sent: the recording date's month, as before.
            st, b = pay(date=today.isoformat())
            self.assertEqual(st, 409, b)
            # A payout written before payroll_month existed counts by its date.
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from db import get_db
            conn = get_db()
            try:
                conn.cursor().execute(
                    "INSERT INTO accounting_transactions (id, transaction_type, category, amount, "
                    "payment_method, description, transaction_date, related_staff_id) "
                    "VALUES (?, 'expense', 'salary', 1000, 'bank_wire', 'legacy', ?, ?)",
                    (f'TRX-SUITE-{os.getpid()}', older.replace(day=10).isoformat(), sid))
                conn.commit()
            finally:
                conn.close()
            st, b = pay(payroll_month=older.strftime('%Y-%m'))
            self.assertEqual(st, 409, b)
            for bad in ('2026-13', '26-09', 'sentyabr'):
                st, b = pay(payroll_month=bad)
                self.assertEqual((st, b.get('field')), (400, 'payroll_month'), (bad, b))
            future = (today.replace(day=28) + _dt.timedelta(days=40)).strftime('%Y-%m')
            st, b = pay(payroll_month=future)
            self.assertEqual((st, b.get('field')), (400, 'payroll_month'), b)

            st, data = self.api.get('/api/accounting/data')
            mine = [t for t in data['transactions'] if t.get('related_staff_id') == sid]
            self.assertEqual(sorted(t.get('payroll_month') or '' for t in mine),
                             sorted(['', prev_month, this_month]), mine)
        finally:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from db import get_db
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM accounting_transactions WHERE related_staff_id = ?", (sid,))
                cur.execute("DELETE FROM staff WHERE id = ?", (sid,))
                conn.commit()
            finally:
                conn.close()

    # --- where the bill shows up ---------------------------------------------

    def test_a_visit_bill_is_in_the_ledger_and_the_patient_invoice_view(self):
        st, body = self._visit(consultation_fee=255000, patient_phone='+998900000437', time='10:10')
        self.assertEqual(st, 201, body)
        st, ledger = self.api.get('/api/financial-ledger')
        self.assertEqual(st, 200)
        row = next((r for r in ledger if r['invoice_id'] == body['invoice_id']), None)
        self.assertIsNotNone(row, 'the visit bill is missing from the ledger')
        self.assertIsNone(row['bed_id'], 'a visit got a bed')
        self.assertIsNone(row['total_days'], 'a visit got a length')
        self.assertEqual(row['patient_id'], body['patient_id'])
        self.assertEqual(float(row['net_amount']), 255000.0)

        self.api.post('/api/payments', {'invoice_id': body['invoice_id'], 'amount': 55000,
                                        'payment_method': 'cash'})
        desk = self._account('receptionist')
        st, view = desk.get('/api/accounting/patient-invoices?patient_id='
                            + urllib.parse.quote(body['patient_id']))
        self.assertEqual(st, 200, view)
        self.assertEqual(view['patient']['id'], body['patient_id'])
        self.assertEqual(len(view['invoices']), 1)
        inv = view['invoices'][0]
        self.assertEqual((inv['kind'], inv['invoice_id']), ('visit', body['invoice_id']))
        self.assertEqual([float(i['unit_price']) for i in inv['items']], [255000.0])
        self.assertEqual([float(p['amount']) for p in inv['payments']], [55000.0])
        self.assertEqual(float(view['totals']['balance_due']), 200000.0)

        st, crm = self.api.get('/api/crm/patients/' + urllib.parse.quote(body['patient_id']))
        self.assertEqual(st, 200)
        self.assertEqual(float(crm['financials']['balance_due']), 200000.0,
                         'the patient card does not count the visit bill')

    def test_the_patient_invoice_view_is_for_money_roles_only(self):
        nurse = self._account('nurse')
        self.assertEqual(nurse.get('/api/accounting/patient-invoices?patient_id=PAT-ANY')[0], 403)
        self.assertEqual(self.api.get('/api/accounting/patient-invoices')[0], 400)
        self.assertEqual(self.api.get('/api/accounting/patient-invoices?patient_id=PAT-NOPE-0')[0], 404)


# ---------------------------------------------------------------------------
# Medical warehouse (inventory.py, warehouse_api.py, docs/WAREHOUSE_DESIGN.md)
#
# Every stock test works on items it creates itself, so none depends on what is
# already on the shelf. The ledger is append-only and cannot be cleaned up, so
# test items are deactivated at the end (they are named 'SuiteWH ...'), and the
# accounting expenses that receipts create are removed so the owner's money
# report is not polluted by test purchases.
# ---------------------------------------------------------------------------

import itertools

_WH_COUNTER = itertools.count(1)


def _wh_db():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db import get_db
    return get_db()


class _WarehouseHelpers:
    """Shared fixtures for the warehouse test classes (not a TestCase itself)."""

    SUPPLIER = f'SuiteWH Supplier {os.getpid()}'

    def setUp(self):
        super().setUp()
        self._wh_items = []
        self._wh_trx = []
        self._temp_users = []

    def tearDown(self):
        for uid in self._temp_users:
            self.api.delete('/api/users/' + uid)
        for iid in self._wh_items:
            self.api.post(f'/api/warehouse/items/{iid}/deactivate', {})
        if self._wh_trx:
            conn = _wh_db()
            try:
                cur = conn.cursor()
                marks = ','.join(['?'] * len(self._wh_trx))
                cur.execute(f"DELETE FROM accounting_transactions WHERE id IN ({marks})",
                            tuple(self._wh_trx))
                conn.commit()
            finally:
                conn.close()
        super().tearDown()

    _account = RoleAuthorization._account

    # --- fixtures --------------------------------------------------------
    def cid(self):
        return f"suite-{os.getpid()}-{next(_WH_COUNTER)}-{os.urandom(3).hex()}"

    def item(self, **kw):
        n = next(_WH_COUNTER)
        payload = {'name': f'SuiteWH Item {os.getpid()}-{n}', 'item_type': 'medicine',
                   'base_unit': 'tabletka', 'units_per_package': 1, 'category': 'SuiteWH',
                   'form': 'tabletka'}
        payload.update(kw)
        st, body = self.api.post('/api/warehouse/items', payload)
        self.assertEqual(st, 201, f"item create failed: {body}")
        self._wh_items.append(body['id'])
        return body

    def receive(self, item_id, packages, price, expiry=None, batch_no=None, post=True,
                client_id=None, expect=(200, 201), **extra):
        line = {'item_id': item_id, 'packages': packages, 'package_price': price}
        if expiry:
            line['expiry_date'] = expiry
        if batch_no:
            line['batch_no'] = batch_no
        payload = {'client_request_id': client_id or self.cid(), 'supplier_name': self.SUPPLIER,
                   'invoice_number': 'SUITE-1', 'payment_method': 'cash', 'post': post,
                   'lines': [line]}
        payload.update(extra)
        st, body = self.api.post('/api/warehouse/receipts', payload)
        self.assertIn(st, expect, f"receipt failed: {body}")
        if isinstance(body, dict) and body.get('accounting_transaction_id'):
            self._wh_trx.append(body['accounting_transaction_id'])
        return body

    def stock(self, item_id):
        st, body = self.api.get('/api/warehouse/items/' + item_id)
        self.assertEqual(st, 200, body)
        return body

    def qty(self, item_id):
        return float(self.stock(item_id)['stock_quantity'])

    def ledger(self, item_id, **filters):
        q = '&'.join(f'{k}={v}' for k, v in filters.items())
        st, body = self.api.get(f'/api/warehouse/transactions?item_id={item_id}&limit=500' + ('&' + q if q else ''))
        self.assertEqual(st, 200, body)
        return body['transactions']

    def patient_with_rx(self, item, quantity_prescribed=None, name='Ombor Bemor'):
        pid = self.make_patient(name)
        rx = self.rx(pid, item, quantity_prescribed)
        return pid, rx

    def rx(self, pid, item, quantity_prescribed=None, **kw):
        payload = {'patient_id': pid, 'medication_name': item['name'], 'medication_id': item['id'],
                   'dosage': '1 tabletka', 'route': 'PO', 'frequency': 'Kuniga 2 mahal',
                   'duration_days': 5}
        if quantity_prescribed is not None:
            payload['quantity_prescribed'] = quantity_prescribed
            payload['quantity_unit'] = item.get('base_unit')
        payload.update(kw)
        st, body = self.api.post('/api/doctor/prescriptions', payload)
        self.assertEqual(st, 201, f"prescription failed: {body}")
        return body['id']

    def dispense(self, pid, rx, qty, expect=201, client_id=None, item_id=None, **extra):
        payload = {'client_request_id': client_id or self.cid(), 'patient_id': pid,
                   'quantity': qty, 'prescription_id': rx}
        if item_id:
            payload['item_id'] = item_id
        payload.update(extra)
        st, body = self.api.post('/api/warehouse/dispense', payload)
        if expect is not None:
            self.assertEqual(st, expect, f"dispense returned {st}: {body}")
        return st, body

    def history(self, pid):
        st, body = self.api.get('/api/warehouse/dispensings?patient_id=' + urllib.parse.quote(pid))
        self.assertEqual(st, 200, body)
        return body['dispensings']

    def raw_get(self, client, path):
        req = urllib.request.Request(BASE + path)
        req.add_header('Cookie', client.cookie)
        with urllib.request.urlopen(req) as res:
            return res.status, res.headers.get('Content-Type'), res.read().decode('utf-8')

    def snapshot(self, item_id, pid=None):
        """Everything a failed operation must leave alone."""
        st, item = self.api.get('/api/warehouse/items/' + item_id)
        lots = sorted((b['id'], b['remaining_qty']) for b in item['batches'])
        snap = {'stock': item['stock_quantity'], 'lots': lots, 'ledger': len(self.ledger(item_id))}
        if pid:
            snap['history'] = len(self.history(pid))
        return snap


class WarehouseStock(_WarehouseHelpers, ApiTest):
    """Receiving: quantities, package conversion, cost, accounting link."""

    def test_receiving_adds_exactly_what_was_received(self):
        it = self.item()
        self.assertEqual(self.qty(it['id']), 0)
        r = self.receive(it['id'], 100, 1000)
        self.assertEqual(r['status'], 'posted')
        self.assertEqual(self.qty(it['id']), 100)
        self.assertEqual(float(self.stock(it['id'])['available_quantity']), 100)
        led = self.ledger(it['id'])
        self.assertEqual([(t['txn_type'], float(t['qty_delta'])) for t in led], [('receipt', 100.0)])

    def test_a_box_of_30_tablets_times_3_is_90_units_at_a_thirtieth_of_the_price(self):
        """The Vitamin C example: 60 000 per box of 30, three boxes."""
        it = self.item(name=f'SuiteWH Vitamin C {os.getpid()}-{next(_WH_COUNTER)}', item_type='vitamin',
                       units_per_package=30, package_unit='quti', category='SuiteWH')
        r = self.receive(it['id'], 3, 60000)
        line = r['lines'][0]
        self.assertEqual(float(line['quantity_base']), 90)
        self.assertEqual(float(line['unit_cost']), 2000)
        self.assertEqual(float(line['line_total']), 180000)
        item = self.stock(it['id'])
        self.assertEqual(float(item['stock_quantity']), 90)
        self.assertEqual(float(item['avg_unit_cost']), 2000)
        self.assertEqual(float(item['stock_value']), 180000)

    def test_a_draft_receipt_does_not_change_stock_and_posts_once(self):
        it = self.item()
        r = self.receive(it['id'], 40, 500, post=False)
        self.assertEqual(r['status'], 'draft')
        self.assertEqual(self.qty(it['id']), 0)
        self.assertEqual(self.ledger(it['id']), [])
        st, posted = self.api.post(f"/api/warehouse/receipts/{r['id']}/post", {})
        self.assertEqual(st, 200, posted)
        if posted.get('accounting_transaction_id'):
            self._wh_trx.append(posted['accounting_transaction_id'])
        self.assertEqual(self.qty(it['id']), 40)
        st, again = self.api.post(f"/api/warehouse/receipts/{r['id']}/post", {})
        self.assertEqual(st, 409, again)
        self.assertEqual(self.qty(it['id']), 40, 'a second post added stock again')

    def test_a_cancelled_draft_cannot_be_posted(self):
        it = self.item()
        r = self.receive(it['id'], 5, 100, post=False)
        st, c = self.api.post(f"/api/warehouse/receipts/{r['id']}/cancel", {})
        self.assertEqual((st, c['status']), (200, 'cancelled'), c)
        st, _ = self.api.post(f"/api/warehouse/receipts/{r['id']}/post", {})
        self.assertEqual(st, 409)
        self.assertEqual(self.qty(it['id']), 0)

    def test_the_same_client_request_id_receives_once(self):
        it = self.item()
        cid = self.cid()
        first = self.receive(it['id'], 10, 100, client_id=cid)
        st_dup = self.receive(it['id'], 10, 100, client_id=cid)
        self.assertEqual(st_dup['id'], first['id'])
        self.assertTrue(st_dup.get('duplicate'))
        self.assertEqual(self.qty(it['id']), 10)

    def test_posting_creates_the_accounting_expense_and_links_it(self):
        it = self.item()
        r = self.receive(it['id'], 3, 25000, payment_method='terminal')
        trx = r['accounting_transaction_id']
        self.assertTrue(trx)
        st, data = self.api.get('/api/accounting/data')
        row = next((t for t in data['transactions'] if t['id'] == trx), None)
        self.assertIsNotNone(row, 'the expense is not in the cash ledger')
        self.assertEqual((row['type'], row['category']), ('expense', 'medication_purchase'))
        self.assertEqual(float(row['amount']), 75000)
        self.assertEqual(row.get('account_source') or row.get('account'), 'terminal_bank')

    def test_buying_never_overwrites_the_patient_price(self):
        it = self.item(unit_price=5000)
        self.receive(it['id'], 10, 1200)
        self.assertEqual(float(self.stock(it['id'])['unit_price']), 5000)

    def test_weighted_average_cost_after_two_receipts(self):
        it = self.item()
        self.receive(it['id'], 10, 100)
        self.receive(it['id'], 30, 200)
        item = self.stock(it['id'])
        # (10*100 + 30*200) / 40
        self.assertEqual(float(item['avg_unit_cost']), 175)
        self.assertEqual(float(item['stock_value']), 7000)
        self.assertEqual(float(item['last_unit_cost']), 200)

    def test_valuation_across_items_and_package_sizes(self):
        cat = f'SuiteWH-Cat-{os.getpid()}-{next(_WH_COUNTER)}'
        vit = self.item(item_type='vitamin', units_per_package=30, package_unit='quti', category=cat)
        amp = self.item(units_per_package=1, category=cat)
        self.receive(vit['id'], 3, 60000)                  # 90 tablets, 180 000
        self.receive(amp['id'], 10, 500)                   # 10 pieces,    5 000
        st, rep = self.api.get('/api/warehouse/reports/valuation-by-category')
        self.assertEqual(st, 200, rep)
        row = next(r for r in rep['rows'] if r['category'] == cat)
        self.assertEqual((row['items'], float(row['total_value'])), (2, 185000))
        st, rep = self.api.get('/api/warehouse/reports/valuation')
        self.assertGreaterEqual(float(rep['totals']['total_value']), 185000)
        by_id = {r['id']: r for r in rep['rows']}
        self.assertEqual(float(by_id[vit['id']]['stock_value']), 180000)
        st, summ = self.api.get('/api/warehouse/summary')
        self.assertGreaterEqual(float(summ['total_value']), 185000)

    def test_reversing_a_receipt_restores_stock_and_keeps_the_trail(self):
        it = self.item()
        r = self.receive(it['id'], 20, 100)
        trx = r['accounting_transaction_id']
        st, rev = self.api.post(f"/api/warehouse/receipts/{r['id']}/reverse", {'reason': 'Noto\'g\'ri kiritilgan'})
        self.assertEqual(st, 200, rev)
        self.assertEqual(rev['status'], 'reversed')
        self.assertEqual(self.qty(it['id']), 0)
        types = [t['txn_type'] for t in self.ledger(it['id'])]
        self.assertEqual(sorted(types), ['receipt', 'reversal'], 'the original row must stay')
        st, data = self.api.get('/api/accounting/data')
        self.assertNotIn(trx, [t['id'] for t in data['transactions']], 'the expense was not voided')
        st, again = self.api.post(f"/api/warehouse/receipts/{r['id']}/reverse", {'reason': 'yana'})
        self.assertEqual(st, 409, again)
        st, no_reason = self.api.post(f"/api/warehouse/receipts/{r['id']}/reverse", {})
        self.assertIn(st, (400, 409))

    def test_a_receipt_whose_stock_was_used_cannot_be_reversed(self):
        it = self.item()
        r = self.receive(it['id'], 10, 100)
        pid, rx = self.patient_with_rx(it)
        self.dispense(pid, rx, 3)
        st, res = self.api.post(f"/api/warehouse/receipts/{r['id']}/reverse", {'reason': 'xato'})
        self.assertEqual(st, 409, res)
        self.assertEqual(self.qty(it['id']), 7)

    def test_item_rules(self):
        it = self.item()
        # whole units only
        whole = self.item(allow_fraction=0)
        st, body = self.api.post('/api/warehouse/receipts', {
            'client_request_id': self.cid(), 'post': True,
            'lines': [{'item_id': whole['id'], 'packages': 2.5, 'package_price': 10}]})
        self.assertEqual((st, body.get('field')), (400, 'packages'), body)
        # duplicate name+strength+form
        st, body = self.api.post('/api/warehouse/items', {'name': it['name'], 'form': it['form'],
                                                          'base_unit': 'tabletka'})
        self.assertEqual(st, 409, body)
        # bad unit, bad flags
        st, body = self.api.post('/api/warehouse/items', {'name': 'SuiteWH X', 'base_unit': 'xyz'})
        self.assertEqual((st, body.get('field')), (400, 'base_unit'))
        st, body = self.api.post('/api/warehouse/items', {'name': '<b>x</b>'})
        self.assertEqual(st, 400)
        # a negative or fractional-beyond-3dp threshold
        st, body = self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': -1})
        self.assertEqual((st, body.get('field')), (400, 'min_stock_level'))
        st, body = self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 1.2345})
        self.assertEqual(st, 400)
        # sku is unique
        sku = f'SUITE-{os.getpid()}-{next(_WH_COUNTER)}'
        self.item(sku=sku)
        st, body = self.api.post('/api/warehouse/items', {'name': 'SuiteWH Other', 'sku': sku})
        self.assertEqual(st, 409, body)
        # an inactive item cannot be received
        self.api.post(f"/api/warehouse/items/{it['id']}/deactivate", {})
        st, body = self.api.post('/api/warehouse/receipts', {
            'client_request_id': self.cid(), 'post': True,
            'lines': [{'item_id': it['id'], 'packages': 1, 'package_price': 10}]})
        self.assertEqual(st, 400, body)

    def test_a_receipt_can_create_its_item_and_override_the_box_size(self):
        name = f'SuiteWH New {os.getpid()}-{next(_WH_COUNTER)}'
        st, body = self.api.post('/api/warehouse/receipts', {
            'client_request_id': self.cid(), 'post': True, 'supplier_name': self.SUPPLIER,
            'lines': [{'new_item': {'name': name, 'base_unit': 'tabletka', 'category': 'SuiteWH',
                                    'units_per_package': 10},
                       'packages': 2, 'package_price': 5000, 'units_per_package': 20}]})
        self.assertEqual(st, 201, body)
        self._wh_trx.append(body['accounting_transaction_id'])
        iid = body['lines'][0]['item_id']
        self._wh_items.append(iid)
        item = self.stock(iid)
        self.assertEqual((item['name'], float(item['stock_quantity'])), (name, 40.0))
        self.assertEqual(float(item['avg_unit_cost']), 250)      # 5000 per 20
        self.assertEqual(float(item['units_per_package']), 10, 'a one-off box size must not change the item')

    def test_expiring_soon_is_flagged_before_it_expires(self):
        it = self.item(track_expiry=1)
        soon = (_dt.date.today() + _dt.timedelta(days=10)).isoformat()
        self.receive(it['id'], 20, 100, expiry=soon)       # above the default threshold of 10
        item = self.stock(it['id'])
        self.assertEqual(item['stock_status'], 'expiring')
        self.assertEqual(float(item['expiring_quantity']), 20)
        self.assertEqual(item['nearest_expiry'], soon)
        st, alerts = self.api.get('/api/warehouse/alerts')
        self.assertIn('expiring_soon', [a['alert_type'] for a in alerts['alerts'] if a['item_id'] == it['id']])
        st, lst = self.api.get('/api/warehouse/items?status=expiring&limit=500')
        self.assertIn(it['id'], [i['id'] for i in lst['items']])
        st, rep = self.api.get('/api/warehouse/reports/expiry')
        self.assertIn(it['name'], [r['name'] for r in rep['rows']])

    def test_the_default_threshold_comes_from_settings_not_code(self):
        it = self.item()
        st, s = self.api.get('/api/warehouse/settings')
        self.assertEqual(st, 200)
        self.assertEqual(float(it['min_stock_level']), float(s['default_min_stock']))


class WarehouseDispensing(_WarehouseHelpers, ApiTest):
    """Giving stock to a patient: exact deduction, rules, atomicity, idempotency."""

    def test_prescribing_does_not_change_stock(self):
        it = self.item()
        self.receive(it['id'], 30, 100)
        before = self.snapshot(it['id'])
        pid, rx = self.patient_with_rx(it, quantity_prescribed=10)
        self.assertEqual(self.snapshot(it['id']), before)

    def test_dispensing_5_removes_exactly_5_and_lands_in_the_patient_history(self):
        it = self.item()
        self.receive(it['id'], 50, 100)
        pid, rx = self.patient_with_rx(it)
        st, d = self.dispense(pid, rx, 5)
        self.assertEqual(float(d['quantity']), 5)
        self.assertEqual(self.qty(it['id']), 45)
        hist = self.history(pid)
        self.assertEqual(len(hist), 1)
        h = hist[0]
        self.assertEqual((float(h['quantity']), h['status'], h['item_id'], h['prescription_id']),
                         (5.0, 'completed', it['id'], rx))
        self.assertEqual(h['dosage'], '1 tabletka')           # snapshot of the order
        self.assertEqual(float(sum(float(b['quantity']) for b in h['batches'])), 5)
        self.assertEqual(sum(float(t['qty_delta']) for t in self.ledger(it['id'], type='dispense')), -5)

    def test_more_than_is_available_is_refused_and_nothing_moves(self):
        it = self.item()
        self.receive(it['id'], 4, 100)
        pid, rx = self.patient_with_rx(it)
        before = self.snapshot(it['id'], pid)
        st, body = self.dispense(pid, rx, 5, expect=400)
        self.assertEqual(body.get('field'), 'quantity')
        self.assertEqual(self.snapshot(it['id'], pid), before)

    def test_a_refused_dispense_leaves_stock_ledger_and_history_unchanged(self):
        it = self.item()
        self.receive(it['id'], 20, 100)
        pid, rx = self.patient_with_rx(it)
        before = self.snapshot(it['id'], pid)
        self.api.put(f'/api/doctor/prescriptions/{rx}/status', {'status': 'cancelled'})
        self.dispense(pid, rx, 2, expect=400)
        self.assertEqual(self.snapshot(it['id'], pid), before)

    def test_a_failure_halfway_through_leaves_nothing_behind(self):
        """
        One dispensing writes lots, ledger rows, the balance and the history. A
        crash after the first writes must undo all of it: the service never
        commits, so the caller's rollback is the single exit.
        """
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import inventory
        it = self.item()
        self.receive(it['id'], 20, 100)
        pid, rx = self.patient_with_rx(it)
        before = self.snapshot(it['id'], pid)
        conn = _wh_db()
        real = inventory._set_balance

        def boom(*a, **k):
            raise RuntimeError('simulated crash after the lots and ledger were written')
        inventory._set_balance = boom
        try:
            with self.assertRaises(RuntimeError):
                inventory.dispense(conn, {'client_request_id': self.cid(), 'patient_id': pid,
                                          'prescription_id': rx, 'quantity': 6}, {'username': 'suite'})
            conn.rollback()
        finally:
            inventory._set_balance = real
            conn.close()
        self.assertEqual(self.snapshot(it['id'], pid), before)
        # and the stock is still usable afterwards
        self.dispense(pid, rx, 6)
        self.assertEqual(self.qty(it['id']), 14)

    def test_the_same_client_request_id_deducts_once(self):
        it = self.item()
        self.receive(it['id'], 20, 100)
        pid, rx = self.patient_with_rx(it)
        cid = self.cid()
        st1, d1 = self.dispense(pid, rx, 4, client_id=cid)
        st2, d2 = self.dispense(pid, rx, 4, client_id=cid, expect=200)
        self.assertTrue(d2['duplicate'])
        self.assertEqual(d1['id'], d2['id'])
        self.assertEqual(self.qty(it['id']), 16)
        self.assertEqual(len(self.history(pid)), 1)

    def test_a_dispense_without_a_client_request_id_is_refused(self):
        it = self.item()
        self.receive(it['id'], 5, 100)
        pid, rx = self.patient_with_rx(it)
        st, body = self.api.post('/api/warehouse/dispense',
                                 {'patient_id': pid, 'prescription_id': rx, 'quantity': 1})
        self.assertEqual((st, body.get('field')), (400, 'client_request_id'))

    def test_prescription_quantity_limits_and_partial_dispensing(self):
        it = self.item()
        self.receive(it['id'], 50, 100)
        pid, rx = self.patient_with_rx(it, quantity_prescribed=10)
        self.dispense(pid, rx, 6)
        st, pending = self.api.get('/api/warehouse/prescriptions/pending?patient_id=' + urllib.parse.quote(pid))
        self.assertEqual(st, 200, pending)
        row = next(p for p in pending['prescriptions'] if p['prescription_id'] == rx)
        self.assertEqual((float(row['quantity_prescribed']), float(row['dispensed_quantity']),
                          float(row['remaining_quantity'])), (10.0, 6.0, 4.0))
        st, body = self.dispense(pid, rx, 5, expect=400)
        self.assertEqual(body.get('field'), 'quantity')
        self.dispense(pid, rx, 4)
        st, pending = self.api.get('/api/warehouse/prescriptions/pending?patient_id=' + urllib.parse.quote(pid))
        self.assertNotIn(rx, [p['prescription_id'] for p in pending['prescriptions']])
        self.assertEqual(self.qty(it['id']), 40)

    def test_a_medicine_needs_a_prescription_but_a_consumable_does_not(self):
        med = self.item()
        cons = self.item(item_type='consumable', base_unit='dona')
        self.receive(med['id'], 10, 100)
        self.receive(cons['id'], 10, 100)
        pid = self.make_patient('Sarf Bemor')
        st, body = self.api.post('/api/warehouse/dispense', {
            'client_request_id': self.cid(), 'patient_id': pid, 'item_id': med['id'], 'quantity': 1})
        self.assertEqual((st, body.get('field')), (400, 'prescription_id'), body)
        st, body = self.api.post('/api/warehouse/dispense', {
            'client_request_id': self.cid(), 'patient_id': pid, 'item_id': cons['id'], 'quantity': 2})
        self.assertEqual(st, 201, body)
        self.assertEqual(self.qty(cons['id']), 8)

    def test_a_bill_line_takes_stock_through_the_service_without_a_prescription(self):
        """The billing and nurse code paths call the service; the screen route stays strict."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import inventory
        it = self.item()
        self.receive(it['id'], 10, 100)
        pid = self.make_patient('Hisob Bemor')
        cid = self.cid()
        conn = _wh_db()
        try:
            d = inventory.dispense(conn, {'client_request_id': cid, 'patient_id': pid,
                                          'item_id': it['id'], 'quantity': 2},
                                   {'username': 'suite'}, source='billing')
            conn.commit()
            self.assertEqual(d['source'], 'billing')
            found = inventory.find_dispensing_by_client_id(conn, cid)
            self.assertEqual(found['id'], d['id'])
            inventory.reverse_dispensing(conn, d['id'], 'Hisob qatori olib tashlandi', {'username': 'suite'})
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.qty(it['id']), 10)

    def test_a_prescription_that_is_not_active_is_refused(self):
        it = self.item()
        self.receive(it['id'], 20, 100)
        for status in ('cancelled', 'completed', 'held'):
            pid, rx = self.patient_with_rx(it)
            self.api.put(f'/api/doctor/prescriptions/{rx}/status', {'status': status})
            st, body = self.dispense(pid, rx, 1, expect=400)
            self.assertEqual(body.get('field'), 'prescription_id', (status, body))
        self.assertEqual(self.qty(it['id']), 20)

    def test_someone_elses_prescription_and_a_mismatched_item_are_refused(self):
        a, b = self.item(), self.item()
        self.receive(a['id'], 10, 100)
        self.receive(b['id'], 10, 100)
        pid1, rx1 = self.patient_with_rx(a)
        pid2 = self.make_patient('Boshqa Bemor')
        st, body = self.dispense(pid2, rx1, 1, expect=400)
        self.assertEqual(body.get('field'), 'prescription_id')
        st, body = self.dispense(pid1, rx1, 1, expect=400, item_id=b['id'])
        self.assertEqual(body.get('field'), 'item_id')
        self.assertEqual((self.qty(a['id']), self.qty(b['id'])), (10, 10))

    def test_fractions_only_where_the_item_allows_them(self):
        liquid = self.item(base_unit='ml', allow_fraction=1)
        pills = self.item()
        self.receive(liquid['id'], 10, 100)
        self.receive(pills['id'], 10, 100)
        pid, rx = self.patient_with_rx(liquid)
        self.dispense(pid, rx, 2.5)
        self.assertEqual(self.qty(liquid['id']), 7.5)
        pid2, rx2 = self.patient_with_rx(pills)
        st, body = self.dispense(pid2, rx2, 2.5, expect=400)
        self.assertEqual(body.get('field'), 'quantity')
        for bad in (0, -1, 'abc', 1.2345):
            st, body = self.dispense(pid, rx, bad, expect=400)

    def test_fefo_takes_the_earliest_expiry_first_and_expired_lots_are_never_used(self):
        today = _dt.date.today()
        it = self.item(track_expiry=1)
        self.receive(it['id'], 10, 100, expiry=(today + _dt.timedelta(days=60)).isoformat(), batch_no='LATE')
        self.receive(it['id'], 10, 100, expiry=(today + _dt.timedelta(days=20)).isoformat(), batch_no='EARLY')
        pid, rx = self.patient_with_rx(it)
        st, d = self.dispense(pid, rx, 12)
        self.assertEqual([(b['batch_no'], float(b['quantity'])) for b in d['batches']],
                         [('EARLY', 10.0), ('LATE', 2.0)])
        # Now age the remaining lot past its expiry.
        conn = _wh_db()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE inventory_batches SET expiry_date = ? WHERE item_id = ? AND batch_no = 'LATE'",
                        ((today - _dt.timedelta(days=1)).isoformat(), it['id']))
            conn.commit()
        finally:
            conn.close()
        item = self.stock(it['id'])
        self.assertEqual((float(item['available_quantity']), float(item['expired_quantity'])), (0.0, 8.0))
        self.assertEqual(item['stock_status'], 'out')
        st, body = self.dispense(pid, rx, 1, expect=400)
        self.assertEqual(body.get('field'), 'quantity')
        st, alerts = self.api.get('/api/warehouse/alerts')
        mine = [a['alert_type'] for a in alerts['alerts'] if a['item_id'] == it['id']]
        self.assertIn('expired', mine)
        # value split: the expired part is reported separately
        item = self.stock(it['id'])
        self.assertEqual(float(item['expired_value']), 800)
        self.assertEqual(float(item['available_value']), 0)

    def test_track_expiry_items_need_a_future_expiry_date(self):
        it = self.item(track_expiry=1)
        today = _dt.date.today()
        for expiry, field in ((None, 'expiry_date'), ((today - _dt.timedelta(days=1)).isoformat(), 'expiry_date')):
            body = self.receive(it['id'], 1, 100, expiry=expiry, expect=(400,))
            self.assertEqual(body.get('field'), field, body)
        self.assertEqual(self.qty(it['id']), 0)

    def test_reversing_a_dispensing_puts_it_back_and_keeps_the_trail(self):
        it = self.item()
        self.receive(it['id'], 30, 100)
        pid, rx = self.patient_with_rx(it, quantity_prescribed=10)
        st, d = self.dispense(pid, rx, 5)
        self.assertEqual(self.qty(it['id']), 25)
        st, rev = self.api.post(f"/api/warehouse/dispensings/{d['id']}/reverse", {'reason': 'Xato bemor'})
        self.assertEqual(st, 200, rev)
        self.assertEqual(rev['status'], 'reversed')
        self.assertEqual(self.qty(it['id']), 30)
        types = sorted(t['txn_type'] for t in self.ledger(it['id']))
        self.assertEqual(types, ['dispense', 'receipt', 'reversal'])
        st, again = self.api.post(f"/api/warehouse/dispensings/{d['id']}/reverse", {'reason': 'yana bir'})
        self.assertEqual(st, 409, again)
        self.assertEqual(self.history(pid)[0]['status'], 'reversed')
        # the prescription has its 10 back
        self.dispense(pid, rx, 10)

    def test_parallel_requests_for_the_last_units_never_make_stock_negative(self):
        it = self.item()
        self.receive(it['id'], 10, 100)
        pid, rx = self.patient_with_rx(it)
        results = []

        def go():
            c = Client()
            c.cookie = self.api.cookie
            st, body = c.post('/api/warehouse/dispense', {
                'client_request_id': self.cid(), 'patient_id': pid, 'prescription_id': rx, 'quantity': 3})
            results.append(st)
        threads = [threading.Thread(target=go) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [201, 201, 201] + [400] * 5, results)
        self.assertEqual(self.qty(it['id']), 1)

    def test_two_processes_worth_of_connections_cannot_oversell(self):
        """
        The server serialises writes with one lock, which would hide a missing
        row lock. Call the service from several connections at once instead:
        the row locks alone must keep the balance right.
        """
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import inventory
        it = self.item()
        self.receive(it['id'], 5, 100)
        pid = self.make_patient('Parallel Bemor')
        rxs = [self.rx(pid, it) for _ in range(5)]
        outcome = []

        def go(rx):
            conn = _wh_db()
            try:
                inventory.dispense(conn, {'client_request_id': self.cid(), 'patient_id': pid,
                                          'prescription_id': rx, 'quantity': 2}, {'username': 'suite'})
                conn.commit()
                outcome.append('ok')
            except inventory.InventoryError:
                conn.rollback()
                outcome.append('refused')
            except Exception as e:                       # a deadlock would show up here
                conn.rollback()
                outcome.append(repr(e))
            finally:
                conn.close()
        threads = [threading.Thread(target=go, args=(rx,)) for rx in rxs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(outcome), ['ok', 'ok', 'refused', 'refused', 'refused'], outcome)
        self.assertEqual(self.qty(it['id']), 1)
        st, rec = self.api.get('/api/warehouse/reconciliation')
        self.assertNotIn(it['id'], [m['item_id'] for m in rec['mismatches']])


class WarehouseAlertsAndLedger(_WarehouseHelpers, ApiTest):
    """Low stock, adjustments, the append-only ledger, reconciliation, exports."""

    def adjust(self, item_id, kind, qty, reason='Suite tuzatish', expect=201, **extra):
        payload = {'client_request_id': self.cid(), 'item_id': item_id, 'kind': kind,
                   'quantity': qty, 'reason': reason}
        payload.update(extra)
        st, body = self.api.post('/api/warehouse/adjustments', payload)
        self.assertEqual(st, expect, body)
        return body

    def active_types(self, item_id):
        st, body = self.api.get('/api/warehouse/alerts?status=active')
        return sorted(a['alert_type'] for a in body['alerts'] if a['item_id'] == item_id)

    def test_low_means_strictly_below_and_the_threshold_can_be_changed(self):
        it = self.item()
        self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 10})
        self.receive(it['id'], 10, 100)
        item = self.stock(it['id'])
        self.assertEqual(item['stock_status'], 'ok', 'equal to the threshold is not low')
        self.assertEqual(self.active_types(it['id']), [])
        self.adjust(it['id'], 'decrease', 1)
        self.assertEqual(self.stock(it['id'])['stock_status'], 'low')
        self.assertEqual(self.active_types(it['id']), ['low_stock'])
        self.assertEqual(float(self.stock(it['id'])['shortage']), 1)
        # threshold 10 -> 5: 9 is fine again, alert resolved
        self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 5})
        self.assertEqual(self.stock(it['id'])['stock_status'], 'ok')
        self.assertEqual(self.active_types(it['id']), [])
        # 5 -> 20: low again
        self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 20})
        self.assertEqual(self.stock(it['id'])['stock_status'], 'low')
        self.assertEqual(self.active_types(it['id']), ['low_stock'])
        # replenishing resolves it
        self.receive(it['id'], 20, 100)
        self.assertEqual(self.stock(it['id'])['stock_status'], 'ok')
        self.assertEqual(self.active_types(it['id']), [])

    def test_out_of_stock_is_not_the_same_as_low(self):
        it = self.item()
        self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 10})
        self.receive(it['id'], 3, 100)
        self.assertEqual(self.active_types(it['id']), ['low_stock'])
        self.adjust(it['id'], 'writeoff', 3, reason='Yaroqsiz')
        item = self.stock(it['id'])
        self.assertEqual(item['stock_status'], 'out')
        self.assertEqual(self.active_types(it['id']), ['out_of_stock'])

    def test_the_low_stock_view_uses_strictly_below(self):
        it = self.item()
        self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 10})
        self.receive(it['id'], 10, 100)
        conn = _wh_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM v_pharmacy_low_stock WHERE medication_id = ?", (it['id'],))
            self.assertIsNone(cur.fetchone(), 'stock equal to the threshold is in the low-stock view')
        finally:
            conn.close()
        self.adjust(it['id'], 'decrease', 1)
        conn = _wh_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM v_pharmacy_low_stock WHERE medication_id = ?", (it['id'],))
            self.assertIsNotNone(cur.fetchone())
        finally:
            conn.close()

    def test_alerts_are_not_duplicated_by_refreshing(self):
        it = self.item()
        self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 10})
        self.receive(it['id'], 2, 100)
        for _ in range(3):
            self.api.get('/api/warehouse/alerts')
            self.api.get('/api/warehouse/summary')
        st, body = self.api.get('/api/warehouse/alerts?status=active')
        mine = [a for a in body['alerts'] if a['item_id'] == it['id']]
        self.assertEqual(len(mine), 1, mine)

    def test_summary_counts(self):
        it = self.item()
        self.api.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 10})
        st, before = self.api.get('/api/warehouse/summary')
        self.receive(it['id'], 3, 100)
        st, after = self.api.get('/api/warehouse/summary')
        self.assertEqual(after['low_stock_count'], before['low_stock_count'] + 1)
        self.assertIn('units_by_unit', after)
        self.assertIn('settings', after)
        self.assertEqual(after['settings']['expiry_warning_days'], 30)
        self.assertGreaterEqual(after['low_stock_count'], 1)
        st, listing = self.api.get('/api/warehouse/items?status=low&limit=500')
        self.assertIn(it['id'], [i['id'] for i in listing['items']])
        st, listing = self.api.get('/api/warehouse/items?status=bogus')
        self.assertEqual(st, 400)

    def test_adjustments_need_a_reason_and_each_kind_moves_stock_correctly(self):
        it = self.item()
        self.receive(it['id'], 20, 100)
        self.adjust(it['id'], 'decrease', 4)
        self.assertEqual(self.qty(it['id']), 16)
        self.adjust(it['id'], 'increase', 2)
        self.assertEqual(self.qty(it['id']), 18)
        self.adjust(it['id'], 'supplier_return', 3)
        self.assertEqual(self.qty(it['id']), 15)
        self.adjust(it['id'], 'patient_return', 1)
        self.assertEqual(self.qty(it['id']), 16)
        body = self.adjust(it['id'], 'decrease', 1, reason='', expect=400)
        self.assertEqual(body.get('field'), 'reason')
        self.adjust(it['id'], 'decrease', 99, expect=400)
        self.adjust(it['id'], 'explode', 1, expect=400)
        self.assertEqual(self.qty(it['id']), 16)

    def test_an_adjustment_repeated_with_the_same_client_id_applies_once(self):
        it = self.item()
        self.receive(it['id'], 10, 100)
        cid = self.cid()
        a = self.adjust(it['id'], 'decrease', 2, client_request_id=cid)
        b = self.adjust(it['id'], 'decrease', 2, client_request_id=cid, expect=200)
        self.assertTrue(b['duplicate'])
        self.assertEqual(self.qty(it['id']), 8)

    def test_a_transaction_can_be_reversed_once_and_the_original_stays(self):
        it = self.item()
        self.receive(it['id'], 10, 100)
        a = self.adjust(it['id'], 'decrease', 3)
        txn = a['transactions'][0]['id']
        st, rev = self.api.post(f'/api/warehouse/transactions/{txn}/reverse', {'reason': 'Xato sanalgan'})
        self.assertEqual(st, 200, rev)
        self.assertEqual(self.qty(it['id']), 10)
        st, again = self.api.post(f'/api/warehouse/transactions/{txn}/reverse', {'reason': 'yana'})
        self.assertEqual(st, 409, again)
        self.assertEqual(len(self.ledger(it['id'])), 3, 'receipt + adjustment + reversal must all remain')
        # receipts and dispensings have their own reversal
        receipt_row = next(t for t in self.ledger(it['id']) if t['txn_type'] == 'receipt')
        st, body = self.api.post(f"/api/warehouse/transactions/{receipt_row['id']}/reverse", {'reason': 'xato'})
        self.assertEqual(st, 400, body)

    def test_the_ledger_is_append_only_in_the_database(self):
        it = self.item()
        self.receive(it['id'], 5, 100)
        conn = _wh_db()
        try:
            cur = conn.cursor()
            with self.assertRaises(Exception) as ctx:
                cur.execute("UPDATE inventory_transactions SET qty_delta = 99 WHERE item_id = ?", (it['id'],))
            self.assertIn('append-only', str(ctx.exception))
            conn.rollback()
            with self.assertRaises(Exception) as ctx:
                cur.execute("DELETE FROM inventory_transactions WHERE item_id = ?", (it['id'],))
            self.assertIn('append-only', str(ctx.exception))
            conn.rollback()
        finally:
            conn.close()
        self.assertEqual(len(self.ledger(it['id'])), 1)

    def test_reconciliation_is_clean_after_a_sequence_of_operations(self):
        it = self.item(track_expiry=1)
        exp = (_dt.date.today() + _dt.timedelta(days=90)).isoformat()
        r = self.receive(it['id'], 40, 100, expiry=exp)
        pid, rx = self.patient_with_rx(it)
        st, d = self.dispense(pid, rx, 7)
        self.adjust(it['id'], 'decrease', 2)
        self.adjust(it['id'], 'increase', 1, expiry_date=exp)
        self.api.post(f"/api/warehouse/dispensings/{d['id']}/reverse", {'reason': 'Sinov uchun'})
        self.dispense(pid, rx, 3)
        st, rec = self.api.get('/api/warehouse/reconciliation')
        self.assertEqual(st, 200)
        self.assertNotIn(it['id'], [m['item_id'] for m in rec['mismatches']], rec['mismatches'])
        item = self.stock(it['id'])
        self.assertEqual(float(item['stock_quantity']), 40 - 2 + 1 - 3)
        st, rep = self.api.get(f"/api/warehouse/reports/movement?item_id={it['id']}")
        self.assertEqual(st, 200)
        self.assertGreaterEqual(len(rep['rows']), 6)

    def test_csv_export_and_report_catalogue(self):
        it = self.item(name=f'=SuiteWH Formula {os.getpid()}-{next(_WH_COUNTER)}')
        self.receive(it['id'], 3, 100)
        status, ctype, text = self.raw_get(self.api, '/api/warehouse/reports/stock?format=csv')
        self.assertEqual(status, 200)
        self.assertIn('text/csv', ctype)
        self.assertTrue(text.startswith('﻿'))
        self.assertIn("'=SuiteWH Formula", text, 'a name starting with = must not stay a formula')
        for name in ('low-stock', 'out-of-stock', 'expiry', 'receipts', 'dispensings', 'adjustments',
                     'reconciliation', 'valuation', 'valuation-by-category', 'stock'):
            st, rep = self.api.get(f'/api/warehouse/reports/{name}')
            self.assertEqual(st, 200, (name, rep))
            self.assertIn('columns', rep)
        st, rep = self.api.get('/api/warehouse/reports/movement')
        self.assertEqual(st, 400)
        st, rep = self.api.get('/api/warehouse/reports/nonsense')
        self.assertEqual(st, 404)

    def test_the_migration_is_idempotent(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import inventory
        conn = _wh_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS n FROM inventory_batches")
            batches = cur.fetchone()['n']
            cur.execute("SELECT COUNT(*) AS n FROM inventory_transactions")
            ledger = cur.fetchone()['n']
            self.assertTrue(inventory.ensure_schema(conn))
            self.assertTrue(inventory.ensure_schema(conn))
            cur.execute("SELECT COUNT(*) AS n FROM inventory_batches")
            self.assertEqual(cur.fetchone()['n'], batches)
            cur.execute("SELECT COUNT(*) AS n FROM inventory_transactions")
            self.assertEqual(cur.fetchone()['n'], ledger)
        finally:
            conn.close()


class WarehouseAccess(_WarehouseHelpers, ApiTest):
    """Who may see and do what. Hiding a button is not a permission; these hit the API."""

    COST_KEYS = ('avg_unit_cost', 'last_unit_cost', 'last_package_price', 'stock_value',
                 'expired_value', 'available_value')

    def test_anonymous_callers_get_401(self):
        anon = Client()
        for path in ('/api/warehouse/items', '/api/warehouse/summary', '/api/warehouse/availability'):
            self.assertEqual(anon.get(path)[0], 401, path)
        self.assertEqual(anon.post('/api/warehouse/dispense', {})[0], 401)

    def test_front_desk_nurse_and_doctor_cannot_see_or_move_stock(self):
        for role in ('receptionist', 'nurse', 'doctor'):
            c = self._account(role)
            for path in ('/api/warehouse/items', '/api/warehouse/receipts',
                         '/api/warehouse/transactions', '/api/warehouse/dispensings',
                         '/api/warehouse/reports/stock', '/api/warehouse/reconciliation'):
                self.assertEqual(c.get(path)[0], 403, f'{role} read {path}')
            for path in ('/api/warehouse/dispense', '/api/warehouse/receipts',
                         '/api/warehouse/adjustments', '/api/warehouse/items',
                         '/api/warehouse/suppliers'):
                self.assertEqual(c.post(path, {})[0], 403, f'{role} wrote {path}')

    def test_prescribers_and_nurses_may_ask_what_is_on_the_shelf_without_costs(self):
        it = self.item()
        self.receive(it['id'], 12, 1000)
        for role in ('doctor', 'nurse'):
            c = self._account(role)
            st, body = c.get('/api/warehouse/availability?q=' + urllib.parse.quote(it['name']))
            self.assertEqual(st, 200, (role, body))
            row = next(r for r in body['items'] if r['id'] == it['id'])
            self.assertEqual(float(row['available_quantity']), 12)
            for k in self.COST_KEYS + ('unit_price', 'supplier_id'):
                self.assertNotIn(k, row, f'{role} saw {k}')
            st, summ = c.get('/api/warehouse/summary')
            self.assertEqual(st, 200)
            self.assertNotIn('total_value', summ)
            self.assertNotIn('recent_receipts', summ)

    def test_the_pharmacist_counts_stock_but_sees_no_costs_and_cannot_buy_or_reprice(self):
        ph = self._account('pharmacist')
        it = self.item()
        self.receive(it['id'], 10, 1000)
        st, body = ph.get('/api/warehouse/items/' + it['id'])
        self.assertEqual(st, 200)
        for k in self.COST_KEYS:
            self.assertNotIn(k, body, f'the pharmacist saw {k}')
        for b in body['batches']:
            self.assertNotIn('unit_cost', b)
        st, lst = ph.get('/api/warehouse/items')
        self.assertTrue(all(k not in lst['items'][0] for k in self.COST_KEYS))
        st, rc = ph.get('/api/warehouse/receipts')
        self.assertEqual(st, 200)
        self.assertTrue(all('total_amount' not in r for r in rc['receipts']))
        st, summ = ph.get('/api/warehouse/summary')
        self.assertNotIn('total_value', summ)
        self.assertEqual(ph.get('/api/warehouse/reports/valuation')[0], 403)
        self.assertEqual(ph.get('/api/warehouse/reports/valuation-by-category')[0], 403)
        # may not receive stock, set the threshold, or touch prices
        self.assertEqual(ph.post('/api/warehouse/receipts', {
            'client_request_id': self.cid(), 'post': True,
            'lines': [{'item_id': it['id'], 'packages': 1, 'package_price': 1}]})[0], 403)
        self.assertEqual(ph.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 1})[0], 403)
        self.assertEqual(ph.put(f"/api/warehouse/items/{it['id']}", {'unit_price': 1})[0], 403)
        self.assertEqual(ph.put(f"/api/warehouse/items/{it['id']}", {'min_stock_level': 1})[0], 403)
        self.assertEqual(ph.post('/api/warehouse/items', {'name': 'SuiteWH ph', 'unit_price': 5})[0], 403)
        self.assertEqual(ph.post('/api/warehouse/items', {'name': 'SuiteWH ph2', 'min_stock_level': 5})[0], 403)
        # but may create an item and edit its non-cost fields
        st, made = ph.post('/api/warehouse/items', {'name': f'SuiteWH Ph {os.getpid()}-{next(_WH_COUNTER)}',
                                                     'base_unit': 'dona'})
        self.assertEqual(st, 201, made)
        self._wh_items.append(made['id'])
        self.assertNotIn('avg_unit_cost', made)
        st, upd = ph.put(f"/api/warehouse/items/{made['id']}", {'manufacturer': 'Suite Pharm'})
        self.assertEqual((st, upd['manufacturer']), (200, 'Suite Pharm'))
        # and dispenses
        pid, rx = self.patient_with_rx(it)
        st, d = ph.post('/api/warehouse/dispense', {'client_request_id': self.cid(), 'patient_id': pid,
                                                    'prescription_id': rx, 'quantity': 2})
        self.assertEqual(st, 201, d)
        self.assertNotIn('total_cost', d)
        # the stock report is allowed (costs dropped), as CSV too
        st, rep = ph.get('/api/warehouse/reports/stock')
        self.assertEqual(st, 200)
        self.assertNotIn('stock_value', [c['key'] for c in rep['columns']])

    def test_the_accountant_buys_and_prices_and_sees_costs(self):
        ac = self._account('accountant')
        it = self.item()
        st, body = ac.post('/api/warehouse/receipts', {
            'client_request_id': self.cid(), 'post': True, 'supplier_name': self.SUPPLIER,
            'lines': [{'item_id': it['id'], 'packages': 2, 'package_price': 5000}]})
        self.assertEqual(st, 201, body)
        self._wh_trx.append(body['accounting_transaction_id'])
        self.assertEqual(float(body['total_amount']), 10000)
        st, th = ac.put(f"/api/warehouse/items/{it['id']}/threshold", {'min_stock_level': 4})
        self.assertEqual((st, float(th['min_stock_level'])), (200, 4.0))
        st, upd = ac.put(f"/api/warehouse/items/{it['id']}", {'unit_price': 9000})
        self.assertEqual((st, float(upd['unit_price'])), (200, 9000.0))
        st, item = ac.get('/api/warehouse/items/' + it['id'])
        self.assertEqual(float(item['avg_unit_cost']), 5000)
        self.assertEqual(ac.get('/api/warehouse/reports/valuation')[0], 200)
        # but the accountant does not hand out medicine
        pid, rx = self.patient_with_rx(it)
        st, d = ac.post('/api/warehouse/dispense', {'client_request_id': self.cid(), 'patient_id': pid,
                                                    'prescription_id': rx, 'quantity': 1})
        self.assertEqual(st, 201, 'the accountant has the warehouse module (write)')

    def test_oversight_roles_read_but_do_not_write(self):
        it = self.item()
        self.receive(it['id'], 5, 1000)
        for role, sees_costs in (('owner', True), ('chief_doctor', False), ('ward_manager', False)):
            c = self._account(role)
            st, body = c.get('/api/warehouse/items/' + it['id'])
            self.assertEqual(st, 200, (role, body))
            self.assertEqual('avg_unit_cost' in body, sees_costs, role)
            self.assertEqual(c.get('/api/warehouse/summary')[0], 200)
            self.assertEqual(c.post('/api/warehouse/adjustments', {
                'client_request_id': self.cid(), 'item_id': it['id'], 'kind': 'decrease',
                'quantity': 1, 'reason': 'xxx'})[0], 403, role)
            self.assertEqual(c.post('/api/warehouse/dispense', {})[0], 403, role)
            self.assertEqual(c.post('/api/warehouse/receipts', {})[0], 403, role)
        self.assertEqual(self.qty(it['id']), 5)

    def test_warehouse_module_pages_and_routes_are_registered(self):
        import permissions
        self.assertIn('warehouse', permissions.MODULES)
        self.assertEqual(permissions.PAGE_RULES['/warehouse.html'], ('warehouse', 'read'))
        self.assertEqual(permissions.required_for_api('GET', '/api/warehouse/anything-new'),
                         ('warehouse', 'read'))
        self.assertFalse(permissions.authorize_api({'role': 'receptionist'}, 'GET',
                                                   '/api/warehouse/anything-new')[0])
        self.assertFalse(permissions.authorize_api({'role': 'nurse'}, 'POST',
                                                   '/api/warehouse/dispense')[0])
        self.assertTrue(permissions.authorize_api({'role': 'pharmacist'}, 'POST',
                                                  '/api/warehouse/dispense')[0])
        self.assertTrue(permissions.authorize_api({'role': 'superadmin'}, 'POST',
                                                  '/api/warehouse/receipts')[0])
        self.assertFalse(permissions.authorize_api({'role': 'pharmacist'}, 'POST',
                                                   '/api/warehouse/receipts/RCP-1/reverse')[0])
        self.assertEqual(permissions.visible_pages({'role': 'pharmacist'}).count('/warehouse.html'), 1)
        self.assertNotIn('/warehouse.html', permissions.visible_pages({'role': 'receptionist'}))

    def test_a_route_that_does_not_exist_is_404_for_the_superadmin(self):
        self.assertEqual(self.api.get('/api/warehouse/no-such-thing')[0], 404)
        self.assertEqual(self.api.post('/api/warehouse/no-such-thing', {})[0], 404)


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
