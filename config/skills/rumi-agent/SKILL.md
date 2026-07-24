---
name: rumi-agent
description: Hand org-wide Rumi skills asks (Notion, data, LP, Slack via rumixtempa) to a Cursor job on the vendored pack
triggers:
  - use rumi
  - ask rumi
  - via rumi
  - with rumi
  - rumi do
  - rumi please
  - rumi skills
  - rumi skill
  - rumixtempa
  - agent-skills
  - agent skills
  - do you have rumi
  - can rumi
workers: []
channels:
  - slack
  - dashboard
priority: 90
---

# Rumi agent skills (vendored pack)

When a teammate asks Tempa to **use rumi** (or names rumixtempa / agent-skills / rumi skills):

1. Do **not** run a product coding/PR job, a QA lint scan, or a meeting-archive search.
2. **Capability asks** (“do you have rumi skills?”) → answer immediately from the vendored pack inventory.
3. **Work asks** (“use rumi to …”) → **background Cursor** job with `cwd=/repos/rumixtempa` and `job_kind=rumi_agent`, full pack context in the prompt.
4. Credentials stay on disk (`TOKENS.md` / `KEYS.md`) — never invent a `.env`.

Bare “Rumi” in Meet chatter (bot joined/left) is **not** this skill — require explicit phrasing above.
