#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 扫描 spec-draft-n-max：找最优 draft 长度
BIN=$ROOT/llama.cpp/build/bin
D=$ROOT/models
O=$ROOT/ctest
TARGET=$D/qwen3-4b-q4_k_m.gguf
DRAFT=$D/Qwen3-0.6B-q4_k_m.gguf
PORT=8101

scan () {  # $1=n-max  $2=port
  local nmax=$1 port=$2
  $BIN/llama-server.exe -m $TARGET -md $DRAFT --spec-type draft-simple \
    --spec-draft-n-max $nmax -t 12 -c 4096 --port $port > $O/scan_$nmax.log 2>&1 &
  local SRV=$!
  for i in $(seq 1 90); do grep -q "listening on http" $O/scan_$nmax.log 2>/dev/null && break; sleep 1; done
  sleep 3
  local out=""
  for r in 1 2; do
    curl -sS --noproxy '*' --max-time 900 -X POST http://127.0.0.1:$port/v1/completions \
      -H "Content-Type: application/json" --data-binary @$O/req.json -o /dev/null
    out="$out $(sed 's/\x1b\[[0-9;]*m//g' $O/scan_$nmax.log | grep -oE "tg = +[0-9.]+ t/s" | tail -1 | grep -oE '[0-9.]+')"
  done
  local acc=$(sed 's/\x1b\[[0-9;]*m//g' $O/scan_$nmax.log | grep -oE "draft acceptance = [0-9.]+.*mean len = +[0-9.]+" | tail -1)
  kill $SRV 2>/dev/null; sleep 3
  echo "n-max=$nmax -> tok/s:$out  | $acc"
}

for n in 6 8 12; do
  scan $n $PORT
  PORT=$((PORT+1))
done
echo DONE_SCAN
