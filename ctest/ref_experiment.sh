#!/usr/bin/env bash
# Does the speaker reference actually move the synthesised pitch, or does the
# clone pull every voice back to the model prior?
#
# The earlier "cloning lands in 237-294 Hz whatever reference is used" note was
# measured with ctest/f0.py (autocorrelation), which we later found reads low and
# unstable on real speech (it reported 294 Hz where pyin reported 328 Hz on the
# same file). So re-run the whole thing under one ruler: librosa.pyin.
#
# Every run uses the same sentence, same seed, same token budget, so the only
# variable is --tts-speaker-file.
set -u
BIN=./llama.cpp/build/bin/llama-tts.exe
M=models/Qwen3-TTS-0.6B-f16.gguf
MM=models/mmproj-Qwen3-TTS-0.6B-f16.gguf
OUT=ctest/voice_ab/refscan
mkdir -p "$OUT"
TEXT="今天天气真不错呀，我们出去玩吧。"

run() {  # name, ref-or-empty
  local name="$1"; local ref="$2"
  local args=(-m "$M" -mm "$MM" --tts-lang zh -t 12 -n 96 -s 1
              -o "$OUT/$name.wav" -p "$TEXT")
  [ -n "$ref" ] && args+=(--tts-speaker-file "$ref")
  "$BIN" "${args[@]}" >/dev/null 2>&1
  echo "$name done"
}

run out_noref     ""
run out_spk1      "models/speaker_refs/spk_1.wav"
run out_spk2      "models/speaker_refs/spk_2.wav"
run out_xy_one    "ctest/voice_ab/refs/ref_xy_one.wav"
run out_xy_all    "ctest/voice_ab/refs/ref_xy_all.wav"
run out_spk1_p3   "ctest/voice_ab/refs/ref_spk1_p3.wav"
echo ALLDONE
