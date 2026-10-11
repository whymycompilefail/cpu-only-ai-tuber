#!/usr/bin/env bash
# Start the danmaku half of the local VTuber stack:
#   1. llama-server   :8099   (Qwen3.5-2B)
#   2. VTuber backend :12393  (Open-LLM-VTuber, serves the Live2D page)
#   3. danmaku bridge :8765   (filter + priority + busy gating + page channel)
#
# This script does NOT bring up the browser side. The browser is interactive
# (first run needs a QR scan) so it stays a separate step -- see
# LIVE_RUNBOOK.md for the full order and how to verify each stage.
#
# Run in a REAL terminal (not the agent's shell): backgrounded processes here
# survive, but anything started from a tool call gets reaped when it ends.
#
#   bash ctest/start_live.sh            # danmaku over the DOM route (default)
#   DANMAKU_SOURCE=stdin bash ctest/start_live.sh   # type lines by hand
#
# Do NOT use DANMAKU_SOURCE=bilibili. That route is dead: with real cookies
# getInfoByRoom returns code=0 (IP fine, login fine) but getDanmuInfo returns
# -352 for every combination we tried (default UA, +Referer, real Edge UA
# +Origin, without `type`, with `wts`) -- so it is neither missing cookies nor
# a missing WBI signature. Do not spend time on it again.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJ="$ROOT/Open-LLM-VTuber"
LOGDIR="$ROOT/ctest"
PY="$PROJ/.venv/Scripts/python.exe"
LLAMA="$ROOT/llama.cpp/build/bin/llama-server.exe"
MODEL="${STACK_MODEL:-$ROOT/Qwen3.5-2B-GGUF/Qwen3.5-2B-Q4_K_M.gguf}"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"
# Browser cookies that clear code -352 on the token APIs. Default location is
# gitignored on purpose: this may hold SESSDATA, i.e. full account authority.
BILI_COOKIE_FILE="${BILI_COOKIE_FILE:-$ROOT/ctest/bili_cookie.txt}"
[ -f "$BILI_COOKIE_FILE" ] || BILI_COOKIE_FILE=""
COOKIE_ARG=""
[ -n "$BILI_COOKIE_FILE" ] && COOKIE_ARG="--cookie-file $BILI_COOKIE_FILE"
DANMAKU_SOURCE="${DANMAKU_SOURCE:-http}"
WAIT=0
[ "${1:-}" = "--wait" ] && WAIT=1
# Snapshot BEFORE collapsing unset to 0, otherwise every run looks "explicitly
# set" and the local file below is always clobbered.
ROOM_FROM_ENV="${BILI_ROOM_ID:-}"
BILI_ROOM_ID="${BILI_ROOM_ID:-0}"

# Machine-local values (the room id) live in a file that is never committed, so
# they cannot leak through git history, a screenshot or a copy of this tree.
# One-time setup: cp ctest/live.local.example.sh ctest/live.local.sh, fill in.
LOCAL_CFG="$ROOT/ctest/live.local.sh"
if [ -f "$LOCAL_CFG" ]; then
    # shellcheck disable=SC1090
    . "$LOCAL_CFG"
    echo "loaded local config $LOCAL_CFG"
fi
# An explicit environment variable still wins.
[ -n "$ROOM_FROM_ENV" ] && BILI_ROOM_ID="$ROOM_FROM_ENV"

# Qwen3.5 is a thinking model: without this everything lands in
# `reasoning_content` and `content` comes back empty, which reads as "she said
# nothing". Do NOT pass it as --chat-template-kwargs '{...}': through this shell
# the quotes arrive literally and llama-server dies on JSON parse. The env var
# does not go through argv, so it survives.
export LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'

case "$DANMAKU_SOURCE" in
  http|stdin) ;;
  bilibili)
    echo "ERROR: 直连方案已失效，不要用。" >&2
    echo "  getDanmuInfo 恒返回 -352（已排除 cookie 与 WBI 签名）。" >&2
    echo "  改用 DOM 方案：bash ctest/start_live.sh  然后按 LIVE_RUNBOOK.md 起浏览器。" >&2
    exit 1 ;;
  *) echo "ERROR: unknown DANMAKU_SOURCE '$DANMAKU_SOURCE' (http|stdin)" >&2
     exit 1 ;;
esac

