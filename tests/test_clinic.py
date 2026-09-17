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

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get('FMH_TEST_BASE', 'http://127.0.0.1:3000')
USERNAME = os.environ.get('FMH_TEST_USER', 'superadmin')
PASSWORD = os.environ.get('FMH_TEST_PASS', 'superadmin2026')

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


class ApiTest(unittest.TestCase):
    """Base class: one signed-in client, and cleanup of created rows."""

    @classmethod
    def setUpClass(cls):
        if not server_is_up():
            raise unittest.SkipTest(f"no server at {BASE} — start `python3 server.py 3000` first")
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
        self.release_beds()

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

        rec = self.patient_record(pid)
        self.assertAlmostEqual(rec['total_billed'], 10 * RATE, delta=1,
                               msg='ten nights at the daily rate should be billed')

        status, pay = self.api.post('/api/payments', {
            'admission_id': adm['admission_id'], 'amount': 2_000_000,
            'payment_method': 'cash'})
        self.assertEqual(status, 201, f"payment failed: {pay}")

        rec = self.patient_record(pid)
        self.assertAlmostEqual(rec['total_paid'], 2_000_000, delta=1)
        self.assertAlmostEqual(rec['balance_due'], 10 * RATE - 2_000_000, delta=1,
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

    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
