"""
Fayz Medical House — Roles & Access Control

Authentication only proves who someone is. This module decides what they may
do, so a receptionist cannot run payroll and a nurse cannot delete a patient
record — and, just as importantly, so each member of staff sees only the
portals their job needs instead of all ten.

Model
-----
A permission is either a bare module name, granting read and write:

    'nursery'            -> may read and change the nurse station

or a module with an explicit action, granting only that:

    'crm:read'           -> may view patient records, not edit them

'*' grants everything and is reserved for the superadmin.

Every API route and every portal page is mapped to (module, action) below.
Nothing is reachable unless it appears in one of those tables, so a route
added later is denied by default rather than silently open — the failure mode
points at a missing entry instead of at an unguarded endpoint.
"""

import fnmatch

# ---------------------------------------------------------------------------
# Modules — one per area of the clinic, matching the portal pages.
# ---------------------------------------------------------------------------
MODULES = {
    'reception':  "Qabulxona va ro'yxatga olish",
    'doctors':    "Shifokor posti, konsultatsiya va ko'rik",
    'nursery':    "Hamshiralar posti va dori berish",
    # Placing a patient in a bed is separate from configuring the building:
    # reception and the ward admit people, but only an administrator adds or
    # removes rooms. Discharge and transfer are clinical calls and sit under
    # 'facility' rather than here.
    'admissions': "Bemorni karavotga joylashtirish",
    'facility':   "Statsionar, xonalar va karavotlar",
    'pharmacy':   "Farmakologiya va dorilar bazasi",
    'crm':        "Bemorlar kartotekasi va kasallik tarixi",
    'accounting': "Kassa, to'lovlar va moliya",
    'hr':         "Kadrlar, smenalar va maosh",
    'duty':       "24/7 Navbatchilik jadvali va smenalar",
    'kitchen':    "Parhez va oshxona",
    'admin':      "Foydalanuvchilar, rollar va sozlamalar",
    'owner':      "Klinika egasi: pul oqimi hisoboti",
}

# ---------------------------------------------------------------------------
# Roles
#
# Each role lists what that job actually needs. Read-only grants appear where
# a role must see context without owning it: a nurse needs to know which bed a
# patient is in, but bed assignment belongs to reception and the ward.
# ---------------------------------------------------------------------------
ROLES = {
    # Full access. Should belong to one or two people, not a shared login.
    'superadmin': {
        'label': 'Bosh administrator',
        'permissions': ['*'],
        'home': '/superpage.html',
    },

    # Runs the clinic day to day; everything except user administration.
    'admin': {
        'label': 'Administrator',
        'permissions': ['reception', 'doctors', 'nursery', 'admissions', 'facility',
                        'pharmacy', 'crm', 'accounting', 'hr', 'kitchen', 'admin:read', 'duty'],
        'home': '/superpage.html',
    },

    # Clinical lead: full clinical reach plus oversight of the ward and desk.
    'chief_doctor': {
        'label': 'Bosh shifokor',
        'permissions': ['doctors', 'crm', 'pharmacy', 'admissions', 'facility', 'nursery',
                        'reception:read', 'accounting:read', 'hr:read', 'duty:read'],
        'home': '/doctor.html',
    },

    # Consultations, check-ups, prescriptions.
    'doctor': {
        'label': 'Shifokor',
        'permissions': ['doctors', 'crm', 'pharmacy:read', 'admissions:read', 'facility:read', 'duty:read'],
        'home': '/doctor.html',
    },

    # Administers medication and records vitals; does not diagnose or bill.
    'nurse': {
        'label': 'Hamshira',
        'permissions': ['nursery', 'kitchen', 'crm:read', 'admissions:read',
                        'facility:read', 'pharmacy:read', 'doctors:read', 'duty:read'],
        # The nurse station now exists, so a nurse lands on her own round
        # rather than on the patient list. This still said /crm.html from
        # when nurse.html was only planned.
        'home': '/nurse.html',
    },

    # Intake: registers patients and routes them to a doctor or a bed.
    'receptionist': {
        'label': 'Qabulxona xodimi',
        'permissions': ['reception', 'crm', 'admissions', 'facility:read', 'accounting:read'],
        'home': '/reception.html',
    },

    # Cash desk and financial reporting. Sees who owes what, not why clinically.
    'accountant': {
        'label': 'Buxgalter / Kassir',
        'permissions': ['accounting', 'crm:read', 'admissions:read', 'facility:read'],
        'home': '/accounting.html',
    },

    # Staff records, rosters, payroll. No clinical or patient access.
    'hr_manager': {
        'label': 'Kadrlar bo\'limi',
        'permissions': ['hr', 'duty'],
        'home': '/hr.html',
    },

    # Dispensing and stock. Needs to see prescriptions, not write them.
    'pharmacist': {
        'label': 'Farmatsevt',
        'permissions': ['pharmacy', 'doctors:read', 'crm:read'],
        # The hub, until a dedicated dispensing page exists.
        'home': '/superpage.html',
    },

    # Ward supervision: beds, transfers, sanitation.
    'ward_manager': {
        'label': 'Statsionar menejeri',
        'permissions': ['facility', 'admissions', 'nursery:read', 'crm:read', 'kitchen', 'duty:read'],
        'home': '/building_management.html',
    },

    # Meals and dietary plans only.
    'kitchen_staff': {
        'label': 'Oshxona xodimi',
        'permissions': ['kitchen', 'facility:read'],
        'home': '/building_management.html',
    },

    # The owner follows the money from a phone: every income and expense,
    # read-only. Accounting stays the place where money is entered.
    'owner': {
        'label': 'Klinika egasi',
        'permissions': ['owner', 'accounting:read'],
        'home': '/owner.html',
    },

    # 24/7 Ward sanitation & shift duty roster view.
    'sanitar': {
        'label': 'Sanitarka (Navbatchilik)',
        'permissions': ['duty'],
        'home': '/duty_schedule.html',
    },
}

