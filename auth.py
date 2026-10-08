"""
Fayz Medical House — Authentication & Session Layer

Until now every /api/* endpoint was unauthenticated: anything that could reach
the port could read and write patient records, and GET /api/users returned the
full staff list including passwords. Under the deployment this project
documents (Nginx proxying fayzcontrol.uz to 127.0.0.1:3000) that surface was
reachable from the public internet.

This module supplies:
  * PBKDF2-SHA256 password hashing, with transparent migration of the
    plaintext passwords currently in data/users.json.
  * Opaque session tokens held server-side, issued as an HttpOnly cookie.
    Same-origin fetch() sends cookies automatically, so the existing frontend
    keeps working without touching its request calls.
  * Helpers the request handler uses to gate routes.

Only the standard library is used, so there is nothing new to install.
"""

import os
import json
import hmac
import hashlib
import secrets
import threading
import datetime as _dt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(BASE_DIR, 'data', 'users.json')

# PBKDF2 cost. 240k iterations of SHA-256 is a few hundred milliseconds on the
# kind of machine this runs on — unnoticeable on a login, expensive in bulk.
_PBKDF2_ROUNDS = 240_000
_HASH_PREFIX = 'pbkdf2_sha256'

# Sessions are recorded in MySQL (table user_sessions) so a restart or deploy
# no longer signs every member of staff out mid-shift. This dict is only a
# cache in front of that table, keyed by the SHA-256 hash of the token (the
# raw token is never kept server-side, in memory or in the database). See the
# Sessions section below.
_SESSIONS = {}
_SESSION_LOCK = threading.RLock()

SESSION_COOKIE = 'fmh_session'
# A shift plus a margin. Idle sessions past this are rejected and discarded.
SESSION_IDLE_SECONDS = int(os.environ.get('FMH_SESSION_IDLE_SECONDS', 12 * 3600))
# How often a session's last_seen is written to the database. Every page loads
# several API calls; writing each one would turn every read into a write.
SESSION_TOUCH_SECONDS = int(os.environ.get('FMH_SESSION_TOUCH_SECONDS', 60))

# Endpoints reachable without a session. Everything else under /api/ requires one.
PUBLIC_API_PATHS = {
    '/api/auth/login',
    '/api/auth/logout',
    '/api/auth/session',
    # The public website's booking enquiry. The only route that accepts a
    # write without a session: it inserts into appointment_requests and
    # touches nothing clinical, and reception decides what is real. See the
    # handler in server.py for the rate limit and the field caps.
    '/api/public/appointment-request',
}

# Reachable by any signed-in user regardless of role: these are about the
# caller's own account, not about clinic data, so the permission tables in
# permissions.py do not apply to them.
SELF_SERVICE_API_PATHS = {
    '/api/auth/change-password',
}

# Pages reachable without a session (the login screen itself and its assets).
PUBLIC_PAGE_PATHS = {
    '/login.html',
    '/favicon.ico',
    '/robots.txt',
}


# ---------------------------------------------------------------------------
# What may be served off disk at all
#
# requires_session() used to answer this by exclusion: anything that was not
# an /api/ path and did not end in .html counted as a harmless static asset
# and was handed to whoever asked. That is the wrong way round for a directory
# that also holds the source, the schema, the request log and the database
# credentials. Every one of these returned 200 to an anonymous caller:
#
#     /db_config.json      the MySQL password, in plaintext
#     /auth.py             this file, including the hashing parameters
#     /permissions.py      the whole access-control table
#     /server.py           every endpoint and query in the system
#     /data/users.json     the user store
#     /server_log.txt      request history
#     /data/seed_data.sql  and the rest of the schema dumps
#
# The rule is now an allow-list. A file is servable only if it is a portal
# page, an asset the portals actually load, or one of the three reference
# files the pages fetch by name; everything else is 404 whether or not the
# caller is signed in, because no member of staff needs to download the
# credentials file through the browser either.
# ---------------------------------------------------------------------------

STATIC_ASSET_DIRS = ('/css/', '/js/', '/assets/')

STATIC_ASSET_SUFFIXES = (
    '.css', '.js', '.mjs', '.map',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico',
    '.woff', '.woff2', '.ttf', '.eot',
    '.xlsx',
)

# Reference data the portals fetch by name: the ward layout and the two drug
# catalogues. Everything else under data/ is clinic data or configuration.
SERVABLE_DATA_FILES = {
    '/data/clinic_rooms.json',
    '/data/pharmacology_db.json',
    '/data/fayz_house_meds.json',
    '/FMH_Xodimlar_Royxati_2026.xlsx',
}

