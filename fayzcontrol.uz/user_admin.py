"""
Fayz Medical House — user administration rules (the Super-Portal console).

The /api/users routes took whatever they were sent: any role name (including
ones permissions.py does not know, which signs in with no access at all), a
password typed straight into an account with no rotation, an id built from
the user count that could repeat after a deletion (and DELETE removes every
account with that id), and they would happily delete or block the superadmin
or the administrator's own account. These helpers hold the checks so the
handlers in server.py stay short.

Accounts live in data/users.json; this module never prints a record.
"""

import re

import auth
import permissions

# The account the whole system is configured from. It is never deleted,
# demoted, blocked or reset from the console; its owner changes their own
# password on the change-password screen.
PROTECTED_USERNAME = 'superadmin'

_USERNAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{2,39}$')
MIN_PASSWORD = 8          # same rule as /api/auth/change-password


def role_list():
    """Every role permissions.py defines, for the console's role picker."""
    return [{'key': k, 'label': v.get('label') or k, 'home': v.get('home')}
            for k, v in permissions.ROLES.items()]


def sanitize(user, caller=None, users=None):
    """A record safe to send to the browser: no hash, plus a protection flag."""
    out = dict(user or {})
    out.pop('password', None)
    out.pop('password_hash', None)
    if caller is not None:
        out['protected'] = bool(protection_reason(user, caller, users or [], 'delete'))
    return out


def find(users, uid):
    for u in users:
        if u.get('id') == uid or u.get('username') == uid:
            return u
    return None


def _active_superadmins(users):
    return [u for u in users
            if u.get('role') == 'superadmin' and u.get('is_active', True) is not False]


# Holding admin:write lets a person manage accounts, but that alone must not
# let them make themselves (or a friend) all-powerful: an "admin" given the
# admin module could create a superadmin, grant '*', or reset a superadmin's
# password and sign in as them. Only a superadmin grants these or touches an
# account that holds them.
ELEVATION_DENIED = ("Bosh administrator rolini, '*' yoki foydalanuvchilarni boshqarish "
                    "(admin) ruxsatini faqat bosh administrator bera oladi.")
TARGET_DENIED = ("Bosh administrator yoki foydalanuvchilarni boshqaradigan hisobni faqat "
                 "bosh administrator o'zgartira oladi.")


def grants_user_admin(role, perms):
    """True when this role / explicit permission list can manage accounts."""
    if role == 'superadmin':
        return True
    for p in perms or []:
        if p in ('*', 'admin', 'admin:write'):
            return True
    return False


def is_elevated(user):
    """An account that is a superadmin or can manage accounts."""
    if not user:
        return False
    return grants_user_admin(user.get('role'), permissions.permissions_for(user))


def caller_is_superadmin(caller):
    return '*' in permissions.permissions_for(caller or {})


def protection_reason(target, caller, users, action):
    """
    Why `caller` may not perform `action` on `target`, or None.

    action is one of 'delete', 'demote', 'block', 'reset', 'permissions',
    'edit'.
    """
    if not target:
        return None
    tname = (target.get('username') or '').lower()
    cname = ((caller or {}).get('username') or '').lower()
    if action == 'edit':
        # Name and phone: anyone may fix their own; a superadmin's or an
        # account manager's only a superadmin may touch. Role, block and
        # permission changes go through the stricter actions below.
        if tname and tname == cname:
            return None
        if is_elevated(target) and not caller_is_superadmin(caller):
            return TARGET_DENIED
        return None
    if tname == PROTECTED_USERNAME:
        return ("Bosh administrator (superadmin) hisobini bu yerdan o'chirib, bloklab, "
                "rolini yoki parolini o'zgartirib bo'lmaydi.")
    if tname and tname == cname:
        if action == 'reset':
            return ("O'z parolingizni \"Parolni o'zgartirish\" sahifasida almashtiring.")
        return "O'z hisobingizni o'chirib, bloklab yoki rolini o'zgartirib bo'lmaydi."
    if is_elevated(target) and not caller_is_superadmin(caller):
        return TARGET_DENIED
    # The last working superadmin is the only account that can manage users;
    # removing it would leave nobody able to fix anything from the console.
    if (target.get('role') == 'superadmin' and action != 'reset'
            and target.get('is_active', True) is not False
            and len(_active_superadmins(users)) <= 1):
        return "Bu oxirgi faol bosh administrator hisobi; uni o'zgartirib bo'lmaydi."
    return None


