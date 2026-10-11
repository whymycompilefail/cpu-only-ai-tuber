#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 单用户场景关键实验：上下文长度对 decode 速度的影响 + KV 量化是否提速
# llama-bench 的 tg 测量不带 prompt 上下文（已验证不可信），改用 llama-cli 实测
BIN=$ROOT/llama.cpp/build/bin
O=$ROOT/ctest
PY=$ROOT/.venv/Scripts/python.exe
M=$ROOT/models/qwen0.6b-q2_k.gguf

# 生成不同长度的填充 prompt（重复固定句子，长度可控）
$PY - <<'PYEOF'
base = "The quick brown fox jumps over the lazy dog near the riverbank every morning. "
for n in (64, 1024, 4096, 8192):
    s = base
    while len(s) // 4 < n:
        s += base
    s = s[: n * 4]
    open(r"$ROOT/ctest/ctx_%d.txt" % n, "w", encoding="utf-8").write(s)
    print("wrote ctx_%d.txt  ~%d chars" % (n, len(s)))
PYEOF

run () {
  P=$1; shift
  timeout 600 $BIN/llama-cli.exe -st -m $M -t 12 -n 128 -c 16384 -f $O/ctx_$P.txt "$@" \
    > $O/ctx_run.txt 2>&1
  sed 's/\x1b\[[0-9;]*m//g; s/\r//g' $O/ctx_run.txt \
    | grep -oE "Generation: +[0-9.]+ t/s" | tail -1 | grep -oE "[0-9.]+"
}

echo "=== Q2_K 325MB，KV=f16（默认）==="
for p in 64 1024 4096 8192; do
  echo "  ctx≈$p : $(run $p)"
done

echo "=== Q2_K 325MB，KV=q8_0（-ctk/-ctv）==="
for p in 4096 8192; do
  echo "  ctx≈$p : $(run $p -ctk q8_0 -ctv q8_0)"
done

echo "=== Q2_K 325MB，KV=q4_0 ==="
for p in 4096 8192; do
  echo "  ctx≈$p : $(run $p -ctk q4_0 -ctv q4_0)"
done
