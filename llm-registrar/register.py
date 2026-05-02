#!/usr/bin/env python3
"""
Fully autonomous provider signup. Drives browser-harness via subprocess.
No hermes involvement after launch - runs end to end.

Usage:
  python3 register.py <provider>

Supported: sambanova, cohere, cloudflare
"""

import email as email_lib
import imaplib
import json
import os
import re
import secrets
import smtplib
import sqlite3
import string
import subprocess
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SCOUT_PY = SCRIPT_DIR.parent / "llm-scout" / "scout.py"
SCOUT_DB = Path(os.environ.get("SCOUT_DB", SCRIPT_DIR.parent / "llm-scout" / "providers.db"))


def _load_hermes_env():
    """Load email credentials from ~/.hermes/.env if not already in environment."""
    env_file = Path.home() / ".hermes" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and not os.environ.get(k):
            os.environ[k] = v


_load_hermes_env()

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
IMAP_HOST = os.environ.get("EMAIL_IMAP_HOST", "imap.gmail.com")
SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
USER_EMAIL = (os.environ.get("EMAIL_ALLOWED_USERS", "") or "").split(",")[0].strip()

PROVIDERS = {
    "sambanova": {
        "name": "SambaNova",
        "signup_url": "https://cloud.sambanova.ai",
        "api_key_url": "https://cloud.sambanova.ai/apis",
        "model": "Meta-Llama-3.3-70B-Instruct",
        "email_hint": "sambanova",
    },
    "cohere": {
        "name": "Cohere",
        "signup_url": "https://dashboard.cohere.com/register",
        "api_key_url": "https://dashboard.cohere.com/api-keys",
        "model": "command-r-plus-08-2024",
        "email_hint": "cohere",
    },
    "cloudflare": {
        "name": "Cloudflare",
        "signup_url": "https://dash.cloudflare.com/sign-up",
        "api_key_url": "https://dash.cloudflare.com/profile/api-tokens",
        "model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "email_hint": "cloudflare",
        "notes": "Requires account_id in base_url - check Workers AI after registration",
    },
}

# ── browser-harness ────────────────────────────────────────────────────────────

_BH_CANDIDATES = [
    "/Users/azzbeeter/.local/bin/browser-harness",
    os.path.expanduser("~/.local/bin/browser-harness"),
    "/opt/homebrew/bin/browser-harness",
]

def _find_bh() -> str:
    import shutil
    found = shutil.which("browser-harness")
    if found:
        return found
    for p in _BH_CANDIDATES:
        if os.path.exists(p):
            return p
    return "browser-harness"

_BH = _find_bh()


