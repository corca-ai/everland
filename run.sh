#!/usr/bin/env bash
set -euo pipefail

LOGFILE="$(dirname "$0")/server.log"
exec >> "$LOGFILE" 2>&1

start_server() {
    uv run main.py &
    SERVER_PID=$!
    echo "서버 시작 (PID: $SERVER_PID)"
}

stop_server() {
    if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "서버 종료 (PID: $SERVER_PID)"
        kill "$SERVER_PID"
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}

trap 'stop_server; exit 0' INT TERM

start_server

while true; do
    sleep 60
    git fetch -q origin main 2>/dev/null || continue
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "변경 감지: $LOCAL -> $REMOTE"
        stop_server
        git pull --ff-only origin main
        start_server
    fi
done
