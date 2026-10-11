#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Bring up the whole local VTuber stack:
#   1. llama-server  (our fork, OpenAI-compatible) on 127.0.0.1:8099
#   2. Open-LLM-VTuber backend                    on 127.0.0.1:12393
# Log to ctest/ ; safe to re-run (kills the previous instance first).

# usage: bash ctest/run_stack.sh            # start and return (processes stay up)
#        bash ctest/run_stack.sh --wait     # stay attached until Ctrl+C

set -u
LLAMA="$ROOT/llama.cpp/build/bin/llama-server.exe"
# Chat model. Qwen3.5-2B Q4_K_M replaced MiniCPM5-2B Q4_K_M on 2026-10-02:
# same 0/15 persona-break rate under the real persona config, but replies are
# less formulaic and emotion tags come back reliably instead of being dropped.
# See ctest/benchmark_model_choice.md. Swap back with
#   STACK_MODEL=$ROOT/MiniCPM5-2B-gguf/MiniCPM5-2B-Q4_K_M.gguf
MODEL="${STACK_MODEL:-$ROOT/Qwen3.5-2B-GGUF/Qwen3.5-2B-Q4_K_M.gguf}"
# Qwen3.5 is a thinking model: by default everything lands in
# `reasoning_content` and `content` comes back empty, which reads as "she said
# nothing". Request-level `chat_template_kwargs` also works, but doing it here
# means every client gets it with no code change. NOTE: do NOT try to pass this
# as --chat-template-kwargs '{...}': through this shell the quotes arrive
# literally and llama-server dies with a JSON parse error. The env var does not
# go through argv, so it survives.
export LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
PROJ="$ROOT/Open-LLM-VTuber"
LOGDIR="$ROOT/ctest"
PORT=8099
WAIT=0
[ "${1:-}" = "--wait" ] && WAIT=1

echo "=== 0. kill leftovers ==="
for p in 8099 12393; do
    netstat -ano 2>/dev/null | grep ":$p .*LISTENING" | awk '{print $5}' | sort -u | while read -r pid; do
        echo "killing pid $pid on :$p"; taskkill //F //PID "$pid" 2>&1 | head -2
    done
done
sleep 1

echo "=== 1. start llama-server ==="
cd "$(dirname "$LLAMA")" || exit 1
# --reasoning off: Qwen3 otherwise emits only `reasoning_content` and leaves
# `content` empty on short replies, which the VTuber reads as "said nothing".
# --dry-multiplier / --repeat-penalty: without them the 0.6B model degenerates
# into repeating one sentence (measured: "讲个笑话" got the exact same answer as
# the previous turn). DRY penalises repeated n-grams, which is the actual cure.
# Plain background (& + disown). Do NOT use nohup here: under Git Bash with a
# sandboxed shell, nohup'd children get reaped when the invoking call returns,
# whereas a disowned background job survives across tool calls.
"$LLAMA" -m "$MODEL" -c 4096 -t 12 --reasoning off \
    --dry-multiplier 0.8 --repeat-penalty 1.05 \
    --host 127.0.0.1 --port $PORT \
    > "$LOGDIR/llama_server.log" 2>&1 &
SRV_PID=$!
echo "llama-server pid=$SRV_PID"

echo "=== 2. wait for health ==="
for i in $(seq 1 60); do
    if curl -s --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q '"status"'; then
        echo "healthy after ${i}s"; break
    fi
    sleep 1
done
curl -s --max-time 5 "http://127.0.0.1:$PORT/health"; echo

echo "=== 3. start Open-LLM-VTuber backend ==="
disown $SRV_PID 2>/dev/null
cd "$PROJ" || exit 1
"$PROJ/.venv/Scripts/python.exe" -u run_server.py > "$LOGDIR/vtuber_server.log" 2>&1 &
VT_PID=$!
disown $VT_PID 2>/dev/null
echo "vtuber pid=$VT_PID"

echo "=== 4. wait then report ==="
for i in $(seq 1 90); do
    if netstat -ano 2>/dev/null | grep -q ":12393 .*LISTENING"; then
        echo "backend listening after ${i}s"; break
    fi
    sleep 1
done
sleep 3

echo "=== ports ==="
netstat -ano 2>/dev/null | grep -E ":(8099|12393) .*LISTENING"
echo "=== vtuber log tail ==="
tail -40 "$LOGDIR/vtuber_server.log"

echo
echo "=== ready ==="
echo "  llama-server :$PORT (pid $SRV_PID)   backend :12393 (pid $VT_PID)"
echo "  open http://localhost:12393 in Chrome/Edge (the built-in preview has no microphone)"
echo "  logs: $LOGDIR/llama_server.log , $LOGDIR/vtuber_server.log"
echo "  stop: bash $LOGDIR/stop_stack.sh"

if [ "$WAIT" = "1" ]; then
    echo
    echo "=== Ctrl+C to stop (this also shuts the stack down) ==="
    trap 'echo "stopping..."; taskkill //F //PID $SRV_PID //PID $VT_PID 2>/dev/null' INT TERM
    while true; do sleep 5; done
fi
