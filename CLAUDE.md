# Fayz Medical House — fayzcontrol
Hospital management / EMR suite for Fayz Medical House (Tashkent): reception, doctor EMR, narcology/psychiatry consultation, ward, nurse rounds, CRM, accounting, HR, building management. Staff sign in with accounts limited to their role. Production is https://fayzcontrol.uz; the current goal is shipping to production safely.
Sessions open in this parent folder. The git repo is `fayzcontrol.uz/` (local only, branch `main`, no remote). Run commands from `fayzcontrol.uz/` and use `git -C fayzcontrol.uz …`, because the parent is not a repo.

## Run & verify
All from `fayzcontrol.uz/`. System `python3` 3.9.6; PyMySQL and reportlab are already installed with `--user`.
- Deps: `python3 -m pip install --user PyMySQL reportlab`
- DB config: `cp db_config.example.json db_config.json && chmod 600 db_config.json`, then fill it in. `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME` env vars override it. Local DB is `fayzhouse` on Homebrew MySQL (`brew services`).
- Fresh DB (tables are not auto-created): `mysql -u <user> -p <db> < data/schema.mysql.sql`, then the same with `data/seed_data.sql`. The seed is safe to re-run (`INSERT IGNORE`). The schema is for an empty DB only: tables are `IF NOT EXISTS`, but its `CREATE INDEX`/`CREATE TRIGGER` statements fail on a second run (nothing is wiped).
- Read-only DB check: `python3 install.py`
- Run: `python3 server.py 3000`, then open http://127.0.0.1:3000. It binds 127.0.0.1; set `BIND_HOST=0.0.0.0` only behind a TLS proxy.
- Health: `curl -s http://127.0.0.1:3000/api/health` → 200 with status/database `ok`; 503 with `degraded`/`unreachable` when MySQL is down.
- Stop: `pkill -f "server.py 3000"`. `pkill -f "python3 server.py"` does NOT match (the process runs as `…/Python.app/…/Python server.py 3000`); the old process keeps serving and you end up testing old code.
- Restart: `pkill -f "server.py 3000"; sleep 1; (nohup python3 server.py 3000 > <scratchpad>/server.log 2>&1 &)`. Python changes need a restart; HTML, JS and CSS are read from disk on every request.
- Tests (server and MySQL must be running): `FMH_TEST_USER=superadmin FMH_TEST_PASS=<ask owner> python3 -u tests/test_clinic.py [-v] [NameFragment]`. A full run is about 1 min. Exit code 2 means the server is down or credentials are missing.
- There is no lint, typecheck or build. Syntax checks: `python3 -m py_compile <file>.py` and `node --check js/<file>.js` (node is at /opt/homebrew/bin; any memory note saying there is no node is stale).
- Ops: `FMH_BACKUP_DIR=<dir> ./scripts/backup.sh [--verify|--list]`; `./scripts/restore-test.sh [dump.sql.gz]` (restores the newest archive into scratch DB `fayzhouse_restore_test`, needs an admin DB user via `FMH_ADMIN_DB_USER`/`FMH_ADMIN_DB_PASSWORD`, never touches the live DB); `./scripts/prune-audit.py --dry-run`
- Browser: `preview_start` with url `http://127.0.0.1:3000/login.html` (there is no launch.json).

