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

# Sessions live in memory: a clinic restart requires signing in again, which is
# an acceptable trade for not having to add a session table or a dependency.
_SESSIONS = {}
_SESSION_LOCK = threading.RLock()

SESSION_COOKIE = 'fmh_session'
# A shift plus a margin. Idle sessions past this are rejected and discarded.
SESSION_IDLE_SECONDS = int(os.environ.get('FMH_SESSION_IDLE_SECONDS', 12 * 3600))

# Endpoints reachable without a session. Everything else under /api/ requires one.
PUBLIC_API_PATHS = {
    '/api/auth/login',
    '/api/auth/logout',
    '/api/auth/session',
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

def _now():
    return _dt.datetime.now(_dt.timezone.utc)


def create_session(user):
    token = secrets.token_urlsafe(32)
    with _SESSION_LOCK:
        _SESSIONS[token] = {
            'user': sanitize_user(user),
            'created': _now(),
            'last_seen': _now(),
        }
    return token


def get_session(token):
    """Return the session for a token, refreshing its activity stamp."""
    if not token:
        return None
    with _SESSION_LOCK:
        sess = _SESSIONS.get(token)
        if not sess:
            return None
        idle = (_now() - sess['last_seen']).total_seconds()
        if idle > SESSION_IDLE_SECONDS:
            _SESSIONS.pop(token, None)
            return None
        sess['last_seen'] = _now()
        return sess


def destroy_session(token):
    if not token:
        return
    with _SESSION_LOCK:
        _SESSIONS.pop(token, None)


def active_session_count():
    with _SESSION_LOCK:
        return len(_SESSIONS)


def sessions_for_user(username):
    """Tokens currently held by one account, so they can all be revoked."""
    uname = (username or '').lower()
    with _SESSION_LOCK:
        return [t for t, s in _SESSIONS.items()
                if (s['user'].get('username') or '').lower() == uname]


def destroy_sessions_for_user(username):
    """Sign an account out everywhere — used after a password change."""
    for token in sessions_for_user(username):
        destroy_session(token)


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


# ---------------------------------------------------------------------------
# Forced password rotation
# ---------------------------------------------------------------------------

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
    # Static assets are harmless on their own; the data behind them is not.
    # Gate the portal pages, leave stylesheets, scripts and images open so the
    # login screen renders correctly.
    if path in ('/', ''):
        return True
    if path.endswith('.html'):
        return True
    return False
