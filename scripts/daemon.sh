#!/bin/bash
# GroupAgent Watchdog Daemon Script

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${1:-$DIR/config.json}"
LOG_FILE="${2:-$DIR/groupagent.log}"
PID_FILE="${3:-$DIR/groupagent.pid}"

echo "$$" > "$PID_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting GroupAgent Watchdog (PID: $$)..." >> "$LOG_FILE"

cleanup() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Watchdog stopping..." >> "$LOG_FILE"
    if [ -n "$CHILD_PID" ]; then
        kill "$CHILD_PID" 2>/dev/null
    fi
    rm -f "$PID_FILE" 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

while true; do
    python3 -m groupagent.cli --config "$CONFIG_FILE" >> "$LOG_FILE" 2>&1 &
    CHILD_PID=$!
    wait "$CHILD_PID"
    EXIT_CODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Process (PID: $CHILD_PID) exited with code $EXIT_CODE. Restarting in 3s..." >> "$LOG_FILE"
    sleep 3
done
