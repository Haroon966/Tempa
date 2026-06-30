---
name: jira-tickets
description: Create, edit, search, and comment on Jira issues from Slack or dashboard
triggers:
  - jira
  - ticket
  - issue
  - jql
  - backlog
  - sprint
  - assign me
  - create ticket
workers:
  - plugin
tools:
  - jira.search
  - jira.get_issue
  - jira.list_projects
channels:
  - slack
  - dashboard
  - whatsapp
priority: 10
---

# Jira Tickets

When the user wants to create or edit a Jira issue:

1. Parse the request for summary, assignee hint, project, and priority.
2. If details are missing, ask one clear question — never invent issue keys or assignees.
3. Show a draft preview before creating anything.
4. Wait for explicit confirmation (yes, go, create it, lgtm, confirm).
5. On confirm, create a pending action `jira_create_issue` — never create silently.

For search or lookup:

- Use `jira.list_projects` when the user asks which projects exist.
- Use `jira.get_issue` when an issue key like ENG-123 appears in the message.
- Use `jira.search` with JQL when the user asks to search or list issues.

Assignee resolution uses synced Jira user profiles. Rate limits apply per user session.

Cancel words: cancel, never mind — clear any active draft.
