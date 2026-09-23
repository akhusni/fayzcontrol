#!/usr/bin/env bash
#
# Fayz Medical House — database backup
#
# This is a medical record system. Losing the database loses patient history,
# and there was no automatic backup of any kind until this script.
#
#   ./scripts/backup.sh              take a backup, then prune old ones
#   ./scripts/backup.sh --verify     take one and check it can be read back
#   ./scripts/backup.sh --list       show what is currently held
#
# Credentials come from db_config.json (or the DB_* environment variables),
# the same place the application reads them, so the password is never typed on
# a command line where `ps` would show it to every user on the machine.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${FMH_BACKUP_DIR:-/var/backups/fayzcontrol}"
KEEP_DAYS="${FMH_BACKUP_KEEP_DAYS:-30}"

die() { echo "[backup] $*" >&2; exit 1; }

# --- read the connection settings the application itself uses ---------------
read_config() {
  python3 - "$HERE" <<'PY'
import json, os, sys
base = sys.argv[1]
cfg = {"host": "127.0.0.1", "port": 3306, "user": "fayzhouse",
       "password": "", "database": "fayzhouse"}
path = os.path.join(base, "db_config.json")
if os.path.exists(path):
    try:
        with open(path, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if not k.startswith("_")})
    except Exception as e:
        print(f"CONFIG_ERROR={e}")
        raise SystemExit(1)
for env, key in (("DB_HOST", "host"), ("DB_PORT", "port"), ("DB_USER", "user"),
                 ("DB_PASSWORD", "password"), ("DB_NAME", "database")):
    if os.environ.get(env):
        cfg[key] = os.environ[env]
for key in ("host", "port", "user", "password", "database"):
    print(f"{key}={cfg[key]}")
PY
}

eval "$(read_config | sed 's/^/CFG_/')" || die "could not read db_config.json"
[ -n "${CFG_database:-}" ] || die "no database name configured"

case "${1:-}" in
  --list)
    ls -lh "$DEST"/fayzhouse_*.sql.gz 2>/dev/null || echo "[backup] nothing in $DEST yet"
    exit 0
    ;;
esac

mkdir -p "$DEST"
chmod 700 "$DEST" 2>/dev/null || true

# The password goes in a 0600 defaults-file rather than on the command line,
# and the file is removed however this script exits.
CNF="$(mktemp "${TMPDIR:-/tmp}/fmh-backup.XXXXXX")"
chmod 600 "$CNF"
trap 'rm -f "$CNF"' EXIT INT TERM
cat > "$CNF" <<CNFEOF
[client]
host=${CFG_host}
port=${CFG_port}
user=${CFG_user}
password=${CFG_password}
CNFEOF

STAMP="$(date +%Y-%m-%d_%H%M)"
OUT="$DEST/fayzhouse_${STAMP}.sql.gz"

# Two ways to get a consistent dump, tried best first.
#
#   --single-transaction  snapshots InnoDB without blocking anyone, but since
#                         MySQL 8.0.32 mysqldump issues FLUSH TABLES for it,
#                         which needs the global RELOAD/FLUSH_TABLES privilege.
#                         The application's own user deliberately does not have
#                         global rights, so this only works if you give the
#                         backup its own account (see README.md).
#   --lock-tables         also consistent, but holds a read lock for the length
#                         of the dump. At this clinic's size that is a second or
#                         two; run it out of hours and nobody notices.
#
# --no-tablespaces avoids needing the global PROCESS privilege.
#
# --set-gtid-purged=OFF matters more than it looks. Without it mysqldump writes
# a SET @@GLOBAL.GTID_PURGED statement into the dump, and restoring that file
# fails at line 24 with "GTID_PURGED cannot be changed" on any server that has
# already executed transactions -- which includes restoring onto the same
# machine you backed up. Found by actually restoring one of these archives.
COMMON=(--no-tablespaces --routines --triggers --set-gtid-purged=OFF
        --default-character-set=utf8mb4)
DUMP_ERR="$(mktemp "${TMPDIR:-/tmp}/fmh-dumperr.XXXXXX")"
trap 'rm -f "$CNF" "$DUMP_ERR"' EXIT INT TERM

MODE="single-transaction (no locking)"
if ! mysqldump --defaults-extra-file="$CNF" --single-transaction --events \
               "${COMMON[@]}" "${CFG_database}" 2>"$DUMP_ERR" | gzip -9 > "$OUT"; then
  if grep -q 'RELOAD\|FLUSH_TABLES' "$DUMP_ERR"; then
    echo "[backup] note: this account cannot use --single-transaction" \
         "(no global RELOAD/FLUSH_TABLES); falling back to --lock-tables." >&2
    MODE="lock-tables (brief read lock)"
    mysqldump --defaults-extra-file="$CNF" --lock-tables \
              "${COMMON[@]}" "${CFG_database}" 2>"$DUMP_ERR" | gzip -9 > "$OUT" \
      || die "mysqldump failed: $(head -1 "$DUMP_ERR")"
  else
    die "mysqldump failed: $(head -1 "$DUMP_ERR")"
  fi
fi

SIZE="$(wc -c < "$OUT" | tr -d ' ')"
[ "$SIZE" -gt 1000 ] || die "dump is only ${SIZE} bytes — something went wrong; kept at $OUT"
echo "[backup] wrote $OUT (${SIZE} bytes, ${MODE})"

# --- optional read-back check ----------------------------------------------
# A backup nobody has read is not a backup. This proves the gzip stream is
# intact and that the dump actually contains the schema; a full restore into a
# scratch database needs rights the application user does not have, and is
# described in README.md.
if [ "${1:-}" = "--verify" ]; then
  gzip -t "$OUT" || die "the archive is corrupt"
  TABLES="$(gunzip -c "$OUT" | grep -c '^CREATE TABLE' || true)"
  INSERTS="$(gunzip -c "$OUT" | grep -c '^INSERT INTO' || true)"
  echo "[backup] verify: gzip intact, ${TABLES} tables, ${INSERTS} insert statements"
  [ "$TABLES" -ge 20 ] || die "expected at least 20 tables, found ${TABLES}"
fi

# --- retention --------------------------------------------------------------
PRUNED="$(find "$DEST" -name 'fayzhouse_*.sql.gz' -mtime "+${KEEP_DAYS}" -print -delete | wc -l | tr -d ' ')"
echo "[backup] kept ${KEEP_DAYS} days; removed ${PRUNED} older archive(s)"
