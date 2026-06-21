# Tempa

Self-hosted AI personal core agent with Gmail, Calendar, Google Meet, and WhatsApp.

## WhatsApp bridge

WhatsApp runs through an **in-repo Baileys bridge** at [`services/whatsapp-bridge/`](services/whatsapp-bridge/). It exposes an Evolution-compatible REST API on port **8080** so the Python daemon does not depend on any `vendor/` folder.

### Docker (recommended)

```bash
cp .env.example .env   # set GROQ_API_KEY, Google OAuth, etc.
docker compose up -d
```

Services: `tempa-daemon` (:8787), `whatsapp-bridge` (:8080), `postgres`, `meet-worker`.

### Native development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env
./scripts/run-native.sh
```

`run-native.sh` starts Postgres via Docker if needed, then the WhatsApp bridge from `services/whatsapp-bridge/`, the Tempa daemon, meet worker, and optional dashboard dev server.

Bridge env template: [`services/whatsapp-bridge/.env.example`](services/whatsapp-bridge/.env.example).

### WhatsApp QR smoke test

```bash
./scripts/test-whatsapp-qr.sh
```

### Migrating from external Evolution API

If you previously used `evoapicloud/evolution-api` with the same Postgres database (`evolution` / `evolution:evolution`), session data is compatible — the bridge uses the same `Instance`, `Session`, `Webhook`, and `Setting` tables. Rename the Docker volume from `evolution_instances` to `whatsapp_instances` or keep mounting the same volume at `/app/instances`.

Environment variable names are unchanged: `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `TEMPA_INSTANCE_NAME`.
