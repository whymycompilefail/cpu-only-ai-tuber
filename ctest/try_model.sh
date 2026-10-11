#!/usr/bin/env bash
# Clean single-model comparison writing to ctest/try_model_<port>.log.
#
# ⚠️ MEASUREMENT HYGIENE (learned 2026-10-02, do not undo):
#   1. A second llama-server ruins numbers even when idle -- its threadpool
#      keeps cores busy, and the same prompt measured 1.47s in one run and
#      2.96s in another. Run ONE server at a time for latency comparisons.
#   2. Wall-clock round-trip is too noisy here; use ctest/measure_speed.py,
#      which reads the server's own timings.predicted_per_second.
#
# usage: bash ctest/try_model.sh <gguf> [label] [port]
set -u
LLAMA="$ROOT/llama.cpp/build/bin/llama-server.exe"
MODEL="${1:?usage: try_model.sh <gguf> [label] [port]}"
LABEL="${2:-$(basename "$MODEL")}"
PORT="${3:-8096}"
PY="C:/Program Files/Python312/python.exe"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Qwen3 family emits only `reasoning_content` without this, which the VTuber
# reads as "said nothing".  DRY is the only thing that stops small models
# from degenerating into repeating one sentence.
OPTS="-c 4096 -t 12 --reasoning off --dry-multiplier 0.8 --repeat-penalty 1.05"

# Qwen3.5 and other hybrid models put everything in `reasoning_content` and
# leave `content` empty unless thinking is off -- which looks exactly like
# "she said nothing". Must be an env var: passing it as --chat-template-kwargs
# '{...}' through this shell sends the quotes literally and llama-server exits
# with a JSON parse error.
export LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'

# Sanity gate: if content comes back empty every metric downstream is fiction
# (including the persona probe, which scores an empty reply as "no break").

echo "=== starting: $LABEL  ($MODEL) ==="
netstat -ano 2>/dev/null | grep ":$PORT .*LISTENING" | awk '{print $5}' | sort -u | \
    while read -r pid; do echo "stale pid $pid on :$PORT"; taskkill //F //PID "$pid" >/dev/null 2>&1; done

cd "$(dirname "$LLAMA")" || exit 1
"$LLAMA" -m "$MODEL" $OPTS --host 127.0.0.1 --port "$PORT" \
    > "$ROOT/ctest/try_model_$PORT.log" 2>&1 &
SRV=$!

cleanup() { echo "=== stopping server (pid $SRV) ==="; taskkill //F //PID "$SRV" >/dev/null 2>&1; }
trap cleanup EXIT

for i in $(seq 1 90); do
    if curl -s --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status"'; then
        echo "healthy after ${i}s"; break
    fi
    sleep 1
done
curl -s --max-time 5 "http://127.0.0.1:$PORT/health" || { echo "SERVER FAILED TO START"; exit 1; }
echo

echo "########## persona-break probe ($LABEL) ##########"
"$PY" "$ROOT/ctest/probe_identity.py" "$PORT" file 2>&1 | tail -40

echo
echo "########## decode speed ($LABEL) ##########"
"$PY" "$ROOT/ctest/measure_speed.py" "$PORT" 2>&1 | tail -10

echo
echo "########## general eval ($LABEL) ##########"
"$PY" "$ROOT/ctest/eval_chat.py" "$PORT" "$LABEL" 2>&1 | tail -45

echo
echo "=== done: $LABEL ==="
