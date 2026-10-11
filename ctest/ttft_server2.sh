#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Turn-2 budget under a resident server: how long does the user actually wait for a
# realistic turn (short new message + 200-token reply) once the context is already warm?
#
#   turn 1 is the cold 6734-token prefill (the cost you pay once per context).
#   turn 2 adds a ~30-token user message and asks for 200 tokens. What we want is the
#   split between TTFT (incremental prefill) and generation - because that split is what
#   decides whether "do the work during idle time" has anything left to win.
#
# Usage: bash ctest/ttft_server2.sh [port]
set -u
PORT="${1:-8081}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN=$ROOT/llama.cpp/build/bin/llama-server.exe
M=$ROOT/models/Qwen3-0.6B-f16.gguf
LOG="$HERE/../server_ttft2.log"

cd "$HERE"

python - <<'PY'
import json
base = open("ctx_8192.txt", encoding="utf-8").read() + "\n\nQuestion: what is this text about?\nAnswer:"
json.dump({"prompt": base, "n_predict": 8, "cache_prompt": True, "temperature": 0},
          open("s1.json", "w", encoding="utf-8"))
open("s1_base.txt", "w", encoding="utf-8").write(base)
PY

rm -f "$LOG"
"$BIN" -m "$M" -c 16384 -t 12 -fa 0 -ctk q8_0 -ctv f16 --port "$PORT" -np 1 --host 127.0.0.1 > "$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT

for i in $(seq 1 120); do
    curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"' && { echo "ready after ${i}s"; break; }
    sleep 1
done

show() { python -c "
import sys,json
d=json.load(sys.stdin); t=d.get('timings',{})
p=t.get('prompt_ms',0.0); g=t.get('predicted_ms',0.0); n=t.get('predicted_n',0)
print('   TTFT(prefill) = %8.0f ms   gen = %8.0f ms / %d tok = %.2f t/s   wall = %.0f ms'
      % (p, g, n, (n/(g/1000.0) if g>0 else 0), p+g))
"; }

echo "=== turn 1: cold ==="
T0=$(date +%s%N); curl -s -m 600 -X POST "http://127.0.0.1:$PORT/completion" -H 'Content-Type: application/json' -d @s1.json > o1.json; T1=$(date +%s%N)
echo "   wall(client) = $(( (T1-T0)/1000000 )) ms"; show < o1.json
GEN=$(python -c "import json;print(json.load(open('o1.json'))['content'])")

python - <<PY
import json
base = open("s1_base.txt", encoding="utf-8").read()
json.dump({"prompt": base + '''$GEN''' + "\n\nQuestion: now tell me the same thing again, but much shorter, in one sentence.\nAnswer:",
           "n_predict": 200, "cache_prompt": True, "temperature": 0},
          open("s2.json", "w", encoding="utf-8"))
PY

echo "=== turn 2: warm context + ~25-token message + 200-token reply ==="
T0=$(date +%s%N); curl -s -m 600 -X POST "http://127.0.0.1:$PORT/completion" -H 'Content-Type: application/json' -d @s2.json > o2.json; T1=$(date +%s%N)
echo "   wall(client) = $(( (T1-T0)/1000000 )) ms"; show < o2.json
python -c "import json;d=json.load(open('o2.json'));print('   reply:', repr(d['content'][:90]))"

echo
echo "=== server view ==="
grep -E "prompt eval time|eval time" "$LOG" | tail -4
