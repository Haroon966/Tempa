---
name: slack-messaging
description: Read and send Slack messages with correct mrkdwn formatting and thread continuity
triggers:
  - slack
  - dm
  - thread
  - send message
  - channel
  - mention
workers:
  - channel
channels:
  - slack
  - dashboard
priority: 8
---

# Slack Messaging

Answer the user's Slack message directly with as much detail as needed.

Formatting (Slack mrkdwn only):

- *bold*, _italic_, `inline code`, triple-backtick code blocks
- Do not use **double asterisks**, ## headers, or [text](url) links

Behavior:

- Continue the thread naturally — do not repeat prior answers or re-introduce yourself
- Do not mention merging specialists or internal tools
- Do not bring up unrelated WhatsApp, email, or calendar unless they asked

Owner sends from Slack skip confirmation when privileged. Guest users cannot access email, calendar, WhatsApp, or meeting tools on Slack — use the guest refusal message if they ask.
