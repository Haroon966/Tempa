---
name: slack-routing-policy
description: Permanent Slack teammate routing — product investigate vs QA vs Cursor
immutable: true
triggers:
  - check if
  - dashboard
  - product
  - scan
  - qa
  - deep review
  - github.com
workers: []
priority: 100
channels:
  - slack
  - dashboard
---

# Slack teammate routing (immutable policy)

- Phrases like "check if the count…", "teacher vanishes", "dashboard shows 128" are **product/data investigations**.
- They must **not** enqueue a lint/tests/security scan just because a product alias maps to a repo.
- **GitHub asks** (github.com URL, `owner/repo`, improve/review/explore a project) go to **Cursor jobs** in the background. Tempa is the Slack face: one short ack, then the Cursor result.
- Short follow-ups in the same thread (`raise PR`, `fix it all`, typos like `rase pr`) inherit the repo from prior turns — never ask which issues to fix when findings are already in the thread.
- **Completed Cursor sessions do not end the thread.** Mid-thread follow-ups still route without another @mention when Tempa already participated or a Cursor job exists for that thread.
- Explicit `github.com/owner/repo` always wins over product aliases. Never let a short alias like `ct` match inside unrelated words (`project`).
- QA scans require **strong** intent (`scan`, `run qa`, `audit`, `deep review`) — never fire just because a message contains `github.com`.
- Product investigations with a known product/repo alias go to **Cursor jobs** (read or write), not `qa_scan_hook`.
- Unmounted GitHub repos use Cursor **cloud** (read/advise, or write with auto PR). Mounted repos use local worktrees for CI fix loops.
- Coding write jobs: one short ack, then silence until the fix is ready. Never spam progress.
- Never post raw exceptions or `fatal:` git advice to Slack.
