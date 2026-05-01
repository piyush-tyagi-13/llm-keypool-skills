#!/usr/bin/env python3
"""
LLM Provider Scout - DB helper for tracking free-tier LLM API providers.

Usage:
  python scout.py init                 # create DB, seed from llm-keypool providers.json
  python scout.py list                 # list all known providers as JSON
  python scout.py new                  # list providers discovered in last 7 days
  python scout.py add <json>           # add or update a provider (JSON string)
  python scout.py mark-seen            # clear is_new flags after report sent
  python scout.py report               # print email-ready markdown report
  python scout.py email-report         # generate report and send via SMTP
  python scout.py run                  # full run: init + email-report (for cron)
"""

import json
import os
import smtplib
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

DB_PATH = Path(os.environ.get("SCOUT_DB", Path(__file__).parent / "providers.db"))

_SEARCH_PATHS = [
    Path.home() / "Documents/GitHub/llm-aggregator/llm_keypool/config/providers.json",
    Path.home() / ".hermes/hermes-agent/venv/lib/python3.11/site-packages/llm_keypool/config/providers.json",
    Path(os.environ.get("KEYPOOL_PROVIDERS_JSON", "/nonexistent")),
]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS providers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            base_url    TEXT,
            free_tier   INTEGER DEFAULT 1,
            tool_calls  INTEGER DEFAULT 0,
            models      TEXT,
            notes       TEXT,
            signup_url  TEXT,
            first_seen  TEXT NOT NULL,
            last_seen   TEXT NOT NULL,
            is_new      INTEGER DEFAULT 1,
            registered  INTEGER DEFAULT 0,
            api_key     TEXT
        )
    """)
    # migrate: add registered/api_key columns if upgrading from old schema
    for col, typedef in [("registered", "INTEGER DEFAULT 0"), ("api_key", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE providers ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    providers_json = None
    for p in _SEARCH_PATHS:
        if p.exists():
            providers_json = p
            break

    if providers_json:
        with open(providers_json) as f:
            data = json.load(f)["providers"]
        now = datetime.now(timezone.utc).isoformat()
        seeded = 0
        for name, cfg in data.items():
            models = cfg.get("models", [])
            if isinstance(models, dict):
                models = [m for ms in models.values() for m in ms]
            existing = conn.execute("SELECT id FROM providers WHERE name=?", (name,)).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO providers (name, base_url, free_tier, tool_calls, models, first_seen, last_seen, is_new, registered)
                    VALUES (?, ?, 1, 0, ?, ?, ?, 0, 0)
                """, (name, cfg.get("base_url", ""), json.dumps(models), now, now))
                seeded += 1
        conn.commit()
        print(f"Seeded {seeded} providers from llm-keypool providers.json", file=sys.stderr)
    else:
        print("Warning: llm-keypool providers.json not found - DB created empty", file=sys.stderr)

    total = conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
    print(f"DB ready at {DB_PATH} ({total} providers)", file=sys.stderr)
    conn.close()
    sync_registered()


def list_all():
    conn = _connect()
    rows = conn.execute("SELECT * FROM providers ORDER BY first_seen DESC").fetchall()
    print(json.dumps([dict(r) for r in rows], indent=2))
    conn.close()


def list_new(days=7):
    conn = _connect()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM providers WHERE first_seen > ? OR is_new=1 ORDER BY first_seen DESC",
        (cutoff,)
    ).fetchall()
    print(json.dumps([dict(r) for r in rows], indent=2))
    conn.close()


def list_unregistered():
    """Print providers discovered but not yet added to llm-keypool."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM providers WHERE free_tier=1 AND registered=0 ORDER BY tool_calls DESC, name"
    ).fetchall()
    print(json.dumps([dict(r) for r in rows], indent=2))
    conn.close()


def add(provider_json: str):
    data = json.loads(provider_json)
    name = data.get("name", "").strip().lower()
    if not name:
        print("Error: 'name' required")
        sys.exit(1)

    conn = _connect()
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute("SELECT id FROM providers WHERE name=?", (name,)).fetchone()
    models = data.get("models", [])
    if isinstance(models, list):
        models = json.dumps(models)

    if existing:
        conn.execute("""
            UPDATE providers SET
                base_url=COALESCE(?,base_url),
                free_tier=COALESCE(?,free_tier),
                tool_calls=COALESCE(?,tool_calls),
                models=COALESCE(?,models),
                notes=COALESCE(?,notes),
                signup_url=COALESCE(?,signup_url),
                last_seen=?
            WHERE name=?
        """, (
            data.get("base_url"), data.get("free_tier"), data.get("tool_calls"),
            models or None, data.get("notes"), data.get("signup_url"),
            now, name
        ))
        print(f"Updated: {name}")
    else:
        conn.execute("""
            INSERT INTO providers (name, base_url, free_tier, tool_calls, models, notes, signup_url, first_seen, last_seen, is_new)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            name,
            data.get("base_url", ""),
            int(data.get("free_tier", 1)),
            int(data.get("tool_calls", 0)),
            models or "[]",
            data.get("notes", ""),
            data.get("signup_url", ""),
            now, now
        ))
        print(f"Added new provider: {name}")

    conn.commit()
    conn.close()


