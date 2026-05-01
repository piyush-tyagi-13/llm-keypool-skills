---
name: llm-keypool-report
description: Emails the user a daily digest of all llm-keypool keys - usage counts, cooldowns, and pool health. Run daily via cron.
---

# llm-keypool-report

Generates and emails a usage digest for all keys registered in llm-keypool.

## When to use

- Daily cron trigger
- User asks: "how are my API keys doing", "send me a key usage report", "llm-keypool status by email"

## Run

```bash
python ~/.hermes/skills/llm-keypool-skills/llm-keypool-report/report.py
```

## What it reports

- Total keys, active vs on cooldown
- Per-key: provider, model, requests today, cooldown status
- Pool health summary
- Any keys that are cooling down with estimated reset time

## Cron setup

Already configured via hermes cron. Runs daily at 9:00 AM alongside the scout run.
