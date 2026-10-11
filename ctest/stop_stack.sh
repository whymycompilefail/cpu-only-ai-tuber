#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Shut the local VTuber stack down: llama-server, the backend, the danmaku
# bridge, and any llama-tts process the backend left resident.
set -u
LOGDIR="$ROOT/ctest"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"

for p in 8099 12393 "$BRIDGE_PORT"; do
    netstat -ano 2>/dev/null | grep ":$p .*LISTENING" | awk '{print $5}' | sort -u | while read -r pid; do
        echo "killing pid $pid (:$p)"
        taskkill //F //PID "$pid" 2>&1 | head -2
    done
done

# llama-tts is spawned by the backend and holds no port, so kill it by name
tasklist //FI "IMAGENAME eq llama-tts.exe" 2>/dev/null | grep -q "llama-tts" && {
    echo "killing resident llama-tts"
    taskkill //F //IM llama-tts.exe 2>&1 | head -2
}

sleep 1
echo "--- remaining ---"
netstat -ano 2>/dev/null | grep -E ":(8099|12393|$BRIDGE_PORT) .*LISTENING" || echo "stack down"
