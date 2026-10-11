#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Full 9-type alternating A/B with f16 bracketing every half-block.
#
#   Why f16 brackets: the machine drifts +-6% (sometimes 30%+ if anything else
#   runs -- see deq_ab.log rep2R/rep3F, which I contaminated myself by running
#   a Python analysis job mid-benchmark). f16 has no quant kernel, so its t/s
#   is a pure probe of machine state. Every quant measurement is divided by the
#   f16 value linearly interpolated between the two f16 measurements that
#   bracket it. See ctest/ab_ratio.py.
#
#   Sequence per direction: f16, m1..m8, f16  (then the whole thing reversed)
#
#   RULE: run this alone. Do not start anything else while it runs.
#
# Usage: bash ctest/deq_ab2.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
B=$ROOT/llama.cpp/build/bin/llama-bench.exe
D=$ROOT/models
cd "$HERE"

QUANTS="Qwen3-0.6B-q8_0 Qwen3-0.6B-q6_K Qwen3-0.6B-q5_K Qwen3-0.6B-q5_0 Qwen3-0.6B-q4_k_m Qwen3-0.6B-q4_0 qwen0.6b-q3_k_l qwen0.6b-q2_k"
FWD="Qwen3-0.6B-f16 $QUANTS Qwen3-0.6B-f16"
REV=$(echo "$FWD" | tr ' ' '\n' | tac | tr '\n' ' ')
REPS=3
T=12

one() {
  "$B" -m "$D/$1.gguf" -n 128 -p 0 -t "$T" -fa 0 -r 2 -o jsonl 2>/dev/null | tail -1 \
    | grep -o '"avg_ts": [0-9.]*' | grep -o '[0-9.]*$'
}

echo "# deq A/B (full)  t=$T  reps=$REPS  $(grep -o 'GGML_AVX_VNNI:BOOL=[A-Z]*' $ROOT/llama.cpp/build/CMakeCache.txt)"
echo "# rep dir model avg_ts"
for r in $(seq 1 $REPS); do
  for dir in F R; do
    if [ "$dir" = F ]; then LIST="$FWD"; else LIST="$REV"; fi
    for m in $LIST; do
      echo "$r $dir $m $(one "$m")"
    done
  done
done
