#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Verify three fixes at once:
#   anti-repetition sampling (llama-server restarted with DRY),
#   no emotion tags leaking into speech (ASR back-read),
#   locked voice + resident TTS surviving across sessions (pitch + timing).
set -u
PROJ="$ROOT/Open-LLM-VTuber"
LOGDIR="$ROOT/ctest"
PY="$PROJ/.venv/Scripts/python.exe"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

LLAMA="$ROOT/llama.cpp/build/bin/llama-server.exe"
MODEL="$ROOT/models/Qwen3-0.6B-q5_0.gguf"
rm -f "$LOGDIR"/e2e_sa_*.wav "$LOGDIR"/e2e_sb_*.wav

echo "=== 0. make sure llama-server is up ==="
if ! curl -s --max-time 3 http://127.0.0.1:8099/health | grep -q '"status"'; then
    echo "llama-server down, starting it"
    cd "$(dirname "$LLAMA")" || exit 1
    "$LLAMA" -m "$MODEL" -c 4096 -t 12 --reasoning off \
        --dry-multiplier 0.8 --repeat-penalty 1.05 \
        --host 127.0.0.1 --port 8099 > "$LOGDIR/llama_server.log" 2>&1 &
    for i in $(seq 1 60); do
        curl -s --max-time 3 http://127.0.0.1:8099/health | grep -q '"status"' && break
        sleep 1
    done
fi
curl -s --max-time 5 http://127.0.0.1:8099/health; echo

echo "=== restart backend only (llama-server keeps DRY sampling) ==="
netstat -ano 2>/dev/null | grep ":12393 .*LISTENING" | awk '{print $5}' | sort -u | while read -r pid; do
    echo "killing pid $pid"; taskkill //F //PID "$pid" 2>&1 | head -1
done
sleep 2
cd "$PROJ" || exit 1
"$PY" -u run_server.py > "$LOGDIR/vtuber_server.log" 2>&1 &
for i in $(seq 1 90); do
    netstat -ano 2>/dev/null | grep -q ":12393 .*LISTENING" && { echo "backend up after ${i}s"; break; }
    sleep 1
done
sleep 10

echo "=== resident llama-tts command line ==="
grep -a "starting resident" "$LOGDIR/vtuber_server.log" | tail -2

echo
echo "=== session A (5 turns) ==="
"$PY" -u "$LOGDIR/multi_turn_probe.py" 5 sa

echo
echo "=== session B (3 turns, brand new connection) ==="
"$PY" -u "$LOGDIR/multi_turn_probe.py" 3 sb

echo
echo "=== is llama-tts still alive after both sessions? ==="
tasklist //FI "IMAGENAME eq llama-tts.exe" 2>&1 | tail -3

echo
echo "=== ASR verification ==="
"$PY" -u "$LOGDIR/asr_verify.py" "$LOGDIR"/e2e_sa_*.wav "$LOGDIR"/e2e_sb_*.wav 2>&1 \
    | grep -v "resampler\|in_sample_rate\|output_sample_rate\|^$"

echo
echo "=== pitch stability ==="
"$PY" -u "$LOGDIR/f0.py" "$LOGDIR"/e2e_sa_*.wav "$LOGDIR"/e2e_sb_*.wav
