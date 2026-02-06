#!/bin/bash

# Start all backend services: Redis, FastAPI, Celery Worker, Celery Beat
# Usage: ./start.sh        — kill existing processes, then start fresh
#        ./start.sh stop   — just kill existing processes
# Stop while running: Ctrl+C

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="logs/.pids"
mkdir -p logs

# --- Kill any existing services from a previous run ---
kill_existing() {
    # Kill from PID file (previous ./start.sh run)
    if [ -f "$PID_FILE" ]; then
        echo "Stopping previous services..."
        while read -r pid; do
            kill "$pid" 2>/dev/null && echo "  Killed PID $pid"
        done < "$PID_FILE"
        rm -f "$PID_FILE"
    fi

    # Kill any stray processes on port 8000 (uvicorn)
    lsof -ti:8000 2>/dev/null | xargs kill 2>/dev/null && echo "  Killed process on port 8000" || true

    # Kill any stray celery processes for this app
    pkill -f "celery -A app.tasks.celery_app" 2>/dev/null && echo "  Killed stray celery processes" || true

    sleep 1
}

kill_existing

# If "stop" was passed, just kill and exit
if [ "${1}" = "stop" ]; then
    echo "All services stopped."
    exit 0
fi

# --- Cleanup on Ctrl+C or exit ---
cleanup() {
    echo ""
    echo "Shutting down all services..."
    kill $REDIS_PID $API_PID $WORKER_PID $BEAT_PID 2>/dev/null
    rm -f "$PID_FILE"
    wait 2>/dev/null
    echo "All services stopped."
}
trap cleanup EXIT

# --- Redis ---
if redis-cli ping &>/dev/null; then
    echo "[redis]   Already running on port 6379"
else
    echo "[redis]   Starting..."
    redis-server --daemonize no --port 6379 > logs/redis.log 2>&1 &
    REDIS_PID=$!
    sleep 1
    if redis-cli ping &>/dev/null; then
        echo "[redis]   Running (PID $REDIS_PID)"
        echo "$REDIS_PID" >> "$PID_FILE"
    else
        echo "[redis]   Failed to start. Check logs/redis.log"
        exit 1
    fi
fi

# --- FastAPI ---
echo "[api]     Starting on port 8000..."
uvicorn app.main:app --reload --port 8000 &
API_PID=$!
echo "[api]     Running (PID $API_PID)"
echo "$API_PID" >> "$PID_FILE"

# --- Celery Worker ---
echo "[worker]  Starting..."
celery -A app.tasks.celery_app worker --loglevel=info > logs/celery-worker.log 2>&1 &
WORKER_PID=$!
echo "[worker]  Running (PID $WORKER_PID)"
echo "$WORKER_PID" >> "$PID_FILE"

# --- Celery Beat ---
echo "[beat]    Starting..."
celery -A app.tasks.celery_app beat --loglevel=info > logs/celery-beat.log 2>&1 &
BEAT_PID=$!
echo "[beat]    Running (PID $BEAT_PID)"
echo "$BEAT_PID" >> "$PID_FILE"

echo ""
echo "All services started. Logs in backend/logs/ directory."
echo "  API:    http://localhost:8000"
echo "  Docs:   http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services."

wait