# ---------------------------------------------------------------------------
# API routes -> (module, action-override or None)
#
# Matched in order: an exact path wins over a prefix. Where None is given the
# action follows the HTTP verb (GET is read, everything else is write).
#
# Order matters for the prefix rules: put the most specific first.
# ---------------------------------------------------------------------------
API_RULES = [
    # --- authentication: reachable by anyone, handled before this table ---

    # --- dashboards / shared context -------------------------------------
    # Read-only clinic totals. Every role needs its own landing figures, and
    # the payload carries no patient identities.
    ('/api/stats/summary',            'crm',        'read'),

    # --- patient records --------------------------------------------------
    ('/api/crm/patients',             'crm',        None),
    ('/api/crm/payments',             'accounting', None),
    ('/api/patients',                 'crm',        None),

    # --- clinical ---------------------------------------------------------
    # Consultation intake and treatment plans. Both are the doctor's work;
    # the nurse and the pharmacist read a plan to carry it out.
    ('/api/consultations/sections',   'doctors',    'read'),
    ('/api/consultations/queue',      'doctors',    'read'),
    ('/api/consultations',            'doctors',    None),
    ('/api/treatment-plans',          'doctors',    None),
    ('/api/doctor/download-pdf/',     'doctors',    'read'),
    ('/api/doctor/clinical/',         'doctors',    'read'),
    ('/api/doctor/consultation-case', 'doctors',    None),
    ('/api/doctor/anamnesis',         'doctors',    None),
    ('/api/doctor/epicrisis',         'doctors',    None),
    # The ward round: read the board, write the day's assessment.
    ('/api/doctor/ward-round',        'doctors',    'read'),
    ('/api/doctor/notes',             'doctors',    None),
    ('/api/doctor/prescriptions',     'doctors',    None),
    # Nurses record administration and vitals against a stay.
    ('/api/nursery/round/pdf',        'nursery',    'read'),
    ('/api/nursery/round',            'nursery',    'read'),
    ('/api/nursery/administer',       'nursery',    'write'),
    # Without the trailing slash so it also covers a POST that names the
    # admission in the body rather than the path.
    ('/api/daily-logs',               'nursery',    None),

    # --- ward / facility --------------------------------------------------
    # Ending a stay or moving a patient is a clinical decision, so those two
    # stay with the ward even though creating the stay does not.
    ('/api/admissions/*/discharge',   'facility',   'write'),
    ('/api/admissions/*/transfer',    'facility',   'write'),
    ('/api/admissions',               'admissions', None),
    ('/api/beds',                     'facility',   None),
    # Read-only: who may see the occupancy board is a wider set than who may
    # rearrange the building. Reception needs it to place a patient at all.
    ('/api/facility/availability',    'facility',   'read'),
    ('/api/facility/rooms',           'facility',   None),
    ('/api/facility/beds',            'facility',   None),

    # --- front desk -------------------------------------------------------
    # The public website's enquiries, and the desk acting on them. The
    # route that receives them is public (auth.PUBLIC_API_PATHS); reading
    # and deciding is reception's work.
    ('/api/reception/requests',       'reception',  None),
    ('/api/reception/appointment',    'reception',  None),
    ('/api/reception/appointments',   'reception',  'read'),
    ('/api/reception/call-log',       'reception',  None),
    ('/api/reception/calls',          'reception',  'read'),
    ('/api/reception/walk-ins',       'reception',  'read'),
    ('/api/reception/data',           'reception',  'read'),

    # --- money ------------------------------------------------------------
    ('/api/accounting/medication-purchases', 'accounting', None),
    ('/api/accounting/transaction',   'accounting', None),
    ('/api/accounting/data',          'accounting', 'read'),
    ('/api/accounting/medicine-usage', 'accounting', 'read'),
    ('/api/owner/summary',            'owner',      'read'),
    ('/api/accounting/medicine-links', 'accounting', None),
    ('/api/financial-ledger',         'accounting', 'read'),
    ('/api/payments',                 'accounting', None),
    # Price list: everyone quoting a price needs to read it; only the office
    # may change it.
    ('/api/settings/pricing',         'accounting', None),

    # --- staff ------------------------------------------------------------
    ('/api/hr/staff',                 'hr',         None),
    ('/api/hr/data',                  'hr',         'read'),
    ('/api/hr',                       'hr',         None),
    ('/api/duty-schedule',            'duty',       None),
    ('/api/staff',                    'hr',         None),
    ('/api/doctors',                  'doctors',    None),

    # --- user administration ---------------------------------------------
    ('/api/users',                    'admin',      None),
]

