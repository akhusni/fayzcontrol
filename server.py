"""
Fayz Medical House — 100% Real Database-Connected REST API & Static Server
Runs out-of-the-box with Python standard library.
Connects all portals (Facility, CRM, Doctor EMR, Accounting, HR, Reception) directly to Enterprise MySQL 8.0.
Enforces real-time relational integrity, autonomous triggers, and live KPI views.
"""

import http.server
import socketserver
import json
import os
import urllib.parse
import sys
import datetime
import datetime as _dt
import decimal
import decimal as _dec
import traceback
import threading
import tempfile


def json_default(obj):
    if isinstance(obj, _dec.Decimal):
        return float(obj)
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, _dt.timedelta):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


_orig_json_dumps = json.dumps
def safe_json_dumps(obj, *args, **kwargs):
    if 'default' not in kwargs:
        kwargs['default'] = json_default
    if 'ensure_ascii' not in kwargs:
        kwargs['ensure_ascii'] = False
    return _orig_json_dumps(obj, *args, **kwargs)

json.dumps = safe_json_dumps


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else int(os.environ.get('PORT', 3000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from pdf_generator import generate_patient_pdf
except Exception as e:
    generate_patient_pdf = None

# ----------------------------------------------------------------------------
# Shared-state safety for the threaded server.
#
# The JSON data files (users.json, clinic_rooms.json, pricing_config.json) are
# read-modify-written by request handlers. ThreadingHTTPServer runs each request
# in its own thread, so without serialization two concurrent writers interleave:
# one thread truncates the file with open(...,'w') while another is still reading
# it, the reader gets a partial document, and the write-back persists that
# truncated state. That silently destroyed whole files.
#
# WRITE_LOCK serializes every mutating request (POST/PUT/DELETE). It also makes
# the read-COUNT-then-INSERT id generators in the staff/user routes correct,
# since a concurrent request can no longer observe the same count.
# write_json_atomic() replaces the file via os.replace(), which is atomic, so a
# concurrent reader always sees either the old or the new complete document and
# never a half-written one.
# ----------------------------------------------------------------------------
WRITE_LOCK = threading.RLock()


def read_json_file(path, default=None):
    """
    Load a JSON data file.

    An absent file yields `default` (there is nothing to lose yet). A file that
    exists but cannot be parsed raises, deliberately: the previous code caught
    every exception here and fell back to an empty list, so a handler that read,
    modified and wrote the document back persisted that empty value and erased
    every existing record. Failing the request is always preferable to silently
    truncating live data.
    """
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json_atomic(path, data):
    """
    Write JSON to `path` atomically: serialize into a temporary file in the same
    directory, flush to disk, then os.replace() it over the target. Readers never
    observe a partially written file.
    """
    directory = os.path.dirname(os.path.abspath(path)) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp-', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


from db import (
    get_db,
    get_active_engine,
    admit_patient,
    transfer_patient_bed,
    discharge_patient,
    load_config
)

import auth
import audit
import permissions


class ClinicRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    # ------------------------------------------------------------------------
    # Authentication gate
    #
    # Every /api/* route other than the auth endpoints, and every portal page,
    # now requires a signed-in session. API callers get 401 JSON; browsers
    # asking for a page get redirected to the login screen. Stylesheets,
    # scripts and images stay open so the login screen can render.
    # ------------------------------------------------------------------------
    def current_session(self):
        token = auth.token_from_cookie_header(self.headers.get('Cookie'))
        return auth.get_session(token)

    def _reject_unauthenticated(self, path):
        """Send the right kind of refusal. Returns True once handled."""
        if path.startswith('/api/'):
            self._set_json_headers(401)
            self.wfile.write(json.dumps({
                'error': 'Avtorizatsiya talab qilinadi',
                'detail': 'Sessiya topilmadi yoki muddati tugagan. Iltimos, qaytadan kiring.',
                'login_url': '/login.html'
            }, ensure_ascii=False).encode('utf-8'))
        else:
            target = '/login.html'
            if path and path not in ('/', ''):
                target += '?next=' + urllib.parse.quote(path, safe='')
            self.send_response(302)
            self.send_header('Location', target)
            self.end_headers()
        return True

    # ------------------------------------------------------------------------
    # Audit capture
    #
    # The route handlers write their JSON straight to the socket, so to record
    # what actually happened the response is teed as it goes out: the status
    # line is noted, and the first few KB of body are kept so a created row's
    # generated id can be pulled out of it. Auditing then happens once, at the
    # dispatch point, instead of being threaded through thirty write branches.
    # ------------------------------------------------------------------------
    class _Tee:
        """Forwards writes to the real stream while keeping a capped copy."""

        LIMIT = 4096

        def __init__(self, inner):
            self._inner = inner
            self.captured = bytearray()

        def write(self, data):
            if len(self.captured) < self.LIMIT:
                try:
                    self.captured.extend(data[: self.LIMIT - len(self.captured)])
                except Exception:
                    pass
            return self._inner.write(data)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def send_response(self, code, message=None):
        self._audit_status = code
        return super().send_response(code, message)

    def _audit_mutation(self, path, body, captured):
        """Record one completed write. Only 2xx outcomes are logged as changes."""
        status = getattr(self, '_audit_status', None)
        if status is None or not (200 <= status < 300):
            return
        if path.startswith('/api/auth/'):
            return          # handled explicitly by the auth routes themselves
        sess = self.current_session()
        user = sess['user'] if sess else None
        response_body = None
        if captured:
            try:
                # end_headers() writes the status line and headers to the same
                # stream, so the capture holds those before the JSON. Drop
                # everything up to the blank line that separates them —
                # otherwise the parse fails and the trail records the URL tail
                # instead of the generated id.
                raw = bytes(captured)
                sep = raw.find(b'\r\n\r\n')
                if sep == -1:
                    sep = raw.find(b'\n\n')
                    body_bytes = raw[sep + 2:] if sep != -1 else raw
                else:
                    body_bytes = raw[sep + 4:]
                response_body = json.loads(body_bytes.decode('utf-8', 'replace'))
            except Exception:
                response_body = None
        try:
            conn = get_db()
            try:
                audit.ensure_schema(conn)
                audit.record(
                    conn,
                    audit.entity_for_path(path),
                    audit.entity_id_from(path, body, response_body),
                    audit.action_for(self.command, path),
                    user=user,
                    new_data=body if isinstance(body, dict) else None,
                    ip_address=self.client_ip(),
                )
            finally:
                conn.close()
        except Exception as e:
            print(f"[!] Could not audit {self.command} {path}: {e}")

    def client_ip(self):
        """
        The caller's address, honouring the proxy header the documented Nginx
        vhost sets. Used for throttling and for the audit trail.
        """
        fwd = self.headers.get('X-Real-IP') or self.headers.get('X-Forwarded-For')
        if fwd:
            return fwd.split(',')[0].strip()
        try:
            return self.client_address[0]
        except Exception:
            return '-'

    def _reject_unauthorized(self, path, reason, user):
        """
        Refuse an authenticated caller who lacks the permission. 403, not 401:
        signing in again will not help, and the difference matters to the
        client-side handler, which must not bounce them to the login screen.
        """
        print(f"[authz] denied {self.command} {path} for "
              f"{(user or {}).get('username')} ({reason})")
        try:
            conn = get_db()
            try:
                audit.record(conn, 'auth', path, 'ACCESS_DENIED', user=user,
                             new_data={'method': self.command, 'required': reason},
                             ip_address=self.client_ip())
            finally:
                conn.close()
        except Exception:
            pass

        if path.startswith('/api/'):
            self._set_json_headers(403)
            self.wfile.write(json.dumps({
                'error': 'Ruxsat etilmagan',
                'detail': "Bu amal uchun sizning lavozimingizda ruxsat yo'q.",
                'required': reason,
            }, ensure_ascii=False).encode('utf-8'))
        else:
            # Send them somewhere they are allowed to be rather than showing an
            # empty shell they cannot populate.
            self.send_response(302)
            self.send_header('Location', permissions.home_for(user))
            self.end_headers()
        return True

    def enforce_auth(self, path):
        """
        Authenticate, then authorize. True when the request has been refused
        and the caller should stop processing.
        """
        if not auth.requires_session(path):
            return False

        sess = self.current_session()
        if not sess:
            return self._reject_unauthenticated(path)

        user = sess['user']

        # An account still on the password it was issued may only reach the
        # change-password screen and the endpoints that serve it.
        if auth.must_change_password(user) and path not in (
                '/change-password.html', '/api/auth/change-password', '/api/auth/session'):
            if path.startswith('/api/'):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({
                    'error': "Parolni o'zgartirish talab qilinadi",
                    'detail': "Davom etishdan oldin standart parolni o'zgartiring.",
                    'change_password_url': '/change-password.html',
                }, ensure_ascii=False).encode('utf-8'))
            else:
                self.send_response(302)
                self.send_header('Location', '/change-password.html')
                self.end_headers()
            return True

        if path.startswith('/api/'):
            allowed, reason = permissions.authorize_api(user, self.command, path)
        else:
            allowed, reason = permissions.authorize_page(user, path)
        if not allowed:
            return self._reject_unauthorized(path, reason, user)
        return False

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('X-Robots-Tag', 'noindex, nofollow, noarchive')
        super().end_headers()

    def _set_json_headers(self, status=200):
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            self.end_headers()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_OPTIONS(self):
        self._set_json_headers(200)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if self.enforce_auth(path):
            return

        # Answered before the database is touched, so a page can still learn
        # whether it is signed in when MySQL is unreachable.
        if path == '/api/auth/session':
            sess = self.current_session()
            user = sess['user'] if sess else None
            payload = {'authenticated': bool(sess), 'user': user}
            if user:
                # The frontend uses these to build the navigation, so each
                # member of staff is shown only the portals their job needs.
                payload.update({
                    'permissions': permissions.permissions_for(user),
                    'modules': permissions.visible_modules(user),
                    'pages': permissions.visible_pages(user),
                    'home': permissions.home_for(user),
                    'role_label': (permissions.ROLES.get(user.get('role')) or {}).get('label'),
                    'must_change_password': auth.must_change_password(user),
                })
            self._set_json_headers(200)
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            return

        if path in ('/', ''):
            self.send_response(302)
            self.send_header('Location', '/superpage.html')
            self.end_headers()
            return

        if path.startswith('/api/'):
            self.handle_api_get(path, query)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.enforce_auth(path):
            return
        if path.startswith('/api/'):
            content_len = int(self.headers.get('Content-Length', 0))
            body_raw = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else '{}'
            try:
                body = json.loads(body_raw)
            except Exception:
                body = {}
            tee = self._Tee(self.wfile)
            self.wfile = tee
            try:
                with WRITE_LOCK:
                    self.handle_api_post(path, body)
            finally:
                self.wfile = tee._inner
                self._audit_mutation(path, body, tee.captured)
        else:
            self._set_json_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.enforce_auth(path):
            return
        if path.startswith('/api/'):
            content_len = int(self.headers.get('Content-Length', 0))
            body_raw = self.rfile.read(content_len).decode('utf-8') if content_len > 0 else '{}'
            try:
                body = json.loads(body_raw)
            except Exception:
                body = {}
            tee = self._Tee(self.wfile)
            self.wfile = tee
            try:
                with WRITE_LOCK:
                    self.handle_api_put(path, body)
            finally:
                self.wfile = tee._inner
                self._audit_mutation(path, body, tee.captured)
        else:
            self._set_json_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.enforce_auth(path):
            return
        if path.startswith('/api/'):
            tee = self._Tee(self.wfile)
            self.wfile = tee
            try:
                with WRITE_LOCK:
                    self.handle_api_delete(path)
            finally:
                self.wfile = tee._inner
                self._audit_mutation(path, {}, tee.captured)
        else:
            self._set_json_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))

    # ------------------------------------------------------------------------
    # API GET HANDLERS (100% Real MySQL 8.0 Database Data)
    # ------------------------------------------------------------------------
    def handle_api_get(self, path, query):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()

            # 0. /api/stats/summary -> Real-Time Hospital KPI summary
            if path == '/api/stats/summary':
                cur.execute("SELECT * FROM v_daily_hospital_kpi")
                kpi_row = cur.fetchone()
                
                # Payment method split
                cur.execute("SELECT COALESCE(SUM(amount), 0.0) FROM payments WHERE payment_method IN ('cash', 'cash_register')")
                cash_paid = cur.fetchone()[0] or 0.0

                cur.execute("SELECT COALESCE(SUM(amount), 0.0) FROM payments WHERE payment_method = 'terminal'")
                terminal_paid = cur.fetchone()[0] or 0.0

                cur.execute("SELECT COALESCE(SUM(amount), 0.0) FROM payments WHERE payment_method IN ('card_transfer', 'payme_click')")
                online_paid = cur.fetchone()[0] or 0.0

                # Staff counts
                cur.execute("SELECT COUNT(*) FROM staff WHERE role IN ('doctor', 'chief_doctor') AND is_active = 1")
                active_doctors = cur.fetchone()[0] or 0

                cur.execute("SELECT COUNT(*) FROM staff WHERE role = 'nurse' AND is_active = 1")
                active_nurses = cur.fetchone()[0] or 0

                # Reception metrics
                cur.execute("SELECT COUNT(*) FROM appointments WHERE appointment_date = DATE('now') AND status != 'cancelled'")
                today_apts = cur.fetchone()[0] or 0

                cur.execute("SELECT COUNT(*) FROM call_logs WHERE status IN ('new', 'in_progress')")
                new_calls = cur.fetchone()[0] or 0

                cur.execute("SELECT COUNT(*) FROM appointments WHERE appointment_date = DATE('now') AND service_type IN ('outpatient', 'home_visit')")
                today_walkins = cur.fetchone()[0] or 0

                # Real-time beds strictly TODAY (Never future reservations)
                cur.execute("""
                    SELECT COUNT(DISTINCT bed_id)
                    FROM admissions
                    WHERE status = 'active'
                      AND DATE('now', 'localtime') >= DATE(start_date)
                      AND DATE('now', 'localtime') <= DATE(COALESCE(actual_end_date, planned_end_date))
                """)
                real_occupied = cur.fetchone()[0] or 0
                real_total = 14
                real_available = max(0, real_total - real_occupied)

                summary = {
                    "total_beds": real_total,
                    "occupied_beds": real_occupied,
                    "available_beds": real_available,
                    "occupancy_rate": kpi_row['occupancy_rate_percent'] if kpi_row else 0.0,
                    "active_inpatients": kpi_row['active_inpatient_count'] if kpi_row else 0,
                    "total_patients": kpi_row['active_patient_count'] if kpi_row else 0,
                    "gross_revenue": kpi_row['total_revenue_billed'] if kpi_row else 0.0,
                    "total_paid": kpi_row['total_revenue_collected'] if kpi_row else 0.0,
                    "balance_due": kpi_row['total_outstanding_debt'] if kpi_row else 0.0,
                    "paid_cash": cash_paid,
                    "paid_terminal": terminal_paid,
                    "paid_online": online_paid,
                    "active_doctors": active_doctors,
                    "active_nurses": active_nurses,
                    "today_appointments": today_apts,
                    "new_calls": new_calls,
                    "today_walkins": today_walkins,
                    "active_prescriptions": kpi_row['active_prescriptions_count'] if kpi_row else 0
                }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(summary, ensure_ascii=False).encode('utf-8'))

            # 1. /api/beds -> Live Bed status with room & active admission
            elif path == '/api/beds':
                cur.execute("SELECT * FROM v_bed_live_status")
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 2. /api/admissions -> List all bookings/admissions
            elif path == '/api/admissions':
                cur.execute("""
                    SELECT a.*, p.patient_code, p.full_name AS patient_name, p.phone AS patient_phone,
                           b.bed_code, r.room_number, r.floor_number, s.full_name AS doctor_name,
                           inv.total_billed, inv.discount_amount, inv.net_amount, inv.total_paid, inv.balance_due, inv.payment_status
                    FROM admissions a
                    JOIN patients p ON a.patient_id = p.id
                    JOIN beds b ON a.bed_id = b.id
                    JOIN rooms r ON b.room_id = r.id
                    LEFT JOIN staff s ON a.attending_doctor_id = s.id
                    LEFT JOIN invoices inv ON a.id = inv.admission_id
                    ORDER BY a.start_date DESC, a.created_at DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 3. /api/patients -> List all registered patients
            elif path == '/api/patients' or path == '/api/crm/patients':
                cur.execute("""
                    SELECT p.*,
                           (SELECT COUNT(*) FROM admissions a WHERE a.patient_id = p.id) AS total_admissions_count,
                           (SELECT COALESCE(SUM(inv.net_amount), 0.0) FROM admissions a JOIN invoices inv ON a.id = inv.admission_id WHERE a.patient_id = p.id) AS total_billed,
                           (SELECT COALESCE(SUM(inv.total_paid), 0.0) FROM admissions a JOIN invoices inv ON a.id = inv.admission_id WHERE a.patient_id = p.id) AS total_paid,
                           (SELECT COALESCE(SUM(inv.balance_due), 0.0) FROM admissions a JOIN invoices inv ON a.id = inv.admission_id WHERE a.patient_id = p.id) AS balance_due
                    FROM patients p
                    ORDER BY p.created_at DESC
                """)
                patients = [dict(r) for r in cur.fetchall()]

                # Enrich with active admission and latest vitals
                for pt in patients:
                    cur.execute("""
                        SELECT a.id AS admission_id, a.bed_id, b.bed_code, r.room_number, r.floor_number,
                               a.start_date, a.planned_end_date, a.daily_price, a.program_type, a.status AS admission_status,
                               a.attending_doctor_id AS doctor_id, s.full_name AS doctor_name
                        FROM admissions a
                        JOIN beds b ON a.bed_id = b.id
                        JOIN rooms r ON b.room_id = r.id
                        LEFT JOIN staff s ON a.attending_doctor_id = s.id
                        WHERE a.patient_id = ? AND a.status = 'active'
                        LIMIT 1
                    """, (pt['id'],))
                    active_adm = cur.fetchone()
                    pt['active_admission'] = dict(active_adm) if active_adm else None

                    # Also fetch consulting doctor from latest medical history
                    cur.execute("""
                        SELECT mh.doctor_id, s.full_name AS doctor_name
                        FROM medical_histories mh
                        LEFT JOIN staff s ON mh.doctor_id = s.id
                        WHERE mh.patient_id = ?
                        ORDER BY mh.created_at DESC LIMIT 1
                    """, (pt['id'],))
                    doc_mh = cur.fetchone()
                    if doc_mh:
                        pt['consulting_doctor_id'] = doc_mh['doctor_id'] if isinstance(doc_mh, dict) else doc_mh[0]
                        pt['consulting_doctor_name'] = doc_mh['doctor_name'] if isinstance(doc_mh, dict) else doc_mh[1]
                    else:
                        pt['consulting_doctor_id'] = None
                        pt['consulting_doctor_name'] = None

                    pt['doctor_id'] = (pt.get('active_admission') and pt['active_admission'].get('doctor_id')) or pt.get('consulting_doctor_id')
                    pt['doctor_name'] = (pt.get('active_admission') and pt['active_admission'].get('doctor_name')) or pt.get('consulting_doctor_name')

                    cur.execute("""
                        SELECT dl.vital_bp_systolic, dl.vital_bp_diastolic, dl.vital_pulse, dl.vital_temp, dl.vital_spo2, dl.log_date, dl.nurse_notes
                        FROM daily_logs dl
                        JOIN admissions a ON dl.admission_id = a.id
                        WHERE a.patient_id = ?
                        ORDER BY dl.log_date DESC, dl.id DESC
                        LIMIT 1
                    """, (pt['id'],))
                    vit = cur.fetchone()
                    pt['latest_vitals'] = dict(vit) if vit else None

                self._set_json_headers(200)
                self.wfile.write(json.dumps(patients, ensure_ascii=False).encode('utf-8'))

            # 3b. /api/crm/patients/<id> -> Full Patient Dossier
            elif path.startswith('/api/crm/patients/'):
                patient_id = path.replace('/api/crm/patients/', '')
                cur.execute("SELECT * FROM patients WHERE id = ? OR patient_code = ?", (patient_id, patient_id))
                pt_row = cur.fetchone()
                if not pt_row:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Patient not found'}).encode('utf-8'))
                else:
                    pt_dict = dict(pt_row)
                    actual_id = pt_dict['id']

                    # All admissions
                    cur.execute("""
                        SELECT a.*, b.bed_code, b.bed_type, r.room_number, r.floor_number, r.room_name_uz,
                               s.full_name AS doctor_name, s.specialty AS doctor_specialty,
                               inv.id AS invoice_id, inv.total_billed, inv.discount_amount, inv.net_amount, inv.total_paid, inv.balance_due, inv.payment_status
                        FROM admissions a
                        JOIN beds b ON a.bed_id = b.id
                        JOIN rooms r ON b.room_id = r.id
                        LEFT JOIN staff s ON a.attending_doctor_id = s.id
                        LEFT JOIN invoices inv ON a.id = inv.admission_id
                        WHERE a.patient_id = ?
                        ORDER BY a.start_date DESC
                    """, (actual_id,))
                    pt_dict['admissions'] = [dict(a) for a in cur.fetchall()]

                    # All payments
                    cur.execute("""
                        SELECT p.*, inv.admission_id, s.full_name AS received_by_name
                        FROM payments p
                        JOIN invoices inv ON p.invoice_id = inv.id
                        JOIN admissions a ON inv.admission_id = a.id
                        LEFT JOIN staff s ON p.received_by_staff_id = s.id
                        WHERE a.patient_id = ?
                        ORDER BY p.payment_date DESC
                    """, (actual_id,))
                    pt_dict['payments'] = [dict(pm) for pm in cur.fetchall()]

                    # All vitals logs
                    cur.execute("""
                        SELECT dl.*, s.full_name AS nurse_name
                        FROM daily_logs dl
                        JOIN admissions a ON dl.admission_id = a.id
                        LEFT JOIN staff s ON dl.recorded_by_staff_id = s.id
                        WHERE a.patient_id = ?
                        ORDER BY dl.log_date DESC
                    """, (actual_id,))
                    pt_dict['daily_logs'] = [dict(dl) for dl in cur.fetchall()]

                    # Financial summary
                    cur.execute("""
                        SELECT COALESCE(SUM(inv.net_amount), 0.0) AS total_billed,
                               COALESCE(SUM(inv.total_paid), 0.0) AS total_paid,
                               COALESCE(SUM(inv.balance_due), 0.0) AS balance_due
                        FROM admissions a
                        JOIN invoices inv ON a.id = inv.admission_id
                        WHERE a.patient_id = ?
                    """, (actual_id,))
                    fin = cur.fetchone()
                    pt_dict['financials'] = dict(fin) if fin else {'total_billed': 0, 'total_paid': 0, 'balance_due': 0}

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(pt_dict, ensure_ascii=False).encode('utf-8'))

            # 4. /api/staff -> List doctors & medical staff
            elif path == '/api/staff' or path == '/api/hr/staff':
                cur.execute("SELECT * FROM staff WHERE is_active = 1 ORDER BY role, full_name")
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 5. /api/financial-ledger -> Full billing and payment balance sheet
            elif path == '/api/financial-ledger':
                cur.execute("SELECT * FROM v_financial_ledger")
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 6. /api/daily-logs/<admission_id>
            elif path.startswith('/api/daily-logs/'):
                admission_id = path.replace('/api/daily-logs/', '')
                cur.execute("""
                    SELECT dl.*, s.full_name AS nurse_name
                    FROM daily_logs dl
                    LEFT JOIN staff s ON dl.recorded_by_staff_id = s.id
                    WHERE dl.admission_id = ?
                    ORDER BY dl.log_date ASC
                """, (admission_id,))
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 7. /api/accounting/data -> 100% Dynamic MySQL-Powered Accounting Dataset
            elif path == '/api/accounting/data' or path == '/api/accounting':
                # Services catalog
                cur.execute("SELECT id, name, category, unit_price AS rate, description FROM services_catalog WHERE is_active = 1")
                pricing_catalog = [dict(r) for r in cur.fetchall()]

                # Pharmacy stock
                cur.execute("SELECT id, name, category, form, standard_dosage, unit_price, stock_quantity, min_stock_level FROM medications_catalog WHERE is_active = 1")
                pharmacy_stock = [dict(r) for r in cur.fetchall()]

                # Patients billing ledger
                cur.execute("SELECT * FROM v_financial_ledger")
                patients_billing = [dict(r) for r in cur.fetchall()]

                # Transactions (single-source from accounting_transactions)
                transactions = []
                cur.execute("""
                    SELECT id, transaction_type AS type, category, description AS title,
                           amount, payment_method, account_source, related_invoice_id AS invoice_id,
                           transaction_date AS date, '12:00' AS time, 'Kassir' AS cashier, description AS notes
                    FROM accounting_transactions
                    ORDER BY transaction_date DESC, id DESC
                """)
                for r in cur.fetchall():
                    transactions.append(dict(r))

                # Doctor payroll calculations
                cur.execute("""
                    SELECT s.id AS doctor_id, s.full_name AS doctor_name, s.specialty,
                           s.salary_base,
                           (SELECT COUNT(*) FROM admissions a WHERE a.attending_doctor_id = s.id) AS patients_treated,
                           ((SELECT COALESCE(SUM(inv.total_paid), 0.0) FROM admissions a JOIN invoices inv ON a.id = inv.admission_id WHERE a.attending_doctor_id = s.id) * 0.1) AS bonus_amount,
                           (s.salary_base + ((SELECT COALESCE(SUM(inv.total_paid), 0.0) FROM admissions a JOIN invoices inv ON a.id = inv.admission_id WHERE a.attending_doctor_id = s.id) * 0.1)) AS total_pay
                    FROM staff s
                    WHERE s.role IN ('doctor', 'chief_doctor') AND s.is_active = 1
                """)
                doctors_payroll = [dict(r) for r in cur.fetchall()]

                acc_data = {
                    "clinic_info": {
                        "name": "FAYZ MEDICAL HOUSE",
                        "license": "№ 14285-L Toshkent Sh. SSV",
                        "inn": "309812456",
                        "bank_account": "20208000900123456001",
                        "bank_name": "Ipak Yo'li Banki Chilonzor filiali",
                        "mfo": "00444",
                        "address": "Toshkent sh., Chilonzor tumani, Muqimiy ko'chasi 44-uy",
                        "phone": "+998 71 200-44-00",
                        "telegram": "@fayz_medical_house"
                    },
                    "pricing_catalog": pricing_catalog,
                    "pharmacy_stock": pharmacy_stock,
                    "patients_billing": patients_billing,
                    "transactions": transactions,
                    "doctors_payroll": doctors_payroll,
                    "expense_categories": [
                        {"id": "medication_purchase", "name_uz": "Dori-darmon xaridi (Ombor)"},
                        {"id": "salary", "name_uz": "Xodimlar va Shifokorlar maoshi"},
                        {"id": "utilities", "name_uz": "Kommunal to'lovlar & Internet"},
                        {"id": "rent", "name_uz": "Bino ijarasi"},
                        {"id": "food_catering", "name_uz": "Bemorlar oziq-ovqati (Katering)"},
                        {"id": "equipment", "name_uz": "Tibbiy jihozlar & Sarflov materiallari"},
                        {"id": "operational_expense", "name_uz": "Boshqa xo'jalik xarajatlari"}
                    ]
                }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(acc_data, ensure_ascii=False).encode('utf-8'))

            # 8. /api/hr/data -> 100% Dynamic MySQL-Powered HR Dataset
            elif path == '/api/hr/data' or path.startswith('/api/hr'):
                cur.execute("SELECT * FROM staff ORDER BY role, full_name")
                staff_list = [dict(r) for r in cur.fetchall()]

                cur.execute("""
                    SELECT sa.*, s.full_name AS staff_name, s.role, s.specialty
                    FROM staff_attendance sa
                    JOIN staff s ON sa.staff_id = s.id
                    ORDER BY sa.work_date DESC, sa.created_at DESC
                """)
                attendance = [dict(r) for r in cur.fetchall()]

                hr_data = {
                    "facility_info": {
                        "name": "FAYZ MEDICAL HOUSE",
                        "total_floors": 2,
                        "total_beds": 14,
                        "operating_mode": "24/7 Statsionar & Poliklinika"
                    },
                    "duty_tariffs": {
                        "doctor_night": 350000,
                        "nurse_24h": 400000,
                        "sanitar_24h": 300000
                    },
                    "staff": staff_list,
                    "total_staff_count": len(staff_list),
                    "attendance_records": attendance
                }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(hr_data, ensure_ascii=False).encode('utf-8'))

            # 9. /api/reception/* -> Dynamic Reception Portal Data
            elif path == '/api/reception/data' or path == '/api/reception':
                cur.execute("""
                    SELECT apt.*, p.patient_code, s.full_name AS doctor_name, s.specialty AS doctor_specialty
                    FROM appointments apt
                    LEFT JOIN patients p ON apt.patient_id = p.id
                    LEFT JOIN staff s ON apt.doctor_id = s.id
                    ORDER BY apt.appointment_date DESC, apt.appointment_time ASC
                """)
                appointments = [dict(r) for r in cur.fetchall()]

                cur.execute("""
                    SELECT cl.*, s.full_name AS handled_by_name
                    FROM call_logs cl
                    LEFT JOIN staff s ON cl.handled_by_staff_id = s.id
                    ORDER BY cl.call_time DESC
                """)
                call_logs = [dict(r) for r in cur.fetchall()]

                cur.execute("SELECT id, full_name AS name, specialty, role, phone FROM staff WHERE role IN ('doctor', 'chief_doctor') AND is_active = 1")
                doctors = [dict(r) for r in cur.fetchall()]

                cur.execute("SELECT id, name, unit_price, category FROM services_catalog WHERE is_active = 1")
                services = [dict(r) for r in cur.fetchall()]

                rec_data = {
                    "facility_info": {
                        "name": "FAYZ MEDICAL HOUSE",
                        "hotline": "+998 71 200-44-00",
                        "reception_desk": "1-Qavat Qabulxona"
                    },
                    "appointments": appointments,
                    "call_logs": call_logs,
                    "doctors": doctors,
                    "service_types": services,
                    "walk_ins": [a for a in appointments if a.get('service_type') in ('outpatient', 'home_visit')]
                }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rec_data, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/reception/appointments':
                cur.execute("""
                    SELECT apt.*, p.patient_code, s.full_name AS doctor_name
                    FROM appointments apt
                    LEFT JOIN patients p ON apt.patient_id = p.id
                    LEFT JOIN staff s ON apt.doctor_id = s.id
                    ORDER BY apt.appointment_date DESC, apt.appointment_time ASC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/reception/calls':
                cur.execute("""
                    SELECT cl.*, s.full_name AS handled_by_name
                    FROM call_logs cl
                    LEFT JOIN staff s ON cl.handled_by_staff_id = s.id
                    ORDER BY cl.call_time DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            elif path == '/api/reception/walk-ins':
                cur.execute("""
                    SELECT apt.*, p.patient_code, s.full_name AS doctor_name
                    FROM appointments apt
                    LEFT JOIN patients p ON apt.patient_id = p.id
                    LEFT JOIN staff s ON apt.doctor_id = s.id
                    WHERE apt.service_type IN ('outpatient', 'home_visit')
                    ORDER BY apt.appointment_date DESC
                """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 10. /api/doctor/anamnesis (Medical Histories)
            elif path.startswith('/api/doctor/anamnesis'):
                pid = query.get('patient_id', [None])[0]
                if not pid and '/' in path.replace('/api/doctor/anamnesis', ''):
                    pid = path.replace('/api/doctor/anamnesis/', '')
                
                if pid:
                    cur.execute("""
                        SELECT mh.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM medical_histories mh
                        JOIN patients p ON mh.patient_id = p.id OR mh.patient_id = p.patient_code
                        LEFT JOIN staff s ON mh.doctor_id = s.id
                        WHERE mh.patient_id = ? OR p.patient_code = ?
                        ORDER BY mh.updated_at DESC LIMIT 1
                    """, (pid, pid))
                    row = cur.fetchone()
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(dict(row) if row else None, ensure_ascii=False).encode('utf-8'))
                else:
                    cur.execute("""
                        SELECT mh.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM medical_histories mh
                        JOIN patients p ON mh.patient_id = p.id
                        LEFT JOIN staff s ON mh.doctor_id = s.id
                        ORDER BY mh.updated_at DESC
                    """)
                    rows = [dict(r) for r in cur.fetchall()]
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 11. /api/doctor/prescriptions (Medication orders / List Naznacheniy)
            elif path.startswith('/api/doctor/prescriptions'):
                pid = query.get('patient_id', [None])[0]
                if not pid and '/' in path.replace('/api/doctor/prescriptions', ''):
                    pid = path.replace('/api/doctor/prescriptions/', '')
                
                if pid:
                    cur.execute("""
                        SELECT rx.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM prescriptions rx
                        JOIN patients p ON rx.patient_id = p.id OR rx.patient_id = p.patient_code
                        LEFT JOIN staff s ON rx.doctor_id = s.id
                        WHERE rx.patient_id = ? OR p.patient_code = ?
                        ORDER BY rx.created_at DESC
                    """, (pid, pid))
                else:
                    cur.execute("""
                        SELECT rx.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM prescriptions rx
                        JOIN patients p ON rx.patient_id = p.id
                        LEFT JOIN staff s ON rx.doctor_id = s.id
                        ORDER BY rx.created_at DESC
                    """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 12. /api/doctor/notes (Daily progress examination diary)
            elif path.startswith('/api/doctor/notes'):
                pid = query.get('patient_id', [None])[0]
                if not pid and '/' in path.replace('/api/doctor/notes', ''):
                    pid = path.replace('/api/doctor/notes/', '')
                
                if pid:
                    cur.execute("""
                        SELECT dn.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM doctor_daily_notes dn
                        JOIN patients p ON dn.patient_id = p.id OR dn.patient_id = p.patient_code
                        LEFT JOIN staff s ON dn.doctor_id = s.id
                        WHERE dn.patient_id = ? OR p.patient_code = ?
                        ORDER BY dn.note_date DESC, dn.created_at DESC
                    """, (pid, pid))
                else:
                    cur.execute("""
                        SELECT dn.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM doctor_daily_notes dn
                        JOIN patients p ON dn.patient_id = p.id
                        LEFT JOIN staff s ON dn.doctor_id = s.id
                        ORDER BY dn.note_date DESC, dn.created_at DESC
                    """)
                rows = [dict(r) for r in cur.fetchall()]
                self._set_json_headers(200)
                self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 13. /api/doctor/epicrisis (Discharge Epicrises)
            elif path.startswith('/api/doctor/epicrisis'):
                pid = query.get('patient_id', [None])[0]
                if not pid and '/' in path.replace('/api/doctor/epicrisis', ''):
                    pid = path.replace('/api/doctor/epicrisis/', '')
                
                if pid:
                    cur.execute("""
                        SELECT de.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM discharge_epicrises de
                        JOIN patients p ON de.patient_id = p.id OR de.patient_id = p.patient_code
                        LEFT JOIN staff s ON de.doctor_id = s.id
                        WHERE de.patient_id = ? OR p.patient_code = ?
                        ORDER BY de.epicrisis_date DESC, de.created_at DESC LIMIT 1
                    """, (pid, pid))
                    row = cur.fetchone()
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(dict(row) if row else None, ensure_ascii=False).encode('utf-8'))
                else:
                    cur.execute("""
                        SELECT de.*, p.full_name AS patient_name, p.patient_code, s.full_name AS doctor_name
                        FROM discharge_epicrises de
                        JOIN patients p ON de.patient_id = p.id
                        LEFT JOIN staff s ON de.doctor_id = s.id
                        ORDER BY de.epicrisis_date DESC, de.created_at DESC
                    """)
                    rows = [dict(r) for r in cur.fetchall()]
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(rows, ensure_ascii=False).encode('utf-8'))

            # 14. /api/doctor/clinical/<patient_id> -> Complete EMR dossier
            elif path.startswith('/api/doctor/clinical/'):
                pid = path.replace('/api/doctor/clinical/', '')
                cur.execute("SELECT * FROM patients WHERE id = ? OR patient_code = ?", (pid, pid))
                p_row = cur.fetchone()
                if not p_row:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Patient not found'}).encode('utf-8'))
                else:
                    patient = dict(p_row)
                    actual_id = patient['id']

                    # Anamnesis
                    cur.execute("SELECT * FROM medical_histories WHERE patient_id = ? ORDER BY updated_at DESC LIMIT 1", (actual_id,))
                    mh_row = cur.fetchone()
                    patient['anamnesis'] = dict(mh_row) if mh_row else None

                    # Prescriptions
                    cur.execute("SELECT * FROM prescriptions WHERE patient_id = ? ORDER BY created_at DESC", (actual_id,))
                    patient['prescriptions'] = [dict(r) for r in cur.fetchall()]

                    # Daily Notes
                    cur.execute("SELECT * FROM doctor_daily_notes WHERE patient_id = ? ORDER BY note_date DESC", (actual_id,))
                    patient['daily_notes'] = [dict(r) for r in cur.fetchall()]

                    # Epicrisis
                    cur.execute("SELECT * FROM discharge_epicrises WHERE patient_id = ? ORDER BY epicrisis_date DESC LIMIT 1", (actual_id,))
                    epi_row = cur.fetchone()
                    patient['discharge_epicrisis'] = dict(epi_row) if epi_row else None

                    # Active Admission
                    cur.execute("""
                        SELECT a.*, b.bed_code, r.room_number, r.floor_number, s.full_name AS doctor_name
                        FROM admissions a
                        JOIN beds b ON a.bed_id = b.id
                        JOIN rooms r ON b.room_id = r.id
                        LEFT JOIN staff s ON a.attending_doctor_id = s.id
                        WHERE a.patient_id = ? AND a.status = 'active'
                        LIMIT 1
                    """, (actual_id,))
                    adm_row = cur.fetchone()
                    patient['active_admission'] = dict(adm_row) if adm_row else None

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps(patient, ensure_ascii=False).encode('utf-8'))

            # 15. /api/doctor/download-pdf/<patient_id>
            elif path.startswith('/api/doctor/download-pdf/'):
                pid = path.replace('/api/doctor/download-pdf/', '')
                if generate_patient_pdf:
                    try:
                        # generate_patient_pdf() returns the rendered PDF as bytes.
                        # This branch used to pass that value straight to
                        # os.path.exists(), which is never true for a PDF byte
                        # string, so every export fell through to the 404 below.
                        # Both shapes are accepted now: raw bytes, or a path to a
                        # file already written to disk.
                        pdf_result = generate_patient_pdf(pid)
                        pdf_data = None
                        if isinstance(pdf_result, (bytes, bytearray)):
                            pdf_data = bytes(pdf_result)
                        elif pdf_result and isinstance(pdf_result, str) and os.path.exists(pdf_result):
                            with open(pdf_result, 'rb') as f:
                                pdf_data = f.read()
                        if pdf_data:
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/pdf')
                            self.send_header('Content-Disposition', f'attachment; filename="Fayz_Medical_History_{pid}.pdf"')
                            self.send_header('Content-Length', str(len(pdf_data)))
                            self.end_headers()
                            self.wfile.write(pdf_data)
                            return
                    except Exception as e_pdf:
                        print("PDF Generation error:", e_pdf)
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'PDF generator unavailable or patient not found'}).encode('utf-8'))

            # 16. /api/settings/pricing -> Dynamic Pricing Config
            elif path == '/api/settings/pricing':
                pricing_file = os.path.join(BASE_DIR, 'data', 'pricing_config.json')
                if os.path.exists(pricing_file):
                    try:
                        with open(pricing_file, 'r', encoding='utf-8') as f:
                            p_data = json.load(f)
                    except Exception:
                        p_data = {}
                else:
                    p_data = {
                        "packages": {
                            "statsionar_shared": {"daily_rate": 720000, "name_uz": "Statsionar (1 karavot / 2 kishilik xona)"},
                            "statsionar_full_room": {"daily_rate": 1100000, "name_uz": "Statsionar Butun Xona (VIP Solo)"},
                            "kunlik_statsionar": {"daily_rate": 630000, "name_uz": "Kunlik Statsionar (Kunduzgi o'rin)"},
                            "ambulator_1": {"daily_rate": 310000, "name_uz": "Ambulator (1 mahal)"},
                            "ambulator_2": {"daily_rate": 500000, "name_uz": "Ambulator (2 mahal)"}
                        },
                        "additional_services": []
                    }
                self._set_json_headers(200)
                self.wfile.write(json.dumps(p_data, ensure_ascii=False).encode('utf-8'))

            # 17. /api/users -> List platform user accounts
            elif path == '/api/users':
                users_file = os.path.join(BASE_DIR, 'data', 'users.json')
                if os.path.exists(users_file):
                    try:
                        with open(users_file, 'r', encoding='utf-8') as f:
                            u_data = json.load(f)
                    except Exception:
                        u_data = []
                else:
                    u_data = []
                sanitized = []
                for u in u_data:
                    u_copy = dict(u)
                    u_copy['password'] = '********'
                    sanitized.append(u_copy)
                self._set_json_headers(200)
                self.wfile.write(json.dumps(sanitized, ensure_ascii=False).encode('utf-8'))

            # 18. /api/facility/rooms -> Rooms & Bed layout
            elif path == '/api/facility/rooms':
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                if os.path.exists(rooms_file):
                    try:
                        with open(rooms_file, 'r', encoding='utf-8') as f:
                            r_data = json.load(f)
                    except Exception:
                        r_data = {"floors": []}
                else:
                    r_data = {"floors": []}
                self._set_json_headers(200)
                self.wfile.write(json.dumps(r_data, ensure_ascii=False).encode('utf-8'))

            else:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'API Endpoint not found'}).encode('utf-8'))

        except Exception as e:
            traceback.print_exc()
            self._set_json_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

    # ------------------------------------------------------------------------
    # API POST HANDLERS (100% Real MySQL Database Data & Triggers)
    # ------------------------------------------------------------------------
    def handle_api_post(self, path, body):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()

            # 1. POST /api/admissions (Book / Admit Inpatient via Atomic db.py Workflow)
            if path == '/api/admissions':
                patient_id = body.get('patient_id')
                patient_name = (body.get('patient_name') or 'Yangi Bemor').strip()
                patient_phone = body.get('patient_phone', '')
                bed_id = body.get('bed_id')
                start_date = (body.get('start_date') or datetime.date.today().isoformat())[:10]
                end_date = (body.get('planned_end_date') or body.get('end_date') or datetime.date.today().isoformat())[:10]
                daily_price = float(body.get('daily_price', 720000.0))
                doc_id = body.get('attending_doctor_id') or body.get('doctor_id')

                if not patient_id:
                    # Auto-create patient
                    patient_id = f"PAT-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                    pcode = f"FMH-2026-{patient_id[-4:]}"
                    cur.execute("""
                        INSERT INTO patients (id, patient_code, full_name, phone, referral_source, is_anonymous, status)
                        VALUES (?, ?, ?, ?, 'reception', 0, 'active')
                    """, (patient_id, pcode, patient_name, patient_phone))
                    conn.commit()

                if not doc_id:
                    cur.execute("SELECT id FROM staff WHERE role IN ('doctor', 'chief_doctor') AND is_active = 1 LIMIT 1")
                    doc_row = cur.fetchone()
                    doc_id = (doc_row['id'] if isinstance(doc_row, dict) or hasattr(doc_row, 'keys') else doc_row[0]) if doc_row else None

                prog_type = body.get('program_type') or 'detox'

                success, res_data = admit_patient(
                    conn, patient_id, bed_id, doc_id, prog_type,
                    start_date, end_date, daily_price, body.get('notes', '')
                )

                if not success:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': str(res_data)}, ensure_ascii=False).encode('utf-8'))
                    return

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': 'Admission created successfully',
                    'id': res_data.get('admission_id'),
                    'admission_id': res_data.get('admission_id'),
                    'invoice_id': res_data.get('invoice_id'),
                    'patient_id': patient_id,
                    'days': res_data.get('days'),
                    'bed_code': res_data.get('bed_code')
                }, ensure_ascii=False).encode('utf-8'))

            # 1b. POST /api/admissions/<id>/discharge or /api/admissions/discharge
            elif '/discharge' in path:
                adm_id = body.get('admission_id') or (path.split('/')[3] if len(path.split('/')) > 3 else None)
                today_str = datetime.date.today().isoformat()
                discharge_date = (body.get('discharge_date') or body.get('actual_end_date') or today_str)[:10]
                summary = body.get('discharge_summary') or body.get('summary') or "Statsionardan chiqarildi"

                success, res_data = discharge_patient(conn, adm_id, discharge_date, summary)
                if not success:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': str(res_data)}, ensure_ascii=False).encode('utf-8'))
                    return

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Bemor muvaffaqiyatli chiqarildi va karavot tozalash holatiga (cleaning) o\'tkazildi',
                    'result': res_data
                }, ensure_ascii=False).encode('utf-8'))

            # 1c. POST /api/admissions/<id>/transfer or /api/admissions/transfer
            elif '/transfer' in path:
                adm_id = body.get('admission_id') or (path.split('/')[3] if len(path.split('/')) > 3 else None)
                new_bed_id = body.get('new_bed_id')
                transfer_date = (body.get('transfer_date') or datetime.date.today().isoformat())[:10]
                reason = body.get('reason') or "Palata ko'chirildi"
                staff_id = body.get('staff_id') or 'STF-REC-01'

                success, res_data = transfer_patient_bed(conn, adm_id, new_bed_id, transfer_date, reason, staff_id)
                if not success:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': str(res_data)}, ensure_ascii=False).encode('utf-8'))
                    return

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Bemor yangi karavotga ko\'chirildi, avvalgi karavot tozalashga yuborildi',
                    'result': res_data
                }, ensure_ascii=False).encode('utf-8'))

            # 1d. POST /api/beds/<id>/status or /api/beds/<id>/clean (Sanitation Handover)
            elif path.startswith('/api/beds/') and (path.endswith('/status') or path.endswith('/clean')):
                bed_id = path.split('/')[3]
                # The beds.status column accepts only the physical states in its
                # CHECK constraint: operational, cleaning, maintenance,
                # out_of_service. 'available', 'occupied' and 'reserved' are
                # values the v_bed_live_status view DERIVES from admissions, not
                # things that can be stored. This route used to map the other way
                # round -- rewriting 'operational' to 'available' -- so every
                # request violated beds_chk_3 and failed with a 500. Discharge and
                # transfer both leave a bed 'cleaning', so the action that returns
                # it to service never worked and beds accumulated as unusable.
                PHYSICAL = {'operational', 'cleaning', 'maintenance', 'out_of_service'}
                DERIVED_TO_PHYSICAL = {'available': 'operational',
                                       'occupied': 'operational',
                                       'reserved': 'operational'}
                requested = 'operational' if path.endswith('/clean') else str(body.get('status', 'operational')).strip().lower()
                new_status = DERIVED_TO_PHYSICAL.get(requested, requested)
                if new_status not in PHYSICAL:
                    new_status = 'operational'

                cur.execute("UPDATE beds SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? OR bed_code = ?", (new_status, bed_id, bed_id))
                conn.commit()

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': f"Karavot holati muvaffaqiyatli saqlandi: {new_status}",
                    'bed_id': bed_id,
                    'status': new_status
                }, ensure_ascii=False).encode('utf-8'))

            # 2. POST /api/payments (Record Signed Patient Payment or Refund Payout)
            elif path == '/api/payments' or path == '/api/crm/payments':
                # Same bounded random space as patient ids: probe for a free id so a
                # collision cannot reject a real payment.
                pay_id = body.get('id')
                if not pay_id:
                    for _ in range(200):
                        candidate = f"PAY-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                        cur.execute("SELECT 1 FROM payments WHERE id = ? LIMIT 1", (candidate,))
                        if not cur.fetchone():
                            pay_id = candidate
                            break
                    if not pay_id:
                        pay_id = f"PAY-2026-{int(datetime.datetime.now().timestamp() * 1000)}"
                inv_id = body.get('invoice_id')
                amount = float(body.get('amount', 0))

                # Normalize payment method
                raw_method = str(body.get('payment_method', 'cash')).lower()
                method_map = {
                    'cash': 'cash', 'cash_register': 'cash_register',
                    'card': 'terminal', 'terminal': 'terminal',
                    'card_transfer': 'card_transfer', 'online': 'payme_click',
                    'payme_click': 'payme_click', 'click': 'payme_click',
                    'payme': 'payme_click', 'bank_wire': 'bank_wire', 'bank': 'bank_wire',
                    'mixed': 'cash'
                }
                method = method_map.get(raw_method, 'cash')

                # Normalize account destination
                raw_acc = str(body.get('account_destination', 'kassa')).lower()
                acc_map = {
                    'kassa': 'kassa', 'bank': 'terminal_bank',
                    'terminal_bank': 'terminal_bank',
                    'click_payme_merchant': 'click_payme_merchant',
                    'main_bank_account': 'main_bank_account'
                }
                acc = acc_map.get(raw_acc, 'kassa')
                pay_date = (body.get('payment_date') or datetime.date.today().isoformat())[:10]

                # If invoice_id not provided directly, resolve from admission_id
                if not inv_id and body.get('admission_id'):
                    cur.execute("SELECT id FROM invoices WHERE admission_id = ?", (body.get('admission_id'),))
                    inv_row = cur.fetchone()
                    if inv_row:
                        inv_id = inv_row['id'] if isinstance(inv_row, dict) or hasattr(inv_row, 'keys') else inv_row[0]

                if not inv_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invoice ID is required for payment'}, ensure_ascii=False).encode('utf-8'))
                    return

                if amount == 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'To`lov summasi 0 bo`lishi mumkin emas'}, ensure_ascii=False).encode('utf-8'))
                    return

                cur.execute("""
                    INSERT INTO payments (id, invoice_id, amount, payment_method, account_destination, transaction_ref, payment_date, notes, received_by_staff_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pay_id,
                    inv_id,
                    amount,
                    method,
                    acc,
                    body.get('transaction_ref', f"CHK-{pay_id[-4:]}"),
                    pay_date,
                    body.get('notes', ''),
                    body.get('received_by_staff_id', 'STF-REC-01')
                ))

                conn.commit()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': 'Payment recorded successfully',
                    'payment_id': pay_id,
                    'invoice_id': inv_id,
                    'amount': amount,
                    'is_refund': amount < 0
                }, ensure_ascii=False).encode('utf-8'))

            # 3. POST /api/accounting/transaction (Create Expense / Incasso / Operational Cash Flow)
            elif path == '/api/accounting/transaction':
                trx_id = body.get('id') or f"TRX-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                amount = float(body.get('amount', 0))
                txn_type = body.get('type', 'expense')
                category = body.get('category', 'operational_expense')
                method = body.get('payment_method', 'cash')
                date_str = (body.get('date') or datetime.date.today().isoformat())[:10]
                desc = body.get('title') or body.get('description') or 'Kassa operatsiyasi'

                cur.execute("""
                    INSERT INTO accounting_transactions (id, transaction_type, category, amount, payment_method, account_source, description, transaction_date)
                    VALUES (?, ?, ?, ?, ?, 'kassa', ?, ?)
                """, (
                    trx_id,
                    txn_type,
                    category,
                    amount,
                    method,
                    desc,
                    date_str
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Transaction saved', 'id': trx_id}, ensure_ascii=False).encode('utf-8'))

            # 4. POST /api/staff or POST /api/hr/staff (Create / Update Staff & Doctor)
            elif path == '/api/staff' or path == '/api/hr/staff':
                raw_role = body.get('role', 'doctor')
                valid_roles = {'admin', 'chief_doctor', 'doctor', 'nurse', 'receptionist', 'accountant'}
                role = raw_role if raw_role in valid_roles else 'admin'

                full_name = (body.get('full_name') or '').strip()
                if not full_name:
                    conn.close()
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Xodim F.I.Sh kiritilishi shart'}, ensure_ascii=False).encode('utf-8'))
                    return
                
                prefix = 'DOC' if role in ('doctor', 'chief_doctor') else ('NRS' if role == 'nurse' else 'ADM')
                cur.execute("SELECT COUNT(*) FROM staff WHERE id LIKE ?", (f"STF-{prefix}-%",))
                count = (cur.fetchone()[0] or 0) + 1
                staff_id = body.get('id') or f"STF-{prefix}-{str(count).zfill(2)}"
                specialty = body.get('specialty', '')
                phone = body.get('phone', '')
                email = body.get('email', '')
                shift_raw = str(body.get('shift_type') or 'day').lower()
                shift_db = 'night' if 'night' in shift_raw else ('24h' if '24h' in shift_raw else ('rotating' if 'call' in shift_raw or 'rotating' in shift_raw else 'day'))
                salary_base = float(body.get('base_salary') or body.get('salary_base') or 10000000.0)

                cur.execute("""
                    INSERT INTO staff (id, full_name, role, specialty, phone, email, salary_base, shift_type, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(id) DO UPDATE SET
                        full_name = excluded.full_name,
                        role = excluded.role,
                        specialty = excluded.specialty,
                        phone = excluded.phone,
                        email = excluded.email,
                        salary_base = excluded.salary_base,
                        shift_type = excluded.shift_type,
                        is_active = 1
                """, (staff_id, full_name, role, specialty, phone, email, salary_base, shift_db))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'message': 'Xodim muvaffaqiyatli saqlandi',
                    'id': staff_id,
                    'staff': {
                        'id': staff_id,
                        'full_name': full_name,
                        'role': role,
                        'specialty': specialty,
                        'phone': phone,
                        'email': email,
                        'base_salary': salary_base,
                        'salary_base': salary_base,
                        'shift_type': shift_raw,
                        'is_active': 1
                    }
                }, ensure_ascii=False).encode('utf-8'))

            # 5. POST /api/crm/patients (Create new patient)
            elif path == '/api/crm/patients' or path == '/api/patients':
                # A random 4-digit id draws from only 9000 values with no uniqueness
                # check, so registrations started failing on duplicate primary keys
                # well before the clinic reached a few hundred patients. Probe for a
                # free id in the same PAT-#### format, falling back to a millisecond
                # timestamp if the random space is saturated.
                pid = body.get('id')
                if not pid:
                    for _ in range(200):
                        candidate = f"PAT-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                        cur.execute("SELECT 1 FROM patients WHERE id = ? LIMIT 1", (candidate,))
                        if not cur.fetchone():
                            pid = candidate
                            break
                    if not pid:
                        pid = f"PAT-{int(datetime.datetime.now().timestamp() * 1000)}"
                pcode = body.get('patient_code') or f"FMH-2026-{pid[-4:]}"
                cur.execute("""
                    INSERT INTO patients (id, patient_code, full_name, phone, emergency_contact, gender, birth_year, referral_source, is_anonymous, medical_allergies, chronic_conditions, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pid,
                    pcode,
                    body.get('full_name', 'Anonim Bemor'),
                    body.get('phone', ''),
                    body.get('emergency_contact', ''),
                    body.get('gender', 'male'),
                    body.get('birth_year', 1990),
                    body.get('referral_source', 'hotline'),
                    1 if body.get('is_anonymous', True) else 0,
                    body.get('medical_allergies', "Yo'q"),
                    body.get('chronic_conditions', "Yo'q"),
                    body.get('status', 'active')
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Patient created', 'id': pid, 'patient_code': pcode}).encode('utf-8'))

            # 6. POST /api/reception/appointment (Book Consultation / Appointment)
            elif path == '/api/reception/appointment':
                apt_id = body.get('id') or f"APT-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                patient_name = (body.get('patient_name') or 'Bemor').strip()
                patient_phone = body.get('patient_phone', '')
                doc_id = body.get('doctor_id')
                date_str = body.get('date') or datetime.date.today().isoformat()
                time_str = body.get('time') or '10:00'
                srv_type = body.get('service_type', 'outpatient')

                # Check if patient exists or auto-create
                cur.execute("SELECT id FROM patients WHERE phone = ? OR full_name = ?", (patient_phone, patient_name))
                p_exist = cur.fetchone()
                if p_exist:
                    patient_id = p_exist[0]
                else:
                    patient_id = f"PAT-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                    cur.execute("""
                        INSERT INTO patients (id, patient_code, full_name, phone, referral_source, is_anonymous, status)
                        VALUES (?, ?, ?, ?, 'reception', 0, 'active')
                    """, (patient_id, f"FMH-2026-{patient_id[-4:]}", patient_name, patient_phone))

                cur.execute("""
                    INSERT INTO appointments (id, patient_id, patient_name, patient_phone, doctor_id, service_type, appointment_date, appointment_time, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    apt_id,
                    patient_id,
                    patient_name,
                    patient_phone,
                    doc_id,
                    srv_type,
                    date_str,
                    time_str,
                    body.get('status', 'confirmed'),
                    body.get('notes', '')
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Appointment booked', 'id': apt_id, 'patient_id': patient_id}, ensure_ascii=False).encode('utf-8'))

            # 7. POST /api/reception/call-log (Log Hotline / CRM Call)
            elif path == '/api/reception/call-log':
                call_id = body.get('id') or f"CALL-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                cur.execute("""
                    INSERT INTO call_logs (id, caller_name, caller_phone, call_direction, source, category, priority, status, notes)
                    VALUES (?, ?, ?, 'inbound', ?, ?, ?, ?, ?)
                """, (
                    call_id,
                    body.get('caller_name', "Noma'lum qo'ng'iroqchi"),
                    body.get('caller_phone', ''),
                    body.get('source', 'hotline'),
                    body.get('category', 'Konsultatsiya'),
                    body.get('priority', 'medium'),
                    body.get('status', 'new'),
                    body.get('notes', '')
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Call log saved', 'id': call_id}, ensure_ascii=False).encode('utf-8'))

            # 8. POST /api/doctor/anamnesis (Save/Update Medical History)
            elif path == '/api/doctor/anamnesis':
                pid = body.get('patient_id')
                cur.execute("SELECT id FROM medical_histories WHERE patient_id = ? OR patient_id = (SELECT id FROM patients WHERE patient_code = ?)", (pid, pid))
                existing = cur.fetchone()
                
                if existing:
                    hid = existing[0]
                    cur.execute("""
                        UPDATE medical_histories
                        SET doctor_id = COALESCE(?, doctor_id),
                            complaints = COALESCE(?, complaints),
                            anamnesis_morbi = COALESCE(?, anamnesis_morbi),
                            anamnesis_vitae = COALESCE(?, anamnesis_vitae),
                            allergic_status = COALESCE(?, allergic_status),
                            somatic_status = COALESCE(?, somatic_status),
                            psychiatric_status = COALESCE(?, psychiatric_status),
                            diagnosis_primary = COALESCE(?, diagnosis_primary),
                            diagnosis_secondary = COALESCE(?, diagnosis_secondary),
                            icd10_code = COALESCE(?, icd10_code),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (
                        body.get('doctor_id'),
                        body.get('complaints'),
                        body.get('anamnesis_morbi'),
                        body.get('anamnesis_vitae'),
                        body.get('allergic_status'),
                        body.get('somatic_status'),
                        body.get('psychiatric_status'),
                        body.get('diagnosis_primary'),
                        body.get('diagnosis_secondary'),
                        body.get('icd10_code'),
                        hid
                    ))
                else:
                    hid = body.get('id') or f"MH-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                    cur.execute("""
                        INSERT INTO medical_histories (id, patient_id, admission_id, doctor_id, complaints, anamnesis_morbi, anamnesis_vitae, allergic_status, somatic_status, psychiatric_status, diagnosis_primary, diagnosis_secondary, icd10_code)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        hid,
                        pid,
                        body.get('admission_id'),
                        body.get('doctor_id', 'STF-DOC-01'),
                        body.get('complaints', ''),
                        body.get('anamnesis_morbi', ''),
                        body.get('anamnesis_vitae', ''),
                        body.get('allergic_status', ''),
                        body.get('somatic_status', ''),
                        body.get('psychiatric_status', ''),
                        body.get('diagnosis_primary', ''),
                        body.get('diagnosis_secondary', ''),
                        body.get('icd10_code', 'F10.2')
                    ))
                
                if body.get('allergic_status'):
                    cur.execute("UPDATE patients SET medical_allergies = ? WHERE id = ? OR patient_code = ?", (body.get('allergic_status'), pid, pid))

                conn.commit()
                conn.close()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Medical history saved', 'id': hid}).encode('utf-8'))

            # 9. POST /api/doctor/prescriptions (Add medication order)
            elif path == '/api/doctor/prescriptions':
                rx_id = body.get('id') or f"RX-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                cur.execute("""
                    INSERT INTO prescriptions (id, patient_id, admission_id, doctor_id, medication_name, form, dosage, route, frequency, duration_days, timing, instructions, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rx_id,
                    body.get('patient_id'),
                    body.get('admission_id'),
                    body.get('doctor_id', 'STF-DOC-01'),
                    body.get('medication_name', ''),
                    body.get('form', 'Infuzion flakon'),
                    body.get('dosage', '400 ml'),
                    body.get('route', 'V/I tomchilab (kapelnitsa)'),
                    body.get('frequency', 'Kuniga 1 mahal'),
                    int(body.get('duration_days', 5)),
                    body.get('timing', 'Ertalab'),
                    body.get('instructions', ''),
                    body.get('status', 'active')
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Prescription created', 'id': rx_id}).encode('utf-8'))

            # 10. POST /api/doctor/notes (Add daily examination note)
            elif path == '/api/doctor/notes':
                cur.execute("""
                    INSERT INTO doctor_daily_notes (patient_id, admission_id, doctor_id, note_date, patient_condition, vital_bp, vital_pulse, vital_temp, vital_spo2, dynamics_notes, treatment_adjustments)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    body.get('patient_id'),
                    body.get('admission_id'),
                    body.get('doctor_id', 'STF-DOC-01'),
                    body.get('note_date', datetime.date.today().isoformat()),
                    body.get('patient_condition', 'moderate'),
                    body.get('vital_bp', '120/80'),
                    int(body.get('vital_pulse', 72)),
                    float(body.get('vital_temp', 36.6)),
                    int(body.get('vital_spo2', 98)),
                    body.get('dynamics_notes', 'Holat barqaror'),
                    body.get('treatment_adjustments', '')
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Daily note saved'}).encode('utf-8'))

            # 11. POST /api/doctor/epicrisis (Save Discharge Epicrisis)
            elif path == '/api/doctor/epicrisis':
                epi_id = body.get('id') or f"EPI-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                cur.execute("""
                    INSERT INTO discharge_epicrises (id, patient_id, admission_id, doctor_id, epicrisis_date, diagnosis_final, icd10_code, treatment_summary, home_prescriptions, psycho_recommendations, discharge_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    epi_id,
                    body.get('patient_id'),
                    body.get('admission_id'),
                    body.get('doctor_id', 'STF-DOC-01'),
                    body.get('epicrisis_date', datetime.date.today().isoformat()),
                    body.get('diagnosis_final', 'Alkogol intoksikatsiyasi remissiya davri'),
                    body.get('icd10_code', 'F10.2'),
                    body.get('treatment_summary', ''),
                    body.get('home_prescriptions', ''),
                    body.get('psycho_recommendations', ''),
                    body.get('discharge_status', 'recovered')
                ))
                conn.commit()
                conn.close()
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Epicrisis saved', 'id': epi_id}).encode('utf-8'))

            # 11b. POST /api/doctor/consultation-case (Atomic Consultation, Kasallik Varaqasi & Retseptlar)
            elif path == '/api/doctor/consultation-case':
                doc_id = body.get('doctor_id') or 'STF-DOC-01'
                doc_name = body.get('doctor_name') or 'Dr. Bobur Mirzayev'
                
                # Verify doctor name from staff table if possible
                try:
                    cur.execute("SELECT full_name FROM staff WHERE id = ?", (doc_id,))
                    d_row = cur.fetchone()
                    if d_row:
                        doc_name = d_row['full_name'] if isinstance(d_row, dict) else d_row[0]
                except Exception:
                    pass

                pt_data = body.get('patient') or {}
                pt_name = (pt_data.get('full_name') or body.get('patient_name') or 'Yangi Bemor').strip()
                pt_phone = pt_data.get('phone') or body.get('patient_phone') or ''
                pt_gender = pt_data.get('gender') or body.get('gender') or 'male'
                pt_birth = int(pt_data.get('birth_year') or body.get('birth_year') or 1990)
                pt_address = pt_data.get('address') or body.get('address') or ''
                pt_emergency = pt_data.get('emergency_contact') or body.get('emergency_contact') or ''

                anam_data = body.get('anamnesis') or {}
                allergy = anam_data.get('allergic_status') or body.get('allergic_status', "Yo'q")

                pid = body.get('patient_id') or pt_data.get('id')
                p_row = None
                if pid:
                    cur.execute("SELECT id, patient_code FROM patients WHERE id = ? OR patient_code = ?", (pid, pid))
                    p_row = cur.fetchone()
                elif pt_phone:
                    cur.execute("SELECT id, patient_code FROM patients WHERE phone = ?", (pt_phone,))
                    p_row = cur.fetchone()

                if p_row:
                    patient_id = p_row['id'] if isinstance(p_row, dict) else p_row[0]
                    patient_code = p_row['patient_code'] if isinstance(p_row, dict) else p_row[1]
                    cur.execute("""
                        UPDATE patients 
                        SET full_name = ?, phone = ?, emergency_contact = ?, gender = ?, birth_year = ?, address = ?, medical_allergies = ?, status = 'active', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (pt_name, pt_phone, pt_emergency, pt_gender, pt_birth, pt_address, allergy, patient_id))
                else:
                    patient_id = f"PAT-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                    patient_code = f"FMH-2026-{patient_id[-4:]}"
                    cur.execute("""
                        INSERT INTO patients (id, patient_code, full_name, phone, emergency_contact, gender, birth_year, address, referral_source, is_anonymous, medical_allergies, chronic_conditions, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'doctor_consultation', 0, ?, "Yo'q", 'active')
                    """, (patient_id, patient_code, pt_name, pt_phone, pt_emergency, pt_gender, pt_birth, pt_address, allergy))
                conn.commit()

                consultation_type = body.get('consultation_type', 'outpatient')
                admission_id = None

                if consultation_type == 'inpatient':
                    inpatient_info = body.get('inpatient_details') or {}
                    bed_id = inpatient_info.get('bed_id')
                    prog_type = inpatient_info.get('program_type') or 'Statsionar davolanish'
                    start_date = (inpatient_info.get('start_date') or datetime.date.today().isoformat())[:10]
                    end_date = (inpatient_info.get('end_date') or datetime.date.today().isoformat())[:10]
                    daily_price = float(inpatient_info.get('daily_price') or 720000.0)

                    if bed_id:
                        success, res_data = admit_patient(
                            conn, patient_id, bed_id, doc_id, prog_type,
                            start_date, end_date, daily_price, body.get('notes', f"Shifokor {doc_name} statsionar ko'rigi")
                        )
                        if success:
                            admission_id = res_data.get('admission_id')
                            try:
                                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                                if os.path.exists(rooms_file):
                                    with open(rooms_file, 'r', encoding='utf-8') as rf:
                                        cr_data = json.load(rf)
                                    bookings_list = cr_data.get('sample_calendar_bookings', [])
                                    bookings_list.append({
                                        'id': admission_id,
                                        'bed_id': res_data.get('bed_code') or bed_id,
                                        'patient_name': pt_name,
                                        'patient_phone': pt_phone,
                                        'doctor': doc_name,
                                        'program': prog_type,
                                        'daily_rate': daily_price,
                                        'start_date': start_date,
                                        'end_date': end_date,
                                        'status': 'active'
                                    })
                                    cr_data['sample_calendar_bookings'] = bookings_list
                                    write_json_atomic(rooms_file, cr_data)
                            except Exception as e_cr:
                                print("Warning syncing clinic_rooms.json on admission:", e_cr)

                apt_id = f"APT-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                apt_service = 'inpatient_consult' if consultation_type == 'inpatient' else 'outpatient'
                cur.execute("""
                    INSERT INTO appointments (id, patient_id, patient_name, patient_phone, doctor_id, service_type, appointment_date, appointment_time, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?)
                """, (
                    apt_id,
                    patient_id,
                    pt_name,
                    pt_phone,
                    doc_id,
                    apt_service,
                    datetime.date.today().isoformat(),
                    datetime.datetime.now().strftime('%H:%M'),
                    body.get('notes', f"Shifokor {doc_name} konsultatsiyasi")
                ))
                conn.commit()

                hid = f"MH-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                complaints = anam_data.get('complaints') or body.get('complaints', '')
                anam_morbi = anam_data.get('anamnesis_morbi') or body.get('anamnesis_morbi', '')
                anam_vitae = anam_data.get('anamnesis_vitae') or body.get('anamnesis_vitae', '')
                somatic = anam_data.get('somatic_status') or body.get('somatic_status', '')
                psychiatric = anam_data.get('psychiatric_status') or body.get('psychiatric_status', '')
                diag_pri = anam_data.get('diagnosis_primary') or body.get('diagnosis_primary', '')
                diag_sec = anam_data.get('diagnosis_secondary') or body.get('diagnosis_secondary', '')
                icd10 = anam_data.get('icd10_code') or body.get('icd10_code', 'F10.2')

                cur.execute("""
                    INSERT INTO medical_histories (id, patient_id, admission_id, doctor_id, complaints, anamnesis_morbi, anamnesis_vitae, allergic_status, somatic_status, psychiatric_status, diagnosis_primary, diagnosis_secondary, icd10_code)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    hid,
                    patient_id,
                    admission_id,
                    doc_id,
                    complaints,
                    anam_morbi,
                    anam_vitae,
                    allergy,
                    somatic,
                    psychiatric,
                    diag_pri,
                    diag_sec,
                    icd10
                ))
                conn.commit()

                rx_items = body.get('prescriptions') or []
                saved_rx = []
                for rx in rx_items:
                    rx_id = f"RX-2026-{int(os.urandom(3).hex(), 16) % 9000 + 1000}"
                    med_name = rx.get('medication_name') or rx.get('name', '')
                    if not med_name:
                        continue
                    form = rx.get('form') or 'Infuzion flakon'
                    dosage = rx.get('dosage') or '400 ml'
                    route = rx.get('route') or 'V/I tomchilab (kapelnitsa)'
                    frequency = rx.get('frequency') or 'Kuniga 1 mahal'
                    duration = int(rx.get('duration_days') or rx.get('duration') or 5)
                    timing = rx.get('timing') or 'Ertalab'
                    instructions = rx.get('instructions') or ''

                    cur.execute("""
                        INSERT INTO prescriptions (id, patient_id, admission_id, doctor_id, medication_name, form, dosage, route, frequency, duration_days, timing, instructions, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                    """, (
                        rx_id,
                        patient_id,
                        admission_id,
                        doc_id,
                        med_name,
                        form,
                        dosage,
                        route,
                        frequency,
                        duration,
                        timing,
                        instructions
                    ))
                    saved_rx.append(rx_id)

                conn.commit()
                conn.close()

                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'success': True,
                    'message': f"Kasallik varaqasi va {len(saved_rx)} ta dori retsepti muvaffaqiyatli rasmiylashtirildi!",
                    'patient_id': patient_id,
                    'patient_code': patient_code,
                    'patient_name': pt_name,
                    'doctor_id': doc_id,
                    'doctor_name': doc_name,
                    'admission_id': admission_id,
                    'history_id': hid,
                    'prescriptions_count': len(saved_rx),
                    'consultation_type': consultation_type
                }, ensure_ascii=False).encode('utf-8'))

            # 12. POST /api/settings/pricing (Superadmin updates any price dynamically)
            elif path == '/api/settings/pricing':
                pricing_file = os.path.join(BASE_DIR, 'data', 'pricing_config.json')
                existing = read_json_file(pricing_file, {})
                
                if 'packages' in body:
                    if 'packages' not in existing:
                        existing['packages'] = {}
                    existing['packages'].update(body['packages'])
                if 'additional_services' in body:
                    existing['additional_services'] = body['additional_services']
                existing['updated_at'] = datetime.datetime.now().isoformat()
                existing['updated_by'] = body.get('updated_by', 'superadmin')

                write_json_atomic(pricing_file, existing)

                # Also update MySQL beds default_daily_rate if shared rate updated
                if 'packages' in body and 'statsionar_shared' in body['packages']:
                    try:
                        new_shared = float(body['packages']['statsionar_shared'].get('daily_rate', 720000))
                        cur.execute("UPDATE beds SET default_daily_rate = ? WHERE bed_type = 'standard'", (new_shared,))
                        conn.commit()
                    except Exception as e_pr:
                        print("Error updating beds daily_rate:", e_pr)

                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': "Narxlar muvaffaqiyatli saqlandi va barcha bo'limlarga tatbiq etildi", 'pricing': existing}, ensure_ascii=False).encode('utf-8'))

            # 13. POST /api/auth/login
            #
            # Verifies against a PBKDF2 hash (and still accepts a not-yet
            # migrated plaintext record), then issues an HttpOnly session
            # cookie. The password comparison is constant-time, and a failure
            # says only that the pair was wrong — never which half.
            elif path == '/api/auth/login':
                username = (body.get('username') or '').strip().lower()
                password = body.get('password') or ''

                ip = self.client_ip()

                # Refuse while locked out, before the password is even checked,
                # so a throttled attacker learns nothing from the response.
                locked = auth.lockout_remaining(username, ip)
                if locked:
                    minutes = max(1, locked // 60)
                    audit.record(conn, 'auth', username or '-', 'LOGIN_FAILED',
                                 new_data={'reason': 'locked_out', 'seconds_remaining': locked},
                                 ip_address=ip)
                    self._set_json_headers(429)
                    self.wfile.write(json.dumps({
                        'error': "Juda ko'p urinish",
                        'detail': f"Xavfsizlik uchun kirish vaqtincha bloklandi. "
                                  f"{minutes} daqiqadan so'ng qayta urinib ko'ring.",
                        'retry_after_seconds': locked,
                    }, ensure_ascii=False).encode('utf-8'))
                    return

                found = auth.find_user(username)
                ok = bool(found) and found.get('is_active', True) and \
                    auth.verify_password(password, found.get('password'))

                if ok:
                    auth.note_login_success(username, ip)
                    token = auth.create_session(found)
                    user_info = auth.sanitize_user(found)
                    needs_change = auth.must_change_password(found)
                    is_https = self.headers.get('X-Forwarded-Proto') == 'https'
                    audit.ensure_schema(conn)
                    audit.record(conn, 'auth', username, 'LOGIN', user=found,
                                 new_data={'role': found.get('role')}, ip_address=ip)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Set-Cookie', auth.build_session_cookie(
                        token, secure=is_https, max_age=auth.SESSION_IDLE_SECONDS))
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'message': 'Muvaffaqiyatli tizimga kirildi',
                        'user': user_info,
                        'permissions': permissions.permissions_for(found),
                        'pages': permissions.visible_pages(found),
                        'home': '/change-password.html' if needs_change else permissions.home_for(found),
                        'must_change_password': needs_change,
                    }, ensure_ascii=False).encode('utf-8'))
                    print(f"[auth] login ok: {username} ({found.get('role')})")
                else:
                    remaining = auth.note_login_failure(username, ip)
                    print(f"[auth] login failed for {username!r} from {ip} "
                          f"({remaining} attempt(s) before lockout)")
                    audit.ensure_schema(conn)
                    audit.record(conn, 'auth', username or '-', 'LOGIN_FAILED',
                                 new_data={'attempts_remaining': remaining}, ip_address=ip)
                    self._set_json_headers(401)
                    # The message never distinguishes a wrong username from a
                    # wrong password, so the endpoint cannot be used to find
                    # out which accounts exist.
                    payload = {'error': "Login yoki parol noto'g'ri"}
                    if remaining <= 3:
                        payload['detail'] = (f"Yana {remaining} ta urinish qoldi, "
                                             f"so'ngra kirish vaqtincha bloklanadi.")
                    self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

            # 13b. POST /api/auth/logout — discard the session server-side.
            elif path == '/api/auth/logout':
                token = auth.token_from_cookie_header(self.headers.get('Cookie'))
                sess = auth.get_session(token)
                if sess:
                    audit.ensure_schema(conn)
                    audit.record(conn, 'auth', sess['user'].get('username', '-'),
                                 'LOGOUT', user=sess['user'], ip_address=self.client_ip())
                auth.destroy_session(token)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                # Expire the cookie in the browser too.
                self.send_header('Set-Cookie',
                                 f"{auth.SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
                self.end_headers()
                self.wfile.write(json.dumps({'message': 'Tizimdan chiqildi'}, ensure_ascii=False).encode('utf-8'))

            # 13c. POST /api/auth/change-password
            #
            # Reachable by any signed-in user for their own account, including
            # one still locked to the change-password screen. Changing the
            # password revokes that account's other sessions, so a password
            # handed out and then changed cannot still be in use elsewhere.
            elif path == '/api/auth/change-password':
                sess = self.current_session()
                if not sess:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Avtorizatsiya talab qilinadi'},
                                                ensure_ascii=False).encode('utf-8'))
                    return

                username = sess['user'].get('username')
                current = body.get('current_password') or ''
                new = body.get('new_password') or ''
                confirm = body.get('confirm_password')

                record = auth.find_user(username)
                if not record or not auth.verify_password(current, record.get('password')):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps(
                        {'error': "Hozirgi parol noto'g'ri"}, ensure_ascii=False).encode('utf-8'))
                    return
                if confirm is not None and new != confirm:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps(
                        {'error': 'Yangi parollar mos kelmadi'}, ensure_ascii=False).encode('utf-8'))
                    return
                if len(new) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps(
                        {'error': "Yangi parol kamida 8 belgidan iborat bo'lishi kerak"},
                        ensure_ascii=False).encode('utf-8'))
                    return
                if auth.verify_password(new, record.get('password')):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps(
                        {'error': "Yangi parol avvalgisidan farq qilishi kerak"},
                        ensure_ascii=False).encode('utf-8'))
                    return

                if not auth.set_password(username, new):
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps(
                        {'error': "Parolni saqlab bo'lmadi"}, ensure_ascii=False).encode('utf-8'))
                    return

                audit.ensure_schema(conn)
                audit.record(conn, 'users', username, 'PASSWORD_CHANGED',
                             user=sess['user'], ip_address=self.client_ip())

                # Revoke every session for this account, then issue a fresh one
                # so the person who just changed it stays signed in here.
                auth.destroy_sessions_for_user(username)
                refreshed = auth.find_user(username)
                token = auth.create_session(refreshed)
                is_https = self.headers.get('X-Forwarded-Proto') == 'https'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Set-Cookie', auth.build_session_cookie(
                    token, secure=is_https, max_age=auth.SESSION_IDLE_SECONDS))
                self.end_headers()
                self.wfile.write(json.dumps({
                    'message': "Parol muvaffaqiyatli o'zgartirildi",
                    'home': permissions.home_for(refreshed),
                }, ensure_ascii=False).encode('utf-8'))

            # 14. POST /api/users (Create / Register user)
            elif path == '/api/users':
                users_file = os.path.join(BASE_DIR, 'data', 'users.json')
                u_list = read_json_file(users_file, [])

                username = (body.get('username') or '').strip().lower()
                if not username:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Foydalanuvchi logini kiritilishi shart'}, ensure_ascii=False).encode('utf-8'))
                    return

                for u in u_list:
                    if u.get('username', '').lower() == username:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': f"'{username}' logini allaqachon mavjud"}, ensure_ascii=False).encode('utf-8'))
                        return

                uid = body.get('id') or f"USR-{body.get('role', 'staff')[:3].upper()}-{len(u_list) + 1:02d}"
                new_u = {
                    "id": uid,
                    "username": username,
                    # Stored as a PBKDF2 hash, never as the typed value.
                    "password": auth.hash_password(body.get('password') or 'fayz2026'),
                    "full_name": body.get('full_name') or username,
                    "role": body.get('role') or 'doctor',
                    "avatar": body.get('avatar') or ('👑' if body.get('role') == 'superadmin' else '👤'),
                    "phone": body.get('phone', ''),
                    "is_active": True,
                    # A new account issued with a password someone else chose
                    # must set its own before it can be used.
                    "must_change_password": True,
                }
                # Only store an explicit permission list when one was actually
                # supplied. This used to default to [role] — the role's *name*
                # as a permission string, which matches no module in
                # permissions.py, so a new receptionist or pharmacist was
                # created with effectively no access at all. With the key
                # absent the role's own defaults apply, which also means
                # changing a role updates everyone holding it.
                explicit = body.get('permissions')
                if isinstance(explicit, list) and explicit:
                    new_u['permissions'] = explicit
                u_list.append(new_u)
                write_json_atomic(users_file, u_list)

                sanitized = dict(new_u)
                sanitized.pop('password', None)
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Foydalanuvchi muvaffaqiyatli ro\'yxatdan o\'tkazildi', 'user': sanitized}, ensure_ascii=False).encode('utf-8'))

            # 15. POST /api/facility/rooms (Create Room)
            elif path == '/api/facility/rooms':
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                floor_num = int(body.get('floor_number', 1))
                room_num = str(body.get('room_number', '15')).strip()
                room_id = f"ROOM-WARD-{room_num}"
                room_name = body.get('room_name_uz') or f"{room_num}-xona"
                room_type = body.get('room_type') or 'stationary'
                
                floor_obj = None
                for fl in r_data.get('floors', []):
                    if fl.get('floor_number') == floor_num:
                        floor_obj = fl
                        break
                if not floor_obj:
                    floor_obj = {
                        "floor_number": floor_num,
                        "name_uz": f"{floor_num}-Qavat",
                        "name_ru": f"{floor_num}-й Этаж",
                        "total_beds": 0,
                        "rooms": []
                    }
                    r_data['floors'].append(floor_obj)

                new_room = {
                    "id": room_id,
                    "floor": floor_num,
                    "room_number": room_num,
                    "name_uz": room_name,
                    "name_ru": f"{room_num}-палата",
                    "name_en": f"Room {room_num}",
                    "type": room_type,
                    "has_beds": True,
                    "beds": []
                }
                floor_obj['rooms'].append(new_room)
                r_data['facility_info']['total_inpatient_rooms'] = sum(1 for fl in r_data.get('floors', []) for r in fl.get('rooms', []) if r.get('has_beds'))

                write_json_atomic(rooms_file, r_data)

                try:
                    cur.execute("""
                        INSERT INTO rooms (id, floor_number, room_number, room_name_uz, room_type, total_capacity, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                        ON DUPLICATE KEY UPDATE room_name_uz = VALUES(room_name_uz), room_type = VALUES(room_type)
                    """, (room_id, floor_num, room_num, room_name, 'standard_ward' if room_type == 'stationary' else 'vip_ward', int(body.get('capacity', 2))))
                    conn.commit()
                except Exception as e_rm:
                    print("MySQL room sync error:", e_rm)

                self._set_json_headers(201)
                self.wfile.write(json.dumps({'message': 'Xona muvaffaqiyatli qo\'shildi', 'room': new_room}, ensure_ascii=False).encode('utf-8'))

            # 16. POST /api/facility/beds (Attach bed to room)
            elif path == '/api/facility/beds':
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                target_room_id = body.get('room_id')
                bed_num = str(body.get('bed_number', '1A')).strip()
                bed_id = body.get('bed_id') or f"BED-{bed_num}"
                daily_rate = float(body.get('daily_rate', 720000))
                bed_type = body.get('bed_type', 'standard')

                attached = False
                for fl in r_data.get('floors', []):
                    for r in fl.get('rooms', []):
                        if r.get('id') == target_room_id or r.get('room_number') == target_room_id:
                            r['has_beds'] = True
                            if 'beds' not in r or not isinstance(r['beds'], list):
                                r['beds'] = []
                            new_bed = {
                                "bed_id": bed_id,
                                "floor": fl.get('floor_number', 1),
                                "room_id": r.get('id'),
                                "room_number": r.get('room_number'),
                                "bed_number": bed_num,
                                "full_label": f"{r.get('room_number')}-xona {bed_num} karavot",
                                "type": bed_type,
                                "status": "available",
                                "daily_rate": daily_rate,
                                "equipment": ["Smart TV", "IV shtativ", "EKG monitor"]
                            }
                            r['beds'].append(new_bed)
                            attached = True
                            break

                if attached:
                    total_beds = sum(len(r.get('beds', [])) for fl in r_data.get('floors', []) for r in fl.get('rooms', []))
                    r_data['facility_info']['total_inpatient_beds'] = total_beds
                    write_json_atomic(rooms_file, r_data)

                    try:
                        cur.execute("""
                            INSERT INTO beds (id, room_id, bed_code, bed_type, default_daily_rate, status)
                            VALUES (?, ?, ?, ?, ?, 'operational')
                            ON DUPLICATE KEY UPDATE default_daily_rate = VALUES(default_daily_rate), status = 'operational'
                        """, (bed_id, target_room_id, bed_id, bed_type, daily_rate))
                        conn.commit()
                    except Exception as e_bd:
                        print("MySQL bed sync error:", e_bd)

                    self._set_json_headers(201)
                    self.wfile.write(json.dumps({'message': f"{bed_id} karavot muvaffaqiyatli ulandi (Attached)", 'bed_id': bed_id}, ensure_ascii=False).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': f"'{target_room_id}' xonasi topilmadi"}, ensure_ascii=False).encode('utf-8'))

            else:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'POST Endpoint not found'}).encode('utf-8'))

        except Exception as e:
            traceback.print_exc()
            self._set_json_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

    # ------------------------------------------------------------------------
    # API PUT HANDLERS
    # ------------------------------------------------------------------------
    def handle_api_put(self, path, body):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()

            # PUT /api/doctor/prescriptions/<id>/status
            if path.startswith('/api/doctor/prescriptions/') and path.endswith('/status'):
                rx_id = path.split('/')[4]
                new_status = body.get('status', 'completed')
                cur.execute("UPDATE prescriptions SET status = ? WHERE id = ?", (new_status, rx_id))
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Prescription status updated', 'status': new_status}).encode('utf-8'))

            # PUT /api/admissions/<id>/discharge
            elif '/discharge' in path:
                adm_id = body.get('admission_id') or (path.split('/')[3] if len(path.split('/')) > 3 else None)
                today_str = datetime.date.today().isoformat()
                discharge_date = (body.get('discharge_date') or body.get('actual_end_date') or today_str)[:10]
                summary = body.get('discharge_summary') or body.get('summary') or "Statsionardan chiqarildi"

                success, res_data = discharge_patient(conn, adm_id, discharge_date, summary)
                if not success:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': str(res_data)}, ensure_ascii=False).encode('utf-8'))
                    return

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Bemor muvaffaqiyatli chiqarildi va karavot tozalash holatiga (cleaning) o\'tkazildi',
                    'result': res_data
                }, ensure_ascii=False).encode('utf-8'))

            # PUT /api/admissions/<id>/transfer
            elif '/transfer' in path:
                adm_id = body.get('admission_id') or (path.split('/')[3] if len(path.split('/')) > 3 else None)
                new_bed_id = body.get('new_bed_id')
                transfer_date = (body.get('transfer_date') or datetime.date.today().isoformat())[:10]
                reason = body.get('reason') or "Palata ko'chirildi"
                staff_id = body.get('staff_id') or 'STF-REC-01'

                success, res_data = transfer_patient_bed(conn, adm_id, new_bed_id, transfer_date, reason, staff_id)
                if not success:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': str(res_data)}, ensure_ascii=False).encode('utf-8'))
                    return

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': 'Bemor yangi karavotga ko\'chirildi, avvalgi karavot tozalashga yuborildi',
                    'result': res_data
                }, ensure_ascii=False).encode('utf-8'))

            # PUT /api/beds/<id>/status or /clean
            elif path.startswith('/api/beds/') and (path.endswith('/status') or path.endswith('/clean')):
                bed_id = path.split('/')[3]
                # The beds.status column accepts only the physical states in its
                # CHECK constraint: operational, cleaning, maintenance,
                # out_of_service. 'available', 'occupied' and 'reserved' are
                # values the v_bed_live_status view DERIVES from admissions, not
                # things that can be stored. This route used to map the other way
                # round -- rewriting 'operational' to 'available' -- so every
                # request violated beds_chk_3 and failed with a 500. Discharge and
                # transfer both leave a bed 'cleaning', so the action that returns
                # it to service never worked and beds accumulated as unusable.
                PHYSICAL = {'operational', 'cleaning', 'maintenance', 'out_of_service'}
                DERIVED_TO_PHYSICAL = {'available': 'operational',
                                       'occupied': 'operational',
                                       'reserved': 'operational'}
                requested = 'operational' if path.endswith('/clean') else str(body.get('status', 'operational')).strip().lower()
                new_status = DERIVED_TO_PHYSICAL.get(requested, requested)
                if new_status not in PHYSICAL:
                    new_status = 'operational'

                cur.execute("UPDATE beds SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? OR bed_code = ?", (new_status, bed_id, bed_id))
                conn.commit()

                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'message': f"Karavot holati muvaffaqiyatli saqlandi: {new_status}",
                    'bed_id': bed_id,
                    'status': new_status
                }, ensure_ascii=False).encode('utf-8'))
            elif path.startswith('/api/facility/beds/'):
                bed_id = urllib.parse.unquote(path.replace('/api/facility/beds/', ''))
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                updated = False
                for fl in r_data.get('floors', []):
                    for r in fl.get('rooms', []):
                        for b in r.get('beds', []):
                            if b.get('bed_id') == bed_id:
                                if 'daily_rate' in body:
                                    b['daily_rate'] = float(body['daily_rate'])
                                if 'type' in body:
                                    b['type'] = body['type']
                                if 'status' in body:
                                    b['status'] = body['status']
                                updated = True

                if updated:
                    write_json_atomic(rooms_file, r_data)
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({'message': f"{bed_id} karavot yangilandi"}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': f"'{bed_id}' karavot topilmadi"}).encode('utf-8'))

            elif path.startswith('/api/users/'):
                uid = urllib.parse.unquote(path.replace('/api/users/', ''))
                users_file = os.path.join(BASE_DIR, 'data', 'users.json')
                if os.path.exists(users_file):
                    with open(users_file, 'r', encoding='utf-8') as f:
                        u_list = json.load(f)
                    
                    found = None
                    for u in u_list:
                        if u.get('id') == uid or u.get('username') == uid:
                            found = u
                            break
                    if found:
                        if 'full_name' in body: found['full_name'] = body['full_name']
                        if 'role' in body: found['role'] = body['role']
                        if 'password' in body and body['password']:
                            found['password'] = auth.hash_password(body['password'])
                        if 'phone' in body: found['phone'] = body['phone']
                        if 'is_active' in body: found['is_active'] = bool(body['is_active'])
                        if 'permissions' in body: found['permissions'] = body['permissions']

                        write_json_atomic(users_file, u_list)

                        sanitized = dict(found)
                        sanitized.pop('password', None)
                        self._set_json_headers(200)
                        self.wfile.write(json.dumps({'message': 'Foydalanuvchi ma\'lumotlari yangilandi', 'user': sanitized}, ensure_ascii=False).encode('utf-8'))
                    else:
                        self._set_json_headers(404)
                        self.wfile.write(json.dumps({'error': 'Foydalanuvchi topilmadi'}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Users fayli mavjud emas'}).encode('utf-8'))

            else:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Endpoint not found'}).encode('utf-8'))

        except Exception as e:
            traceback.print_exc()
            self._set_json_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

    # ------------------------------------------------------------------------
    # API DELETE HANDLERS
    # ------------------------------------------------------------------------
    def handle_api_delete(self, path):
        conn = None
        try:
            conn = get_db()
            cur = conn.cursor()

            if path.startswith('/api/doctor/prescriptions/'):
                rx_id = path.replace('/api/doctor/prescriptions/', '')
                cur.execute("DELETE FROM prescriptions WHERE id = ?", (rx_id,))
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Prescription deleted'}).encode('utf-8'))

            elif path.startswith('/api/patients/') or path.startswith('/api/crm/patients/'):
                pid = urllib.parse.unquote(path.replace('/api/patients/', '').replace('/api/crm/patients/', ''))
                cur.execute("PRAGMA foreign_keys = OFF;")
                cur.execute("SELECT id, full_name, patient_code FROM patients WHERE id = ? OR patient_code = ? OR full_name = ?", (pid, pid, pid))
                p_rows = cur.fetchall()
                target_ids = [r[0] for r in p_rows] if p_rows else [pid]

                for tid in target_ids:
                    cur.execute("DELETE FROM payments WHERE invoice_id IN (SELECT id FROM invoices WHERE admission_id IN (SELECT id FROM admissions WHERE patient_id = ?))", (tid,))
                    cur.execute("DELETE FROM invoices WHERE admission_id IN (SELECT id FROM admissions WHERE patient_id = ?)", (tid,))
                    # 'operational', not 'available': the latter is a value the
                    # v_bed_live_status view derives, and beds.status rejects it.
                    cur.execute("UPDATE beds SET status = 'operational' WHERE id IN (SELECT bed_id FROM admissions WHERE patient_id = ?)", (tid,))
                    cur.execute("DELETE FROM admissions WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM medical_histories WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM prescriptions WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM doctor_daily_notes WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM discharge_epicrises WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM appointments WHERE patient_id = ?", (tid,))
                    cur.execute("DELETE FROM patients WHERE id = ?", (tid,))

                cur.execute("PRAGMA foreign_keys = ON;")
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Patient and all linked clinical & billing records deleted'}).encode('utf-8'))

            elif path.startswith('/api/admissions/'):
                adm_id = urllib.parse.unquote(path.replace('/api/admissions/', ''))
                cur.execute("PRAGMA foreign_keys = OFF;")
                # 'operational', not 'available' -- see above.
                cur.execute("UPDATE beds SET status = 'operational' WHERE id IN (SELECT bed_id FROM admissions WHERE id = ?)", (adm_id,))
                cur.execute("DELETE FROM payments WHERE invoice_id IN (SELECT id FROM invoices WHERE admission_id = ?)", (adm_id,))
                cur.execute("DELETE FROM invoices WHERE admission_id = ?", (adm_id,))
                cur.execute("DELETE FROM daily_logs WHERE admission_id = ?", (adm_id,))
                cur.execute("DELETE FROM bed_transfers WHERE admission_id = ?", (adm_id,))
                cur.execute("DELETE FROM admissions WHERE id = ?", (adm_id,))
                cur.execute("PRAGMA foreign_keys = ON;")
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Admission and linked records deleted'}).encode('utf-8'))

            elif path.startswith('/api/staff/') or path.startswith('/api/hr/staff/'):
                stf_id = urllib.parse.unquote(path.replace('/api/staff/', '').replace('/api/hr/staff/', ''))
                cur.execute("UPDATE staff SET is_active = 0 WHERE id = ?", (stf_id,))
                conn.commit()
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': 'Staff member deactivated'}).encode('utf-8'))

            elif path.startswith('/api/facility/beds/'):
                bid = urllib.parse.unquote(path.replace('/api/facility/beds/', ''))
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                detached = False
                for fl in r_data.get('floors', []):
                    for r in fl.get('rooms', []):
                        if 'beds' in r and isinstance(r['beds'], list):
                            orig_len = len(r['beds'])
                            r['beds'] = [b for b in r['beds'] if b.get('bed_id') != bid]
                            if len(r['beds']) < orig_len:
                                detached = True

                if detached:
                    total_beds = sum(len(r.get('beds', [])) for fl in r_data.get('floors', []) for r in fl.get('rooms', []))
                    r_data['facility_info']['total_inpatient_beds'] = total_beds
                    write_json_atomic(rooms_file, r_data)

                    try:
                        cur.execute("DELETE FROM beds WHERE id = ? OR bed_code = ?", (bid, bid))
                        conn.commit()
                    except Exception as e_dbd:
                        print("MySQL bed delete warning:", e_dbd)

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({'message': f"{bid} karavot muvaffaqiyatli ajratildi (Detached)"}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': f"'{bid}' karavot topilmadi"}).encode('utf-8'))

            elif path.startswith('/api/facility/rooms/'):
                rid = urllib.parse.unquote(path.replace('/api/facility/rooms/', ''))
                rooms_file = os.path.join(BASE_DIR, 'data', 'clinic_rooms.json')
                with open(rooms_file, 'r', encoding='utf-8') as f:
                    r_data = json.load(f)

                removed = False
                for fl in r_data.get('floors', []):
                    orig_len = len(fl.get('rooms', []))
                    fl['rooms'] = [r for r in fl.get('rooms', []) if r.get('id') != rid and r.get('room_number') != rid]
                    if len(fl['rooms']) < orig_len:
                        removed = True

                if removed:
                    total_beds = sum(len(r.get('beds', [])) for fl in r_data.get('floors', []) for r in fl.get('rooms', []))
                    r_data['facility_info']['total_inpatient_beds'] = total_beds
                    r_data['facility_info']['total_inpatient_rooms'] = sum(1 for fl in r_data.get('floors', []) for r in fl.get('rooms', []) if r.get('has_beds'))
                    write_json_atomic(rooms_file, r_data)

                    try:
                        cur.execute("DELETE FROM rooms WHERE id = ? OR room_number = ?", (rid, rid))
                        conn.commit()
                    except Exception as e_drm:
                        print("MySQL room delete warning:", e_drm)

                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({'message': f"Xona muvaffaqiyatli o'chirildi"}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': f"'{rid}' xonasi topilmadi"}).encode('utf-8'))

            elif path.startswith('/api/users/'):
                uid = urllib.parse.unquote(path.replace('/api/users/', ''))
                users_file = os.path.join(BASE_DIR, 'data', 'users.json')
                if os.path.exists(users_file):
                    with open(users_file, 'r', encoding='utf-8') as f:
                        u_list = json.load(f)
                    u_list = [u for u in u_list if u.get('id') != uid and u.get('username') != uid]
                    write_json_atomic(users_file, u_list)
                self._set_json_headers(200)
                self.wfile.write(json.dumps({'message': f"Foydalanuvchi muvaffaqiyatli o'chirildi"}).encode('utf-8'))

            else:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Delete endpoint not found'}).encode('utf-8'))

        except Exception as e:
            traceback.print_exc()
            self._set_json_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        finally:
            if conn:
                try: conn.close()
                except Exception: pass

def run_server():
    cfg = load_config()

    # Upgrade any plaintext password still sitting in data/users.json. Logins
    # keep working across the change because verification accepts both forms.
    auth.migrate_plaintext_passwords()

    # Widen audit_logs.action_type so sign-ins and refusals can be recorded.
    try:
        _c = get_db()
        try:
            audit.ensure_schema(_c)
        finally:
            _c.close()
    except Exception as _e:
        print(f'[!] Could not prepare the audit trail: {_e}')

    # Listen on loopback only by default.
    #
    # This used to bind "" (every interface) and additionally try to seize port
    # 80, which exposed the EMR to every machine on the network — and, where the
    # documented Nginx vhost is in use, to the public internet. That contradicts
    # the project's own deployment guide, which proxies to 127.0.0.1:3000, so
    # the server never needed a public socket of its own; port 80 belongs to
    # Nginx in that setup.
    #
    # Set BIND_HOST to override (BIND_HOST=0.0.0.0 restores the old behaviour)
    # and BIND_PORT_80=1 to additionally serve port 80 directly. Do neither
    # without a reverse proxy, TLS and the authentication below in front.
    bind_host = os.environ.get('BIND_HOST', '127.0.0.1')
    print(f"🏥 FAYZ CONTROL — Enterprise Pure MySQL 8.0 Server running at http://{bind_host}:{PORT}")
    print(f"   Connected Engine: MySQL 8.0 ({cfg.get('user')}@{cfg.get('host')}:{cfg.get('port')}/{cfg.get('database')})")
    if bind_host not in ('127.0.0.1', 'localhost', '::1'):
        print(f"   [!] WARNING: bound to {bind_host} — reachable beyond this machine.")
        print( "       Ensure a reverse proxy and TLS are in front of it.")
    http.server.ThreadingHTTPServer.allow_reuse_address = True

    if PORT != 80 and os.environ.get('BIND_PORT_80') == '1':
        try:
            httpd_80 = http.server.ThreadingHTTPServer((bind_host, 80), ClinicRequestHandler)
            t = threading.Thread(target=httpd_80.serve_forever, daemon=True)
            t.start()
            print(f"🌐 Port 80 also bound on {bind_host} (BIND_PORT_80=1).")
        except Exception as e:
            print(f"[i] Port 80 not bound ({e}), running on port {PORT}.")

    with http.server.ThreadingHTTPServer((bind_host, PORT), ClinicRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server...")

if __name__ == '__main__':
    run_server()
