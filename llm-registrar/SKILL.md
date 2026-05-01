---
name: llm-registrar
description: Semi-autonomous signup for free-tier LLM API providers. Given a provider name, navigates their signup flow, handles email verification, extracts the API key, and adds it to llm-keypool. Pauses for human CAPTCHA solving when needed.
---

# llm-registrar

Registers for a free-tier LLM API provider and loads the resulting key into llm-keypool. Semi-autonomous - handles email verification automatically, pauses and emails the user when a CAPTCHA is encountered.

## When to use

User asks: "register me for <provider>", "sign me up for <provider>", "get an API key for <provider>", "run llm-registrar for <provider>"

## Prerequisites

- browser-harness skill available
- llm-scout DB initialized (for provider metadata)
- llm-keypool installed and on PATH
- EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_SMTP_HOST, EMAIL_ALLOWED_USERS env vars set

## Workflow

### Step 1 - Look up provider

```bash
python ~/.hermes/skills/llm-keypool-skills/llm-scout/scout.py list
```

Find the provider by name. Get: `signup_url`, `base_url`, `models`, `tool_calls`.

If provider not in DB, ask user to confirm the signup URL before proceeding.

### Step 2 - Navigate signup

Use browser-harness. Open signup URL in new tab:

```python
browser-harness <<'PY'
new_tab("<signup_url>")
wait_for_load()
capture_screenshot()
PY
```

Fill the signup form using hermes's own email address (EMAIL_ADDRESS env var).

For name fields: use "Hermes Agent" or "AI Assistant".
For password: generate a random 16-char alphanumeric string. Save it in the notes field via `registrar.py save-password <provider> <password>`.
Do NOT use the user's personal passwords.

### Step 3 - Email verification

After submitting the signup form, watch the EMAIL_ADDRESS inbox for a verification email:

```bash
python ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py wait-verify <provider>
```

This polls IMAP every 30s for up to 10 minutes for an email from the provider containing a verification link. When found, it prints the link. Navigate to that link via browser-harness to complete verification.

### Step 4 - CAPTCHA handling

If you encounter a CAPTCHA (Cloudflare Turnstile, reCAPTCHA, hCaptcha) at any point:

1. Take a screenshot
2. Run:
```bash
python ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py captcha-alert <provider> <current_url>
```
This emails the user with the URL and instructions to solve the CAPTCHA and reply.

3. Wait for reply in inbox:
```bash
python ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py wait-reply <provider>
```
Polls inbox every 60s for up to 30 minutes. Returns when user replies "done" or "solved".

4. After reply: take a fresh screenshot, verify CAPTCHA is gone, continue.

### Step 5 - Find the API key

After successful signup/login, navigate to the provider's API keys page. Common patterns:
- Look for "API Keys", "Developer", "Settings" in the navigation
- Common URLs: `/settings/api-keys`, `/api-keys`, `/account/api-keys`, `/dashboard/api-keys`
- Take a screenshot to find the correct navigation

Create a new API key if needed. Copy the key value.

### Step 6 - Add to llm-keypool

Determine the best model for the key - prefer tool-call-capable models, llama-3.x family:

```bash
llm-keypool add --provider <provider_name> --key <api_key> --model <model_name> --category general_purpose
```

If llm-keypool does not have a built-in provider entry for this provider, use `--provider openrouter` with the provider's base_url override if supported, or add as a custom entry.

Then mark the provider as registered in the scout DB:

```bash
python ~/.hermes/skills/llm-keypool-skills/llm-scout/scout.py mark-registered <provider>
```

### Step 7 - Send report

```bash
python ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py send-report <provider> <model> <success|failed> <notes>
```

Emails the user a summary of what happened.

## Error handling

- If signup page requires phone verification: stop, email user explaining phone verification required, skip provider
- If terms require human agreement review: show the key terms to the user in chat before proceeding
- If API key page is not findable after 5 minutes: stop, email user asking them to extract the key manually
- Always email user on completion or failure

## Notes

- Only use EMAIL_ADDRESS (hermes's own email) for signups - never the user's personal email
- Hermes's email is: read from EMAIL_ADDRESS env var
- Store generated passwords in registrar.py's local DB - never reuse across providers
- Each provider gets its own account on hermes's email
