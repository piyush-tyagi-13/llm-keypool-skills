---
name: llm-scout
description: Searches the web for new free-tier LLM API providers, evaluates them, updates the scout DB, and emails a report. Run daily via cron.
---

# llm-scout

Discovers free-tier LLM API providers. Uses browser-harness to search the web, evaluates each provider's free tier and tool-call support, persists results to SQLite, and emails a report.

## When to use

- Daily cron trigger (9:15 PM)
- User asks: "find new free LLM providers", "scout for APIs", "any new providers?"

## Run

```bash
python ~/.hermes/skills/llm-keypool-skills/llm-scout/scout.py run
```

Or trigger manually in chat: "run llm-scout"

## Workflow

1. Call `scout.py init` to ensure DB exists
2. Use browser-harness to search for new providers (see search queries below)
3. For each result: visit signup/docs page, extract provider details
4. Call `scout.py add '<json>'` for each provider found
5. Call `scout.py report` to get formatted report text
6. Email report to user via SMTP (credentials from env: EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_SMTP_HOST)
7. Call `scout.py mark-seen` to clear new flags

## Browser search queries

Run these searches in sequence, deduplicate results:

- `"free LLM API 2025 no credit card" site:reddit.com OR site:news.ycombinator.com`
- `"free tier LLM API key" tool calling 2025`
- `"openai compatible API" free tier 2025`
- `site:github.com "free LLM" OR "free tier" API provider 2025`

For each candidate URL found, visit the page and extract:
- Provider name
- Base URL (OpenAI-compatible endpoint if available)
- Free tier details (RPM, RPD, token limits)
- Tool/function calling support (yes/no/unknown)
- Signup URL
- Recommended model name

Skip providers already in the DB (check with `scout.py list` first).

## Provider evaluation criteria

Include if ALL true:
- Free tier available with no credit card required
- OpenAI-compatible API (or has SDK)
- At least one text generation model

Prefer if:
- Tool/function calling supported
- Llama 3.x or similar open model available
- RPD >= 100

Skip:
- Paid-only or requires credit card for free tier
- No API access (chat-only products)
- Already in DB

## scout.py add JSON shape

```json
{
  "name": "provider-name",
  "base_url": "https://api.provider.com/v1",
  "free_tier": 1,
  "tool_calls": 1,
  "models": ["model-name-1", "model-name-2"],
  "notes": "100 RPD free, no CC required",
  "signup_url": "https://provider.com/signup"
}
```

## Email report

Subject: `LLM Scout Report - YYYY-MM-DD`
Body: output of `scout.py report` (markdown)
To: value of EMAIL_ALLOWED_USERS env var (first address)
From: EMAIL_ADDRESS env var

Send via SMTP: EMAIL_SMTP_HOST:587, STARTTLS, auth with EMAIL_ADDRESS + EMAIL_PASSWORD.
