#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 干净环境重测：Qwen3-4B 无 draft vs draft n-max=4
BIN=$ROOT/llama.cpp/build/bin
D=$ROOT/models
O=$ROOT/ctest
TARGET=$D/qwen3-4b-q4_k_m.gguf
DRAFT=$D/Qwen3-0.6B-q4_k_m.gguf

run () {  # $1=tag $2=port $3..=extra
  local tag=$1 port=$2; shift 2
  $BIN/llama-server.exe -m $TARGET -t 12 -c 4096 --port $port "$@" > $O/rt_$tag.log 2>&1 &
  local SRV=$!
  for i in $(seq 1 90); do grep -q "listening on http" $O/rt_$tag.log 2>/dev/null && break; sleep 1; done
  sleep 3
  local out=""
  for r in 1 2 3; do
    curl -sS --noproxy '*' --max-time 600 -X POST http://127.0.0.1:$port/v1/completions \
      -H "Content-Type: application/json" --data-binary @$O/req.json -o /dev/null
    out="$out $(sed 's/\x1b\[[0-9;]*m//g' $O/rt_$tag.log | grep -oE 'tg = +[0-9.]+ t/s' | tail -1 | grep -oE '[0-9.]+')"
  done
  local acc=$(sed 's/\x1b\[[0-9;]*m//g' $O/rt_$tag.log | grep -oE 'draft acceptance = [0-9.]+.*mean len = +[0-9.]+' | tail -1)
  kill $SRV 2>/dev/null; sleep 3
  echo "$tag -> tok/s:$out  | $acc"
}

run base    8101
run draft4  8102 -md $DRAFT --spec-type draft-simple --spec-draft-n-max 4
run base    8103
run draft4  8104 -md $DRAFT --spec-type draft-simple --spec-draft-n-max 4
echo DONE_RETEST