def bh(code: str, timeout: int = 60) -> str:
    """Run Python code via browser-harness -c flag. Return stdout+stderr."""
    try:
        r = subprocess.run([_BH, "-c", code], capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        print(f"[register] ERROR: browser-harness not found (tried: {_BH})", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def bh_json(code: str, timeout: int = 60) -> dict:
    out = bh(code, timeout)
    # find last JSON object in output
    for m in reversed(list(re.finditer(r'\{[^{}]{2,}\}', out, re.DOTALL))):
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {"raw": out}


# ── signup helpers ─────────────────────────────────────────────────────────────

_FILL_JS = r"""(function(em, pw) {
    function find(sels) { for (var s of sels) { var e=document.querySelector(s); if(e) return e; } return null; }
    function fill(e, v) {
        if (!e) return false;
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e, v);
        e.dispatchEvent(new Event('input',{bubbles:true}));
        e.dispatchEvent(new Event('change',{bubbles:true}));
        return true;
    }
    fill(find(['input[type="email"]','input[name="email"]','input[id*="email" i]','input[placeholder*="email" i]']), em);
    fill(find(['input[type="password"]','input[name="password"]','input[id*="password" i]']), pw);
    fill(find(['input[name="name"]','input[name="full_name"]','input[id*="name" i]','input[placeholder*="full name" i]']), 'Hermes Agent');
    fill(find(['input[name="first_name"]','input[name="firstName"]','input[id*="first" i]','input[placeholder*="first" i]']), 'Hermes');
    fill(find(['input[name="last_name"]','input[name="lastName"]','input[id*="last" i]','input[placeholder*="last" i]']), 'Agent');
    var body = document.body.innerHTML.toLowerCase();
    var cap = body.includes('captcha')||body.includes('turnstile')||body.includes('hcaptcha')||body.includes('cf-challenge');
    var sub = document.querySelector('button[type="submit"]') ||
        Array.from(document.querySelectorAll('button')).find(b=>/sign.?up|register|create|get.?start|continue/i.test(b.innerText));
    return JSON.stringify({captcha:cap, submit:!!sub, url:location.href, title:document.title});
})('EMAIL','PASSWORD')"""

_SUBMIT_JS = r"""(function() {
    var btn = document.querySelector('button[type="submit"]') ||
        Array.from(document.querySelectorAll('button')).find(b=>/sign.?up|register|create|continue/i.test(b.innerText));
    if (btn) { btn.click(); return {clicked:true, text:btn.innerText.trim()}; }
    return {clicked:false};
})()"""

_FIND_KEY_JS = r"""(function() {
    var inputs = Array.from(document.querySelectorAll('input,textarea')).map(i=>(i.value||'').trim()).filter(v=>v.length>20&&v.length<300);
    var codes = Array.from(document.querySelectorAll('code,pre,[class*="key"],[class*="token"],[class*="secret"],[class*="api-key"]'))
        .map(e=>e.innerText.trim()).filter(v=>v.length>20&&v.length<300&&/^[A-Za-z0-9_\-\.]+$/.test(v));
    var create = Array.from(document.querySelectorAll('button,a')).find(b=>/create|add|generate|new.*key/i.test(b.innerText));
    return JSON.stringify({inputs:inputs.slice(0,5), codes:codes.slice(0,5), hasCreate:!!create, url:location.href, title:document.title});
})()"""


def navigate_fill_submit(signup_url: str, email: str, password: str) -> dict:
    fill_js = _FILL_JS.replace("EMAIL", email).replace("PASSWORD", password)
    code = f"""
import json, time
new_tab({json.dumps(signup_url)})
wait_for_load()
time.sleep(2)
fill_r = js({json.dumps(fill_js)})
print("FILL:" + (fill_r if isinstance(fill_r, str) else json.dumps(fill_r)))
"""
    out = bh(code, timeout=30)
    fill_data = {}
    m = re.search(r'FILL:(\{.*\})', out)
    if m:
        try:
            fill_data = json.loads(m.group(1))
        except Exception:
            pass

    if fill_data.get("captcha"):
        return {**fill_data, "stage": "pre_submit"}

    # submit
    code2 = f"""
import json, time
sub_r = js({json.dumps(_SUBMIT_JS)})
time.sleep(3)
wait_for_load()
time.sleep(2)
body = js('document.body.innerHTML.toLowerCase()') or ''
info = page_info()
cap = any(k in body for k in ['captcha','turnstile','hcaptcha','cf-challenge'])
err = any(k in body for k in ['error','invalid','already exists','already registered'])
ok  = any(k in body for k in ['verify','check your email','confirmation','thank you','success','check your inbox'])
print(json.dumps({{'submitted': sub_r, 'captcha': cap, 'error': err, 'success': ok, 'url': info.get('url',''), 'title': info.get('title',''), 'stage': 'post_submit'}}))
"""
    return bh_json(code2, timeout=30)


def nav_link(url: str) -> dict:
    code = f"""
import json, time
new_tab({json.dumps(url)})
wait_for_load()
time.sleep(3)
info = page_info()
print(json.dumps({{'url': info.get('url',''), 'title': info.get('title','')}}))
"""
    return bh_json(code, timeout=20)


def get_api_key(api_key_url: str) -> str | None:
    code = f"""
import json, time
new_tab({json.dumps(api_key_url)})
wait_for_load()
time.sleep(3)
create_r = js({json.dumps(_FIND_KEY_JS)})
if isinstance(create_r, dict) and create_r.get('hasCreate'):
    # try clicking create button
    click_js = '''(function() {{
        var b = Array.from(document.querySelectorAll('button,a')).find(b=>/create|add|generate|new.*key/i.test(b.innerText));
        if (b) {{ b.click(); return true; }}
        return false;
    }})()'''
    js(click_js)
    import time as t; t.sleep(2)
r2 = js({json.dumps(_FIND_KEY_JS)})
print(r2 if isinstance(r2, str) else json.dumps(r2))
"""
    data = bh_json(code, timeout=30)
    pat = re.compile(r'^[A-Za-z0-9_\-\.]+$')
    for val in data.get("inputs", []) + data.get("codes", []):
        val = val.strip()
        if 20 < len(val) < 300 and pat.match(val):
            return val
    return None


# ── email ──────────────────────────────────────────────────────────────────────

def _body(msg) -> str:
    out = ""
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() in ("text/plain", "text/html"):
                try: out += p.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception: pass
    else:
        try: out = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception: pass
    return out


def poll_verify(hint: str, timeout_min: int = 10) -> str | None:
    print(f"[register] Polling inbox for {hint} verification email...")
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL(IMAP_HOST)
            m.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            m.select("INBOX")
            _, data = m.search(None, "UNSEEN")
            for uid in reversed((data[0] or b"").split()):
                _, raw = m.fetch(uid, "(RFC822)")
                msg = email_lib.message_from_bytes(raw[0][1])
                sender = (msg.get("From") or "").lower()
                subj = (msg.get("Subject") or "").lower()
                if hint in sender or hint in subj or any(k in subj for k in ("verify","confirm","activate")):
                    body = _body(msg)
                    links = re.findall(r'https?://[^\s<>"\']+', body)
                    vlinks = [l for l in links if any(k in l.lower() for k in ("verify","confirm","activate","token","validation"))]
                    link = (vlinks or links or [None])[0]
                    if link:
                        m.store(uid, "+FLAGS", "\\Seen")
                        m.logout()
                        print(f"[register] Verify link: {link}")
                        return link
            m.logout()
        except Exception as e:
            print(f"[register] IMAP: {e}", file=sys.stderr)
        remaining = int(deadline - time.time())
        if remaining > 10:
            print(f"[register] No email yet ({remaining}s left)...")
            time.sleep(30)
    return None


def poll_reply(timeout_min: int = 30) -> bool:
    print(f"[register] Waiting for user 'done' reply...")
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL(IMAP_HOST)
            m.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            m.select("INBOX")
            _, data = m.search(None, "UNSEEN")
            for uid in reversed((data[0] or b"").split()):
                _, raw = m.fetch(uid, "(RFC822)")
                msg = email_lib.message_from_bytes(raw[0][1])
                sender = (msg.get("From") or "").lower()
                body = _body(msg).lower()
                if USER_EMAIL.lower() in sender and any(k in body for k in ("done","solved","ok","yes","complete")):
                    m.store(uid, "+FLAGS", "\\Seen")
                    m.logout()
                    return True
            m.logout()
        except Exception as e:
            print(f"[register] IMAP: {e}", file=sys.stderr)
        time.sleep(60)
    return False


def _smtp(subject: str, body: str):
    if not USER_EMAIL: return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = USER_EMAIL
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(SMTP_HOST, 587) as s:
        s.starttls()
        s.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        s.sendmail(EMAIL_ADDRESS, USER_EMAIL, msg.as_string())


def captcha_alert(provider: str, url: str):
    _smtp(f"[Hermes] CAPTCHA needed - {provider}",
          f"CAPTCHA at: {url}\n\nSolve it then reply 'done'.\n\n- Hermes")
    print(f"[register] CAPTCHA alert -> {USER_EMAIL}")


def send_report(provider: str, model: str, ok: bool, notes: str = ""):
    label = "SUCCESS" if ok else "FAILED"
    body = (f"Registered: {provider}\nModel: {model}\nKey in llm-keypool (agentic).\n{notes}\n\n- Hermes"
            if ok else f"Failed: {provider}\n{notes}\n\n- Hermes")
    _smtp(f"[Hermes] Registration {label} - {provider}", body)
    print(f"[register] Report sent: {label}")


# ── main ───────────────────────────────────────────────────────────────────────

def register(provider_name: str):
    cfg = PROVIDERS.get(provider_name.lower())
    if not cfg:
        print(f"Unknown provider: {provider_name}. Supported: {', '.join(PROVIDERS)}")
        sys.exit(1)

    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print("ERROR: EMAIL_ADDRESS or EMAIL_PASSWORD not set")
        sys.exit(1)

    name = cfg["name"]
    pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(18))

    print(f"\n[register] {name} - autonomous signup")
    print(f"[register] Email: {EMAIL_ADDRESS}")
    print(f"[register] Signup: {cfg['signup_url']}")

    # 1. navigate, fill, submit
    print("\n[register] Step 1: Fill and submit signup form")
    result = navigate_fill_submit(cfg["signup_url"], EMAIL_ADDRESS, pw)
    print(f"[register] {result}")

    if result.get("captcha"):
        print("[register] CAPTCHA detected - alerting user")
        captcha_alert(name, result.get("url", cfg["signup_url"]))
        if not poll_reply(30):
            send_report(provider_name, "", False, "CAPTCHA timeout - no user reply")
            sys.exit(1)
        # retry submit after captcha
        result = navigate_fill_submit(cfg["signup_url"], EMAIL_ADDRESS, pw)
        print(f"[register] After captcha: {result}")

    if result.get("error"):
        print("[register] Warning: error detected on page after submit (may already be registered or form failed)")

    # 2. email verification
    print("\n[register] Step 2: Email verification")
    link = poll_verify(cfg["email_hint"], timeout_min=10)
    if link:
        print(f"\n[register] Step 3: Navigate verification link")
        nav = nav_link(link)
        print(f"[register] Now at: {nav.get('url','?')}")
        time.sleep(2)
    else:
        print("[register] No verification email (may not be required, continuing)")

    # 3. extract API key
    print(f"\n[register] Step 4: Extract API key from {cfg['api_key_url']}")
    api_key = get_api_key(cfg["api_key_url"])

    if not api_key:
        print("[register] Could not extract key automatically")
        send_report(provider_name, "", False,
                    f"Key not found at {cfg['api_key_url']} - register manually at {cfg['signup_url']}")
        sys.exit(1)

    print(f"[register] Key found: {api_key[:8]}...{api_key[-4:]}")

    # 4. add to keypool
    print("\n[register] Step 5: Add to llm-keypool")
    r = subprocess.run(
        ["llm-keypool", "add", "--provider", provider_name, "--key", api_key,
         "--model", cfg["model"], "--category", "agentic"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f"[register] keypool add failed: {r.stderr}")
        send_report(provider_name, "", False, f"llm-keypool add failed: {r.stderr.strip()}")
        sys.exit(1)
    print(f"[register] Added to keypool (agentic category)")

    # mark scout DB
    if SCOUT_PY.exists():
        subprocess.run(["python3", str(SCOUT_PY), "mark-registered", provider_name], capture_output=True)

    # 5. report
    notes = cfg.get("notes", "")
    send_report(provider_name, cfg["model"], True, notes)
    print(f"\n[register] Done! {name} registered.")
    if notes:
        print(f"[register] Note: {notes}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    register(sys.argv[1])
