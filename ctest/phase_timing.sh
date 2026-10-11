#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 用 -v 抓投机路径的分阶段耗时：draft 前向 / target 验证 / KV 回滚
BIN=$ROOT/llama.cpp/build/bin
D=$ROOT/models
O=$ROOT/ctest

probe () {  # $1=tag  $2..=server args
  local tag=$1; shift
  $BIN/llama-server.exe -m $D/qwen3-4b-q4_k_m.gguf -t 12 -c 4096 --port 8310 -v "$@" > $O/pt_$tag.log 2>&1 &
  local SRV=$!
  for i in $(seq 1 90); do grep -q "listening on http" $O/pt_$tag.log 2>/dev/null && break; sleep 1; done
  sleep 2
  curl -sS --noproxy '*' --max-time 600 -X POST http://127.0.0.1:8310/v1/completions \
    -H "Content-Type: application/json" --data-binary @$O/req.json -o /dev/null
  sleep 1
  kill $SRV 2>/dev/null; sleep 2
  echo "===== $tag ====="
  sed 's/\x1b\[[0-9;]*m//g' $O/pt_$tag.log \
    | grep -oE "eval time = +[0-9.]+ ms / +[0-9]+ runs|prompt eval time = +[0-9.]+ ms / +[0-9]+ tokens|draft acceptance = .*|total time = +[0-9.]+ ms" \
    | tail -25
}

probe base_nospec
probe draft_n4 -md $D/Qwen3-0.6B-q4_k_m.gguf --spec-type draft-simple --spec-draft-n-max 4
echo DONE_PHASE_TIMING
