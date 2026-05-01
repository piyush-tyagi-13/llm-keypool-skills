#!/usr/bin/env python3
"""
register.py <provider> <command> [args]

State-machine registrar. Each command does its automation then prints the exact
next step for hermes to follow. Hermes reads output and executes the next command.

Commands:
  start              - look up provider, print browser instructions + next command
  verify             - poll inbox for verification email, navigate to link
  getkey             - print instructions to find API key page
  addkey <api_key>   - add key to llm-keypool, mark registered, email report
  fail <reason>      - mark failed, email report
  status             - show current registration state
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SCOUT_DB = Path(os.environ.get("SCOUT_DB", SCRIPT_DIR.parent / "llm-scout" / "providers.db"))
REG_DB = Path(os.environ.get("REGISTRAR_DB", SCRIPT_DIR / "registrar.db"))

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_IMAP_HOST = os.environ.get("EMAIL_IMAP_HOST", "imap.gmail.com")
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
USER_EMAIL = (os.environ.get("EMAIL_ALLOWED_USERS", "") or "").split(",")[0].strip()

REGISTRAR_PY = SCRIPT_DIR / "registrar.py"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _reg_db():
    conn = sqlite3.connect(REG_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            provider   TEXT PRIMARY KEY,
            state      TEXT DEFAULT 'pending',
            signup_url TEXT,
            password   TEXT,
            api_key    TEXT,
            model      TEXT,
            notes      TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()
    return conn


def _set_state(provider: str, state: str, **kwargs):
    conn = _reg_db()
    now = datetime.now(timezone.utc).isoformat()
    row = dict(conn.execute("SELECT * FROM registrations WHERE provider=?", (provider,)).fetchone() or {})
    row.update({"provider": provider, "state": state, "updated_at": now})
    row.update(kwargs)
    conn.execute("""
        INSERT OR REPLACE INTO registrations (provider, state, signup_url, password, api_key, model, notes, updated_at)
        VALUES (:provider, :state, :signup_url, :password, :api_key, :model, :notes, :updated_at)
    """, {k: row.get(k) for k in ("provider", "state", "signup_url", "password", "api_key", "model", "notes", "updated_at")})
    conn.commit()
    conn.close()


def _get_state(provider: str) -> dict:
    conn = _reg_db()
    row = conn.execute("SELECT * FROM registrations WHERE provider=?", (provider,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def _get_provider_info(provider: str) -> dict:
    if not SCOUT_DB.exists():
        return {}
    conn = sqlite3.connect(SCOUT_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM providers WHERE name=?", (provider.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else {}


def _gen_password() -> str:
    import secrets, string
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(16))


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_start(provider: str):
    info = _get_provider_info(provider)
    signup_url = info.get("signup_url") or ""
    models = json.loads(info.get("models") or "[]")
    best_model = models[0] if models else "unknown"

    if not signup_url:
        print(f"ERROR: No signup URL for {provider} in scout DB.")
        print(f"Add it first: python3 {SCRIPT_DIR.parent}/llm-scout/scout.py add '{{\"name\":\"{provider}\",\"signup_url\":\"<url>\"}}'")
        sys.exit(1)

    password = _gen_password()
    _set_state(provider, "awaiting_verify", signup_url=signup_url, password=password, model=best_model)

    print("=" * 60)
    print(f"REGISTRAR: {provider} - Step 1 of 4")
    print("=" * 60)
    print()
    print("ACTION: Open signup page and fill the form using browser-harness:")
    print()
    print(f"  Signup URL : {signup_url}")
    print(f"  Email      : {EMAIL_ADDRESS or '<EMAIL_ADDRESS env var>'}")
    print(f"  Name       : Hermes Agent")
    print(f"  Password   : {password}")
    print()
    print("Use browser-harness to:")
    print("  1. new_tab(\"" + signup_url + "\")")
    print("  2. wait_for_load()")
    print("  3. Fill email, name, password fields")
    print("  4. Submit the form")
    print()
    print("NEXT COMMAND (run after submitting the form):")
    print(f"  python3 {SCRIPT_DIR}/register.py {provider} verify")
    print("=" * 60)


def cmd_verify(provider: str):
    state = _get_state(provider)
    if not state:
        print(f"ERROR: No registration in progress for {provider}. Run 'start' first.")
        sys.exit(1)

    print("=" * 60)
    print(f"REGISTRAR: {provider} - Step 2 of 4")
    print("=" * 60)
    print()
    print("ACTION: Polling hermes inbox for verification email...")
    print(f"  Checking: {EMAIL_ADDRESS}")
    print()

    result = subprocess.run(
        ["python3", str(REGISTRAR_PY), "wait-verify", provider],
        capture_output=True, text=True, timeout=660
    )

    verify_link = result.stdout.strip()
    if result.returncode != 0 or not verify_link:
        print("ERROR: No verification email received within 10 minutes.")
        print(result.stderr)
        print()
        print("NEXT COMMAND (mark as failed):")
        print(f"  python3 {SCRIPT_DIR}/register.py {provider} fail 'no verification email'")
        sys.exit(1)

    _set_state(provider, "awaiting_key")
    print(f"Verification link found: {verify_link}")
    print()
    print("ACTION: Navigate to the verification link using browser-harness:")
    print()
    print(f"  new_tab(\"{verify_link}\")")
    print(f"  wait_for_load()")
    print(f"  capture_screenshot()")
    print()
    print("NEXT COMMAND (run after verification page loads):")
    print(f"  python3 {SCRIPT_DIR}/register.py {provider} getkey")
    print("=" * 60)


def cmd_getkey(provider: str):
    info = _get_provider_info(provider)
    signup_url = info.get("signup_url") or ""
    base = signup_url.split("/")[0] + "//" + signup_url.split("/")[2] if signup_url else "<provider dashboard>"

    print("=" * 60)
    print(f"REGISTRAR: {provider} - Step 3 of 4")
    print("=" * 60)
    print()
    print("ACTION: Navigate to API keys page and copy the key using browser-harness:")
    print()
    print("Try these URLs in order (stop at the one that works):")
    for path in ["/api-keys", "/settings/api-keys", "/account/api-keys", "/dashboard/api-keys", "/dashboard"]:
        print(f"  {base}{path}")
    print()
    print("browser-harness steps:")
    print(f"  new_tab(\"{base}/api-keys\")  # or whichever URL works")
    print("  wait_for_load()")
    print("  capture_screenshot()  # find 'Create API Key' or 'Generate Key' button")
    print("  # click the button, copy the displayed key")
    print()
    print("NEXT COMMAND (replace <key> with the actual API key):")
    print(f"  python3 {SCRIPT_DIR}/register.py {provider} addkey <key>")
    print("=" * 60)


def cmd_addkey(provider: str, api_key: str):
    if not api_key or api_key == "<key>":
        print("ERROR: provide the actual API key")
        print(f"Usage: python3 {SCRIPT_DIR}/register.py {provider} addkey sk-abc123...")
        sys.exit(1)

    state = _get_state(provider)
    model = state.get("model") or "unknown"

    print("=" * 60)
    print(f"REGISTRAR: {provider} - Step 4 of 4")
    print("=" * 60)
    print()
    print(f"Adding key to llm-keypool (provider={provider}, model={model})...")

    result = subprocess.run(
        ["llm-keypool", "add", "--provider", provider, "--key", api_key, "--model", model, "--category", "general_purpose"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"llm-keypool add failed: {result.stderr}")
        print()
        print("NEXT COMMAND:")
        print(f"  python3 {SCRIPT_DIR}/register.py {provider} fail 'llm-keypool add failed: {result.stderr.strip()}'")
        sys.exit(1)

    print(result.stdout.strip() or "Key added.")

    # mark registered in scout DB
    subprocess.run(
        ["python3", str(SCRIPT_DIR.parent / "llm-scout" / "scout.py"), "mark-registered", provider],
        capture_output=True
    )

    _set_state(provider, "complete", api_key=api_key)

    # send success report
    subprocess.run(["python3", str(REGISTRAR_PY), "send-report", provider, model, "success"], capture_output=True)

    print()
    print(f"SUCCESS: {provider} registered. Key added to llm-keypool.")
    print(f"Run 'llm-keypool status' to verify.")
    print("=" * 60)


def cmd_fail(provider: str, reason: str):
    state = _get_state(provider)
    model = state.get("model") or ""
    _set_state(provider, "failed", notes=reason)
    subprocess.run(["python3", str(REGISTRAR_PY), "send-report", provider, model, "failed", reason], capture_output=True)
    print(f"Marked {provider} as failed: {reason}")
    print("Report emailed to user.")


def cmd_status(provider: str):
    state = _get_state(provider)
    if state:
        print(json.dumps(state, indent=2))
    else:
        print(f"No registration record for {provider}")


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    provider = sys.argv[1].lower().strip()
    command = sys.argv[2].lower().strip()

    if command == "start":
        cmd_start(provider)
    elif command == "verify":
        cmd_verify(provider)
    elif command == "getkey":
        cmd_getkey(provider)
    elif command == "addkey":
        api_key = sys.argv[3] if len(sys.argv) > 3 else ""
        cmd_addkey(provider, api_key)
    elif command == "fail":
        reason = sys.argv[3] if len(sys.argv) > 3 else "unknown"
        cmd_fail(provider, reason)
    elif command == "status":
        cmd_status(provider)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)
