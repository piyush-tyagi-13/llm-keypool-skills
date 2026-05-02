---
name: llm-registrar
description: ROADMAP - autonomous signup for free-tier LLM API providers. Not yet implemented.
---

# llm-registrar - Future Roadmap

This skill is a placeholder for future autonomous provider registration.

## Status

**NOT IMPLEMENTED.** Autonomous browser signup was attempted and abandoned.

## What was attempted

A generic script (`register.py`) that:
- Opened signup pages via browser-harness
- Used JS selectors to fill email/password/name fields
- Polled IMAP for verification email
- Tried to extract API key from dashboard via JS

**Why it failed:** Generic JS selectors are blind to page layout. Every provider has a different DOM structure, field names, and flow. Without a vision model seeing the actual rendered page, a script cannot reliably fill and submit arbitrary signup forms.

## What is needed to implement this properly

### Option A - Vision model loop (preferred)
1. Open signup URL in browser
2. Take screenshot
3. Send screenshot to vision-capable model (GPT-4V, Claude 3.5+, Gemini Vision)
4. Model identifies form fields and emits structured actions: `{field: "email", value: "..."}`
5. Execute actions via browser-harness CDP
6. Loop: screenshot -> model -> actions, until dashboard reached
7. Screenshot dashboard, model extracts API key
8. Call `llm-keypool add-key` with extracted key

This requires hermes to have access to a vision model endpoint. Currently not available in the free-tier stack.

### Option B - Per-provider hardcoded flows
Write a dedicated handler per provider (sambanova.py, cohere.py, etc.) with exact selectors and flow steps. Brittle - breaks when provider updates their UI. Does not scale to newly discovered providers.

## Helper utilities (ready for future use)

`registrar.py` contains working email helpers:
- `wait_verify(provider)` - polls IMAP for verification email, returns link
- `captcha_alert(provider)` - emails user asking them to solve CAPTCHA
- `wait_reply(timeout)` - waits for user reply via IMAP
- `send_report(provider, key)` - sends completion email to user
- `save_password(provider, password)` - saves generated password to ~/.hermes/passwords/

These can be plugged into any future implementation.

## Trigger conditions (for future)

When implemented, hermes should run this skill when:
- llm-scout reports new unregistered providers
- User says "register me for <provider>"
- User says "get an API key for <provider>"