# GET /api/settings/pricing and GET /api/staff are needed far more widely than
# write access to them: a doctor picks an attending physician, reception quotes
# a room rate. These grant the READ side to any signed-in user while leaving
# writes to the owning module above.
API_READ_EXEMPT = {
    '/api/settings/pricing',
    '/api/staff',
    '/api/doctors',
    '/api/hr/data',
    '/api/duty-schedule',
}

# A treatment plan is an instruction other people carry out, so reading one is
# granted to the nursery and pharmacy as well as to the doctors. Writing stays
# with the doctors via the rule table above.
PLAN_READERS = ('doctors', 'nursery', 'pharmacy')

# ---------------------------------------------------------------------------
# Portal pages -> module. A role that cannot read the module is redirected to
# its own home page rather than shown an empty shell.
# ---------------------------------------------------------------------------
# Each entry is (module, action). The action matters: a nurse needs to READ
# prescriptions through the API to know what to administer, but the doctor's
# console is not her workspace, so that page asks for write on 'doctors' while
# the API keeps granting her the read. Pages are scoped to the people whose job
# they are, which is the whole point of not showing staff all ten portals.
PAGE_RULES = {
    '/superpage.html':            ('crm',        'read'),
    '/reception.html':            ('reception',  'read'),
    '/doctor.html':               ('doctors',    'write'),
    '/consultation.html':         ('doctors',    'write'),
    # The stationary ward round. Writing the day's assessment is the
    # point of the page, so it needs the same grant as the other two
    # clinical screens rather than read-only.
    '/ward.html':                 ('doctors',    'write'),
    '/nurse.html':                ('nursery',    'read'),
    '/duty_schedule.html':        ('duty',       'read'),
    '/building_management.html':  ('facility',   'read'),
    '/crm.html':                  ('crm',        'read'),
    '/accounting.html':           ('accounting', 'read'),
    '/owner.html':                ('owner',      'read'),
    '/hr.html':                   ('hr',         'read'),
    '/medical_blank.html':        ('doctors',    'write'),
    '/database_report.html':      ('admin',      'read'),
    '/grand_total_report.html':   ('admin',      'read'),
}


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def permissions_for(user):
    """
    The effective permission list for a user record.

    An explicit `permissions` list on the account wins, so one person can be
    granted something their role does not normally carry. Otherwise the role's
    default list applies.
    """
    if not user:
        return []
    explicit = user.get('permissions')
    if isinstance(explicit, list) and explicit:
        return explicit
    role = ROLES.get(user.get('role'))
    return list(role['permissions']) if role else []


