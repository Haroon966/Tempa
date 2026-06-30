---
name: qa-repos
description: Monitor repos, explain CI failures, propose fixes, trigger QA scans
triggers:
  - ci fail
  - ci failed
  - test fail
  - vulnerability
  - branch health
  - dependabot
  - qa status
  - qa report
  - code quality
workers:
  - qa
channels:
  - slack
  - dashboard
priority: 6
---

# QA and Repos

When the user reports CI failures, test failures, or security issues:

1. Invoke the QA worker to scan configured repos from varys.yaml
2. Explain findings in plain language with file/line references when available
3. For deep fixes, point to the agent-playbook API — do not silently push code

Repo scans that modify state require pending action `qa_repo_scan` approval.

If the repo is ambiguous, ask for the GitHub URL or owner/repo name.