## Map (inside `fayzcontrol.uz/`)
- `server.py`: the whole HTTP layer (stdlib `ThreadingHTTPServer`). Holds `enforce_auth`, static serving, the API as `if/elif path ==` chains in `handle_api_get/post/put/delete`, input validators, and `run_server` (startup migrations).
- `db.py`: `get_db()` (no pool), `_convert_sql` (SQLite→MySQL translator, on the cursor wrapper), `DictRow`, booking logic (`admit_patient`, `transfer_patient_bed`, `discharge_patient`, `find_booking_conflict`), `FULL_ROOM_PROGRAMS`, `ensure_*` migrations.
- `auth.py`: PBKDF2 hashing, in-memory sessions (cookie `fmh_session`), login throttle, `PUBLIC_API_PATHS`, `is_servable_path`, `STATIC_ASSET_DIRS`.
- `permissions.py`: `ROLES` (11), `API_RULES`, `PAGE_RULES`, `authorize_api/page`. `audit.py`: `audit_logs` writes, retention (`prune`), `_ENTITY_BY_PREFIX`.
- `consultation.py`: 6-section intake and treatment plans; the field labels live only here. `nursery.py`: nurse medication round, vitals, ward-round board. `pdf_generator.py`: ReportLab PDFs.
- Top-level `*.html` are the portals, one per page, each with `js/<page>.js` and `css/<page>.css`. `/` and `index.html` redirect to `superpage.html`.
- Shared frontend: `js/fmh_dialogs.js` (`FMH_Toast`, `fmhConfirm`, a fetch wrapper that sends 401s to login, nav trimming), `js/theme_engine.js`, `js/unified_print_engine.js`, `css/unified_header.css` (tokens, header), `css/unified_print.css`.
- `data/`: `schema.mysql.sql` (the only valid schema) and `seed_data.sql`. The server writes `users.json`, `clinic_rooms.json` and `pricing_config.json`. Drug catalogues: `pharmacology_db.json`, `fayz_house_meds.json`. Legacy (unused by the server): `hr_db/accounting_db/reception_db.json`.
- `tests/test_clinic.py` is the entire suite (stdlib unittest over HTTP). `scripts/`: backup, restore test, audit prune, cron file.
- Docs: `README.md` (Uzbek: setup, roles, backup, tests), `DEPLOYMENT_AND_DOMAINS.md` (systemd + Nginx), `CHANGES.md` (Uzbek change report for the PO).
- Ignore: `pymysql.broken.vendored/` (broken, gitignored; never import it), `.htaccess`, `.vercelignore`, `run_clinic_server.ps1`, `start_clinic.bat` (legacy).
- Parent folder: `fayzcontrol-2026-09-25.zip` (PO package); `fayzcontrol.uz-20260916T045105Z-1-001.zip` (original vendor zip, keep it); `*.patch` (already applied); `FMH_hisoblar_va_parollar.xlsx` (credentials, never open).

## How it works
- Request order: `/api/health` (no auth) → `enforce_auth` (session cookie → `must_change_password` gate → `authorize_api`/`authorize_page`) → `/api/auth/session` (no DB) → `handle_api_*`, or a static file if it passes `is_servable_path` (else 404).
- Each `handle_api_*` opens its own `get_db()` and closes it in `finally`. `autocommit=False`, so call `conn.commit()`. All writes run under the global `WRITE_LOCK`, one at a time; each 2xx write (except `/api/auth/*`, which audits itself) adds one `audit_logs` row.
- Errors: 400 returns `{"error": "<Uzbek>", "field": …}` via `_send_validation_error`. 500 returns a generic Uzbek message; the traceback goes to stdout only.
- Auth: users live in `data/users.json`, not MySQL. Sessions and the login throttle are in memory: 12 h idle timeout; 8 failures per user or 50 per IP gives a 15-min lockout (HTTP 429).
- Unauthenticated API: login/logout/session, plus the only unauthenticated data write, `POST /api/public/appointment-request` (from fayzmedical.uz). It has CORS via `FMH_PUBLIC_SITE_ORIGIN`, per-IP rate limits and honeypot fields `website`/`company`.
- Permissions are `module`, `module:read|write` or `*`. API routes match exact → glob → longest prefix. Hiding nav items in the frontend is cosmetic only.
- MySQL holds clinical and financial data. Business rules are in triggers (invoices, invoice_items, payments) and views (`v_bed_live_status`, `v_financial_ledger`, `v_patient_full_profile`, `v_daily_hospital_kpi`, `v_pharmacy_low_stock`).
- Frontend: vanilla JS calling same-origin `fetch('/api/…')`. Role, permissions and home come from `GET /api/auth/session`. No build step. Fonts, icons, html2pdf and mermaid load from CDNs; SheetJS is vendored.
- Prod: systemd `fayzcontrol.service` behind FastPanel/Nginx `proxy_pass http://127.0.0.1:3000`.
  - Nginx must send `X-Forwarded-Proto` (without it the cookie loses its Secure flag) and `X-Real-IP`.
  - Serving the HTML from Apache, Vercel or any static host bypasses all auth. Never do it.

## Owner's rules
- Bug fixes must not change logic or look. Flag any change to visible behaviour before making it.
- The owner delegates ("do what you think is best", "yes do it all"). Act; ask only for real product decisions, as a short numbered question.
- Work easy → hard from a prioritized list. The owner pushes for completeness ("is that all problems??").
- **Nothing clinical may be invented**: no default gender, birth year, vitals, diagnosis, allergy or doctor. A missing value stays empty, or the request is refused.
- Decided 2026-09-19: only `statsionar_full_room` sells a whole room (the second bed stays empty). A bed freed on the departure day goes straight to the next patient, with no hold day.
- PO package: zip the working tree, including `data/users.json` and `BOSHLASH.md`. `BOSHLASH.md` is not in git or the working tree; it exists only inside the last package, so carry it over. Keep only the latest package. Never delete the vendor zip without asking.
- Credentials: the credential sheet goes separately from the zip and is deleted after handover. Passwords are hashed, so "listing" them means re-issuing them, which invalidates any earlier sheet.
- Never open, cat or print `db_config.json`, `data/users.json`, `data/users*` or the xlsx. Never put passwords in CLAUDE.md, commits, CHANGES.md or handoff text.

