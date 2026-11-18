#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Qwen3-TTS length-scaling experiment:
#   is the "vocoder" cost FIXED (amortisable) or PROPORTIONAL to audio length?
# model is 12.5 Hz -> audio_s = frames / 12.5
LLAMA_DIR="${LLAMA_DIR:-$ROOT/../cpu-afterburner/llama.cpp}"   # 唯一真源：cpu-afterburner 仓内
[ -d "$LLAMA_DIR/build/bin" ] || { echo "no llama build at $LLAMA_DIR/build/bin -- run ctest/build_llama.bat" >&2; exit 1; }
cd "$LLAMA_DIR" || exit 1
TTS=build/bin/llama-tts.exe
M="$ROOT/models/Qwen3-TTS-0.6B-q8_0.gguf"
MM="$ROOT/models/mmproj-Qwen3-TTS-0.6B-f16.gguf"

for th in 12 22; do
  for L in short med long; do
    echo "###### threads=$th  len=$L  $(date +%H:%M:%S)"
    timeout 300 $TTS -m $M -mm $MM -f ../ctest/tts_len_${L}.txt \
        --tts-lang zh -o ../ctest/tts_${L}_${th}.wav -t $th 2>&1 \
      | grep -E "generated|timings|output audio|frames"
    echo
  done
done
echo "ALL DONE $(date +%H:%M:%S)"
