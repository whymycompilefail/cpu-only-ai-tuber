#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# 决定性实验：decode 阶段（不是 prefill）在 CPU 上到底吃不吃批处理
# 短 prompt（prefill 可忽略）+ 长生成，隔离出纯 decode
# 若 decode 批处理有效 -> 聚合 t/s 随 N 上升；若无效 -> 聚合 t/s 恒定
BIN=$ROOT/llama.cpp/build/bin
O=$ROOT/ctest
PY=$ROOT/.venv/Scripts/python.exe
M=$ROOT/models/qwen3-4b-q4_k_m.gguf
NTOK=256

$PY -c "import json; open(r'$ROOT/ctest/req_short.json','w',encoding='utf-8').write(json.dumps({'prompt':'Write a detailed technical explanation of how CPU memory bandwidth affects large language model inference throughput:','max_tokens':$NTOK,'temperature':0}))"

run_np () {
  N=$1; PORT=$2
  $BIN/llama-server.exe -m $M -np $N -cb -t 12 -c 8192 --port $PORT > $O/np_$N.log 2>&1 &
  SRV=$!
  for i in $(seq 1 120); do grep -q "listening on http" $O/np_$N.log 2>/dev/null && break; sleep 1; done
  rm -f $O/np_${N}_*.json

  T0=$($PY -c "import time;print(time.time())")
  PIDS=""
  for i in $(seq 1 $N); do
    curl -sS --noproxy '*' --max-time 900 -X POST http://127.0.0.1:$PORT/v1/completions \
      -H "Content-Type: application/json" --data-binary @$O/req_short.json \
      -o $O/np_${N}_$i.json >/dev/null 2>&1 &
    PIDS="$PIDS $!"
  done
  wait $PIDS 2>/dev/null
  T1=$($PY -c "import time;print(time.time())")

  $PY -c "
import json,glob,re
wall=$T1-$T0
tot=0
for f in glob.glob(r'$ROOT/ctest/np_${N}_*.json'):
    try: tot+=json.load(open(f,encoding='utf-8')).get('usage',{}).get('completion_tokens',0)
    except Exception: pass
agg=tot/wall if wall>0 else 0
print(f'np=$N  并发=$N  gen_tokens={tot}  墙钟={wall:.1f}s  聚合={agg:.2f} t/s  单请求={agg/$N:.2f} t/s')
"
  # 顺带读 server 侧纯 decode 计时
  sed 's/\x1b\[[0-9;]*m//g' $O/np_$N.log | grep -oE "eval time = +[0-9.]+ ms / +[0-9]+ tokens \( *[0-9.]+ ms per token" \
    | grep -oE "[0-9]+ tokens" | head -1 >/dev/null
  kill $SRV 2>/dev/null
  sleep 4
}

run_np 1 8121
run_np 2 8122
run_np 4 8123
run_np 8 8124
