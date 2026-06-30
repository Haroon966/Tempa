---
name: meet-copilot
description: Join Google Meet, retrieve minutes and transcripts from unified memory
triggers:
  - meet.google.com
  - minutes
  - transcript
  - last meeting
  - standup
  - join meeting
  - meeting summary
workers:
  - meet
  - rag
tools:
  - meet.join
  - memory.search
channels:
  - slack
  - dashboard
  - whatsapp
priority: 9
---

# Meet Copilot

When a meet.google.com URL appears, queue a join via meet.join if auto-join is enabled.

For "what happened in the meeting" or minutes requests:

1. Search unified memory with tool=meet via memory.search
2. Summarize from retrieved transcript chunks — do not invent attendees or decisions

Auto-join follows Tempa meet settings (trigger before start, skip keywords like OOO).

After Meet completes, transcripts and minutes are ingested to RAG automatically.