def sync_registered():
    """Cross-reference llm-keypool status to mark which providers actually have keys."""
    import subprocess
    try:
        result = subprocess.run(["llm-keypool", "status"], capture_output=True, text=True, timeout=30)
        output = result.stdout.lower()
    except Exception as e:
        print(f"Error running llm-keypool status: {e}", file=sys.stderr)
        sys.exit(1)

    conn = _connect()
    rows = conn.execute("SELECT name FROM providers").fetchall()
    updated = 0
    for row in rows:
        name = row["name"].lower()
        has_key = name in output
        conn.execute("UPDATE providers SET registered=? WHERE name=?", (1 if has_key else 0, name))
        if has_key:
            updated += 1
    conn.commit()
    conn.close()
    print(f"Synced: {updated} providers marked as registered")


def mark_registered(name: str, api_key: str = ""):
    conn = _connect()
    conn.execute(
        "UPDATE providers SET registered=1, api_key=? WHERE name=?",
        (api_key, name.lower().strip())
    )
    conn.commit()
    conn.close()
    print(f"Marked registered: {name}")


def mark_seen():
    conn = _connect()
    conn.execute("UPDATE providers SET is_new=0")
    conn.commit()
    conn.close()
    print("Cleared is_new flags")


def report() -> str:
    conn = _connect()
    now = datetime.now(timezone.utc)
    cutoff_7d = (now - timedelta(days=7)).isoformat()

    all_rows = conn.execute("SELECT * FROM providers WHERE free_tier=1 ORDER BY registered ASC, tool_calls DESC, name").fetchall()
    new_rows = conn.execute(
        "SELECT * FROM providers WHERE free_tier=1 AND (is_new=1 OR first_seen > ?) ORDER BY first_seen DESC",
        (cutoff_7d,)
    ).fetchall()
    unregistered = [r for r in all_rows if not r["registered"]]

    lines = []
    lines.append(f"## LLM Scout Report - {now.strftime('%Y-%m-%d')}")
    lines.append(f"**Total free-tier providers tracked:** {len(all_rows)}")
    lines.append(f"**New this week:** {len(new_rows)}")
    lines.append(f"**Not yet added to llm-keypool:** {len(unregistered)}")
    lines.append("")

    if new_rows:
        lines.append("### NEW Providers Discovered This Week")
        for r in new_rows:
            models = json.loads(r["models"] or "[]")
            tc = "yes" if r["tool_calls"] else "unknown"
            reg = " (already registered)" if r["registered"] else " **- needs key**"
            lines.append(f"- **{r['name']}**{reg} | Tool calls: {tc}")
            if r["base_url"]:
                lines.append(f"  - Base URL: `{r['base_url']}`")
            if r["signup_url"]:
                lines.append(f"  - Sign up: {r['signup_url']}")
            if models:
                lines.append(f"  - Models: {', '.join(models[:3])}{'...' if len(models) > 3 else ''}")
            if r["notes"]:
                lines.append(f"  - Notes: {r['notes']}")
        lines.append("")

    if unregistered:
        lines.append("### Providers Ready to Register (not yet in llm-keypool)")
        for r in unregistered:
            tc = "yes" if r["tool_calls"] else "?"
            lines.append(f"- **{r['name']}** | Tool calls: {tc} | {r['signup_url'] or 'no signup URL'}")
        lines.append("")
        lines.append("To register: ask hermes to 'run llm-registrar for <provider-name>'")
        lines.append("")

    lines.append("### All Tracked Free-Tier Providers")
    for r in all_rows:
        tc = "yes" if r["tool_calls"] else "?"
        new_tag = " NEW" if r["is_new"] or r["first_seen"] > cutoff_7d else ""
        reg_tag = " [registered]" if r["registered"] else " [needs key]"
        lines.append(f"- **{r['name']}**{new_tag}{reg_tag} | Tool calls: {tc} | First seen: {r['first_seen'][:10]}")

    conn.close()
    return "\n".join(lines)


def _get_smtp_config():
    return {
        "host": os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com"),
        "address": os.environ.get("EMAIL_ADDRESS", ""),
        "password": os.environ.get("EMAIL_PASSWORD", ""),
        "recipient": (os.environ.get("EMAIL_ALLOWED_USERS", "") or "").split(",")[0].strip(),
    }


def send_email(subject: str, body: str):
    cfg = _get_smtp_config()
    if not cfg["address"] or not cfg["password"]:
        print("Error: EMAIL_ADDRESS or EMAIL_PASSWORD not set", file=sys.stderr)
        sys.exit(1)
    if not cfg["recipient"]:
        print("Error: EMAIL_ALLOWED_USERS not set", file=sys.stderr)
        sys.exit(1)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["address"]
    msg["To"] = cfg["recipient"]
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(cfg["host"], 587) as smtp:
        smtp.starttls()
        smtp.login(cfg["address"], cfg["password"])
        smtp.sendmail(cfg["address"], cfg["recipient"], msg.as_string())

    print(f"Report emailed to {cfg['recipient']}")


def email_report():
    body = report()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    send_email(f"LLM Scout Report - {date_str}", body)
    mark_seen()


def run():
    """Full cron run: init DB, print report to stdout, email it."""
    init()
    body = report()
    print(body)
    email_report()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "init":
        init()
    elif cmd == "list":
        list_all()
    elif cmd == "new":
        list_new()
    elif cmd == "unregistered":
        list_unregistered()
    elif cmd == "add":
        add(sys.argv[2])
    elif cmd == "sync":
        sync_registered()
    elif cmd == "mark-seen":
        mark_seen()
    elif cmd == "mark-registered":
        api_key = sys.argv[3] if len(sys.argv) > 3 else ""
        mark_registered(sys.argv[2], api_key)
    elif cmd == "report":
        print(report())
    elif cmd == "email-report":
        email_report()
    elif cmd == "run":
        run()
    else:
        print(__doc__)
