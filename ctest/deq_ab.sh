#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Alternating A/B measurement to defeat system drift (+-6%).
#
#   Problem this exists for: a single llama-bench run drifted by ~6% between
#   sessions (VNNI=ON rebuild measured f16 at 37.83 t/s where a previous
#   session had 40.05, and f16 has no quant kernel at all -- so that delta is
#   pure machine drift, not code). Any conclusion below ~8% needs A/B repeats.
#
#   Method: for each rep, run the models in FORWARD order, then in REVERSE
#   order. A monotonic drift (thermal / background load) then cancels:
#       ratio = mean(forward_i) / mean(reverse_i)  is drift-free
#   We report per-rep paired ratio, plus mean +- sd over reps.
#
#   Serial, zero concurrency (project rule for anything measured).
#
# Usage: bash ctest/deq_ab.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
B=$ROOT/llama.cpp/build/bin/llama-bench.exe
D=$ROOT/models
cd "$HERE"

ORDER="Qwen3-0.6B-f16 Qwen3-0.6B-q4_k_m Qwen3-0.6B-q4_0 Qwen3-0.6B-q5_0"
REVS=$(echo "$ORDER" | tr ' ' '\n' | tac | tr '\n' ' ')
REPS=4
T=12

one() {
  "$B" -m "$D/$1.gguf" -n 128 -p 0 -t "$T" -fa 0 -r 2 -o jsonl 2>/dev/null | tail -1 \
    | grep -o '"avg_ts": [0-9.]*' | grep -o '[0-9.]*$'
}

echo "# deq A/B  t=$T  reps=$REPS  VNNI=$(grep -o 'GGML_AVX_VNNI:BOOL=[A-Z]*' $ROOT/llama.cpp/build/CMakeCache.txt)"
echo "# rep dir model avg_ts"

for r in $(seq 1 $REPS); do
  for dir in F R; do
    if [ "$dir" = F ]; then LIST="$ORDER"; else LIST="$REVS"; fi
    for m in $LIST; do
      V=$(one "$m")
      echo "$r $dir $m $V"
    done
  done
done
