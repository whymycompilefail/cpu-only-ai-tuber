#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# A/B：Qwen3-0.6B 无 draft vs 自 draft（d=b，理论预测零收益）
BIN=$ROOT/llama.cpp/build/bin
D=$ROOT/models
O=$ROOT/ctest
M=$D/Qwen3-0.6B-q4_k_m.gguf

start () {
  local extra=$2
  $BIN/llama-server.exe -m $M -t 12 -c 2048 --port $1 $extra > $3 2>&1 &
  SRV=$!
  for i in $(seq 1 60); do grep -q "listening on http" $3 2>/dev/null && break; sleep 1; done
  sleep 3
}
stop () { kill $SRV 2>/dev/null; sleep 3; }

req () {
  curl -sS --noproxy '*' --max-time 300 -X POST http://127.0.0.1:$1/v1/completions \
    -H "Content-Type: application/json" --data-binary @$O/req.json -o /dev/null
}
tps () { sed 's/\x1b\[[0-9;]*m//g' $1 | grep -oE "tg = +[0-9.]+ t/s" | tail -1 | grep -oE "[0-9.]+"; }
acc () { sed 's/\x1b\[[0-9;]*m//g' $1 | grep -oE "draft acceptance = [0-9.]+.*mean len = +[0-9.]+" | tail -1; }

echo "--- 无 draft ---"
start 8091 $O/s_none.log
for i in 1 2 3; do req 8091; echo "  round$i: $(tps $O/s_none.log)"; done
stop

echo "--- 自 draft (n-max=4) ---"
start 8092 "-md $M --spec-type draft-simple --spec-draft-n-max 4" $O/s_self.log
for i in 1 2 3; do req 8092; echo "  round$i: $(tps $O/s_self.log)"; done
stop
echo "  acceptance: $(acc $O/s_self.log)"
echo DONE
