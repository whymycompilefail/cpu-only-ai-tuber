#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Measures the TTFT of a *resident* llama-server across two turns of one conversation.
#
#   The point: llama-bench's tg number carries no prompt context, and llama-cli -f re-prefills
#   the whole context on every process start. Neither answers the question that actually
#   matters for a chat deployment: on turn N+1, how many tokens get recomputed?
#   llama-server reports exactly that - "prompt eval time = X ms / N tokens" counts
#   stats.n_prompt_processed, i.e. the tokens it did NOT find in the slot cache.
#
# Usage: bash ctest/ttft_server.sh [ctx_file] [port]
set -u

CTX="${1:-ctx_8192.txt}"
PORT="${2:-8080}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN=$ROOT/llama.cpp/build/bin/llama-server.exe
M=$ROOT/models/Qwen3-0.6B-f16.gguf
LOG="$HERE/../server_ttft.log"

cd "$HERE"

# turn 1 prompt = the long context + a question; turn 2 = same + a short suffix.
# turn 2 therefore shares its entire prefix with turn 1 - a resident process with a warm
# slot should only have to prefill the suffix.
python - <<'PY'
import json
ctx = open("ctx_8192.txt", encoding="utf-8").read()
base = ctx + "\n\nQuestion: what is this text about?\nAnswer:"
json.dump({"prompt": base, "n_predict": 16, "cache_prompt": True, "temperature": 0},
          open("r1.json", "w", encoding="utf-8"))
open("r1_base.txt", "w", encoding="utf-8").write(base)
PY

rm -f "$LOG"
echo "starting server on :$PORT ..."
"$BIN" -m "$M" -c 16384 -t 12 -fa 0 -ctk q8_0 -ctv f16 --port "$PORT" -np 1 \
    --host 127.0.0.1 > "$LOG" 2>&1 &
SRV=$!

cleanup() { kill $SRV 2>/dev/null; wait $SRV 2>/dev/null; }
trap cleanup EXIT

for i in $(seq 1 120); do
    if curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"'; then
        echo "ready after ${i}s"; break
    fi
    sleep 1
done

post() {   # post <json file> -> prints timings line
    curl -s -m 600 -X POST "http://127.0.0.1:$PORT/completion" \
         -H 'Content-Type: application/json' \
         -d @"$1"
}

echo
echo "=== turn 1: cold, full 8192-token prefill ==="
T0=$(date +%s%N)
R1=$(post r1.json)
T1=$(date +%s%N)
echo "wall = $(( (T1 - T0) / 1000000 )) ms"
echo "$R1" | python -c "import sys,json; d=json.load(sys.stdin); t=d.get('timings',{}); print('  prompt_n=%s prompt_ms=%.0f prompt_per_token_ms=%.2f predicted_n=%s' % (t.get('prompt_n'), t.get('prompt_ms',0), t.get('prompt_per_token_ms',0), t.get('predicted_n')))"
GEN=$(echo "$R1" | python -c "import sys,json; print(json.load(sys.stdin).get('content',''))")
echo "  generated: ${GEN:0:60}"

# turn 2: identical prefix + a short new question
python - <<PY
import json
base = open("r1_base.txt", encoding="utf-8").read()
gen  = '''$GEN'''
json.dump({"prompt": base + gen + "\n\nQuestion: say it again shorter.\nAnswer:",
           "n_predict": 16, "cache_prompt": True, "temperature": 0},
          open("r2.json", "w", encoding="utf-8"))
PY

echo
echo "=== turn 2: same prefix + short suffix (slot cache warm) ==="
T0=$(date +%s%N)
R2=$(post r2.json)
T1=$(date +%s%N)
echo "wall = $(( (T1 - T0) / 1000000 )) ms"
echo "$R2" | python -c "import sys,json; d=json.load(sys.stdin); t=d.get('timings',{}); print('  prompt_n=%s prompt_ms=%.0f prompt_per_token_ms=%.2f predicted_n=%s' % (t.get('prompt_n'), t.get('prompt_ms',0), t.get('prompt_per_token_ms',0), t.get('predicted_n')))"
echo "  generated: $(echo "$R2" | python -c "import sys,json; print(json.load(sys.stdin).get('content','')[:60])")"

echo
echo "=== server-side view (n_prompt_processed = tokens actually recomputed) ==="
grep -E "prompt eval time|eval time|slot .* : id" "$LOG" | tail -8
