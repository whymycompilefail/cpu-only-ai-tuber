#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Spec 03 acceptance - correctness half.
#
#   G2 (*): default paths must be bit-exact against bin-gqa (the build before Spec 03).
#           Spec 03 only changes behaviour when the V cache is quantized, so every f16-V
#           configuration has to come out byte-identical. Any diff here is a hard fail.
#   G6    : the TQ op must produce sane text. It is checked against the upstream-legal
#           FA + quantized-V configuration, which computes the same mathematical object
#           through a completely independent path. Token agreement is reported, but the
#           formal correctness gate is the PPL oracle (spec §7 G1).
#
# NOTE (2026-09-28): the op ships OFF by default (spec §10 - G3 failed at 0.67x). The G6
#   leg therefore has to switch it on explicitly; without LLAMA_QV_OP=1 every -ctv q8_0
#   run in this section exits with "quantized V cache requires flash_attn", writes zero
#   tokens, and prints a misleading 0/N. G5 asserts that off-by-default behaviour.
#
# Usage: bash ctest/verify_spec03.sh [case_no ...]
set -u

cd $ROOT/ctest

run() {   # run <bindir> <args...>  -> prints generated text only
    local bindir="$1"; shift
    local out
    out="$("$bindir/llama-cli.exe" -st --temp 0 -t 12 -n 256 "$@" 2>/dev/null)"
    printf '%s\n' "$out" | awk 'f{ if ($0 ~ /^\[ Prompt:/) exit; print } /^> /{f=1}'
}

# --- G2: default paths, must be IDENTICAL ----------------------------------
# case_no | label | model | prompt | ctxsize | args
EXACT=(
  "1|legacy f16  @8192      |$ROOT/models/qwen0.6b-q2_k.gguf |ctx_8192.txt |16384 |-fa 0"
  "2|FA     f16  @512       |$ROOT/models/qwen0.6b-q2_k.gguf |ctx_512.txt  |1024  |-fa 1"
  "3|legacy q8K/f16V @8192  |$ROOT/models/qwen0.6b-q2_k.gguf |ctx_8192.txt |16384 |-fa 0 -ctk q8_0 -ctv f16"
  "4|f16model FA @512       |$ROOT/models/Qwen3-0.6B-f16.gguf|ctx_512.txt  |1024  |-fa 1"
  "5|FA     f16  @8192      |$ROOT/models/qwen0.6b-q2_k.gguf |ctx_8192.txt |16384 |-fa 1"
  "6|legacy f16  @512       |$ROOT/models/qwen0.6b-q2_k.gguf |ctx_512.txt  |1024  |-fa 0"
)

mkdir -p out_tq

echo "======================================================================"
echo " Spec 03 / G2  bit-exactness of the default paths: bin-gqa vs bin-tq"
echo "======================================================================"
printf "%-30s %-10s %s\n" "CASE" "RESULT" "bytes(gqa/tq)"
echo "----------------------------------------------------------------------"

FAIL=0
for c in "${EXACT[@]}"; do
    IFS='|' read -r no label model prompt ctxsize args <<< "$c"
    if [ $# -gt 0 ] && [[ ! " $* " == *" $no "* ]]; then continue; fi
    model="$(echo "$model" | xargs)"

    echo "[case $no] running: $label ..." >&2
    run bin-gqa -m "$model" -f "$prompt" -c "$ctxsize" $args > out_tq/gqa_$no.txt
    run bin-tq  -m "$model" -f "$prompt" -c "$ctxsize" $args > out_tq/tq_$no.txt

    if diff -q out_tq/gqa_$no.txt out_tq/tq_$no.txt > /dev/null; then
        res="IDENTICAL"
    else
        res="**DIFF**"; FAIL=1
    fi
    printf "%-30s %-10s %s\n" "$label" "$res" "$(wc -c < out_tq/gqa_$no.txt)/$(wc -c < out_tq/tq_$no.txt)"
done

echo "----------------------------------------------------------------------"

# --- G5: with the op OFF by default, quantized V + legacy must behave upstream ---------
echo
echo "======================================================================"
echo " Spec 03 / G5  rollback: LLAMA_QV_OP unset -> upstream semantics"
echo "======================================================================"
# The f16 model is mandatory here. qwen0.6b-q2_k.gguf is a broken conversion (benchmark_results.md
# §15.6: PPL 264-321 against 21.97 for the f16 model) and emits garbage on *every* path, including
# the untouched upstream one - text-level agreement against it measures nothing.
M=$ROOT/models/Qwen3-0.6B-f16.gguf
unset LLAMA_QV_OP
ERR=$(bin-tq/llama-cli.exe -m $M -f ctx_512.txt -c 1024 -fa 0 -ctk q8_0 -ctv q8_0 -st -n 8 2>&1 >/dev/null | grep -c "requires flash_attn")
if [ "$ERR" -gt 0 ]; then echo "  -fa 0 -ctv q8_0 (op off):  PASS  (upstream error restored)"
else echo "  -fa 0 -ctv q8_0 (op off):  **FAIL** (no upstream error)"; FAIL=1; fi
if bin-tq/llama-cli.exe -m $M -f ctx_512.txt -c 1024 -fa 0 -ctv f16 -st -n 8 2>/dev/null | grep -q .; then
    echo "  -fa 0 -ctv f16  (op off):  PASS  (normal default path)"
else echo "  -fa 0 -ctv f16  (op off):  **FAIL**"; FAIL=1; fi

# --- G6: TQ op sanity - same math, two independent implementations ---------
echo
echo "======================================================================"
echo " Spec 03 / G6  legacy+TQ (q8K/q8V)  vs  FA (q8K/q8V) - same math"
echo "  (runs with LLAMA_QV_OP=1 - the op is off by default, see spec §10)"
echo "======================================================================"
export LLAMA_QV_OP=1
M=$ROOT/models/Qwen3-0.6B-f16.gguf
run bin-tq -m $M -f ctx_512.txt -c 1024 -fa 0 -ctk q8_0 -ctv q8_0 > out_tq/tq_q8v.txt
run bin-tq -m $M -f ctx_512.txt -c 1024 -fa 1 -ctk q8_0 -ctv q8_0 > out_tq/fa_q8v.txt
run bin-tq -m $M -f ctx_512.txt -c 1024 -fa 0 -ctk q8_0 -ctv f16 > out_tq/tq_f16v.txt

for pair in "tq_q8v.txt:fa_q8v.txt:legacy+TQ vs FA (both q8V)" "tq_q8v.txt:tq_f16v.txt:legacy+TQ q8V vs legacy f16V"; do
    IFS=':' read -r a b lbl <<< "$pair"
    ta=$(tr -s ' \n' ' ' < out_tq/$a | tr ' ' '\n' | grep -c .)
    tb=$(tr -s ' \n' ' ' < out_tq/$b | tr ' ' '\n' | grep -c .)
    sa=$(tr -s ' \n' ' ' < out_tq/$a | tr ' ' '\n' | grep -v '^$')
    sb=$(tr -s ' \n' ' ' < out_tq/$b | tr ' ' '\n' | grep -v '^$')
    same=$(paste <(printf '%s\n' "$sa") <(printf '%s\n' "$sb") 2>/dev/null | awk -F'\t' '$1==$2' | wc -l)
    min=$(( ta < tb ? ta : tb ))
    echo "$(printf '%-38s' "$lbl") tokens=$ta/$tb  identical_prefix_words=$same/$min"
done
echo
echo "artifacts: ctest/out_tq/*.txt"
echo "======================================================================"
exit $FAIL
