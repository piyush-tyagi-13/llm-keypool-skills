---
name: llm-registrar
description: Semi-autonomous signup for free-tier LLM API providers. Given a provider name, navigates their signup flow, handles email verification, extracts the API key, and adds it to llm-keypool. Pauses for human CAPTCHA solving when needed.
---

# llm-registrar

## IMPORTANT - execute commands, do not reason

Every step below is a shell command or browser-harness script to run. Do not describe, summarize, or ask the user anything unless a step explicitly says to. Run each step in sequence.

## Invocation

User says: "run llm-registrar for <provider>" or "register me for <provider>" or "get an API key for <provider>"

## Step 1 - Get provider details from scout DB

Run immediately:

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-scout/scout.py list
```

Find the provider entry. Get `signup_url`, `base_url`, `models`. If `signup_url` is empty, search the web for "<provider> free API signup" and use the result.

## Step 2 - Open signup page

Run immediately:

```bash
browser-harness <<'PY'
new_tab("<signup_url from step 1>")
wait_for_load()
capture_screenshot()
PY
```

## Step 3 - Fill signup form

Use the hermes email address from the EMAIL_ADDRESS environment variable. Fill:
- Email: value of $EMAIL_ADDRESS
- Name: "Hermes Agent"
- Password: generate a random 16-char alphanumeric string

Save the generated password immediately:

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py save-password <provider> <generated_password>
```

Submit the form via browser-harness.

## Step 4 - Poll for verification email

Run immediately after form submit. Do NOT ask the user to check email:

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py wait-verify <provider>
```

When the script prints a URL, navigate to it:

```bash
browser-harness <<'PY'
new_tab("<url printed by wait-verify>")
wait_for_load()
capture_screenshot()
PY
```

## Step 5 - Handle CAPTCHA (only if encountered)

If a screenshot shows a CAPTCHA, run immediately - do not ask user in chat:

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py captcha-alert <provider> <current_url>
```

Then poll for user's reply - do not wait in chat:

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py wait-reply <provider>
```

After script returns, take a new screenshot and continue.

## Step 6 - Find and copy the API key

Navigate to the API keys page. Common patterns to try in order:
- Look for "API Keys" or "Developer" in the nav menu
- Try URLs: `/api-keys`, `/settings/api-keys`, `/account/api-keys`, `/dashboard`

Take a screenshot. Create a new key if needed. Copy the key value.

## Step 7 - Add to llm-keypool

Run immediately:

```bash
llm-keypool add --provider <provider> --key <api_key> --model <best_model_from_step_1> --category general_purpose
```

Then mark as registered in scout DB:

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-scout/scout.py mark-registered <provider>
```

## Step 8 - Send completion report

Run immediately:

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py send-report <provider> <model> success
```

Or on failure:

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-registrar/registrar.py send-report <provider> "" failed "<reason>"
```

## Stop conditions (only times to pause and ask user)

- Signup page requires phone number verification
- After 5 minutes cannot find API key page
- Provider requires paid plan to access API
