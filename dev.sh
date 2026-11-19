#!/usr/bin/env bash
# One-command local stack for the S&P 500 Radar.
#
#   ./dev.sh start          Docker Kafka + producer + live consumer + API/UI
#   ./dev.sh restart        Restart API/UI only (Kafka, producer, live stay up)
#   ./dev.sh restart-live   Restart the Kafka live consumer only
#   ./dev.sh restart-producer Restart the Alpaca → Kafka producer only
#   ./dev.sh stop           Stop producer, live, API (leave Kafka running)
#   ./dev.sh down           stop + docker compose stop
#   ./dev.sh status         What is running
#   ./dev.sh logs [name]    Tail logs (app|live|producer|all)
#
# Optional env:
#   DEV_SYMBOLS=AAPL,MSFT,NVDA   Limit producer to these tickers (default: full S&P 500 file)
#   DEV_SKIP_PRODUCER=1         Start without Alpaca producer
#   DEV_SKIP_LIVE=1             Start without live consumer
#   DEV_PORT=8010               API port

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${ROOT}/.run"
COMPOSE_FILE="${ROOT}/docker-compose.yml"
APP_DIR="${ROOT}/alert_service"
INGEST_DIR="${ROOT}/stream_ingest"
PORT="${DEV_PORT:-8010}"
# Empty = full S&P 500 list from stream_ingest (WS ≤30 on Basic + REST for the rest).
SYMBOLS="${DEV_SYMBOLS:-}"
HOST="127.0.0.1"
UI_URL="http://${HOST}:${PORT}/ui"

mkdir -p "${RUN_DIR}"

die() { echo "error: $*" >&2; exit 1; }
info() { echo "==> $*"; }

pid_file() { echo "${RUN_DIR}/$1.pid"; }
log_file() { echo "${RUN_DIR}/$1.log"; }

