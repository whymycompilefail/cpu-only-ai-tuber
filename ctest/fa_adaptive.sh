#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 验证 -fa auto 新判定逻辑：按请求的上下文大小选择 FA / legacy 路径
# 对照：-fa 1（旧 auto 的实际行为，恒定 FA）与 -fa 0（恒定 legacy）
# 注意：判定用的是 -c（n_ctx），所以测试要按"按需设 -c"来跑，这才是自适应能生效的场景
BIN=$ROOT/llama.cpp/build/bin
O=$ROOT/ctest
M=$ROOT/models/qwen0.6b-q2_k.gguf

run () {
  P=$1; C=$2; shift 2
  timeout 600 $BIN/llama-cli.exe -st -m $M -t 12 -n 128 -c $C -f $O/ctx_$P.txt "$@" \
    > $O/fa_run.txt 2>&1
  sed 's/\x1b\[[0-9;]*m//g; s/\r//g' $O/fa_run.txt \
    | grep -oE "Generation: +[0-9.]+ t/s" | tail -1 | grep -oE "[0-9.]+"
}

pick () {  # 判定日志：auto 到底选了哪条路
  sed 's/\x1b\[[0-9;]*m//g; s/\r//g' $O/fa_run.txt \
    | grep -oE "n_ctx \(-?[0-9]+\) > fa_kv_threshold" | head -1
}

echo "=== 按需设 -c（-c = 2*prompt，短对话用小 -c）==="
echo "prompt | -c   | auto(新) | -fa 1 | -fa 0 | auto选了"
for p in 64 256 512 1024 2048 4096 8192; do
  c=$((p*2)); if [ $c -lt 512 ]; then c=512; fi
  a=$(run $p $c);  pa=$(pick)
  f1=$(run $p $c -fa 1)
  f0=$(run $p $c -fa 0)
  echo "$p | $c | $a | $f1 | $f0 | ${pa:-FA}"
done

echo
echo "=== 用户把 -c 设很大（-c 16384）时的行为：auto 会全程判为 legacy ==="
echo "prompt | auto | -fa 1 | -fa 0"
for p in 64 512 2048 8192; do
  a=$(run $p 16384)
  f1=$(run $p 16384 -fa 1)
  f0=$(run $p 16384 -fa 0)
  echo "$p | $a | $f1 | $f0"
done
