#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# perceived latency = when does the user SEE the first token?
#
#   §16/§18 measured TTFT as prompt_ms. But under streaming the user starts reading
#   at first-token, not at completion. Nielsen's thresholds (0.1 / 1 / 10 s) are about
#   perceived responsiveness, so the number that matters is time-to-first-chunk.
#
#   Also compares generation speed against human reading speed: if tok/s > reading
#   speed, the user is limited by their own reading, never by the model.
#
# Requires: ctest/slotsave/slot0.bin (produced by ttft_persist.sh)
set -u

PORT="${1:-8083}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN=$ROOT/llama.cpp/build/bin/llama-server.exe
M=$ROOT/models/Qwen3-0.6B-f16.gguf
SAVE="$HERE/slotsave"

cd "$HERE"

"$BIN" -m "$M" -c 16384 -t 12 -fa 0 -ctk q8_0 -ctv f16 --port "$PORT" -np 1 \
    --host 127.0.0.1 --slot-save-path "$SAVE" > "$SAVE/run3.log" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT

for i in $(seq 1 180); do
    curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"' && { echo "ready after ${i}s"; break; }
    sleep 1
done

python - "$PORT" <<'PY'
import json, sys, time, urllib.request
port = sys.argv[1]
BASE = "http://127.0.0.1:%s" % port

def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=900).read())

r = post("/slots/0?action=restore", {"filename": "slot0.bin"})
print("restore: n_restored=%s" % r.get("n_restored"))

base = open("p1_base.txt", encoding="utf-8").read()
gen  = open("p1_gen.txt", encoding="utf-8").read()

for label, npred in (("short (16 tok)", 16), ("full reply (200 tok)", 200)):
    body = json.dumps({"prompt": base + gen + "\n\nQuestion: say it again shorter.\nAnswer:",
                       "n_predict": npred, "id_slot": 0, "cache_prompt": True,
                       "temperature": 0, "stream": True}).encode()
    req = urllib.request.Request(BASE + "/completion", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=900)
    first = None; ntok = 0; last = t0
    for line in resp:
        s = line.decode("utf-8").strip()
        if not s.startswith("data:"):
            continue
        d = json.loads(s[5:].strip())
        if first is None:
            first = (time.time() - t0) * 1000
        ntok += 1
        last = time.time()
        if d.get("stop"):
            break
    total = (last - t0)
    print("stream %-20s first_chunk=%6.1f ms   n_chunks=%3d   total=%6.2f s   %.2f tok/s"
          % (label, first, ntok, total, ntok / total if total else 0))

print()
print("human reading speed for reference: 200-250 wpm ~ 4.3-5.5 tok/s (1 word ~ 1.3 tok)")
PY
