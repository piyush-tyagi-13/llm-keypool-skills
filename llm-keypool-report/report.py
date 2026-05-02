#!/usr/bin/env python3
"""
LLM Keypool Report - daily usage digest via email.

Usage:
  python report.py          # generate report, print to stdout, and email user
  python report.py print    # print report only, no email
  python report.py email    # email only (no stdout)
"""

import os
import smtplib
import subprocess
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def _load_hermes_env():
    from pathlib import Path
    env_file = Path.home() / ".hermes" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and not os.environ.get(k):
            os.environ[k] = v

_load_hermes_env()

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
USER_EMAIL = (os.environ.get("EMAIL_ALLOWED_USERS", "") or "").split(",")[0].strip()


def _run_keypool_status() -> str:
    try:
        result = subprocess.run(
            ["llm-keypool", "status"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip() or result.stderr.strip() or "No output from llm-keypool status"
    except FileNotFoundError:
        return "Error: llm-keypool not found on PATH"
    except subprocess.TimeoutExpired:
        return "Error: llm-keypool status timed out"
    except Exception as e:
        return f"Error running llm-keypool status: {e}"


def _run_health_check() -> str:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5) as r:
            return r.read().decode()
    except Exception:
        return "proxy not running or unreachable"


def generate_report() -> str:
    now = datetime.now(timezone.utc)
    lines = []
    lines.append(f"## llm-keypool Daily Report - {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    status_output = _run_keypool_status()
    lines.append("### Key Status")
    lines.append("```")
    lines.append(status_output)
    lines.append("```")
    lines.append("")

    proxy_health = _run_health_check()
    lines.append("### Proxy Health (localhost:8000)")
    lines.append(f"`{proxy_health}`")
    lines.append("")

    # parse status output for a quick summary
    active = status_output.lower().count("yes")
    cooling = status_output.lower().count("no") if "no" in status_output.lower() else 0

    lines.append("### Summary")
    lines.append(f"- Active keys: {active}")
    if cooling:
        lines.append(f"- Keys on cooldown: {cooling}")
    lines.append("")
    lines.append("Run `llm-keypool status` for live details.")
    lines.append("")
    lines.append("---")
    lines.append("Hermes Agent")

    return "\n".join(lines)


def send_email(body: str):
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print("Error: EMAIL_ADDRESS or EMAIL_PASSWORD not set", file=sys.stderr)
        sys.exit(1)
    if not USER_EMAIL:
        print("Error: EMAIL_ALLOWED_USERS not set", file=sys.stderr)
        sys.exit(1)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"llm-keypool Report - {date_str}"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = USER_EMAIL
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(EMAIL_SMTP_HOST, 587) as smtp:
        smtp.starttls()
        smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        smtp.sendmail(EMAIL_ADDRESS, USER_EMAIL, msg.as_string())

    print(f"Report emailed to {USER_EMAIL}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    report = generate_report()

    if cmd in ("all", "print"):
        print(report)

    if cmd in ("all", "email"):
        send_email(report)
