---
name: llm-registrar
description: Semi-autonomous signup for free-tier LLM API providers. Registers for a provider and adds the API key to llm-keypool.
---

# llm-registrar

## When to use

User says: "run llm-registrar for <provider>", "register me for <provider>", "get an API key for <provider>"

## How to run

Run this command immediately. Replace <provider> with the provider name (e.g. sambanova, cohere):

```bash
python3 ~/.hermes/skills/llm-keypool-skills/llm-registrar/register.py <provider> start
```

Read the output. It tells you exactly what to do next and gives you the next command to run.
Follow the output instructions step by step. Do not skip steps or improvise.
Each step ends with a "NEXT COMMAND" line - run that command when the step is done.
