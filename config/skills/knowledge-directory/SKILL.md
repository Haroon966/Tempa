---
name: knowledge-directory
description: Prefer vault knowledge/ people+channels before live Slack/contacts lookups when messaging.
---

# Knowledge directory

When the user asks to message someone or post in a Slack channel / send email / WhatsApp:

1. First consult vault files under `knowledge/`:
   - `knowledge/routing.md` — short aliases (Moawin huddle, Punjab, owner)
   - `knowledge/people.md` — names with Slack ID, email, phone/WhatsApp
   - `knowledge/channels.md` — Slack channel names + ids + membership
2. Use listed Slack user ids / channel ids directly — do not re-search Slack for the same person.
3. Only fall back to live Slack/contacts/WhatsApp APIs when the directory miss or data looks stale.
4. If the directory is empty or clearly outdated, refresh it via knowledge refresh (or ask Tempa ops).
