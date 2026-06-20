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

start_evolution_api() {
  local evo_dir="${ROOT}/vendor/evolution-api"
  local evo_key="${EVOLUTION_API_KEY:-tempa-evolution-key}"
  if curl -sf -H "apikey: ${evo_key}" "http://127.0.0.1:8080/" >/dev/null 2>&1; then
    echo "Evolution API already running on http://127.0.0.1:8080"
    return
  fi
  if [[ ! -d "${evo_dir}/node_modules" ]]; then
    echo "Installing Evolution API dependencies (first run)..."
    npm --prefix "${evo_dir}" ci
    npm --prefix "${evo_dir}" run db:generate
  fi
  if [[ ! -f "${evo_dir}/.env" ]]; then
    echo "Missing ${evo_dir}/.env — copy from vendor/evolution-api/.env.example and set DATABASE_CONNECTION_URI"
    return
  fi
  echo "Starting Evolution API on http://127.0.0.1:8080 ..."
  nohup npm --prefix "${evo_dir}" start >"${LOG_DIR}/tempa-evolution-api.log" 2>&1 &
  for _ in $(seq 1 30); do
    if curl -sf -H "apikey: ${evo_key}" "http://127.0.0.1:8080/" >/dev/null 2>&1; then
      echo "Evolution API is up."
      return
    fi
    sleep 1
  done
  echo "Evolution API failed to start — see ${LOG_DIR}/tempa-evolution-api.log"
}

start_meet_worker
start_daemon
start_evolution_api
start_dashboard_dev

echo ""
echo "Tempa (native)"
echo "  Daemon:    http://127.0.0.1:${PORT}/"
echo "  API:       http://127.0.0.1:${PORT}/api/health"
echo "  Dashboard: http://127.0.0.1:5173/ (dev) or http://127.0.0.1:${PORT}/ (built)"
echo "  Evolution: http://127.0.0.1:8080/"
echo "  Logs:      ${LOG_DIR}/tempa-daemon.log, ${LOG_DIR}/tempa-meet-worker.log, ${LOG_DIR}/tempa-evolution-api.log"
