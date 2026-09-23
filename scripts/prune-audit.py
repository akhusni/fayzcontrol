#!/usr/bin/env python3
"""
Fayz Medical House — audit trail retention

    ./scripts/prune-audit.py            # apply the configured window
    ./scripts/prune-audit.py --days 365 # override it once
    ./scripts/prune-audit.py --dry-run  # say what would go, delete nothing

audit_logs had no retention policy and no index on its timestamp, so it grew
without limit and could only be searched by reading every row. How long a
medical audit trail must be kept is a decision for the clinic and its
regulator; the default here is two years and is deliberately generous.
Set FMH_AUDIT_KEEP_DAYS=0 to keep everything for ever.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db          # noqa: E402
import audit                   # noqa: E402


def main():
    days = audit.KEEP_DAYS
    dry = '--dry-run' in sys.argv
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])

    conn = get_db()
    try:
        audit.ensure_index(conn)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM audit_logs")
        before = cur.fetchone()['n']

        if days <= 0:
            print(f"[audit] retention disabled; {before} entries kept")
            return

        cur.execute("""SELECT COUNT(*) AS n FROM audit_logs
                       WHERE `timestamp` < DATE_SUB(NOW(), INTERVAL ? DAY)""", (days,))
        stale = cur.fetchone()['n']

        if dry:
            print(f"[audit] {before} entries, {stale} older than {days} days "
                  f"(dry run — nothing deleted)")
            return

        removed = audit.prune(conn, days)
        cur.execute("SELECT COUNT(*) AS n FROM audit_logs")
        print(f"[audit] kept {days} days: removed {removed}, "
              f"{cur.fetchone()['n']} entries remain")
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