## Conventions
- UI text and API errors are in Uzbek (Latin). Code comments, docstrings and commits are in English.
- Commits: sentence-case subject saying what changed for the user. The body says why, how it was found and how it was verified, and ends with test counts ("5 tests added, 138 pass."). Code comments are "why" paragraphs about the defect prevented.
- Python must stay 3.9-compatible (no `match`, no `X | None`). Use only the stdlib plus PyMySQL and reportlab.
- New endpoint: `elif` in the right `handle_api_*` → **rule in `permissions.API_RULES`** → optional `audit._ENTITY_BY_PREFIX` entry → validate with the server.py helpers and `_send_validation_error` (never return `str(e)`) → test class in `tests/test_clinic.py`.
- New page: `name.html` + `css/name.css` + `js/name.js` → **entry in `permissions.PAGE_RULES`** → load `css/unified_header.css`, `js/theme_engine.js`, `js/fmh_dialogs.js` → header nav pill. A new asset dir must also go in `auth.STATIC_ASSET_DIRS`.
- JS: IIFE with `'use strict'`; a local `esc()` for HTML; `FMH_Toast`/`fmhConfirm`, never `alert`/`confirm`; `encodeURIComponent` on query params.
- Bump the `?v=N` on the `<script>`/`<link>` tag whenever a JS/CSS file changes, or browsers keep serving the stale file.
- CSS tokens are in `css/unified_header.css`. Night is the default theme; day is `[data-theme="day"]`. The header is a grid `auto | minmax(0,1fr) | auto` with the user name capped at 150px + ellipsis (header overlaps were reported twice).
- JSON stores: read with `read_json_file`, write with `write_json_atomic` (server.py).
- IDs: `new_record_id(cur, table, prefix)` / `new_patient_ids(cur)` in server.py. Never insert a bare random `PREFIX-####`.
- Medication orders: validate with `validate_prescription_fields(rx)`, before any write.
- Frontend saves: check `res.ok` and show `err.error` before updating local state or showing a success toast. doctor.js used to hide server refusals this way.

## Gotchas
- **The Desktop is synced to iCloud** (`FXICloudDriveDesktop=1`). During test runs iCloud renamed `data/users.json` to `data/users`, which caused the old stray `users`/`users 2` files. After a suite run, check `ls data | grep -i user`. If the file is missing, restore it from git or a backup, then restart the server (the next run gets 429 lockouts). Real fix: move the project off the Desktop.
- Test login: the owner's superadmin password may not match the file. Back up `data/users.json` to the scratchpad, set a temporary hash with `auth.hash_password` + `auth._write_users_atomic`, run, then `cp` the backup back and confirm `git status data/` is clean. Claude can't sign in through the browser, so UI changes are syntax-checked only.
- `grep` in this shell is ugrep and rejects some regexes (e.g. empty alternation); use `/usr/bin/grep -E`.
- **APIs are default-deny, pages are default-allow.** A route missing from `API_RULES` gets 403, even for superadmin. A page missing from `PAGE_RULES` is open to every signed-in user.
- SQL uses `?` placeholders, which `_convert_sql` rewrites (along with `DATE('now')`, `INSERT OR IGNORE`, `ON CONFLICT` and `PRAGMA`). When params are passed, write a literal `%` as `%%`. A literal `?` in SQL text gets rewritten too.
- `beds.status` is physical state only: `operational|cleaning|maintenance|out_of_service`. Never write `available/occupied/reserved`; `v_bed_live_status` derives those. Writing them violates a CHECK, which `INSERT IGNORE` swallows silently. This has happened 5 times.
- The stay end date is exclusive (billing uses `DATEDIFF`). Discharge moves the bed to `cleaning`.
- MySQL error 1442: triggers on payments and invoice_items write to `invoices`, so a DELETE with a subquery on `invoices` fails. Collect the ids first, then delete with a plain IN list.
- `PRAGMA foreign_keys=OFF` is mapped to `FOREIGN_KEY_CHECKS=0`, which disables ON DELETE CASCADE. Delete child rows explicitly; orphaned invoice_items once billed the wrong patient.
- CRLF files: `server.py`; the original portals (accounting, building_management, crm, database_report, doctor (incl. doctor.html), grand_total_report, hr, index, medical_blank, reception, superpage `.html`); `js/{accounting,crm,doctor,hr,reception,superpage,unified_print_engine}.js`; `css/{reception,unified_print}.css`.
  - Never rewrite them in Python text mode: that produced 2,800-line diffs three times.
  - Use Edit or byte mode, and check `git -C fayzcontrol.uz diff --stat` before committing.
