#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 自投机自检：确认 acceptance rate 指标是否可读（同一模型自 draft，词表匹配）
BIN=$ROOT/llama.cpp/build/bin
D=$ROOT/models
O=$ROOT/ctest
LOG=$O/srv_selfcheck.log

$BIN/llama-server.exe -m $D/Qwen3-0.6B-q4_k_m.gguf \
  -md $D/Qwen3-0.6B-q4_k_m.gguf \
  --spec-type draft-simple --spec-draft-n-max 4 \
  -t 12 -c 2048 --port 8093 > $LOG 2>&1 &
SRV=$!

for i in $(seq 1 60); do
  grep -q "listening on http" $LOG 2>/dev/null && break
  sleep 1
done
sleep 3

curl -sS --noproxy '*' --max-time 300 -X POST http://127.0.0.1:8093/v1/completions \
  -H "Content-Type: application/json" --data-binary @$O/req.json \
  -o $O/resp_self.json -w "http:%{http_code} time:%{time_total}s\n"

kill $SRV 2>/dev/null
sleep 2

echo "=== 关键日志 ==="
sed 's/\x1b\[[0-9;]*m//g' $LOG | grep -iE "accept|spec|n_gen|t/s|draft" | tail -10
echo "=== 响应大小 ==="
ls -la $O/resp_self.json 2>/dev/null
