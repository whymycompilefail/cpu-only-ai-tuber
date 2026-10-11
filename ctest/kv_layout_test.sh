#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Discriminating experiment for the layout mechanism (spec 04 bedrock).
#
#   Claim: if the context is split into FROZEN / HISTORY / VOLATILE zones and VOLATILE
#   always sits at the END, then rebuilding VOLATILE costs only |VOLATILE| tokens - the
#   FROZEN+HISTORY prefix stays cached. If VOLATILE is inserted in the MIDDLE, everything
#   after it must be recomputed.
#
#   The whole "prompt ledger" mechanism rests on this, so it is measured before any code
#   is written.
#
#   FIRST ATTEMPT FAILED AS AN EXPERIMENT (kept in git history): FROZEN was 76% of the
#   prompt, so even the worst case only lost 23.5% - the measurement was insensitive.
#   Fixed by sizing the zones FROZEN ~12% / HISTORY ~72% / VOLATILE ~16%, and by printing
#   the true token counts from the server's /tokenize endpoint instead of guessing.
#
# Cases:
#   1 cold                     baseline (context established)
#   2 rebuild V at END         expect cache_n = |FROZEN+HISTORY|, prompt_n = |V|
#   3 rebuild V at END again   expect identical -> proves steady state
#   4 V moved to MIDDLE        expect cache_n = |FROZEN|, prompt_n = |V|+|HISTORY|
#   5 back to END              measures the CONTAMINATION CARRY-OVER from case 4
#   6 back to END again        measures whether the slot self-heals
#   7 mutate FROZEN by 1 word  expect total collapse (the thing to forbid)
#
# Usage: bash ctest/kv_layout_test.sh [port]
set -u

PORT="${1:-8085}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN=$ROOT/llama.cpp/build/bin/llama-server.exe
M=$ROOT/models/Qwen3-0.6B-f16.gguf
LOG="$HERE/kvlayout.log"

cd "$HERE"

"$BIN" -m "$M" -c 8192 -t 12 -fa 0 -ctk q8_0 -ctv f16 --port "$PORT" \
    -np 1 --host 127.0.0.1 > "$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT

for i in $(seq 1 120); do
    curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q '"status":"ok"' && break
    sleep 1
done

python - "$PORT" <<'PY'
import json, sys, urllib.request
port = sys.argv[1]
BASE = "http://127.0.0.1:%s" % port

def rpc(path, payload):
    req = urllib.request.Request(BASE + path,
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read())

def ntok(s):
    return len(rpc("/tokenize", {"content": s})["tokens"])

def post(prompt):
    return rpc("/completion", {"prompt": prompt, "n_predict": 4, "id_slot": 0,
                               "cache_prompt": True, "temperature": 0})

doc = open("ctx_512.txt", encoding="utf-8").read()

# ---- three zones, sized so the measurement is sensitive ----------------------
FROZEN  = "You are a careful assistant. Answer briefly.\n\n"
HISTORY = doc[:3000]                      # the bulk of the prompt
VOL     = "\n[tool_output]\n" + "".join(
              "line %d: value=%d status=ok\n" % (i, i * 7 + 3) for i in range(9)) \
          + "[end]\nQ: summarise.\nA:"

nf, nh, nv = ntok(FROZEN), ntok(HISTORY), ntok(VOL)
total = nf + nh + nv
print("zone sizes (from /tokenize): FROZEN=%d  HISTORY=%d  VOLATILE=%d  total=%d"
      % (nf, nh, nv, total))
print("shares: FROZEN=%.0f%%  HISTORY=%.0f%%  VOLATILE=%.0f%%"
      % (100.0*nf/total, 100.0*nh/total, 100.0*nv/total))
print()

def vol(tag):
    return ("\n[tool_output %s]\n" % tag
            + "".join("line %s-%d: value=%d status=ok\n" % (tag, i, i * 7 + 3)
                      for i in range(9))
            + "[end]\nQ: summarise.\nA:")

cases = [
    ("1 cold (V at END)",             FROZEN + HISTORY + vol("A"), 0),
    ("2 rebuild V at END",            FROZEN + HISTORY + vol("B"), nv),
    ("3 rebuild V at END again",      FROZEN + HISTORY + vol("C"), nv),
    ("4 V moved to MIDDLE",           FROZEN + vol("D") + HISTORY, nv + nh),
    ("5 back to END",                 FROZEN + HISTORY + vol("E"), nv),
    ("6 back to END again",           FROZEN + HISTORY + vol("F"), nv),
    ("7 mutate FROZEN by 1 word",     "You are a VERY careful assistant. Answer briefly.\n\n"
                                      + HISTORY + vol("G"), total),
]

print("%-28s %9s %9s %11s %8s %10s" % ("case", "cache_n", "prompt_n", "prompt_ms", "reuse%", "expect_n"))
rows = []
for name, p, expect in cases:
    tm = post(p)["timings"]
    cn, pn = tm.get("cache_n", 0), tm["prompt_n"]
    reuse = 100.0 * cn / (cn + pn) if (cn + pn) else 0.0
    rows.append((name, cn, pn, tm["prompt_ms"], reuse, expect))
    print("%-28s %9d %9d %11.0f %7.1f%% %10s"
          % (name, cn, pn, tm["prompt_ms"], reuse, expect if expect else "-"))

print()
ok_end    = abs(rows[1][2] - nv) <= 3                 # steady state pays only |V|
ok_stable = rows[2][2] == rows[1][2]                  # and it is repeatable
ok_mid    = rows[3][2] >= (nv + nh) - 5               # middle pays |V| + |HISTORY|
ok_heal   = rows[5][2] == rows[1][2]                  # slot self-heals after one turn
ok_frozen = rows[6][1] <= 5                           # mutating FROZEN kills everything
print("checks:")
print("  steady state pays only |VOLATILE| (%d vs expected %d) : %s"
      % (rows[1][2], nv, "PASS" if ok_end else "FAIL"))
print("  repeatable                       (%d == %d)          : %s"
      % (rows[2][2], rows[1][2], "PASS" if ok_stable else "FAIL"))
print("  MIDDLE pays |V|+|HISTORY|        (%d vs expected %d) : %s"
      % (rows[3][2], nv + nh, "PASS" if ok_mid else "FAIL"))
print("  self-heals after 1 turn          (%d vs %d)          : %s"
      % (rows[5][2], rows[1][2], "PASS" if ok_heal else "FAIL"))
print("  mutating FROZEN kills all        (cache_n=%d)        : %s"
      % (rows[6][1], "PASS" if ok_frozen else "FAIL"))
print()
ratio = rows[3][2] / rows[1][2] if rows[1][2] else 0
print("cost of one MIDDLE violation: prompt_n %d -> %d  (%.1fx)"
      % (rows[1][2], rows[3][2], ratio))
print("carry-over into the NEXT turn: %d (vs steady %d) -> %.1fx"
      % (rows[4][2], rows[1][2], rows[4][2] / rows[1][2] if rows[1][2] else 0))
print()
print("VERDICT: %s" % ("BEDROCK HOLDS - volatile-last keeps the prefix cached"
                       if (ok_end and ok_stable and ok_mid and ok_heal and ok_frozen)
                       else "BEDROCK FAILS - rethink the mechanism"))
PY