def home_for(user):
    """Where this user should land after signing in."""
    role = ROLES.get((user or {}).get('role'))
    if role:
        return role['home']
    return '/superpage.html'


def can(user, module, action='read'):
    """True when `user` may perform `action` on `module`."""
    if not module:
        return False
    perms = permissions_for(user)
    if '*' in perms:
        return True
    for p in perms:
        name, _, scope = p.partition(':')
        if name != module:
            continue
        if not scope:
            return True          # bare module: read and write
        if scope == action:
            return True
        if scope == 'write' and action == 'read':
            return True          # writing implies reading
    return False


def required_for_api(method, path):
    """
    The (module, action) an API path demands, or None when the path is not
    recognised — callers must treat None as a denial, not as public access.
    """
    action = 'read' if method == 'GET' else 'write'

    # Exact matches first so '/api/beds' does not shadow '/api/beds/<id>/clean'.
    for route, module, override in API_RULES:
        if '*' not in route and path == route:
            return module, (override or action)

    # Then glob rules, which exist to pick a verb out of the middle of a path
    # (e.g. '/api/admissions/<id>/discharge'). Checked before prefixes so the
    # specific action wins over the generic collection rule.
    for route, module, override in API_RULES:
        if '*' in route and fnmatch.fnmatchcase(path, route):
            return module, (override or action)

    # Then longest prefix, so '/api/doctor/prescriptions/<id>' resolves to the
    # prescriptions rule rather than to a shorter '/api/doctor' one.
    best = None
    for route, module, override in API_RULES:
        if '*' in route:
            continue
        if path.startswith(route) and (best is None or len(route) > len(best[0])):
            best = (route, module, override)
    if best:
        _route, module, override = best
        return module, (override or action)
    return None


# Endpoints about the caller's own account rather than clinic data. Any
# signed-in user may reach these whatever their role.
SELF_SERVICE = {
    '/api/auth/change-password',
}


def authorize_api(user, method, path):
    """
    Decide an API request.

    Returns (True, None) to allow, or (False, reason) to refuse. `reason` is
    safe to log; the caller decides what to tell the client.
    """
    if path in SELF_SERVICE:
        return True, None
    # Reading a plan: allowed for any module that has to act on it.
    if method == 'GET' and path.startswith('/api/treatment-plans'):
        if any(can(user, m, 'read') for m in PLAN_READERS):
            return True, None
        return False, 'doctors:read required'
    if method == 'GET' and path in API_READ_EXEMPT:
        return True, None
    required = required_for_api(method, path)
    if required is None:
        return False, f'no permission rule covers {method} {path}'
    module, action = required
    if can(user, module, action):
        return True, None
    return False, f'{module}:{action} required'


def authorize_page(user, path):
    """Decide a portal page request. Same contract as authorize_api."""
    rule = PAGE_RULES.get(path)
    if rule is None:
        return True, None      # not a gated portal page
    module, action = rule
    if can(user, module, action):
        return True, None
    return False, f'{module}:{action} required'


def visible_modules(user):
    """
    Modules this user may open, for building their navigation. Ordered as
    MODULES is declared so the menu is stable between roles.
    """
    return [m for m in MODULES if can(user, m, 'read')]


def visible_pages(user):
    """Portal pages this user may open, for hiding the rest of the nav."""
    return [p for p, (module, action) in PAGE_RULES.items() if can(user, module, action)]
