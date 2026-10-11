#!/usr/bin/env bash
# Evaluate one GGUF on the VTuber workload.
#
# Everything happens inside a SINGLE bash invocation: this sandbox reaps child
# processes when the call returns, so starting the server here and evaluating
# it from another call simply does not work.
#
# usage: bash ctest/eval_model.sh <model.gguf> <label> [port]
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA="$ROOT/llama.cpp/build/bin/llama-server.exe"
# Was a user-profile absolute path (C:/Users/<name>/.workbuddy/...) -- that leaks
# the Windows account name, and no one cloning this repo has that path anyway.
# Use the project venv instead: it travels with the repo and already has the
# deps this script needs.
PY="$ROOT/Open-LLM-VTuber/.venv/Scripts/python.exe"
MODEL="$1"
LABEL="$2"
PORT="${3:-8199}"
LOG="$ROOT/ctest/eval_${LABEL}.log"

for pid in $(netstat -ano 2>/dev/null | grep ":$PORT .*LISTENING" | awk '{print $5}' | sort -u); do
    taskkill //F //PID "$pid" >/dev/null 2>&1
done
sleep 1

echo "### loading $LABEL ($MODEL)"
"$LLAMA" -m "$MODEL" -c 4096 -t 12 --reasoning off \
    --dry-multiplier 0.8 --repeat-penalty 1.05 \
    --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
SRV=$!

UP=0
for i in $(seq 1 90); do
    if curl -s --noproxy 127.0.0.1 --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status"'; then
        echo "### up after ${i}s"; UP=1; break
    fi
    sleep 1
done

if [ "$UP" != "1" ]; then
    echo "### FAILED to start; log tail:"
    tail -25 "$LOG"
    for pid in $(netstat -ano 2>/dev/null | grep ":$PORT .*LISTENING" | awk '{print $5}' | sort -u); do
        taskkill //F //PID "$pid" >/dev/null 2>&1
    done
    exit 1
fi

MODE="${EVAL_MODE:-chat}"
if [ "$MODE" = "multiturn" ]; then
    SCRIPT="$ROOT/ctest/eval_multiturn.py"
else
    SCRIPT="$ROOT/ctest/eval_chat.py"
fi
NO_PROXY="127.0.0.1,localhost" no_proxy="127.0.0.1,localhost" \
    "$PY" -u "$SCRIPT" "$PORT" "$LABEL"

echo "### shutting down $LABEL"
for pid in $(netstat -ano 2>/dev/null | grep ":$PORT .*LISTENING" | awk '{print $5}' | sort -u); do
    taskkill //F //PID "$pid" >/dev/null 2>&1
done
sleep 1
