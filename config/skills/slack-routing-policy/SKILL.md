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

- **Rumi skills pack** is a hard route (`classify_rumi`): capability asks get the pack inventory; work asks (`use rumi to…`) get a Cursor job on `/repos/rumixtempa`. Never answer these from meeting archives / RAG (name collision with Meet bot and meetings titled “Rumi …”).
- Phrases like "check if the count…", "teacher vanishes", "dashboard shows 128" are **product/data investigations**.
- They must **not** enqueue a lint/tests/security scan just because a product alias maps to a repo.
- **Use rumi / ask rumi / rumixtempa / agent-skills / rumi skills** → pack route above. Bare “Rumi” Meet-bot chatter is not this path.
- **GitHub asks** (github.com URL, `owner/repo`, improve/review/explore a project) go to **Cursor jobs** in the background. Tempa is the Slack face: one short ack, then the Cursor result.
- **Deploy / host / Coolify** (`deploy this repo`, `redeploy`, `coolify`, put live on this machine) go to **Coolify**, not Cursor or QA. Confirm → set envs → deploy → return the live URL.
- Short follow-ups in the same thread (`raise PR`, `fix it all`, typos like `rase pr`) inherit the repo from prior turns — never ask which issues to fix when findings are already in the thread.
- **Completed Cursor sessions do not end the thread.** Mid-thread follow-ups still route without another @mention when Tempa already participated or a Cursor job exists for that thread.
- Explicit `github.com/owner/repo` always wins over product aliases. Never let a short alias like `ct` match inside unrelated words (`project`).
- QA scans require **strong** intent (`scan`, `run qa`, `audit`, `deep review`) — never fire just because a message contains `github.com`.
- Product investigations with a known product/repo alias go to **Cursor jobs** (read or write), not `qa_scan_hook`.
- Unmounted GitHub repos use Cursor **cloud** (read/advise, or write with auto PR). Mounted repos use local worktrees for CI fix loops.
- Unmounted **write** jobs: when Tempa can clone the repo with its GitHub token, use a **local mirror** + `gh pr create` instead of Cursor cloud (cloud often cannot see arbitrary repos).
- Coding write jobs: one short ack, then silence until the fix is ready. Never spam progress.
- Never post raw exceptions or `fatal:` git advice to Slack.
- Never continue a **merged or closed** PR. On write/raise/fix, open a **new** PR; if the user only asks to work on a dead PR, suggest opening a new one.
