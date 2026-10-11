#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Does KV reuse survive a real multi-turn conversation?
#
#   The "every turn re-reads everything" cost is the whole problem (§19). §16/§18 showed
#   ONE warm turn going 63.4s -> 0.22s. But a real conversation is 10+ turns, and agents
#   also MUTATE the prefix (edit an earlier message, compress history, change system
#   prompt). KV reuse only works on an identical token prefix - so the question is:
#
#     A) append-only turns   : does reuse hold, or does it decay?
#     B) one prefix mutation : how much of the cache is destroyed?
#
# Usage: bash ctest/kv_reuse_turns.sh [port]
set -u

PORT="${1:-8084}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN=$ROOT/llama.cpp/build/bin/llama-server.exe
M=$ROOT/models/Qwen3-0.6B-f16.gguf
LOG="$HERE/kvturns.log"

cd "$HERE"

"$BIN" -m "$M" -c 8192 -t 12 -fa 0 -ctk q8_0 -ctv f16 --port "$PORT" -np 1 \
    --host 127.0.0.1 > "$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT

for i in $(seq 1 120); do
    curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"' && break
    sleep 1
done

python - "$PORT" <<'PY'
import json, sys, time, urllib.request
port = sys.argv[1]
BASE = "http://127.0.0.1:%s" % port

def post(prompt, ntok=8):
    req = urllib.request.Request(BASE + "/completion",
        data=json.dumps({"prompt": prompt, "n_predict": ntok, "id_slot": 0,
                         "cache_prompt": True, "temperature": 0}).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=600).read())
    return r, (time.time() - t0) * 1000

# a stable "system prompt + long document" prefix, the thing an agent would keep
ctx = open("ctx_512.txt", encoding="utf-8").read()
system = "You are a careful assistant. Answer briefly.\n\n"
doc = system + ctx

print("=== A) append-only turns: does reuse hold? ===")
print("%-6s %10s %10s %12s %10s" % ("turn", "cache_n", "prompt_n", "prompt_ms", "reuse%"))
convo = doc + "\nQ1: what is this?\nA:"
for t in range(1, 11):
    r, w = post(convo)
    tm = r["timings"]
    cn, pn = tm.get("cache_n", 0), tm["prompt_n"]
    tot = cn + pn
    print("%-6d %10d %10d %12.0f %9.1f%%"
          % (t, cn, pn, tm["prompt_ms"], 100.0 * cn / tot if tot else 0))
    convo = convo + r["content"] + "\nQ%d: go on.\nA:" % (t + 1)

print()
print("=== B) mutate the PREFIX once (simulates history compression / edit) ===")
mutated = "You are a VERY careful assistant. Answer briefly.\n\n" + ctx \
          + "\nQ1: what is this?\nA:"
r, w = post(mutated)
tm = r["timings"]
cn, pn = tm.get("cache_n", 0), tm["prompt_n"]
tot = cn + pn
print("after mutating the first sentence of the system prompt:")
print("  cache_n=%s  prompt_n=%s  prompt_ms=%.0f  reuse=%.1f%%"
      % (cn, pn, tm["prompt_ms"], 100.0 * cn / tot if tot else 0))
PY
