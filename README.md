# llm-keypool-skills

Hermes Agent skills for autonomous free-tier LLM API management. Works with [llm-keypool](https://github.com/piyushtyagi/llm-keypool).

## Skills

| Skill | What it does | Autonomous? |
|---|---|---|
| [llm-scout](llm-scout/) | Searches web for new free-tier LLM providers, updates DB, emails report | Fully autonomous |
| [llm-registrar](llm-registrar/) | Signs up for a provider, handles email verification, adds key to llm-keypool | Semi-autonomous (pauses for CAPTCHA) |
| [llm-keypool-report](llm-keypool-report/) | Emails daily digest of all key usage and pool health | Fully autonomous |

## Setup

### 1. Clone this repo

```bash
git clone https://github.com/piyushtyagi/llm-keypool-skills ~/.hermes/skills/llm-keypool-skills
```

### 2. Add to hermes config

```yaml
# ~/.hermes/config.yaml
skills:
  external_dirs:
    - /Users/<you>/.hermes/skills/llm-keypool-skills/llm-scout
    - /Users/<you>/.hermes/skills/llm-keypool-skills/llm-registrar
    - /Users/<you>/.hermes/skills/llm-keypool-skills/llm-keypool-report
```

### 3. Initialize the scout DB

```bash
python ~/.hermes/skills/llm-keypool-skills/llm-scout/scout.py init
```

### 4. Set up cron in hermes

Ask hermes: "set a daily cron for llm-scout at 9:15 PM and llm-keypool-report at 9:00 AM"

## Requirements

- [hermes-agent](https://github.com/nousresearch/hermes-agent) with email gateway configured
- [browser-harness](https://github.com/piyushtyagi/browser-harness) on PATH
- [llm-keypool](https://github.com/piyushtyagi/llm-keypool) installed
- Env vars: `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_SMTP_HOST`, `EMAIL_ALLOWED_USERS`

## How it fits together

```
llm-scout (nightly)
    finds new free providers
    emails you the list
        |
        v
llm-registrar (on demand)
    you: "register me for <provider>"
    hermes signs up using its own email
    handles email verification automatically
    pauses + emails you if CAPTCHA hit
    adds key to llm-keypool on success
        |
        v
llm-keypool proxy
    transparent rotation across all registered keys
    hermes-agent uses it as its LLM backend
    zero paid API cost
        |
        v
llm-keypool-report (daily)
    emails you usage stats
    shows which keys are active vs cooling
```
