# Host git checkouts for Tempa Cursor (Docker)

Inside the container, checkouts appear under `/repos/<name>`.

**Important:** each checkout must be its own bind in `docker-compose.yml`
(e.g. `/host/path:/repos/my-app`). Do **not** mount a parent `./repos:/repos`
alongside nested `/repos/*` binds — Docker keeps the parent and Tempa sees
missing checkouts (live Slack: “can’t reach the project checkout”).

1. Add a volume line: `- /absolute/host/checkout:/repos/my-app`
2. Add a `repos:` entry in `config/cursor_threads.yaml` with `local_cwd: /repos/my-app`
3. Recreate: `docker compose up -d tempa-daemon`

Default CT + worktrees are already in compose via `COMPLIANCETRACKER_PATH` and
`TEMPA_CURSOR_WORKTREE_HOST`.

Rumi agent skills are vendored at `vendor/rumixtempa` and mounted as
`/repos/rumixtempa` (see `docker-compose.yml`). Slack “use rumi …” asks run a
non-PR Cursor job on that pack.

See `config/cursor_threads.yaml.example`.
