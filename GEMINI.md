# Fayz Medical House — Antigravity Agent Guidelines

Hospital management / EMR suite for Fayz Medical House (Tashkent): reception, doctor EMR, narcology/psychiatry consultation, ward, nurse rounds, CRM, accounting, HR, building management. Staff sign in with accounts limited to their role.

Production is `https://fayzcontrol.uz`. The git repo is `fayzcontrol.uz/` (branch `main`). Run commands from `fayzcontrol.uz/` and use `git -C fayzcontrol.uz …`.

---

## CRITICAL: Token Management & Code Mapping Rules
To prevent context exhaustion and hallucination, you MUST follow these rules:

1. **NEVER read large files in their entirety:**
   - Do NOT run full-file reads on `server.py` (6,625 lines), `inventory.py`, `telegram_service.py`, `update_pharmacology.py`, `test_clinic.py`, `doctor.html`, `medical_blank.html`, `accounting.html`, `data/schema.mysql.sql`, or any `.json`/`.log` files.
   - Never read `js/xlsx.full.min.js`, `server_log.txt`, `pymysql.broken.vendored/`, or `.zip` archives.

2. **How to Map and Explore Code:**
   - **If MCP `code-mapper` is active:** Use `map_symbols(file_path)` to get class/function/route outlines with exact line numbers. Use `search_code(query)` for token-bounded search.
   - **If MCP is pending reload:** Use the local CLI tool:
     ```powershell
     python "C:/Users/Ituser/.gemini/mcp-servers/code-mapper/code_mapper_cli.py" map <file>
     python "C:/Users/Ituser/.gemini/mcp-servers/code-mapper/code_mapper_cli.py" search "<query>"
     python "C:/Users/Ituser/.gemini/mcp-servers/code-mapper/code_mapper_cli.py" slice <file> <start> <end>
     ```
   - **When reading code:** ALWAYS specify `StartLine` and `EndLine` in `view_file` (limit reads to 30–80 lines).

3. **Editing Workflow:**
   - Identify the exact function and enclosing block using the symbol map.
   - Read the enclosing function and its callers to understand context, locks (`WRITE_LOCK`), and permissions (`permissions.API_RULES`).
   - Use `replace_file_content` for surgical block edits. Do NOT rewrite whole files.
   - Preserve Windows CRLF line endings on existing files (do not convert to LF).
   - Immediately verify syntax: `python -m py_compile <file>.py` or `node --check js/<file>.js`.

---

## Project Structure & Architecture
- `server.py`: HTTP layer (`ThreadingHTTPServer`). Holds `enforce_auth`, static serving, `handle_api_get/post/put/delete`, and `WRITE_LOCK`.
- `db.py`: `get_db()`, cursor wrapper (`_convert_sql`), booking logic (`admit_patient`, `discharge_patient`).
- `auth.py`: PBKDF2 hashing, in-memory sessions (cookie `fmh_session`), login throttle.
- `permissions.py`: `ROLES`, `API_RULES`, `PAGE_RULES`, `authorize_api/page`.
- `data/`: `schema.mysql.sql` (the only valid schema) and `seed_data.sql`. User accounts live in `data/users.json`.
- `tests/test_clinic.py`: Unittest suite. Run single test classes when iterating:
  `FMH_TEST_USER=superadmin FMH_TEST_PASS=<pass> python3 -u tests/test_clinic.py [TestClassName]`.

---

## Owner's Constraints
- **Nothing clinical may be invented:** no default gender, birth year, vitals, diagnosis, allergy, or doctor.
- **Never open or cat credentials:** `db_config.json`, `data/users.json`, `FMH_hisoblar_va_parollar.xlsx`.
- **UI text in Uzbek (Latin):** Code comments and commit messages in English.
