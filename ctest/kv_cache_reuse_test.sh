#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Does --cache-reuse rescue the "volatile content in the middle" violation?
#
#   Discovered while writing spec 04: llama-server already implements POSITION-INDEPENDENT
#   KV reuse. server-context.cpp:3238 does, for every matching run of >= n_cache_reuse
#   identical tokens:
#
#       slot.mem.seq_rm (slot.id, head_p, head_c);
#       slot.mem.seq_add(slot.id, head_c, head_c + n_match, kv_shift);   // shift KV
#
#   i.e. it moves a block of cached KV to a new position instead of recomputing it.
#   Default n_cache_reuse = 0 (disabled); the --fim-qwen-1.5b-default preset uses 256.
#
#   If this works, spec 04 rule 4 ("volatile content must go last") stops being a
#   discipline the caller must obey and becomes a server flag. That is the whole point of
#   this measurement.
#
# Usage: bash ctest/kv_cache_reuse_test.sh [port] [reuse1,reuse2,...]
set -u

PORT="${1:-8087}"
REUSES="${2:-0,64,256}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN=$ROOT/llama.cpp/build/bin/llama-server.exe
M=$ROOT/models/Qwen3-0.6B-f16.gguf

cd "$HERE"

python - "$PORT" "$REUSES" "$BIN" "$M" <<'PY'
import json, os, subprocess, sys, time, urllib.request, signal

port, reuses, BIN, M = sys.argv[1], sys.argv[2].split(","), sys.argv[3], sys.argv[4]
BASE = "http://127.0.0.1:%s" % port

def wait_up(proc):
    for _ in range(120):
        try:
            if json.loads(urllib.request.urlopen(BASE + "/health", timeout=2).read()).get("status") == "ok":
                return True
        except Exception:
            pass
        if proc.poll() is not None:
            return False
        time.sleep(1)
    return False

def rpc(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read())

def post(prompt):
    return rpc("/completion", {"prompt": prompt, "n_predict": 4, "id_slot": 0,
                               "cache_prompt": True, "temperature": 0})

doc = open("ctx_512.txt", encoding="utf-8").read()
FROZEN  = "You are a careful assistant. Answer briefly.\n\n"
HISTORY = doc[:3000]

def vol(tag):
    return ("\n[tool_output %s]\n" % tag
            + "".join("line %s-%d: value=%d status=ok\n" % (tag, i, i * 7 + 3)
                      for i in range(9))
            + "[end]\nQ: summarise.\nA:")

# 2 = steady state (V at END), 4 = violation (V in MIDDLE), 5 = recovery
CASES = [
    ("cold",       FROZEN + HISTORY + vol("A")),
    ("V at END",   FROZEN + HISTORY + vol("B")),
    ("V at END 2", FROZEN + HISTORY + vol("C")),
    ("V MIDDLE",   FROZEN + vol("D") + HISTORY),
    ("recover",    FROZEN + HISTORY + vol("E")),
]

print("%-10s %-12s %9s %9s %11s %8s" % ("reuse", "case", "cache_n", "prompt_n", "prompt_ms", "reuse%"))
summary = {}
for r in reuses:
    srv = subprocess.Popen([BIN, "-m", M, "-c", "8192", "-t", "12", "-fa", "0",
                            "-ctk", "q8_0", "-ctv", "f16", "--port", port,
                            "-np", "1", "--host", "127.0.0.1",
                            "--cache-reuse", r],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_up(srv):
            print("reuse=%s : server failed to start" % r); continue
        out = {}
        for name, p in CASES:
            tm = post(p)["timings"]
            cn, pn = tm.get("cache_n", 0), tm["prompt_n"]
            out[name] = (cn, pn, tm["prompt_ms"])
            print("%-10s %-12s %9d %9d %11.0f %7.1f%%"
                  % (r, name, cn, pn, tm["prompt_ms"], 100.0*cn/(cn+pn) if cn+pn else 0))
        summary[r] = out
    finally:
        # NB: do NOT send CTRL_BREAK_EVENT on Windows - it goes to the whole process group
        # and kills this script too. Plain kill() is TerminateProcess, which is enough here.
        srv.kill()
        try: srv.wait(timeout=15)
        except Exception: pass
        time.sleep(2)

print()
print("=== does --cache-reuse rescue the MIDDLE violation? ===")
print("%-10s %12s %12s %12s" % ("reuse", "END prompt_n", "MIDDLE prompt_n", "penalty"))
base = None
for r, out in summary.items():
    if "V at END" not in out or "V MIDDLE" not in out: continue
    e, m = out["V at END"][1], out["V MIDDLE"][1]
    if base is None: base = m
    print("%-10s %12d %12d %11.2fx" % (r, e, m, m / e if e else 0))
print()
print("penalty is (MIDDLE / END); 4.3x with reuse=0. If it drops towards 1.0x,")
print("the engine already handles insertion and spec 04 rule 4 becomes a server flag.")
PY