def _clean_text(raw, limit):
    if raw is None:
        return ''
    return str(raw).strip()[:limit]


def _staff_exists(cur, staff_id):
    cur.execute("SELECT 1 FROM staff WHERE id = ?", (staff_id,))
    return bool(cur.fetchone())


def _check_permissions_list(raw):
    """An explicit permission list: strings naming a module, module:read|write or '*'."""
    if raw is None or raw == []:
        return None, None
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        return None, ("Ruxsatlar ro'yxat (matnlar) ko'rinishida bo'lishi kerak.", 'permissions')
    for p in raw:
        if p == '*':
            continue
        name, _, scope = p.partition(':')
        if name not in permissions.MODULES or scope not in ('', 'read', 'write'):
            return None, (f"Noma'lum ruxsat: {p[:40]}", 'permissions')
    return list(raw), None


def new_user_id(users, role):
    """USR-<ROLE>-NN, probing for a free number rather than counting."""
    taken = {str(u.get('id')) for u in users} | {str(u.get('username')) for u in users}
    prefix = 'USR-' + (role or 'usr')[:3].upper() + '-'
    n = len(users) + 1
    while f'{prefix}{n:02d}' in taken:
        n += 1
    return f'{prefix}{n:02d}'


def build_new_user(body, users, cur, caller=None):
    """
    Validate a POST /api/users body.
    Returns (record, issued_password_or_None, None) or
    (None, None, (message, field[, status])). The record already holds the
    password hash.
    """
    username = _clean_text(body.get('username'), 64).lower()
    if not username:
        return None, None, ('Foydalanuvchi logini kiritilishi shart', 'username')
    if not _USERNAME_RE.match(username):
        return None, None, ("Login 3-40 belgi: kichik lotin harflari, raqamlar, '.', '_' yoki '-'.",
                            'username')
    if any((u.get('username') or '').lower() == username for u in users):
        return None, None, (f"'{username}' logini allaqachon mavjud", 'username')

    full_name = _clean_text(body.get('full_name'), 120)
    if not full_name:
        return None, None, ("F.I.Sh kiritilishi shart", 'full_name')

    role = _clean_text(body.get('role'), 32)
    if role not in permissions.ROLES:
        return None, None, ("Rol tanlanmagan yoki noto'g'ri", 'role')

    typed = body.get('password')
    if typed not in (None, ''):
        if not isinstance(typed, str) or len(typed) < MIN_PASSWORD:
            return None, None, (f"Parol kamida {MIN_PASSWORD} belgidan iborat bo'lishi kerak", 'password')
        if len(typed) > 128:
            return None, None, ("Parol juda uzun", 'password')
        issued = None
        password = typed
    else:
        # An account created without a password used to fall back to a single
        # fixed value shared by every such account. A random one is issued
        # instead and shown once.
        issued = password = auth.generate_temp_password()

    staff_id = _clean_text(body.get('staff_id'), 64)
    if staff_id and not _staff_exists(cur, staff_id):
        return None, None, ("Bunday xodim topilmadi", 'staff_id')

    explicit, err = _check_permissions_list(body.get('permissions'))
    if err:
        return None, None, err
    if grants_user_admin(role, explicit) and not caller_is_superadmin(caller):
        return None, None, (ELEVATION_DENIED, 'role' if role == 'superadmin' else 'permissions', 403)

    uid = _clean_text(body.get('id'), 64)
    if uid:
        if find(users, uid):
            return None, None, ("Bu ID band", 'id')
    else:
        uid = new_user_id(users, role)

    record = {
        'id': uid,
        'username': username,
        'password': auth.hash_password(password),
        'full_name': full_name,
        'role': role,
        'avatar': _clean_text(body.get('avatar'), 8) or ('👑' if role == 'superadmin' else '👤'),
        'phone': _clean_text(body.get('phone'), 40),
        'is_active': True,
        # A password someone else chose must be replaced at first sign-in.
        'must_change_password': True,
    }
    if staff_id:
        record['staff_id'] = staff_id
    # Only an explicit list is stored; with the key absent the role's own
    # defaults apply, so changing a role updates everyone holding it.
    if explicit:
        record['permissions'] = explicit
    return record, issued, None


