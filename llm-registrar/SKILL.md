---
name: llm-registrar
description: Semi-autonomous signup for free-tier LLM API providers. Registers for a provider and adds the API key to llm-keypool.
---

# llm-registrar

## When to use

User says: "run llm-registrar for <provider>", "register me for <provider>", "get an API key for <provider>"

## How to run

Run this single command. It does everything autonomously - no further steps needed from you.
Replace <provider> with the provider name (sambanova, cohere, or cloudflare):

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-registrar/register.py <provider>
```

Wait for it to finish. It will:
- Open the signup page via browser-harness
- Fill and submit the form
- Poll the hermes inbox for verification email
- Navigate the verification link
- Extract the API key from the dashboard
- Add it to llm-keypool
- Email the user a completion report

If it prints "[register] CAPTCHA alert -> ..." that means it emailed the user and is waiting for a reply.
Do not interrupt the process. It runs to completion on its own.