ROOT_PUBLIC_FILES = {'/favicon.ico', '/robots.txt'}


def is_servable_path(path):
    """
    True when `path` may be read off disk and sent to a browser.

    Deliberately an allow-list: a file nobody thought about is refused rather
    than served. Adding a new asset directory means adding it here, which is
    the point.
    """
    if not path.startswith('/') or '..' in path or '\\' in path:
        return False
    if path in ROOT_PUBLIC_FILES or path in SERVABLE_DATA_FILES:
        return True
    if path.endswith('.html'):
        # The portal pages sit at the top level; nothing nested is a page.
        return path.count('/') == 1
    if path.startswith(STATIC_ASSET_DIRS):
        return path.endswith(STATIC_ASSET_SUFFIXES)
    return False


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password):
    """Return a self-describing PBKDF2 hash: pbkdf2_sha256$rounds$salt$hash."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), _PBKDF2_ROUNDS)
    return f"{_HASH_PREFIX}${_PBKDF2_ROUNDS}${salt}${dk.hex()}"


def is_hashed(stored):
    return isinstance(stored, str) and stored.startswith(_HASH_PREFIX + '$')


def verify_password(password, stored):
    """
    Check a password against either a PBKDF2 hash or, for records not yet
    migrated, a plaintext value. Comparison is constant-time in both cases.
    """
    if not isinstance(stored, str) or not stored:
        return False
    if is_hashed(stored):
        try:
            _prefix, rounds, salt, expected = stored.split('$', 3)
            dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                     salt.encode('utf-8'), int(rounds))
            return hmac.compare_digest(dk.hex(), expected)
        except Exception:
            return False
    # Legacy plaintext record.
    return hmac.compare_digest(password, stored)


# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------

def load_users():
    if not os.path.exists(USERS_PATH):
        return []
    with open(USERS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_users_atomic(users):
    """Atomic replace, matching the JSON write discipline used in server.py."""
    import tempfile
    directory = os.path.dirname(USERS_PATH)
    fd, tmp = tempfile.mkstemp(prefix='.tmp-users-', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, USERS_PATH)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        raise


def migrate_plaintext_passwords():
    """
    Replace any plaintext password in users.json with a PBKDF2 hash, in place.

    Called once at startup. Logins keep working across the change because
    verify_password() accepts both forms, so this can run without coordinating
    a password reset for staff.

    Returns the number of records rewritten.
    """
    try:
        users = load_users()
    except Exception as e:
        print(f"[!] Could not read users.json for password migration: {e}")
        return 0
    changed = 0
    for u in users:
        pw = u.get('password')
        if isinstance(pw, str) and pw and not is_hashed(pw):
            u['password'] = hash_password(pw)
            changed += 1
    if changed:
        try:
            _write_users_atomic(users)
            print(f"[✓] Hashed {changed} plaintext password(s) in data/users.json.")
        except Exception as e:
            print(f"[!] Password migration could not be saved: {e}")
            return 0
    return changed


def find_user(username):
    uname = (username or '').strip().lower()
    if not uname:
        return None
    for u in load_users():
        if (u.get('username') or '').lower() == uname:
            return u
    return None


def sanitize_user(user):
    """A copy of the record safe to hand to the browser."""
    out = dict(user or {})
    out.pop('password', None)
    return out


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

#
# The database is the source of truth; _SESSIONS caches what this process has
# already seen. A lookup that misses the cache (the first request after a
# restart) reads user_sessions, checks the idle timeout, and re-reads the
# account from users.json, so a blocked or deleted account or a changed role
# takes effect instead of being revived from a stale copy.
#
# The database can be down while the server is up. GET /api/auth/session must
# still answer then (pages use it to decide whether to show the login
# screen), so every database call here is best-effort: a failure is logged,
# a cached session keeps working, and an uncached one is treated as signed
# out. Nothing in this section raises.
# ---------------------------------------------------------------------------

def _now():
    return _dt.datetime.now(_dt.timezone.utc)


def _db_time(moment):
    """A UTC instant as the naive DATETIME MySQL stores."""
    return moment.astimezone(_dt.timezone.utc).replace(tzinfo=None)


def _from_db_time(value):
    # db.DictRow hands DATETIME columns back as 'YYYY-MM-DD HH:MM:SS' strings,
    # not datetime objects; accept both, or every restore reads as expired.
    if isinstance(value, str):
        try:
            value = _dt.datetime.strptime(value[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None
    if isinstance(value, _dt.datetime):
        return value.replace(tzinfo=_dt.timezone.utc)
    return None


def token_hash(token):
    """What is stored for a token: a leaked table must not be a set of logins."""
    return hashlib.sha256((token or '').encode('utf-8')).hexdigest()


def _db_run(fn):
    """
    Run fn(cursor) on a short-lived autocommit connection of its own.

    Separate from the request's connection on purpose: a session must be
    recorded (or revoked) even when the request's own transaction is later
    rolled back, and it must not wait for that transaction's locks.
    Returns (ok, result).
    """
    conn = None
    try:
        import db  # imported late: auth is loaded before the DB layer
        conn = db.get_db()
        cur = conn.cursor()
        result = fn(cur)
        conn.commit()
        return True, result
    except Exception as e:
        print(f"[auth] session store unavailable: {e}")
        return False, None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _db_insert(key, sess):
    def run(cur):
        cur.execute(
            "INSERT INTO user_sessions (token_hash, username, user_id, created_at, "
            "last_seen, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON DUPLICATE KEY UPDATE last_seen = VALUES(last_seen)",
            (key, sess['username'], sess['user'].get('id'),
             _db_time(sess['created']), _db_time(sess['last_seen']),
             sess.get('ip'), sess.get('user_agent')))
    ok, _ = _db_run(run)
    return ok


def prune_expired_sessions():
    """Delete rows idle past the timeout, so the table does not grow forever."""
    cutoff = _db_time(_now() - _dt.timedelta(seconds=SESSION_IDLE_SECONDS))

    def run(cur):
        cur.execute("DELETE FROM user_sessions WHERE last_seen < ?", (cutoff,))
        return cur.rowcount
    ok, n = _db_run(run)
    with _SESSION_LOCK:
        now = _now()
        for key in [k for k, s in _SESSIONS.items()
                    if (now - s['last_seen']).total_seconds() > SESSION_IDLE_SECONDS]:
            _SESSIONS.pop(key, None)
    return n if ok else 0


def create_session(user, ip=None, user_agent=None):
    token = secrets.token_urlsafe(32)
    key = token_hash(token)
    now = _now()
    sess = {
        'user': sanitize_user(user),
        'username': ((user or {}).get('username') or '').lower(),
        'created': now,
        'last_seen': now,
        'db_seen': now,
        'ip': (ip or None) and str(ip)[:64],
        'user_agent': (user_agent or None) and str(user_agent)[:255],
    }
    # Login already needs MySQL, so this normally succeeds. If it does not,
    # the session still works from memory (and is written on a later touch);
    # it just would not survive a restart.
    sess['persisted'] = _db_insert(key, sess)
    with _SESSION_LOCK:
        _SESSIONS[key] = sess
    # Sign-ins are rare enough to carry the clean-up of abandoned sessions.
    prune_expired_sessions()
    return token


def _touch(key, sess, now):
    """
    Write last_seen at most once per SESSION_TOUCH_SECONDS.

    A missing row means the session was revoked behind this process's back
    (an operator cleared the table, or another process signed the user out),
    so the cached copy is dropped. Returns False when the session must end.
    """
    if (now - sess.get('db_seen', now)).total_seconds() < SESSION_TOUCH_SECONDS:
        return True
    # Stamp first, so a database outage costs one attempt a minute, not one
    # per request.
    sess['db_seen'] = now
    if not sess.get('persisted'):
        sess['persisted'] = _db_insert(key, sess)
        return True

    def run(cur):
        cur.execute("UPDATE user_sessions SET last_seen = ? WHERE token_hash = ?",
                    (_db_time(now), key))
        return cur.rowcount
    ok, rows = _db_run(run)
    if ok and not rows:
        with _SESSION_LOCK:
            _SESSIONS.pop(key, None)
        return False
    return True


def _restore(key):
    """Rebuild a session from user_sessions after a restart. None if invalid."""
    def run(cur):
        cur.execute("SELECT username, created_at, last_seen, ip_address, user_agent "
                    "FROM user_sessions WHERE token_hash = ?", (key,))
        return cur.fetchone()
    ok, row = _db_run(run)
    if not ok or not row:
        return None
    now = _now()
    last_seen = _from_db_time(row.get('last_seen'))
    user = None
    if last_seen and (now - last_seen).total_seconds() <= SESSION_IDLE_SECONDS:
        try:
            user = find_user(row.get('username'))
        except Exception as e:
            print(f"[auth] could not read users.json to restore a session: {e}")
            return None
    if not user or not user.get('is_active', True):
        # Expired, or the account was deleted or blocked while the server
        # was down: the row is worthless, so remove it.
        _db_run(lambda cur: cur.execute(
            "DELETE FROM user_sessions WHERE token_hash = ?", (key,)))
        return None
    sess = {
        'user': sanitize_user(user),
        'username': (user.get('username') or '').lower(),
        'created': _from_db_time(row.get('created_at')) or now,
        'last_seen': now,
        'db_seen': now,
        'ip': row.get('ip_address'),
        'user_agent': row.get('user_agent'),
        'persisted': True,
    }
    _db_run(lambda cur: cur.execute(
        "UPDATE user_sessions SET last_seen = ? WHERE token_hash = ?",
        (_db_time(now), key)))
    with _SESSION_LOCK:
        _SESSIONS[key] = sess
    return sess


def get_session(token):
    """Return the session for a token, refreshing its activity stamp."""
    if not token:
        return None
    key = token_hash(token)
    now = _now()
    expired = False
    with _SESSION_LOCK:
        sess = _SESSIONS.get(key)
        if sess:
            if (now - sess['last_seen']).total_seconds() > SESSION_IDLE_SECONDS:
                _SESSIONS.pop(key, None)
                sess, expired = None, True
            else:
                sess['last_seen'] = now
    if sess:
        return sess if _touch(key, sess, now) else None
    if expired:
        _db_run(lambda cur: cur.execute(
            "DELETE FROM user_sessions WHERE token_hash = ?", (key,)))
        return None
    return _restore(key)


def destroy_session(token):
    if not token:
        return
    key = token_hash(token)
    with _SESSION_LOCK:
        _SESSIONS.pop(key, None)
    _db_run(lambda cur: cur.execute(
        "DELETE FROM user_sessions WHERE token_hash = ?", (key,)))


def active_session_count():
    with _SESSION_LOCK:
        return len(_SESSIONS)


def destroy_sessions_for_user(username):
    """
    Sign an account out everywhere: after a password change or reset, a role,
    block or permission change, or deletion. The database rows go too --
    otherwise the next restart would bring the revoked sessions back.
    """
    uname = (username or '').lower()
    if not uname:
        return
    with _SESSION_LOCK:
        for key in [k for k, s in _SESSIONS.items() if s.get('username') == uname]:
            _SESSIONS.pop(key, None)
    _db_run(lambda cur: cur.execute(
        "DELETE FROM user_sessions WHERE username = ?", (uname,)))


# ---------------------------------------------------------------------------
# Login throttling
#
# The login endpoint previously answered an unlimited number of guesses at full
# speed, which on an internet-exposed deployment is an open invitation to a
# dictionary attack — and the default passwords were guessable words.
#
# Failures are counted per username and per client address. Once the threshold
# is reached that key is refused for a cooling-off period, regardless of
# whether the password offered is correct, so an attacker gains no signal. A
# successful sign-in clears the counter for that key.
# ---------------------------------------------------------------------------
# Per-account threshold: strict, because guesses against one account are what
# a dictionary attack looks like.
MAX_FAILURES = int(os.environ.get('FMH_LOGIN_MAX_FAILURES', 8))

# Per-address threshold: deliberately far higher. Behind the documented Nginx
# proxy the whole clinic can share one apparent address, so a threshold as
# strict as the per-account one would let a single member of staff fumbling
# their password lock every colleague out of the system mid-shift. This still
# blunts distributed guessing across many accounts from one source, without
# turning one person's bad morning into an outage.
MAX_IP_FAILURES = int(os.environ.get('FMH_LOGIN_MAX_IP_FAILURES', 50))

LOCKOUT_SECONDS = int(os.environ.get('FMH_LOGIN_LOCKOUT_SECONDS', 15 * 60))
# Failures older than this stop counting, so an honest typo in the morning does
# not combine with one in the afternoon to lock someone out.
FAILURE_WINDOW_SECONDS = int(os.environ.get('FMH_LOGIN_FAILURE_WINDOW', 15 * 60))

_FAILURES = {}          # key -> list of datetimes
_FAILURE_LOCK = threading.RLock()


def _prune(key, now):
    stamps = [t for t in _FAILURES.get(key, [])
              if (now - t).total_seconds() < FAILURE_WINDOW_SECONDS]
    if stamps:
        _FAILURES[key] = stamps
    else:
        _FAILURES.pop(key, None)
    return stamps


def lockout_remaining(username, ip):
    """
    Seconds until this username/address may try again, or 0 when not locked.

    The account and the address are counted against their own thresholds — see
    MAX_IP_FAILURES for why the address is allowed far more latitude.
    """
    now = _now()
    worst = 0
    with _FAILURE_LOCK:
        for key, limit in ((f'user:{(username or "").lower()}', MAX_FAILURES),
                           (f'ip:{ip or "-"}', MAX_IP_FAILURES)):
            stamps = _prune(key, now)
            if len(stamps) >= limit:
                elapsed = (now - max(stamps)).total_seconds()
                remaining = int(LOCKOUT_SECONDS - elapsed)
                if remaining > worst:
                    worst = remaining
    return max(0, worst)


def note_login_failure(username, ip):
    """Record a failed attempt and report how many remain before lockout."""
    now = _now()
    with _FAILURE_LOCK:
        for key in (f'user:{(username or "").lower()}', f'ip:{ip or "-"}'):
            stamps = _prune(key, now)
            stamps.append(now)
            _FAILURES[key] = stamps
        used = len(_FAILURES.get(f'user:{(username or "").lower()}', []))
    return max(0, MAX_FAILURES - used)


def note_login_success(username, ip):
    with _FAILURE_LOCK:
        _FAILURES.pop(f'user:{(username or "").lower()}', None)
        _FAILURES.pop(f'ip:{ip or "-"}', None)


def clear_user_lockout(username):
    """Forget one account's failed attempts (an administrator reset its password)."""
    with _FAILURE_LOCK:
        _FAILURES.pop(f'user:{(username or "").lower()}', None)


