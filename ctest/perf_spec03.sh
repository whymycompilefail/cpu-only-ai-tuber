#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Spec 03 acceptance - performance half (G3 throughput, G4 prefill).
#
# Discipline carried over from Spec 02: long-context runs must be serial with zero
# concurrency, and every comparison is paired inside one batch in a balanced order,
# because absolute tok/s drifts 10-20% between batches on this laptop.
#
# Usage: bash ctest/perf_spec03.sh [headline|prefill|all]
set -u

cd $ROOT/ctest
B=bin-tq
M=$ROOT/models/qwen0.6b-q2_k.gguf

sp() {  # decode speed
    timeout 900 $B/llama-cli.exe -st -m $M -t 12 -n 128 -c 16384 -f ctx_8192.txt "$@" 2>&1 \
        | sed 's/\x1b\[[0-9;]*m//g; s/\r//g' | grep -oE "Generation: +[0-9.]+ t/s" | tail -1 | grep -oE "[0-9.]+"
}
pp() {  # prefill speed
    timeout 900 $B/llama-cli.exe -st -m $M -t 12 -n 1 -c 16384 -f ctx_8192.txt "$@" 2>&1 \
        | sed 's/\x1b\[[0-9;]*m//g; s/\r//g' | grep -oE "Prompt: +[0-9.]+ t/s" | tail -1 | grep -oE "[0-9.]+"
}

MODE="${1:-all}"

if [ "$MODE" = "headline" ] || [ "$MODE" = "all" ]; then
echo "======================================================================"
echo " G3  decode @ctx8192 t=12 - balanced order, 2 runs each"
echo "     A = legacy+TQ  (-fa 0      -ctk q8_0 -ctv q8_0)   <-- new"
echo "     B = legacy     (-fa 0      -ctk q8_0 -ctv f16 )   <-- today's best (25.5)"
echo "     C = FA         (-fa 1      -ctk q8_0 -ctv q8_0)   <-- upstream legal, 10.5"
echo "     D = legacy     (-fa 0                          )   <-- f16 KV baseline"
echo "======================================================================"
echo "A1 $(sp -fa 0 -ctk q8_0 -ctv q8_0)"
echo "B1 $(sp -fa 0 -ctk q8_0 -ctv f16)"
echo "B2 $(sp -fa 0 -ctk q8_0 -ctv f16)"
echo "A2 $(sp -fa 0 -ctk q8_0 -ctv q8_0)"
echo "C1 $(sp -fa 1 -ctk q8_0 -ctv q8_0)"
echo "D1 $(sp -fa 0)"
echo "A3 $(sp -fa 0 -ctk q8_0 -ctv q8_0)"
echo "B3 $(sp -fa 0 -ctk q8_0 -ctv f16)"
echo "C2 $(sp -fa 1 -ctk q8_0 -ctv q8_0)"
echo "D2 $(sp -fa 0)"
echo "----------------------------------------------------------------------"
echo " E = default user path: -fa auto (long ctx -> legacy) -ctv q8_0"
echo "E1 $(sp -fa auto -ctk q8_0 -ctv q8_0)"
echo "B4 $(sp -fa 0 -ctk q8_0 -ctv f16)"
echo "E2 $(sp -fa auto -ctk q8_0 -ctv q8_0)"
echo "======================================================================"
fi

if [ "$MODE" = "prefill" ] || [ "$MODE" = "all" ]; then
echo
echo "======================================================================"
echo " G4  prefill (Prompt t/s) @ctx8192 t=12 - gate >= 0.90 vs FA"
echo "======================================================================"
echo "FA     q8K/q8V : $(pp -fa 1 -ctk q8_0 -ctv q8_0)"
echo "legacy q8K/q8V : $(pp -fa 0 -ctk q8_0 -ctv q8_0)"
echo "legacy q8K/f16V: $(pp -fa 0 -ctk q8_0 -ctv f16)"
echo "FA     q8K/q8V : $(pp -fa 1 -ctk q8_0 -ctv q8_0)"
echo "legacy q8K/q8V : $(pp -fa 0 -ctk q8_0 -ctv q8_0)"
echo "======================================================================"
fi