- Login needs MySQL (`handle_api_post` opens the DB first, and logins are audited) even though users are stored in JSON. With the DB down, only `/api/health`, `/api/auth/session` and static pages work.
- A restart signs everyone out and clears lockouts. Restarting mid-run breaks the test suite's cookie.
- `pdf_generator` is imported inside try/except, so a syntax error there silently disables PDF export. Run `py_compile` on it after editing.
- `server.py` monkey-patches `json.dumps` (Decimal and date support, `ensure_ascii=False`).
- `client_ip()` trusts `X-Real-IP`/`X-Forwarded-For`. That is fine behind Nginx; without it, clients can spoof their IP.
- Tests write real rows to MySQL; never run them against production. They also add probe accounts to the tracked `data/users.json`, so check `git -C fayzcontrol.uz diff --stat data/users.json` after a run.
- `LoginThrottle` imports `auth` without adding the repo root to `sys.path`, so it errors when run alone.
- Local MySQL is 26.7; production and the schema target 8.0. `mysqldump` needs `--set-gtid-purged=OFF`, and `backup.sh` already passes it.
- Fresh install: load schema and seed by hand. The server itself creates only `consultations`, `treatment_plans`, `medication_administrations` and `appointment_requests`, plus the audit_logs changes, the ward-round unique key on `doctor_daily_notes` and `patients.birth_date`.
- `building_management.html` still keeps bookings in localStorage.
- Stale docs: the README tree says `crm-suite/`, CHANGES.md says 133 tests, and the deploy doc has Windows paths. Deploy paths disagree across the cron file, the systemd example and the docs.

## Keep token use low
- Never read `js/xlsx.full.min.js`, `server_log.txt`, `pymysql.broken.vendored/`, `assets/images/`, or the parent zips and patches.
- Grep only: `data/pharmacology_db.json`, `data/fayz_house_meds.json`, `update_pharmacology.py` (a data list; its logic starts around line 2564).
- Grep, then read line ranges: `server.py`, `tests/test_clinic.py`, `js/{doctor,reception,hr,accounting}.js`, `grand_total_report.html`, `medical_blank.html`, `data/schema.mysql.sql`.
- Iterate with one test class. Run the full suite once at the end with the browser pane closed; with the pane open, runs took 16 min or threw ConnectionResetError. Don't pipe test output through `tail`.
- Browser: prefer `get_page_text`/`read_page`. The pane clamps the viewport to about 280–456px and cannot show `:focus`, so measure layout with one JS probe or `resize_window`. Take screenshots only to show the owner.
- One task per session. Past sessions reached ~900K context and ended on limits. Start fresh after a milestone and keep durable facts here, not in pasted handoffs. Update this file with /revise-claude-md at session end.
- Verify on a freshly restarted server before claiming something works. The doctor check-up was once reported as working while every save returned 500.

## How to talk to me
- I'm not a deep coder and I don't read diffs; I hand finished work to a PO (product owner). Use short, plain English and explain jargon inline.
- For "what changed", give a compact table (#, file, problem, fix), then a "still open / on you" section and one clear next step.
- Problem lists and plans go easy → hard, with red/yellow/green flags and effort (S/M/L).
- Default to a short summary; put the detail in CHANGES.md (Uzbek, for the PO). I report UI bugs with screenshots, and may reply by quoting your text with `>` and giving short numbered answers.

## Status
- Status lives in `git -C fayzcontrol.uz log` (commit bodies give the rationale), `CHANGES.md` (§6 outstanding items, §7 how to run), README and DEPLOYMENT_AND_DOMAINS.md.
- 2026-09-25 (late): HEAD has 165 tests, clean tree; code-reviewed (3cbd4b2..d506736) and fixed. PO package rebuilt as `fayzcontrol-2026-09-25.zip` (old one moved to ~/.Trash).
- Open: localStorage-only work in HR, accounting, superpage caches and building_management (not cleared at logout on purpose — it would lose data); sessions in memory; CDN assets not vendored; no CSP; a shared "post and report error" helper in fmh_dialogs.js to replace per-page copies. CRM creates every patient with is_anonymous=1 (product question, not changed).
- Owner-only: install the backup cron on the server; hand out the credential sheet, then delete it.
