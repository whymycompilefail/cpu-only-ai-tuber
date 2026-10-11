#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Full stack restart: llama-server (with anti-repetition sampling) + backend,
# then drive a multi-turn conversation and verify with ASR + pitch analysis.
set -u
LLAMA="$ROOT/llama.cpp/build/bin/llama-server.exe"
MODEL="$ROOT/models/Qwen3-0.6B-q5_0.gguf"
PROJ="$ROOT/Open-LLM-VTuber"
LOGDIR="$ROOT/ctest"
PY="$PROJ/.venv/Scripts/python.exe"
PORT=8099
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

rm -f "$LOGDIR"/e2e_mt_*.wav

echo "=== 0. kill leftovers ==="
for port in $PORT 12393; do
    netstat -ano 2>/dev/null | grep ":$port .*LISTENING" | awk '{print $5}' | sort -u | while read -r pid; do
        echo "killing pid $pid on :$port"; taskkill //F //PID "$pid" 2>&1 | head -1
    done
done
sleep 2

echo "=== 1. start llama-server (DRY + repeat penalty) ==="
cd "$(dirname "$LLAMA")" || exit 1
"$LLAMA" -m "$MODEL" -c 4096 -t 12 --reasoning off \
    --dry-multiplier 0.8 --repeat-penalty 1.05 \
    --host 127.0.0.1 --port $PORT > "$LOGDIR/llama_server.log" 2>&1 &
for i in $(seq 1 60); do
    curl -s --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status"' && break
    sleep 1
done
curl -s --max-time 5 "http://127.0.0.1:$PORT/health"; echo

echo "=== 2. start backend ==="
cd "$PROJ" || exit 1
"$PY" -u run_server.py > "$LOGDIR/vtuber_server.log" 2>&1 &
for i in $(seq 1 90); do
    netstat -ano 2>/dev/null | grep -q ":12393 .*LISTENING" && { echo "backend up after ${i}s"; break; }
    sleep 1
done
sleep 10

echo "=== resident llama-tts command line ==="
grep -a "starting resident" "$LOGDIR/vtuber_server.log" | tail -1

echo "=== 3. multi-turn probe ==="
"$PY" -u "$LOGDIR/multi_turn_probe.py" 5 sa

echo
echo "=== 3b. second connection after the first one closed ==="
"$PY" -u "$LOGDIR/multi_turn_probe.py" 3 sb

echo
echo "=== 3c. resident process still alive after both connections? ==="
tasklist //FI "IMAGENAME eq llama-tts.exe" 2>&1 | tail -2

echo
echo "=== 4. ASR verification ==="
"$PY" -u "$LOGDIR/asr_verify.py" "$LOGDIR"/e2e_sa_*.wav "$LOGDIR"/e2e_sb_*.wav 2>&1 \
    | grep -v "resampler\|in_sample_rate\|output_sample_rate\|^$"

echo
echo "=== 5. pitch stability ==="
"$PY" -u "$LOGDIR/f0.py" "$LOGDIR"/e2e_sa_*.wav "$LOGDIR"/e2e_sb_*.wav

echo
echo "=== ports ==="
netstat -ano 2>/dev/null | grep -E ":(8099|12393) .*LISTENING"
