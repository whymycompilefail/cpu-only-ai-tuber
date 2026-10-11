#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# draft model 投机命中 A/B 测试
# target = Qwen3-4B-Base Q4_K_M, draft = Qwen3-0.6B Q4_K_M
set -u

BIN=$ROOT/llama.cpp/build/bin
D=$ROOT/models
O=$ROOT/ctest
PROMPT=$O/prompt_long.txt
TARGET=$D/qwen3-4b-q4_k_m.gguf
DRAFT=$D/Qwen3-0.6B-q4_k_m.gguf

REQ () {  # $1=port
  curl -sS --noproxy '*' --max-time 900 -X POST http://127.0.0.1:$1/v1/completions \
    -H "Content-Type: application/json" --data-binary @$O/req.json \
    -o /dev/null -w "%{time_total}"
}

TOKS () {  # 从 server 日志抓最后一个 tok/s
  sed 's/\x1b\[[0-9;]*m//g' "$1" | grep -oE "n_gen = +[0-9]+, tg = +[0-9.]+ t/s" | tail -1 | grep -oE "[0-9.]+ t/s"
}

ACCEPT () {  # 抓 acceptance rate
  sed 's/\x1b\[[0-9;]*m//g' "$1" | grep -iE "acceptance rate|speculative.*accept" | tail -1
}

start () {  # $1=port $2=log $3..=extra args
  local port=$1 log=$2; shift 2
  $BIN/llama-server.exe -m $TARGET -t 12 -c 4096 --port $port "$@" > "$log" 2>&1 &
  echo $! > $O/srv_$port.pid
  for i in $(seq 1 60); do
    grep -q "listening on http" "$log" 2>/dev/null && break
    sleep 2
  done
  sleep 3
}

stop () { kill $(cat $O/srv_$1.pid) 2>/dev/null; sleep 4; }

ROUNDS=${ROUNDS:-3}
PORT_N=8091
PORT_S=8092

echo "=========== 基线：无 draft ==========="
start $PORT_N $O/srv_nolimit.log
for i in $(seq 1 $ROUNDS); do
  REQ $PORT_N > /dev/null
  echo "  round$i: $(TOKS $O/srv_nolimit.log)"
done
echo "  最终: $(TOKS $O/srv_nolimit.log)"
stop $PORT_N

echo "=========== 有 draft: Qwen3-0.6B ==========="
start $PORT_S $O/srv_draft.log -md $DRAFT --spec-type draft-simple --spec-draft-n-max 4
grep -iE "spec common_specu|acceptance|vocab" $O/srv_draft.log | sed 's/\x1b\[[0-9;]*m//g' | head -8
for i in $(seq 1 $ROUNDS); do
  REQ $PORT_S > /dev/null
  echo "  round$i: $(TOKS $O/srv_draft.log)"
done
echo "  最终: $(TOKS $O/srv_draft.log)"
echo "  acceptance: $(ACCEPT $O/srv_draft.log)"
stop $PORT_S

echo "=========== 交替复测（抗噪声）==========="
for i in $(seq 1 $ROUNDS); do
  start $PORT_N $O/srv_nolimit.log; REQ $PORT_N > /dev/null; A=$(TOKS $O/srv_nolimit.log); stop $PORT_N
  start $PORT_S $O/srv_draft.log -md $DRAFT --spec-type draft-simple --spec-draft-n-max 4
  REQ $PORT_S > /dev/null; B=$(TOKS $O/srv_draft.log); stop $PORT_S
  echo "  round$i: 无draft=$A  有draft=$B"
done

echo "DONE"
