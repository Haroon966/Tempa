---
name: coolify-deploy
description: Deploy GitHub repos onto this machine via Coolify (create app, envs, deploy, URL)
triggers:
  - deploy
  - redeploy
  - coolify
  - host this
  - put live
  - ship to coolify
workers:
  - plugin
tools:
  - coolify.deploy
  - coolify.status
  - coolify.list_apps
  - coolify.set_envs
channels:
  - slack
  - dashboard
priority: 20
---

# Coolify Deploy

When a teammate wants to deploy or host a repo on this machine:

1. Parse `github.com/owner/repo` (or `owner/repo`), branch, port, and optional `KEY=value` env lines.
2. Confirm before creating a new Coolify app (or redeploying an existing one).
3. Apply env vars via `coolify.set_envs` / `coolify.deploy` — never echo secret values back to Slack.
4. Return the live URL when the deployment finishes.
5. Private repos use an SSH **deploy key** (no Coolify GitHub App). Tempa adds it via your GitHub token when possible; otherwise it posts the public key for you to paste under repo → Settings → Deploy keys.

Do **not** send deploy/hosting asks to Cursor coding jobs or QA scans.
