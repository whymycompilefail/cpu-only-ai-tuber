#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Does §16's 168x TTFT win survive a process restart?
#
#   §16 measured 65.8s -> 0.39s for turn 2, but only *inside one live process*.
#   A real deployment crashes, gets restarted, gets killed by an OS update. If the
#   KV dies with the process, the user pays the full 65.8s again - and that is the
#   "actual efficiency" question, not tok/s.
#
#   llama-server already ships slot save/restore (--slot-save-path,
#   POST /slots/{id}?action=save|restore). This measures what it COSTS:
#     - write time + bytes on disk
#     - restore time in a FRESH process
#     - turn-2 TTFT after the restart, vs cold 65.8s
#
# Usage: bash ctest/ttft_persist.sh [ctx_file] [port]
set -u

CTX="${1:-ctx_8192.txt}"
PORT="${2:-8082}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN=$ROOT/llama.cpp/build/bin/llama-server.exe
M=$ROOT/models/Qwen3-0.6B-f16.gguf
SAVE="$HERE/slotsave"
LOG1="$SAVE/run1.log"
LOG2="$SAVE/run2.log"

cd "$HERE"
rm -rf "$SAVE"; mkdir -p "$SAVE"

python - <<'PY'
import json
ctx = open("ctx_8192.txt", encoding="utf-8").read()
base = ctx + "\n\nQuestion: what is this text about?\nAnswer:"
open("p1_base.txt", "w", encoding="utf-8").write(base)
json.dump({"prompt": base, "n_predict": 16, "id_slot": 0,
           "cache_prompt": True, "temperature": 0},
          open("p1.json", "w", encoding="utf-8"))
PY

wait_up() {
    for i in $(seq 1 180); do
        if curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"'; then
            echo "  ready after ${i}s"; return 0
        fi
        sleep 1
    done
    echo "  SERVER NEVER CAME UP"; return 1
}

start_server() {
    "$BIN" -m "$M" -c 16384 -t 12 -fa 0 -ctk q8_0 -ctv f16 --port "$PORT" -np 1 \
        --host 127.0.0.1 --slot-save-path "$SAVE" > "$1" 2>&1 &
    SRV=$!
}

echo "################ PHASE 1: cold prefill + save ################"
start_server "$LOG1"
trap 'kill $SRV 2>/dev/null' EXIT
wait_up

python - "$PORT" <<'PY'
import json, sys, time, urllib.request
port = sys.argv[1]
def post(path, obj):
    req = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path),
        data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=900).read())
    return r, (time.time() - t0) * 1000

p1 = json.load(open("p1.json", encoding="utf-8"))
r, w = post("/completion", p1)
t = r["timings"]
print("turn1  wall=%.0f ms  prompt_n=%s prompt_ms=%.0f  gen=%s"
      % (w, t["prompt_n"], t["prompt_ms"], t["predicted_n"]))
open("p1_gen.txt", "w", encoding="utf-8").write(r["content"])

r, w = post("/slots/0?action=save", {"filename": "slot0.bin"})
print("SAVE   wall=%.0f ms  n_saved=%s n_written=%s  (%.1f MiB)"
      % (w, r.get("n_saved"), r.get("n_written"), r.get("n_written", 0) / 1024 / 1024))
PY

echo "  --- killing server (simulates crash / restart) ---"
kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
sleep 2
ls -la "$SAVE"/slot0.bin

echo
echo "################ PHASE 2: fresh process, restore, turn 2 ################"
start_server "$LOG2"
trap 'kill $SRV 2>/dev/null' EXIT
wait_up

python - "$PORT" <<'PY'
import json, sys, time, urllib.request
port = sys.argv[1]
def post(path, obj):
    req = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path),
        data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=900).read())
    return r, (time.time() - t0) * 1000

r, w = post("/slots/0?action=restore", {"filename": "slot0.bin"})
print("RESTORE wall=%.0f ms  n_restored=%s n_read=%s  (%.1f MiB)"
      % (w, r.get("n_restored"), r.get("n_read"), r.get("n_read", 0) / 1024 / 1024))
if "error" in r:
    print("  ERROR:", r["error"]); sys.exit(1)

base = open("p1_base.txt", encoding="utf-8").read()
gen  = open("p1_gen.txt", encoding="utf-8").read()
p2 = {"prompt": base + gen + "\n\nQuestion: say it again shorter.\nAnswer:",
      "n_predict": 16, "id_slot": 0, "cache_prompt": True, "temperature": 0}
r, w = post("/completion", p2)
t = r["timings"]
print("turn2  wall=%.0f ms  cache_n=%s prompt_n=%s prompt_ms=%.0f  gen=%s"
      % (w, t.get("cache_n"), t["prompt_n"], t["prompt_ms"], t["predicted_n"]))
print("  content: %s" % r["content"][:70].replace("\n", " "))
PY

echo
echo "################ server-side view ################"
grep -E "prompt eval time|restored context checkpoint|saved slot|slot .* action" "$LOG1" "$LOG2" | tail -10
