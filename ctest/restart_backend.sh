#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Restart only the Open-LLM-VTuber backend (llama-server is left running) and
# run the Chinese end-to-end probe twice: one English question, one Chinese.
set -u
PROJ="$ROOT/Open-LLM-VTuber"
LOGDIR="$ROOT/ctest"
PY="$PROJ/.venv/Scripts/python.exe"

echo "=== kill backend on :12393 ==="
netstat -ano 2>/dev/null | grep ":12393 .*LISTENING" | awk '{print $5}' | sort -u | while read -r pid; do
    echo "killing pid $pid"; taskkill //F //PID "$pid" 2>&1 | head -2
done
sleep 2

echo "=== llama-server health (left running) ==="
curl -s --max-time 5 http://127.0.0.1:8099/health; echo

echo "=== start backend ==="
cd "$PROJ" || exit 1
"$PY" -u run_server.py > "$LOGDIR/vtuber_server.log" 2>&1 &
for i in $(seq 1 90); do
    if netstat -ano 2>/dev/null | grep -q ":12393 .*LISTENING"; then
        echo "backend listening after ${i}s"; break
    fi
    sleep 1
done
sleep 5

echo "=== probe 1: english question ==="
"$PY" -u "$LOGDIR/e2e_zh.py" "can you speak chinese"

echo
echo "=== probe 2: chinese question ==="
"$PY" -u "$LOGDIR/e2e_zh.py"

echo
echo "=== ai responses from log ==="
grep -a "AI response" "$LOGDIR/vtuber_server.log" | tail -5
