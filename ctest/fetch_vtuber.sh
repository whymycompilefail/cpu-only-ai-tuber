#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Fetch Open-LLM-VTuber into $ROOT/Open-LLM-VTuber
# Strategy: shallow git clone first; fall back to codeload tarball (proxy-safe).
cd $ROOT || exit 1

DEST=Open-LLM-VTuber
echo "=== start $(date +%H:%M:%S) ==="

if [ -d "$DEST/.git" ]; then
    echo "already cloned, pulling"
    cd "$DEST" && git pull --ff-only 2>&1 | tail -5
    echo "PULL_RC=$?"
    exit 0
fi

echo "--- attempt 1: shallow git clone"
git clone --depth 1 https://github.com/Open-LLM-VTuber/Open-LLM-VTuber.git "$DEST" 2>&1 | tail -10
RC=$?
echo "GIT_RC=$RC"

if [ $RC -ne 0 ] || [ ! -d "$DEST/.git" ]; then
    echo "--- git failed (proxy CONNECT?), attempt 2: codeload tarball"
    rm -rf "$DEST"
    curl -sSL -o vtuber.tar.gz \
        https://codeload.github.com/Open-LLM-VTuber/Open-LLM-VTuber/tar.gz/refs/heads/main 2>&1
    echo "CURL_RC=$?"
    ls -la vtuber.tar.gz
    tar xzf vtuber.tar.gz || { echo "TAR FAILED"; exit 1; }
    # tarball root is Open-LLM-VTuber-main
    [ -d Open-LLM-VTuber-main ] && mv Open-LLM-VTuber-main "$DEST"
    rm -f vtuber.tar.gz
    echo "TARBALL_OK"
fi

echo "=== result ==="
ls -la "$DEST" 2>&1 | head -25
echo "=== du ==="
du -sh "$DEST" 2>/dev/null
echo "=== done $(date +%H:%M:%S) ==="
