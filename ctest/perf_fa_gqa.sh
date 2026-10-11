#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Spec 02 / R2,R3,R4,R8: performance acceptance.
#
# Every comparison is made as a RATIO within the same batch, because absolute tok/s drifts
# noticeably between batches on this machine (long-context runs take minutes and the effective
# bandwidth varies with the other load on the box).
#
#   speed()  prints the "Generation: X t/s" value of one run
#
# Usage: bash ctest/perf_fa_gqa.sh <stage>
#   stage = headline | sweep | threads | all
set -u

cd $ROOT/ctest

BASE=bin-base
GQA=bin-gqa
M=$ROOT/models/qwen0.6b-q2_k.gguf
T=12
N=128

speed() {  # speed <bindir> <ctxsize> <prompt> [extra args...]
    local bindir="$1" ctx="$2" prompt="$3"; shift 3
    timeout 900 "$bindir/llama-cli.exe" -st -m $M -t $T -n $N -c "$ctx" -f "$prompt" "$@" 2>&1 \
        | sed 's/\x1b\[[0-9;]*m//g; s/\r//g' \
        | grep -oE "Generation: +[0-9.]+ t/s" | tail -1 | grep -oE "[0-9.]+"
}

ratio() { echo "scale=2; $1 / $2" | bc 2>/dev/null || echo "-"; }

headline() {
    echo "======================================================================"
    echo " R2/R3/R8  ctx=8192, Qwen3-0.6B Q2_K, t=$T, n=$N, -f ctx_8192.txt"
    echo "======================================================================"
    printf "%-30s %8s %8s %8s %7s\n" "CONFIG" "base" "gqa" "legacy" "gqa/leg"
    echo "----------------------------------------------------------------------"

    # f16 KV (path A) - once per variant, interleaved so drift hits both equally
    local fb fg fl fqb fqg fql
    fb=$(speed $BASE 16384 ctx_8192.txt -fa 1 -ctk f16  -ctv f16)
    fg=$(speed $GQA  16384 ctx_8192.txt -fa 1 -ctk f16  -ctv f16)
    fl=$(speed $GQA  16384 ctx_8192.txt -fa 0 -ctk f16  -ctv f16)
    printf "%-30s %8s %8s %8s %7s\n" "KV f16/f16  (path A)" "$fb" "$fg" "$fl" "$(ratio $fg $fl)"

    # quantized K + f16 V (path B) - the highest value legal configuration today
    fqb=$(speed $BASE 16384 ctx_8192.txt -fa 1 -ctk q8_0 -ctv f16)
    fqg=$(speed $GQA  16384 ctx_8192.txt -fa 1 -ctk q8_0 -ctv f16)
    fql=$(speed $GQA  16384 ctx_8192.txt -fa 0 -ctk q8_0 -ctv f16)
    printf "%-30s %8s %8s %8s %7s\n" "K q8_0 / V f16 (path B)" "$fqb" "$fqg" "$fql" "$(ratio $fqg $fql)"

    # quantized V - explicitly NOT a target of this change (independent defect, spec 1.1/7)
    local vqb vqg
    vqb=$(speed $BASE 16384 ctx_8192.txt -fa 1 -ctk q8_0 -ctv q8_0)
    vqg=$(speed $GQA  16384 ctx_8192.txt -fa 1 -ctk q8_0 -ctv q8_0)
    printf "%-30s %8s %8s\n" "K q8_0 / V q8_0 (no promise)" "$vqb" "$vqg"
    echo "----------------------------------------------------------------------"
    echo " R2 needs gqa/legacy >= 0.95 for f16 ; R8 needs >= 0.95 for q8_0/f16"
    echo "======================================================================"
}

sweep() {
    echo "======================================================================"
    echo " R4  no regression below ctx=8192 (t=$T, n=$N)"
    echo "======================================================================"
    printf "%-8s %-8s %10s %10s %8s\n" "ctx" "path" "base" "gqa" "gqa/base"
    echo "----------------------------------------------------------------------"
    for c in 256 512 1024 2048 4096; do
        local ctx=$((c * 2))
        local b g
        b=$(speed $BASE $ctx ctx_$c.txt -fa 1)
        g=$(speed $GQA  $ctx ctx_$c.txt -fa 1)
        local p="A"; [ $c -lt 512 ] && p="B"
        printf "%-8s %-8s %10s %10s %8s\n" "$c" "$p" "$b" "$g" "$(ratio $g $b)"
    done
    echo "----------------------------------------------------------------------"
    echo " R4 needs gqa/base >= 0.95 at every point (0.90 allowed at ctx=4096"
    echo " only if judged against same-batch legacy)"
    echo "======================================================================"
}

threads() {
    echo "======================================================================"
    echo " R3  alpha must no longer track thread count (ctx=8192, KV f16)"
    echo "======================================================================"
    printf "%-6s %10s %10s %10s\n" "t" "FA-base" "FA-gqa" "legacy"
    echo "----------------------------------------------------------------------"
    for t in 4 8 12 16; do
        T=$t
        local b g l
        b=$(speed $BASE 16384 ctx_8192.txt -fa 1)
        g=$(speed $GQA  16384 ctx_8192.txt -fa 1)
        l=$(speed $GQA  16384 ctx_8192.txt -fa 0)
        printf "%-6s %10s %10s %10s\n" "$t" "$b" "$g" "$l"
    done
    T=12
    echo "======================================================================"
}

case "${1:-all}" in
    headline) headline ;;
    sweep)    sweep ;;
    threads)  threads ;;
    all)      headline; echo; sweep; echo; threads ;;
esac
