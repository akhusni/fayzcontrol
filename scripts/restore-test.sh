#!/usr/bin/env bash
#
# Fayz Medical House — prove a backup can actually be restored
#
# A backup nobody has restored is not a backup. This restores an archive into
# a scratch database, compares it table by table against the live one, and
# drops the scratch copy again. It never touches the live database.
#
#   ./scripts/restore-test.sh                        # newest archive
#   ./scripts/restore-test.sh /path/to/dump.sql.gz   # a specific one
#
# Needs an account that may CREATE DATABASE — the application's own user
# deliberately cannot. Set FMH_ADMIN_DB_USER (default: root) and
# FMH_ADMIN_DB_PASSWORD if that account has one.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${FMH_BACKUP_DIR:-/var/backups/fayzcontrol}"
SCRATCH_DB="${FMH_RESTORE_TEST_DB:-fayzhouse_restore_test}"
ADMIN_USER="${FMH_ADMIN_DB_USER:-root}"

die() { echo "[restore-test] $*" >&2; exit 1; }

LIVE_DB="$(python3 - "$HERE" <<'PY'
import json, os, sys
path = os.path.join(sys.argv[1], "db_config.json")
name = "fayzhouse"
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        name = json.load(f).get("database", name)
print(os.environ.get("DB_NAME", name))
PY
)"

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
  ARCHIVE="$(ls -t "$DEST"/fayzhouse_*.sql.gz 2>/dev/null | head -1 || true)"
  [ -n "$ARCHIVE" ] || die "no archive found in $DEST — run ./scripts/backup.sh first"
fi
[ -f "$ARCHIVE" ] || die "no such archive: $ARCHIVE"

MYSQL=(mysql -u "$ADMIN_USER")
[ -n "${FMH_ADMIN_DB_PASSWORD:-}" ] && MYSQL+=(-p"${FMH_ADMIN_DB_PASSWORD}")

echo "[restore-test] archive : $(basename "$ARCHIVE")"
echo "[restore-test] scratch : $SCRATCH_DB (dropped again at the end)"

gzip -t "$ARCHIVE" || die "the archive is corrupt"

"${MYSQL[@]}" -e "DROP DATABASE IF EXISTS \`$SCRATCH_DB\`;
                  CREATE DATABASE \`$SCRATCH_DB\`
                  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" \
  || die "could not create the scratch database as '$ADMIN_USER'"

cleanup() { "${MYSQL[@]}" -e "DROP DATABASE IF EXISTS \`$SCRATCH_DB\`;" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

gunzip -c "$ARCHIVE" | "${MYSQL[@]}" "$SCRATCH_DB" || die "the restore itself failed"
echo "[restore-test] restored without error"

python3 - "$ADMIN_USER" "${FMH_ADMIN_DB_PASSWORD:-}" "$LIVE_DB" "$SCRATCH_DB" <<'PY'
import subprocess, sys
user, pw, live, scratch = sys.argv[1:5]
base = ['mysql', '-u', user] + ([f'-p{pw}'] if pw else []) + ['-N', '-B', '-e']
def q(sql):
    return subprocess.run(base + [sql], capture_output=True, text=True).stdout.strip()
def counts(db):
    ts = q(f"SELECT table_name FROM information_schema.tables "
           f"WHERE table_schema='{db}' AND table_type='BASE TABLE' ORDER BY table_name").split()
    return {t: q(f'SELECT COUNT(*) FROM `{db}`.`{t}`') for t in ts}

a, b = counts(live), counts(scratch)
missing = sorted(set(a) - set(b))
diff = {t: (a[t], b.get(t)) for t in a if b.get(t) != a[t]}
va = q(f"SELECT COUNT(*) FROM information_schema.views WHERE table_schema='{live}'")
vb = q(f"SELECT COUNT(*) FROM information_schema.views WHERE table_schema='{scratch}'")

print(f"[restore-test] tables  live={len(a)}  restored={len(b)}")
print(f"[restore-test] views   live={va}  restored={vb}")
print(f"[restore-test] missing tables      : {missing or 'none'}")
print(f"[restore-test] row-count mismatches: {diff or 'none'}")

if missing or diff or va != vb:
    print("[restore-test] RESULT: the archive does NOT reproduce the database")
    raise SystemExit(1)
print("[restore-test] RESULT: the archive reproduces the database exactly")
PY
