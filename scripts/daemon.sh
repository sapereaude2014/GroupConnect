#!/bin/bash
# GroupConnect Service Manager & Watchdog Daemon
# Supports: start, stop, restart, status

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-start}"
CONFIG_ARG="$2"

# If first argument is a json file, treat as start
if [[ "$ACTION" == *.json ]]; then
    CONFIG_ARG="$ACTION"
    ACTION="start"
fi

CONFIG_FILE="${CONFIG_ARG:-$DIR/config.json}"
if [ ! -f "$CONFIG_FILE" ]; then
    # Try auto-detecting config.*.json
    MATCHES=($DIR/config.*.json)
    if [ -f "${MATCHES[0]}" ]; then
        CONFIG_FILE="${MATCHES[0]}"
    fi
fi

BASENAME=$(basename "$CONFIG_FILE" .json)
LOG_DIR="$DIR/logs"
PID_DIR="$DIR/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

LOG_FILE="$LOG_DIR/${BASENAME}.log"
PID_FILE="$PID_DIR/${BASENAME}.pid"

run_watchdog() {
    echo "$$" > "$PID_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting GroupConnect Watchdog for $CONFIG_FILE (Daemon PID: $$)..." >> "$LOG_FILE"

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
        python3 -m groupconnect.cli --config "$CONFIG_FILE" >> "$LOG_FILE" 2>&1 &
        CHILD_PID=$!
        wait "$CHILD_PID"
        EXIT_CODE=$?
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Process (PID: $CHILD_PID) exited with code $EXIT_CODE. Restarting in 3s..." >> "$LOG_FILE"
        sleep 3
    done
}

start_daemon() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "❌ Error: Config file '$CONFIG_FILE' not found."
        echo "👉 Run 'python3 -m groupconnect.cli --init' to generate one."
        exit 1
    fi

    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
            echo "⚠️ GroupConnect ($BASENAME) is already running (PID: $OLD_PID)."
            exit 0
        fi
        rm -f "$PID_FILE"
    fi

    echo "🚀 Starting GroupConnect ($BASENAME) in background..."
    nohup bash "$0" __internal_run "$CONFIG_FILE" >/dev/null 2>&1 &
    sleep 1

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        echo "✅ GroupConnect ($BASENAME) started successfully! (Daemon PID: $PID)"
        echo "📄 Logs: $LOG_FILE"
        echo "🛑 To stop: ./scripts/daemon.sh stop $CONFIG_FILE"
    else
        echo "⚠️ Started, check logs at $LOG_FILE"
    fi
}

stop_daemon() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            echo "🛑 Stopping GroupConnect ($BASENAME, PID: $PID)..."
            kill "$PID" 2>/dev/null
            sleep 1
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null
            fi
            rm -f "$PID_FILE"
            echo "✅ Stopped successfully."
        else
            echo "⚠️ No active process found for PID in $PID_FILE. Cleaning up."
            rm -f "$PID_FILE"
        fi
    else
        echo "⚠️ GroupConnect ($BASENAME) is not running."
    fi
}

status_daemon() {
    echo "📊 GroupConnect Service Status:"
    echo "=================================================="
    RUNNING_COUNT=0
    for pfile in "$PID_DIR"/*.pid; do
        if [ -f "$pfile" ]; then
            PNAME=$(basename "$pfile" .pid)
            PID=$(cat "$pfile" 2>/dev/null)
            if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
                echo "🟢 $PNAME: Running (PID: $PID, Log: $LOG_DIR/${PNAME}.log)"
                RUNNING_COUNT=$((RUNNING_COUNT + 1))
            else
                echo "🔴 $PNAME: Stale PID file (Process not alive)"
                rm -f "$pfile"
            fi
        fi
    done
    if [ $RUNNING_COUNT -eq 0 ]; then
        echo "⚪ No GroupConnect services are currently running."
    fi
    echo "=================================================="
}

case "$ACTION" in
    __internal_run)
        run_watchdog
        ;;
    start)
        start_daemon
        ;;
    stop)
        stop_daemon
        ;;
    restart)
        stop_daemon
        sleep 1
        start_daemon
        ;;
    status)
        status_daemon
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status} [config_file.json]"
        exit 1
        ;;
esac
