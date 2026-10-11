#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Start llama-server, run the stack validation, then shut the server down.
# llama-server must live in the same Bash invocation as the checks (background
# processes do not survive between calls on this machine).

set -u
LLAMA="$ROOT/llama.cpp/build/bin/llama-server.exe"
MODEL="$ROOT/models/Qwen3-0.6B-q5_0.gguf"
PROJ="$ROOT/Open-LLM-VTuber"
LOGDIR="$ROOT/ctest"
PORT=8099

echo "=== kill leftover on :$PORT ==="
netstat -ano 2>/dev/null | grep ":$PORT .*LISTENING" | awk '{print $5}' | sort -u | while read -r pid; do
    taskkill //F //PID "$pid" 2>&1 | head -1
done
sleep 1

echo "=== start llama-server ==="
cd "$(dirname "$LLAMA")" || exit 1
"$LLAMA" -m "$MODEL" -c 4096 -t 12 --host 127.0.0.1 --port $PORT \
    > "$LOGDIR/llama_server.log" 2>&1 &
SRV_PID=$!
echo "pid=$SRV_PID"

for i in $(seq 1 90); do
    if curl -s --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status"'; then
        echo "healthy after ${i}s"; break
    fi
    sleep 1
done
curl -s --max-time 5 "http://127.0.0.1:$PORT/health"; echo

echo "=== validate ==="
cd "$PROJ" || exit 1
"$PROJ/.venv/Scripts/python.exe" -u validate_local_stack.py 2>&1
RC=$?
echo "VALIDATE_RC=$RC"

echo "=== stop llama-server ==="
kill $SRV_PID 2>/dev/null
sleep 2
taskkill //F //PID $SRV_PID 2>&1 | head -1
exit $RC
