#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Discriminating experiment: is the q4_k_m penalty compute-bound or bandwidth-bound?
#
#   §15/§17 background: no-context tg128 at t=12 gives
#       f16    1509 MB  33.9 t/s  -> 51.1 GB/s  (100%)
#       q8_0    799 MB  55.3 t/s  -> 44.2 GB/s  ( 86%)
#       q4_k_m  484 MB  61.3 t/s  -> 29.7 GB/s  ( 58%)   <-- the target
#       q2_k    347 MB  78.2 t/s  -> 27.1 GB/s  ( 53%)
#
#   If this were a bandwidth wall, q2_k (1/4.35 the bytes of f16) would run at 147 t/s.
#   It runs at 78. So something other than bytes is limiting. Two candidates:
#
#     (A) dequantization is COMPUTE-bound  -> scales with thread count, and the
#         quant kernel's per-byte cost differs by type
#     (B) it is a fixed per-call overhead  -> does not scale with threads
#
#   Thread scaling separates them: compute-bound keeps climbing with threads,
#   bandwidth-bound saturates and then falls.
#
#   Serial, zero concurrency (project rule for anything measured).
#
# Usage: bash ctest/deq_scaling.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
B=$ROOT/llama.cpp/build/bin/llama-bench.exe
D=$ROOT/models
cd "$HERE"

MODELS="Qwen3-0.6B-f16 Qwen3-0.6B-q8_0 Qwen3-0.6B-q4_k_m qwen0.6b-q2_k qwen0.6b-q3_k_l"
THREADS="1 4 8 12 16 22"

for m in $MODELS; do
  for t in $THREADS; do
    R=$("$B" -m "$D/$m.gguf" -n 128 -p 0 -t "$t" -fa 0 -r 1 -o jsonl 2>/dev/null | tail -1)
    TS=$(echo "$R" | grep -o '"avg_ts": [0-9.]*' | grep -o '[0-9.]*$')
    SD=$(echo "$R" | grep -o '"stddev_ts": [0-9.]*' | grep -o '[0-9.]*$')
    echo "$m t=$t avg_ts=$TS stddev=$SD"
  done
done
