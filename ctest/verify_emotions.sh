#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Restart the backend with expression tokens ENABLED and verify they are
# consumed as internal commands: present in Live2D actions, absent from audio.
set -u
PROJ="$ROOT/Open-LLM-VTuber"
LOGDIR="$ROOT/ctest"
PY="$PROJ/.venv/Scripts/python.exe"

echo "=== kill backend on :12393 ==="
netstat -ano 2>/dev/null | grep ":12393 .*LISTENING" | awk '{print $5}' | sort -u | while read -r pid; do
    echo "killing pid $pid"; taskkill //F //PID "$pid" 2>&1 | head -2
done
sleep 2

echo "=== llama-server health ==="
curl -s --noproxy 127.0.0.1 --max-time 5 http://127.0.0.1:8099/health; echo

echo "=== start backend ==="
cd "$PROJ" || exit 1
# VERBOSE=1 turns on full debug logging; off by default because it floods the
# log file. The `control tokens` line is INFO, so it shows up either way.
if [ "${VERBOSE:-0}" = "1" ]; then
    "$PY" -u run_server.py --verbose > "$LOGDIR/vtuber_server.log" 2>&1 &
else
    "$PY" -u run_server.py > "$LOGDIR/vtuber_server.log" 2>&1 &
fi
for i in $(seq 1 90); do
    if netstat -ano 2>/dev/null | grep -q ":12393 .*LISTENING"; then
        echo "backend listening after ${i}s"; break
    fi
    sleep 1
done
sleep 8

echo
echo "=== multi-turn probe ==="
rm -f "$LOGDIR"/e2e_mt_*.wav
NO_PROXY="127.0.0.1,localhost" no_proxy="127.0.0.1,localhost" \
    "$PY" -u "$LOGDIR/multi_turn_probe.py" "${NTURNS:-3}"

echo
echo "=== control tokens consumed (Live2D) ==="
grep -a "control tokens" "$LOGDIR/vtuber_server.log" | tail -12

echo
echo "=== raw LLM output ==="
grep -a "Raw LLM\|raw_llm\|AI response" "$LOGDIR/vtuber_server.log" | tail -8

echo
echo "=== ASR back-read: what was actually spoken ==="
"$PY" -u "$LOGDIR/asr_verify.py" "$LOGDIR"/e2e_mt_*.wav 2>&1 \
    | grep -viE "resampler|in_sample_rate|output_sample_rate|^$" | tail -30