echo "=== 0. kill leftovers ==="
echo "  room id : ${BILI_ROOM_ID%????}****  (source=$DANMAKU_SOURCE)"
for port in 8099 12393 "$BRIDGE_PORT"; do
  netstat -ano 2>/dev/null | grep ":$port .*LISTENING" | awk '{print $5}' \
    | sort -u | while read -r pid; do
        echo "  killing pid $pid on :$port"
        taskkill //F //PID "$pid" >/dev/null 2>&1
      done
done
taskkill //F //IM llama-tts.exe >/dev/null 2>&1
sleep 2

echo "=== 1. llama-server :8099 ==="
cd "$ROOT/llama.cpp/build/bin" || exit 1
"$LLAMA" -m "$MODEL" -c 4096 -t 12 --reasoning off \
    --dry-multiplier 0.8 --repeat-penalty 1.05 \
    --host 127.0.0.1 --port 8099 \
    > "$LOGDIR/llama_server.log" 2>&1 &
LLAMA_PID=$!
disown "$LLAMA_PID" 2>/dev/null
echo "  pid=$LLAMA_PID"

echo "=== 2. VTuber backend :12393 ==="
cd "$PROJ" || exit 1
"$PY" -u run_server.py > "$LOGDIR/vtuber_server.log" 2>&1 &
VT_PID=$!
disown "$VT_PID" 2>/dev/null
echo "  pid=$VT_PID"

echo "=== 3. waiting for backend ==="
for i in $(seq 1 90); do
  if curl -s --noproxy 127.0.0.1 --max-time 3 http://127.0.0.1:12393/ \
      >/dev/null 2>&1; then
    echo "  ready after ${i}s"; break
  fi
  sleep 1
done

echo "=== 4. danmaku bridge :$BRIDGE_PORT (source=$DANMAKU_SOURCE) ==="
# The intake endpoints (POST /danmaku, GET /stats, WS /inject) come up for every
# source: WS /inject is how the Live2D page attaches, and the page's socket is
# the only one anyone can hear -- the backend does not broadcast.
"$PY" -u "$LOGDIR/danmaku_bridge.py" \
    --source "$DANMAKU_SOURCE" \
    --room-id "$BILI_ROOM_ID" \
    --port "$BRIDGE_PORT" \
    --character "米粒" $COOKIE_ARG \
    --window 1.0 --cooldown 20 --max-chars 40 \
    > "$LOGDIR/danmaku_bridge.log" 2>&1 &
BRIDGE_PID=$!
disown "$BRIDGE_PID" 2>/dev/null
echo "  pid=$BRIDGE_PID"

sleep 5
echo
echo "=== status ==="
curl -s --noproxy 127.0.0.1 -o /dev/null -w "  backend :12393 = %{http_code}\n" \
    http://127.0.0.1:12393/
curl -s --noproxy 127.0.0.1 -o /dev/null -w "  llama   :8099  = %{http_code}\n" \
    http://127.0.0.1:8099/health
curl -s --noproxy 127.0.0.1 -w "\n" "http://127.0.0.1:$BRIDGE_PORT/stats" \
    2>/dev/null || echo "  bridge not up yet"
echo
echo "=== 下一步：浏览器（本脚本不做） ==="
echo "  1) Edge: python ctest/edge_cdp.py --profile C:/temp/vtuber-edge --wait"
echo "     首次要扫码登录 B 站 —— 游客没有聊天区，采集器会看起来像坏了。"
echo "  2) 直播姬要捕获的窗口: http://localhost:12393 (Live2D)"
echo "  3) 弹幕泵: python ctest/danmaku_pump.py --room-id \$BILI_ROOM_ID"
echo "     它自己会打开/复用直播间标签页并安装采集器。"
echo "  完整顺序与每步的验收输出见 LIVE_RUNBOOK.md"
echo "Stop with: bash ctest/stop_stack.sh"

if [ "$WAIT" = "1" ]; then
    echo
    echo "=== Ctrl+C to stop (this also shuts the stack down) ==="
    trap 'echo "stopping..."; taskkill //F //PID $LLAMA_PID //PID $VT_PID //PID $BRIDGE_PID 2>/dev/null' INT TERM
    # Stay attached. Backgrounded children started here are reaped if this
    # script returns, so it must never return for as long as you want the
    # stack alive -- which is exactly why this exists.
    while true; do sleep 5; done
fi