def apply_update(target, body, caller, users, cur):
    """
    Validate and apply a PUT /api/users/<id> body to `target` in place.

    Returns (changed_security, None) or (None, (message, field, status)).
    changed_security is True when role, block state, permissions or staff
    link changed, so the caller can end that account's open sessions.
    """
    if 'password' in body:
        return None, ("Parol bu yerda o'zgartirilmaydi: \"Parolni tiklash\" tugmasidan "
                      "foydalaning.", 'password', 400)

    # Any change to a superadmin (or another account manager) needs a
    # superadmin; the caller's own name or phone stays editable.
    why = protection_reason(target, caller, users, 'edit')
    if why:
        return None, (why, None, 403)

    updates = {}
    if 'full_name' in body:
        name = _clean_text(body.get('full_name'), 120)
        if not name:
            return None, ("F.I.Sh bo'sh bo'lishi mumkin emas", 'full_name', 400)
        updates['full_name'] = name
    if 'phone' in body:
        updates['phone'] = _clean_text(body.get('phone'), 40)
    if 'role' in body:
        role = _clean_text(body.get('role'), 32)
        if role not in permissions.ROLES:
            return None, ("Rol noto'g'ri", 'role', 400)
        if role != target.get('role'):
            why = protection_reason(target, caller, users, 'demote')
            if why:
                return None, (why, 'role', 403)
            if role == 'superadmin' and not caller_is_superadmin(caller):
                return None, (ELEVATION_DENIED, 'role', 403)
            updates['role'] = role
    if 'is_active' in body:
        raw = body.get('is_active')
        if not isinstance(raw, bool):
            return None, ("Holat (faol/bloklangan) true yoki false bo'lishi kerak", 'is_active', 400)
        if raw is False and target.get('is_active', True) is not False:
            why = protection_reason(target, caller, users, 'block')
            if why:
                return None, (why, 'is_active', 403)
        updates['is_active'] = raw
    if 'staff_id' in body:
        sid = _clean_text(body.get('staff_id'), 64)
        if sid and not _staff_exists(cur, sid):
            return None, ("Bunday xodim topilmadi", 'staff_id', 400)
        updates['staff_id'] = sid or None
    if 'permissions' in body:
        explicit, err = _check_permissions_list(body.get('permissions'))
        if err:
            return None, (err[0], err[1], 400)
        if explicit != target.get('permissions'):
            why = protection_reason(target, caller, users, 'permissions')
            if why:
                return None, (why, 'permissions', 403)
            if grants_user_admin(None, explicit) and not caller_is_superadmin(caller):
                return None, (ELEVATION_DENIED, 'permissions', 403)
        updates['permissions'] = explicit
    if not updates:
        return None, ("O'zgartirish uchun maydon yuborilmadi", None, 400)

    security = False
    for key, value in updates.items():
        before = target.get(key)
        if key in ('staff_id', 'permissions') and value is None:
            target.pop(key, None)
        else:
            target[key] = value
        if key in ('role', 'is_active', 'staff_id', 'permissions') and before != target.get(key):
            security = True
    return security, None
