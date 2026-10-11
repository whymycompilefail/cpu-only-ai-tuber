#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 干净环境：投机命中完整矩阵重测（draft 各档 + ngram 各变体）
BIN=$ROOT/llama.cpp/build/bin
D=$ROOT/models
O=$ROOT/ctest
TARGET=$D/qwen3-4b-q4_k_m.gguf
DRAFT=$D/Qwen3-0.6B-q4_k_m.gguf

run () {  # $1=tag $2=port $3..=extra args
  local tag=$1 port=$2; shift 2
  $BIN/llama-server.exe -m $TARGET -t 12 -c 4096 --port $port "$@" > $O/rs_$tag.log 2>&1 &
  local SRV=$!
  for i in $(seq 1 90); do grep -q "listening on http" $O/rs_$tag.log 2>/dev/null && break; sleep 1; done
  sleep 3
  local out=""
  for r in 1 2 3; do
    curl -sS --noproxy '*' --max-time 600 -X POST http://127.0.0.1:$port/v1/completions \
      -H "Content-Type: application/json" --data-binary @$O/req.json -o /dev/null
    out="$out $(sed 's/\x1b\[[0-9;]*m//g' $O/rs_$tag.log | grep -oE 'tg = +[0-9.]+ t/s' | tail -1 | grep -oE '[0-9.]+')"
  done
  local acc=$(sed 's/\x1b\[[0-9;]*m//g' $O/rs_$tag.log | grep -oE 'draft acceptance = [0-9.]+.*mean len = +[0-9.]+' | tail -1)
  kill $SRV 2>/dev/null; sleep 3
  echo "$tag | tok/s:$out | ${acc:-（无 acceptance 输出）}"
}

P=8200
run base         $P
P=$((P+1)); run draft_n4  $P -md $DRAFT --spec-type draft-simple --spec-draft-n-max 4
P=$((P+1)); run draft_n6  $P -md $DRAFT --spec-type draft-simple --spec-draft-n-max 6
P=$((P+1)); run draft_n8  $P -md $DRAFT --spec-type draft-simple --spec-draft-n-max 8
P=$((P+1)); run draft_n12 $P -md $DRAFT --spec-type draft-simple --spec-draft-n-max 12
P=$((P+1)); run ngram_cache $P --spec-type ngram-cache
P=$((P+1)); run ngram_mapk  $P --spec-type ngram-map-k
P=$((P+1)); run ngram_mod   $P --spec-type ngram-mod
P=$((P+1)); run base2       $P
echo DONE_SPEC_RETEST
