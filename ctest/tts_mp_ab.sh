#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# A/B: does the vocoder (which lives in mmproj) respond to threads and to quantisation?
# backbone is fixed at q8_0; the 5-prompt loop gives steady-state numbers (iter 0 is warmup).
set -u
LL=$ROOT/llama.cpp/build/bin/llama-tts.exe
M=$ROOT/models
IN=$ROOT/ctest/tts_loop_in.txt
OUT=$ROOT/ctest

run () {
    local tag=$1 mp=$2 t=$3
    echo "=== tag=$tag mmproj=$mp threads=$t ==="
    cd $ROOT/llama.cpp
    LLAMA_TTS_LOOP=1 "$LL" \
        -m "$M/Qwen3-TTS-0.6B-q8_0.gguf" \
        -mm "$M/$mp" \
        --tts-lang zh -o "$OUT/tts_ab_$tag.wav" -t "$t" < "$IN" 2>&1 \
        | grep -E "\[[0-9]\] (generated|timings)"
    echo
}

run t12_f16 mmproj-Qwen3-TTS-0.6B-f16.gguf  12
run t22_f16 mmproj-Qwen3-TTS-0.6B-f16.gguf  22
run t12_q8  mmproj-Qwen3-TTS-0.6B-q8_0.gguf 12
run t22_q8  mmproj-Qwen3-TTS-0.6B-q8_0.gguf 22
