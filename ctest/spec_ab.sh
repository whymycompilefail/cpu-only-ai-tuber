#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 投机命中 A/B 测试脚本
# 用法: spec_ab.sh
# 输出: 每项一次的 Generation tok/s

BIN=$ROOT/llama.cpp/build/bin/llama-cli.exe
M=$ROOT/models/Qwen3-0.6B-q4_k_m.gguf
OUT=$ROOT/ctest/spec_ab
mkdir -p $OUT

# 高重复 pattern 的 prompt：JSON 模板 + 代码骨架
PROMPT='{"schema": {"type": "object", "properties": {"id": {"type": "string"}, "value": {"type": "number"}}, "required": ["id", "value"]}, "data": ['

run_once () {
    local tag="$1"; shift
    timeout 300 $BIN -st -m $M -t 12 -n 128 -c 2048 -f $ROOT/ctest/prompt.txt "$@" \
        > "$OUT/$tag.txt" 2>&1
    local line
    line=$(sed 's/\x1b\[[0-9;]*m//g; s/\r//g' "$OUT/$tag.txt" | grep -oE "Generation: [0-9.]+ t/s" | tail -1)
    local acc
    acc=$(sed 's/\x1b\[[0-9;]*m//g; s/\r//g' "$OUT/$tag.txt" | grep -iE "accept" | tail -1)
    echo "$tag | $line | acc: ${acc:-none}"
}

# 把 prompt 写成文件（llama-cli 的 -f 读文件，避免命令行转义问题）
printf '%s' "$PROMPT" > $ROOT/ctest/prompt.txt

echo "=== A/B: 高重复 JSON 场景, n=128 ==="
run_once "baseline_nospec"
run_once "ngram_cache"  --spec-type ngram-cache
run_once "ngram_map_k4v" --spec-type ngram-map-k4v
run_once "ngram_mod"     --spec-type ngram-mod
run_once "ngram_simple"  --spec-type ngram-simple
