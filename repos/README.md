# Host git checkouts for Tempa Cursor (Docker)

Mount point inside the container: `/repos` (see `TEMPA_REPOS_HOST` in docker-compose).

1. Clone or symlink a repo here, e.g. `./repos/my-app`
2. Add a `repos:` entry in `config/cursor_threads.yaml` with `local_cwd: /repos/my-app`
3. Restart the daemon

See `config/cursor_threads.yaml.example`.
