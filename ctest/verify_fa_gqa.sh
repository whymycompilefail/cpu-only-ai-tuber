#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Spec 02 / R1: bit-exactness acceptance.
#
# Compares the generated token sequence of the modified build (bin-gqa) against the
# pre-change build (bin-base) for every configuration listed in specs/fa-gqa-loop-reorder.md 6.1.
# Any difference is a hard fail - by construction this change must be bit-exact.
#
# Usage: bash ctest/verify_fa_gqa.sh [case_no ...]      (no args = all cases)
set -u

cd $ROOT/ctest

run() {   # run <bindir> <args...>  -> prints generated text only
    local bindir="$1"; shift
    local out
    out="$("$bindir/llama-cli.exe" -st --temp 0 -t 12 -n 256 "$@" 2>/dev/null)"
    printf '%s\n' "$out" | awk 'f{ if ($0 ~ /^\[ Prompt:/) exit; print } /^> /{f=1}'
}

# case_no | label | extra args | model | prompt | ctxsize
CASES=(
  "1|0.6B f16     -fa 1 ctx512        |$ROOT/models/Qwen3-0.6B-f16.gguf     |ctx_512.txt  |1024  |-fa 1"
  "2|0.6B f16     -fa 1 ctx8192       |$ROOT/models/Qwen3-0.6B-f16.gguf     |ctx_8192.txt |16384 |-fa 1"
  "3|0.6B Q2_K    -fa 1 ctx8192       |$ROOT/models/qwen0.6b-q2_k.gguf      |ctx_8192.txt |16384 |-fa 1"
  "4|0.6B Q2_K    -fa 1 q8_0/f16      |$ROOT/models/qwen0.6b-q2_k.gguf      |ctx_8192.txt |16384 |-fa 1 -ctk q8_0 -ctv f16"
  "5|4B   q4_k_m  -fa 1 ctx8192       |$ROOT/models/qwen3-4b-q4_k_m.gguf    |ctx_8192.txt |16384 |-fa 1"
  "6|0.6B Q2_K    -fa 0 ctx8192       |$ROOT/models/qwen0.6b-q2_k.gguf      |ctx_8192.txt |16384 |-fa 0"
)

mkdir -p out_gqa

echo "======================================================================"
echo " R1 bit-exactness: bin-base (before)  vs  bin-gqa (after)"
echo "======================================================================"
printf "%-34s %-10s %s\n" "CASE" "RESULT" "tokens(base/gqa)"
echo "----------------------------------------------------------------------"

for c in "${CASES[@]}"; do
    IFS='|' read -r no label model prompt ctxsize args <<< "$c"
    if [ $# -gt 0 ] && [[ ! " $* " == *" $no "* ]]; then continue; fi

    echo "[case $no] running: $label ..." >&2
    run bin-base -m "$model" -f "$prompt" -c "$ctxsize" $args > out_gqa/base_$no.txt
    run bin-gqa  -m "$model" -f "$prompt" -c "$ctxsize" $args > out_gqa/gqa_$no.txt

    if diff -q out_gqa/base_$no.txt out_gqa/gqa_$no.txt > /dev/null; then
        res="IDENTICAL"
    else
        res="**DIFF**"
    fi
    nb=$(wc -c < out_gqa/base_$no.txt); ng=$(wc -c < out_gqa/gqa_$no.txt)
    printf "%-34s %-10s %s\n" "$label" "$res" "$nb/$ng"
done

echo "----------------------------------------------------------------------"
echo "artifacts: ctest/out_gqa/base_N.txt, gqa_N.txt  (diff -u to inspect)"
echo "======================================================================"
