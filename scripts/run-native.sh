#!/usr/bin/env bash
# Run Tempa without Docker (daemon, meet-worker, optional dashboard dev server).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Missing .venv — create it with: python3 -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

PORT="${TEMPA_DAEMON_PORT:-8787}"
LOG_DIR="${TEMPA_LOG_DIR:-/tmp}"
mkdir -p "$LOG_DIR"

health() {
  curl -sf "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1
}

start_xvfb() {
  if ! pgrep -f "Xvfb :99" >/dev/null 2>&1; then
    echo "Starting Xvfb on :99..."
    Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
    sleep 1
  fi
  export DISPLAY=:99
}

start_meet_worker() {
  if pgrep -f "tempa.meet.worker_main" >/dev/null 2>&1; then
    echo "Meet worker already running."
    return
  fi
  start_xvfb
  echo "Starting meet worker..."
  nohup .venv/bin/tempa-meet-worker >"${LOG_DIR}/tempa-meet-worker.log" 2>&1 &
}

start_daemon() {
  if health; then
    echo "Tempa daemon already running on port ${PORT}."
    return
  fi
  echo "Starting Tempa daemon on port ${PORT}..."
  nohup .venv/bin/tempa start >"${LOG_DIR}/tempa-daemon.log" 2>&1 &
  for _ in $(seq 1 30); do
    if health; then
      echo "Daemon is up."
      return
    fi
    sleep 1
  done
  echo "Daemon failed to start — see ${LOG_DIR}/tempa-daemon.log"
  exit 1
}

start_dashboard_dev() {
  if curl -sf "http://127.0.0.1:5173/" >/dev/null 2>&1; then
    echo "Dashboard dev server already running on http://127.0.0.1:5173"
    return
  fi
  if [[ ! -d dashboard/node_modules ]]; then
    echo "Skipping dashboard dev server (run: cd dashboard && npm install && npm run dev)"
    return
  fi
  echo "Starting dashboard dev server on http://127.0.0.1:5173 ..."
  nohup npm --prefix dashboard run dev -- --port 5173 --host >"${LOG_DIR}/tempa-dashboard.log" 2>&1 &
}

ensure_postgres() {
  if docker compose ps postgres 2>/dev/null | grep -q "running"; then
    return
  fi
  if pg_isready -h 127.0.0.1 -p 5432 -U evolution -d evolution >/dev/null 2>&1; then
    return
  fi
  echo "Starting Postgres for WhatsApp bridge (docker compose up postgres -d)..."
  docker compose up postgres -d
  for _ in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U evolution -d evolution >/dev/null 2>&1; then
      echo "Postgres is up."
      return
    fi
    sleep 1
  done
  echo "Postgres failed to start — check docker compose logs postgres"
  exit 1
}

start_whatsapp_bridge() {
  local bridge_dir="${ROOT}/services/whatsapp-bridge"
  local bridge_key="${EVOLUTION_API_KEY:-tempa-evolution-key}"
  if curl -sf -H "apikey: ${bridge_key}" "http://127.0.0.1:8080/" >/dev/null 2>&1; then
    echo "WhatsApp bridge already running on http://127.0.0.1:8080"
    return
  fi
  ensure_postgres
  if [[ ! -d "${bridge_dir}/node_modules" ]]; then
    echo "Installing WhatsApp bridge dependencies (first run)..."
    npm --prefix "${bridge_dir}" ci
    npm --prefix "${bridge_dir}" run db:generate
  fi
  if [[ ! -f "${bridge_dir}/.env" ]]; then
    if [[ -f "${bridge_dir}/.env.example" ]]; then
      cp "${bridge_dir}/.env.example" "${bridge_dir}/.env"
      echo "Created ${bridge_dir}/.env from .env.example"
    else
      echo "Missing ${bridge_dir}/.env — copy from services/whatsapp-bridge/.env.example"
      return
    fi
  fi
  echo "Running WhatsApp bridge database migrations..."
  npm --prefix "${bridge_dir}" run db:deploy 2>/dev/null || true
  echo "Starting WhatsApp bridge on http://127.0.0.1:8080 ..."
  nohup npm --prefix "${bridge_dir}" start >"${LOG_DIR}/tempa-whatsapp-bridge.log" 2>&1 &
  for _ in $(seq 1 30); do
    if curl -sf -H "apikey: ${bridge_key}" "http://127.0.0.1:8080/" >/dev/null 2>&1; then
      echo "WhatsApp bridge is up."
      return
    fi
    sleep 1
  done
  echo "WhatsApp bridge failed to start — see ${LOG_DIR}/tempa-whatsapp-bridge.log"
}

start_meet_worker
start_daemon
start_whatsapp_bridge
start_dashboard_dev

echo ""
echo "Tempa (native)"
echo "  Daemon:    http://127.0.0.1:${PORT}/"
echo "  API:       http://127.0.0.1:${PORT}/api/health"
echo "  Dashboard: http://127.0.0.1:5173/ (dev) or http://127.0.0.1:${PORT}/ (built)"
echo "  WhatsApp:  http://127.0.0.1:8080/"
echo "  Logs:      ${LOG_DIR}/tempa-daemon.log, ${LOG_DIR}/tempa-meet-worker.log, ${LOG_DIR}/tempa-whatsapp-bridge.log"