is_running() {
  local name="$1"
  local pf
  pf="$(pid_file "$name")"
  [[ -f "$pf" ]] || return 1
  local pid
  pid="$(cat "$pf" 2>/dev/null || true)"
  [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local pf
  pf="$(pid_file "$1")"
  [[ -f "$pf" ]] && cat "$pf" || true
}

stop_named() {
  local name="$1"
  local pf pid
  pf="$(pid_file "$name")"
  if ! is_running "$name"; then
    rm -f "$pf"
    return 0
  fi
  pid="$(cat "$pf")"
  info "Stopping ${name} (pid ${pid})"
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.3
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pf"
}

# Kill anything still bound to the API port (stale uvicorn from outside this script).
free_port() {
  local pids
  pids="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    info "Freeing port ${PORT} (pids: ${pids})"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 0.5
    pids="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
    fi
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

require_venv() {
  local dir="$1"
  [[ -x "${dir}/.venv/bin/python" ]] || die "no venv at ${dir}/.venv — create it (see README Setup)"
}

check_docker() {
  require_cmd docker
  if ! docker info >/dev/null 2>&1; then
    die "Docker is not running. Start Docker Desktop, then re-run ./dev.sh start"
  fi
}

check_postgres() {
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -h localhost -q || die "Postgres is not accepting connections on localhost:5432"
  fi
}

kafka_broker_ready() {
  # TCP open is not enough — aiokafka needs the broker API to answer.
  docker exec ticker-alert-kafka \
    /opt/kafka/bin/kafka-broker-api-versions.sh \
    --bootstrap-server 127.0.0.1:9092 >/dev/null 2>&1
}

wait_kafka() {
  info "Waiting for Kafka broker API on 127.0.0.1:9092"
  local i
  for i in $(seq 1 90); do
    if kafka_broker_ready; then
      info "Kafka broker is ready"
      return 0
    fi
    sleep 1
  done
  die "Kafka broker API did not become ready on 127.0.0.1:9092"
}

start_kafka() {
  check_docker
  info "Starting Docker Kafka"
  docker compose -f "${COMPOSE_FILE}" up -d
  wait_kafka
}

_launch_producer() {
  rm -f "$(pid_file producer)"
  (
    cd "${INGEST_DIR}"
    # Ensure we publish to Kafka even if DRY_RUN=1 is left in .env
    export DRY_RUN=0
    if [[ -n "${SYMBOLS}" ]]; then
      # Explicit short list: WebSocket only for those names.
      nohup .venv/bin/python -m app.main --ws-only --symbols "${SYMBOLS}" \
        >"$(log_file producer)" 2>&1 &
    else
      # Full S&P 500 file: WebSocket first 30 (Basic cap) + REST for the rest.
      nohup .venv/bin/python -m app.main \
        >"$(log_file producer)" 2>&1 &
    fi
    echo $! >"$(pid_file producer)"
  )
}

start_producer() {
  if [[ "${DEV_SKIP_PRODUCER:-0}" == "1" ]]; then
    info "Skipping producer (DEV_SKIP_PRODUCER=1)"
    return 0
  fi
  require_venv "${INGEST_DIR}"
  [[ -f "${INGEST_DIR}/.env" ]] || die "missing ${INGEST_DIR}/.env (copy from .env.example and add Alpaca keys)"
  if is_running producer; then
    info "Producer already running (pid $(read_pid producer))"
    return 0
  fi
  local label attempt
  if [[ -n "${SYMBOLS}" ]]; then
    label="symbols: ${SYMBOLS} (ws-only)"
  else
    label="full S&P 500 (WS + REST)"
  fi
  for attempt in 1 2 3 4 5; do
    info "Starting Alpaca → Kafka producer (${label}) attempt ${attempt}/5"
    _launch_producer
    sleep 3
    if is_running producer; then
      info "Producer running (pid $(read_pid producer))"
      return 0
    fi
    info "Producer exited early — see $(log_file producer); retrying after Kafka settle"
    sleep 2
  done
  die "Producer failed to stay up after 5 attempts — see $(log_file producer)"
}

start_live() {
  if [[ "${DEV_SKIP_LIVE:-0}" == "1" ]]; then
    info "Skipping live consumer (DEV_SKIP_LIVE=1)"
    return 0
  fi
  require_venv "${APP_DIR}"
  if is_running live; then
    info "Live consumer already running (pid $(read_pid live))"
    return 0
  fi
  info "Starting Kafka → Postgres live consumer"
  (
    cd "${APP_DIR}"
    nohup .venv/bin/python -m app.live >"$(log_file live)" 2>&1 &
    echo $! >"$(pid_file live)"
  )
  sleep 1
  if ! is_running live; then
    die "Live consumer failed to stay up — see $(log_file live)"
  fi
}

start_app() {
  require_venv "${APP_DIR}"
  if is_running app; then
    info "API already running (pid $(read_pid app))"
    return 0
  fi
  free_port
  info "Starting API/UI on ${UI_URL}"
  (
    cd "${APP_DIR}"
    nohup .venv/bin/uvicorn app.main:app --reload --host "${HOST}" --port "${PORT}" \
      >"$(log_file app)" 2>&1 &
    echo $! >"$(pid_file app)"
  )
  # Brief wait so a hard fail shows up immediately
  sleep 1
  if ! is_running app; then
    die "API failed to stay up — see $(log_file app)"
  fi
}

cmd_start() {
  check_postgres
  start_kafka
  start_producer
  start_live
  start_app
  echo
  info "Stack is up"
  echo "  UI:       ${UI_URL}"
  echo "  API:      http://${HOST}:${PORT}"
  echo "  Logs:     ${RUN_DIR}/"
  echo "  Restart:  ./dev.sh restart      # API/UI only"
  echo "            ./dev.sh restart-live # live consumer only"
  echo "  Stop:     ./dev.sh stop"
  cmd_status
}

cmd_restart() {
  require_venv "${APP_DIR}"
  stop_named app
  free_port
  start_app
  info "API/UI restarted — open ${UI_URL}"
}

cmd_restart_live() {
  require_venv "${APP_DIR}"
  stop_named live
  start_live
  info "Live consumer restarted"
}

cmd_restart_producer() {
  check_docker
  wait_kafka
  stop_named producer
  start_producer
  info "Producer restarted"
}

cmd_stop() {
  stop_named app
  stop_named live
  stop_named producer
  free_port
  info "Producer, live, and API stopped (Kafka left running)"
}

cmd_down() {
  cmd_stop
  if [[ -f "${COMPOSE_FILE}" ]] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    info "Stopping Docker Kafka"
    docker compose -f "${COMPOSE_FILE}" stop
  fi
  info "Stack down"
}

cmd_status() {
  echo "Process status:"
  for name in app live producer; do
    if is_running "$name"; then
      printf "  %-10s running  pid=%s  log=%s\n" "$name" "$(read_pid "$name")" "$(log_file "$name")"
    else
      printf "  %-10s stopped\n" "$name"
    fi
  done
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if docker compose -f "${COMPOSE_FILE}" ps --status running 2>/dev/null | grep -q kafka; then
      echo "  kafka      running  (docker)"
    else
      echo "  kafka      stopped  (docker)"
    fi
  else
    echo "  kafka      unknown (Docker not available)"
  fi
  if lsof -tiTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "  port ${PORT}  in use → ${UI_URL}"
  else
    echo "  port ${PORT}  free"
  fi
}

cmd_logs() {
  local which="${1:-all}"
  case "$which" in
    app|live|producer)
      [[ -f "$(log_file "$which")" ]] || die "no log yet for ${which}"
      tail -n 80 -f "$(log_file "$which")"
      ;;
    all)
      local files=()
      for name in app live producer; do
        [[ -f "$(log_file "$name")" ]] && files+=("$(log_file "$name")")
      done
      [[ ${#files[@]} -gt 0 ]] || die "no logs under ${RUN_DIR} yet — run ./dev.sh start first"
      tail -n 40 -f "${files[@]}"
      ;;
    *)
      die "usage: ./dev.sh logs [app|live|producer|all]"
      ;;
  esac
}

cmd_help() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    start|up)       cmd_start ;;
    restart|restart-app) cmd_restart ;;
    restart-live)   cmd_restart_live ;;
    restart-producer) cmd_restart_producer ;;
    stop)           cmd_stop ;;
    down)           cmd_down ;;
    status)         cmd_status ;;
    logs)           cmd_logs "${1:-all}" ;;
    help|-h|--help|"") cmd_help ;;
    *)
      die "unknown command: ${cmd} (try: ./dev.sh help)"
      ;;
  esac
}

main "$@"
