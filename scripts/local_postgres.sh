#!/usr/bin/env bash
# Start/stop a self-contained local PostgreSQL 14 instance for this project only,
# isolated from any other Postgres install on the machine (port 5434, data in ./pgdata).
# Used because Docker was not available in this environment; docker-compose.yml is kept
# for environments where Docker is available (update DATABASE_URL back to port 5432 then).
set -euo pipefail
cd "$(dirname "$0")/.."

PG_BIN="/opt/homebrew/opt/postgresql@14/bin"
DATA_DIR="./pgdata"
PORT=5434

if [ ! -x "$PG_BIN/pg_ctl" ]; then
  echo "PostgreSQL 14 binaries not found at $PG_BIN. Install postgresql@14 or use 'docker compose up -d postgres'." >&2
  exit 1
fi

case "${1:-}" in
  start)
    if [ ! -d "$DATA_DIR" ]; then
      "$PG_BIN/initdb" -D "$DATA_DIR" -U claims_app --auth=trust -E UTF8
    fi
    "$PG_BIN/pg_ctl" -D "$DATA_DIR" -l ./pgdata_start.log -o "-p $PORT -k /tmp" start
    ;;
  stop)
    "$PG_BIN/pg_ctl" -D "$DATA_DIR" stop -m fast
    ;;
  status)
    "$PG_BIN/pg_ctl" -D "$DATA_DIR" status
    ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
