"""Verify the TTS output is actually intelligible Chinese.

Feeds the generated wav back into the same SenseVoice ASR the stack uses for
the microphone. If ASR can read it, the whole chain (LLM Chinese text ->
Qwen3-TTS Chinese speech) really works.
"""

import glob
import os
import sys
import wave

MODEL_DIR = (ROOT + "/Open-LLM-VTuber/models/"
             r"sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")

import sherpa_onnx  # noqa: E402
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")


def read_wav(path):
    with wave.open(path, "rb") as f:
        assert f.getnchannels() == 1, f"expected mono, got {f.getnchannels()}"
        samples = f.readframes(f.getnframes())
        rate = f.getframerate()
    import array
    a = array.array("h", samples)
    return [x / 32768.0 for x in a], rate


recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
    model=os.path.join(MODEL_DIR, "model.int8.onnx"),
    tokens=os.path.join(MODEL_DIR, "tokens.txt"),
    use_itn=True,
    num_threads=4,
)

files = sys.argv[1:] or sorted(glob.glob(ROOT + "/ctest/e2e_*.wav"))
for path in files:
    samples, rate = read_wav(path)
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, samples)
    recognizer.decode_stream(stream)
    print("%-28s %.2fs -> %s" % (os.path.basename(path),
                                 len(samples) / rate, stream.result.text))
