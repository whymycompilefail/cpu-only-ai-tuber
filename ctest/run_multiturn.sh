#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Restart the backend, drive a 5-turn conversation on ONE connection, then run
# every produced wav back through ASR so we can hear what was actually said
# (emotion tags leaking into speech? repeated sentences?).
set -u
PROJ="$ROOT/Open-LLM-VTuber"
LOGDIR="$ROOT/ctest"
PY="$PROJ/.venv/Scripts/python.exe"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

rm -f "$LOGDIR"/e2e_mt_*.wav

echo "=== kill backend on :12393 ==="
netstat -ano 2>/dev/null | grep ":12393 .*LISTENING" | awk '{print $5}' | sort -u | while read -r pid; do
    echo "killing pid $pid"; taskkill //F //PID "$pid" 2>&1 | head -2
done
sleep 2

echo "=== start backend ==="
cd "$PROJ" || exit 1
"$PY" -u run_server.py > "$LOGDIR/vtuber_server.log" 2>&1 &
for i in $(seq 1 90); do
    if netstat -ano 2>/dev/null | grep -q ":12393 .*LISTENING"; then
        echo "backend listening after ${i}s"; break
    fi
    sleep 1
done
sleep 8

echo "=== multi-turn probe ==="
"$PY" -u "$LOGDIR/multi_turn_probe.py" 5

echo
echo "=== ASR verification ==="
"$PY" -u "$LOGDIR/asr_verify.py" "$LOGDIR"/e2e_mt_*.wav 2>&1 | grep -v "resampler\|in_sample_rate\|output_sample_rate\|^$"
