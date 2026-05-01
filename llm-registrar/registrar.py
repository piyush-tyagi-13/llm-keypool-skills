#!/usr/bin/env python3
"""
LLM Registrar - helper for semi-autonomous provider signup.

Usage:
  python registrar.py wait-verify <provider>         # poll inbox for verification email, print link
  python registrar.py captcha-alert <provider> <url> # email user that CAPTCHA needs solving
  python registrar.py wait-reply <provider>           # poll inbox for user's "done" reply
  python registrar.py save-password <provider> <pw>  # store generated password in local DB
  python registrar.py send-report <provider> <model> <status> [notes]  # email completion report
"""

import email as email_lib
import imaplib
import json
import os
import re
import smtplib
import sqlite3
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

DB_PATH = Path(os.environ.get("REGISTRAR_DB", Path(__file__).parent / "registrar.db"))

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_IMAP_HOST = os.environ.get("EMAIL_IMAP_HOST", "imap.gmail.com")
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
USER_EMAIL = (os.environ.get("EMAIL_ALLOWED_USERS", "") or "").split(",")[0].strip()


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            provider    TEXT UNIQUE NOT NULL,
            password    TEXT,
            status      TEXT DEFAULT 'pending',
            api_key     TEXT,
            model       TEXT,
            notes       TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_password(provider: str, password: str):
    conn = _db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO registrations (provider, password, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(provider) DO UPDATE SET password=excluded.password, updated_at=excluded.updated_at
    """, (provider.lower(), password, now, now))
    conn.commit()
    conn.close()
    print(f"Password saved for {provider}")


def _imap_connect():
    mail = imaplib.IMAP4_SSL(EMAIL_IMAP_HOST)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    return mail


def _extract_links(body: str) -> list[str]:
    return re.findall(r'https?://[^\s<>"\']+', body)


def _get_email_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                try:
                    body += part.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            pass
    return body


def wait_verify(provider: str, timeout_minutes: int = 10, poll_seconds: int = 30):
    """Poll inbox for verification email from provider. Print the verification link."""
    print(f"Waiting for verification email for {provider} (timeout: {timeout_minutes}min)...", file=sys.stderr)
    deadline = time.time() + timeout_minutes * 60
    provider_lower = provider.lower()

    while time.time() < deadline:
        try:
            mail = _imap_connect()
            mail.select("INBOX")
            _, data = mail.search(None, "UNSEEN")
            ids = data[0].split()

            for uid in reversed(ids):
                _, msg_data = mail.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                sender = (msg.get("From") or "").lower()
                subject = (msg.get("Subject") or "").lower()

                if provider_lower in sender or provider_lower in subject or "verify" in subject or "confirm" in subject:
                    body = _get_email_body(msg)
                    links = _extract_links(body)
                    verify_links = [l for l in links if any(kw in l.lower() for kw in ("verify", "confirm", "activate", "token", "email"))]
                    if verify_links:
                        print(f"Verification link found: {verify_links[0]}")
                        mail.store(uid, "+FLAGS", "\\Seen")
                        mail.logout()
                        return verify_links[0]
                    elif links:
                        print(f"Possible link (no verify keyword): {links[0]}")
                        mail.store(uid, "+FLAGS", "\\Seen")
                        mail.logout()
                        return links[0]

            mail.logout()
        except Exception as e:
            print(f"IMAP error: {e}", file=sys.stderr)

        remaining = int(deadline - time.time())
        if remaining > 0:
            print(f"No email yet, retrying in {poll_seconds}s ({remaining}s left)...", file=sys.stderr)
            time.sleep(poll_seconds)

    print("Timeout: no verification email received", file=sys.stderr)
    sys.exit(1)


def captcha_alert(provider: str, url: str):
    """Email user that CAPTCHA needs solving at url."""
    if not USER_EMAIL:
        print("Error: EMAIL_ALLOWED_USERS not set", file=sys.stderr)
        sys.exit(1)

    subject = f"[Hermes] CAPTCHA needed - {provider} signup"
    body = f"""Hermes encountered a CAPTCHA while signing up for {provider}.

Please open this URL and solve the CAPTCHA:
{url}

Once done, reply to this email with "done" to continue the registration.

---
Hermes Agent
"""
    _send_smtp(subject, body, USER_EMAIL)
    print(f"CAPTCHA alert sent to {USER_EMAIL} for {provider} at {url}")


def wait_reply(provider: str, timeout_minutes: int = 30, poll_seconds: int = 60):
    """Poll inbox for user reply confirming CAPTCHA is solved. Returns when found."""
    print(f"Waiting for user reply for {provider} (timeout: {timeout_minutes}min)...", file=sys.stderr)
    deadline = time.time() + timeout_minutes * 60
    provider_lower = provider.lower()

    while time.time() < deadline:
        try:
            mail = _imap_connect()
            mail.select("INBOX")
            _, data = mail.search(None, "UNSEEN")
            ids = data[0].split()

            for uid in reversed(ids):
                _, msg_data = mail.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                sender = (msg.get("From") or "").lower()
                subject_line = (msg.get("Subject") or "").lower()
                body = _get_email_body(msg).lower()

                is_from_user = any(addr.lower() in sender for addr in (USER_EMAIL, ""))
                mentions_provider = provider_lower in subject_line or provider_lower in body
                has_done = any(kw in body for kw in ("done", "solved", "complete", "finished", "ok", "yes"))

                if is_from_user and (has_done or mentions_provider):
                    print(f"User reply received for {provider} - continuing")
                    mail.store(uid, "+FLAGS", "\\Seen")
                    mail.logout()
                    return

            mail.logout()
        except Exception as e:
            print(f"IMAP error: {e}", file=sys.stderr)

        remaining = int(deadline - time.time())
        if remaining > 0:
            print(f"No reply yet, retrying in {poll_seconds}s ({remaining}s left)...", file=sys.stderr)
            time.sleep(poll_seconds)

    print("Timeout: no user reply received", file=sys.stderr)
    sys.exit(1)


def send_report(provider: str, model: str, status: str, notes: str = ""):
    """Email user a completion report for a registration attempt."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status_label = "SUCCESS" if status == "success" else "FAILED"
    subject = f"[Hermes] Provider Registration {status_label} - {provider}"

    if status == "success":
        body = f"""Registration complete: {provider}

Model added: {model}
Status: {status_label}
Time: {date_str}
{('Notes: ' + notes) if notes else ''}

The key has been added to llm-keypool. Run 'llm-keypool status' to verify.

---
Hermes Agent
"""
    else:
        body = f"""Registration failed: {provider}

Status: {status_label}
Time: {date_str}
{('Reason: ' + notes) if notes else ''}

You may need to register manually at the provider's website.

---
Hermes Agent
"""
    _send_smtp(subject, body, USER_EMAIL)
    print(f"Report sent to {USER_EMAIL}: {provider} {status_label}")

    # update local DB
    conn = _db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO registrations (provider, status, model, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider) DO UPDATE SET status=excluded.status, model=excluded.model, notes=excluded.notes, updated_at=excluded.updated_at
    """, (provider.lower(), status, model, notes, now, now))
    conn.commit()
    conn.close()


def _send_smtp(subject: str, body: str, to: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(EMAIL_SMTP_HOST, 587) as smtp:
        smtp.starttls()
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.sendmail(EMAIL_ADDRESS, to, msg.as_string())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "wait-verify":
        wait_verify(sys.argv[2])
    elif cmd == "captcha-alert":
        captcha_alert(sys.argv[2], sys.argv[3])
    elif cmd == "wait-reply":
        wait_reply(sys.argv[2])
    elif cmd == "save-password":
        save_password(sys.argv[2], sys.argv[3])
    elif cmd == "send-report":
        notes = sys.argv[5] if len(sys.argv) > 5 else ""
        send_report(sys.argv[2], sys.argv[3], sys.argv[4], notes)
    else:
        print(__doc__)