# ---------------------------------------------------------------------------
# Forced password rotation
# ---------------------------------------------------------------------------

def generate_temp_password():
    """
    A one-off password for a newly issued account.

    Readable enough to dictate over the phone once -- no ambiguous characters
    -- but not guessable, unlike the fixed fallback this replaces.
    """
    import string
    alphabet = string.ascii_lowercase.replace('l', '').replace('o', '') + '23456789'
    return 'Fmh-' + ''.join(secrets.choice(alphabet) for _ in range(10))


def must_change_password(user):
    """
    True when this account is still on a password it was handed rather than one
    its owner chose. The seeded demo passwords shipped inside the distributed
    zip, so those accounts are flagged until they are changed.
    """
    return bool((user or {}).get('must_change_password'))


def set_password(username, new_password):
    """
    Replace one account's password with a fresh hash and clear the
    must_change_password flag. Returns True when the account was found.
    """
    users = load_users()
    target = None
    for u in users:
        if (u.get('username') or '').lower() == (username or '').lower():
            target = u
            break
    if not target:
        return False
    target['password'] = hash_password(new_password)
    target.pop('must_change_password', None)
    _write_users_atomic(users)
    return True


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def token_from_cookie_header(cookie_header):
    """Pull the session token out of a raw Cookie header."""
    if not cookie_header:
        return None
    for part in cookie_header.split(';'):
        name, _, value = part.strip().partition('=')
        if name == SESSION_COOKIE:
            return value.strip() or None
    return None


def build_session_cookie(token, secure=False, max_age=None):
    """
    Serialize the session cookie.

    HttpOnly keeps it away from page scripts, so an injected script cannot read
    it. SameSite=Strict means the browser will not attach it to requests
    originating from another site, which is what stops a cross-site page from
    driving the API as a signed-in user.
    """
    bits = [
        f"{SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
    ]
    if max_age is not None:
        bits.append(f"Max-Age={max_age}")
    if secure:
        bits.append("Secure")
    return "; ".join(bits)


def requires_session(path):
    """True when `path` may only be served to an authenticated caller."""
    if path in PUBLIC_PAGE_PATHS:
        return False
    if path.startswith('/api/'):
        return path not in PUBLIC_API_PATHS
    # Stylesheets, scripts and images stay open so the login screen renders.
    # The portal pages and the reference data behind them do not: the ward
    # layout and the drug catalogues are only fetched by pages that already
    # require a session.
    if path in ('/', ''):
        return True
    if path.endswith('.html'):
        return True
    if path in SERVABLE_DATA_FILES:
        return True
    return False
