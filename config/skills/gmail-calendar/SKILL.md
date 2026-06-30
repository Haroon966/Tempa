---
name: gmail-calendar
description: Search Gmail and list Google Calendar events; compose/send requires approval
triggers:
  - email
  - gmail
  - inbox
  - mail
  - calendar
  - schedule
  - agenda
  - tomorrow
  - meeting
  - event
workers:
  - gmail
  - calendar
tools:
  - gmail.search
  - calendar.list_events
channels:
  - slack
  - dashboard
  - whatsapp
priority: 7
---

# Gmail and Calendar

Search vs action:

- Search/read: use gmail.search or calendar.list_events immediately
- Compose, send, reply, forward: create a pending action and wait for owner approval

Calendar queries use the owner's timezone from Tempa settings. When listing events, include Meet links when present.

On Slack, only the owner may access Gmail and Calendar — guests must be refused politely.

When both email and calendar are relevant (e.g. "meetings and unread mail"), run both workers in parallel.
