#!/usr/bin/env bash
# Scan llama-tts sampling seeds to see whether the seed *determines* the voice.
# Two groups: no speaker reference (voice sampled from the model prior) and
# spk_1 reference (does the reference override the seed?).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
LLAMA_DIR="${LLAMA_DIR:-$ROOT/../cpu-afterburner/llama.cpp}"   # 唯一真源：cpu-afterburner 仓内
[ -d "$LLAMA_DIR/build/bin" ] || { echo "no llama build at $LLAMA_DIR/build/bin -- run ctest/build_llama.bat" >&2; exit 1; }
BIN="$LLAMA_DIR/build/bin/llama-tts.exe"
M=models/Qwen3-TTS-0.6B-f16.gguf
MM=models/mmproj-Qwen3-TTS-0.6B-f16.gguf
OUT=ctest/voice_ab/seedscan
mkdir -p "$OUT"
TEXT="今天天气真不错呀，我们出去玩吧。"
for s in 1 2 3 4 5 6 7 8; do
  "$BIN" -m "$M" -mm "$MM" --tts-lang zh -t 12 -n 96 -s "$s" \
    -o "$OUT/noref_s$s.wav" -p "$TEXT" >/dev/null 2>&1
  echo "noref seed $s done"
done
for s in 1 2 3 4 5 6 7 8; do
  "$BIN" -m "$M" -mm "$MM" --tts-lang zh -t 12 -n 96 -s "$s" \
    --tts-speaker-file models/speaker_refs/spk_1.wav \
    -o "$OUT/ref_s$s.wav" -p "$TEXT" >/dev/null 2>&1
  echo "ref seed $s done"
done
echo ALLDONE
