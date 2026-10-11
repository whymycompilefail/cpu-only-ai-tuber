"""Unit tests for the control-token stripper.

The old path relied on `tts_preprocessor.filter_brackets`, which counts bracket
depth: one unclosed `[` and the whole rest of the sentence disappeared. These
cases pin down that behaviour is now safe.
"""
import sys

sys.path.insert(0, ROOT + "/Open-LLM-VTuber/src")

from open_llm_vtuber.agent.transformers import strip_control_tokens  # noqa: E402
from open_llm_vtuber.utils.tts_preprocessor import filter_brackets  # noqa: E402
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

CASES = [
    ("[smirk] 你好呀", "你好呀", ["smirk"]),
    ("[neutral] 今天阳光很好。", "今天阳光很好。", ["neutral"]),
    ("[ neutral ] 你好", "你好", ["neutral"]),
    ("【开心】你好", "你好", ["开心"]),
    # unclosed: the tag must go, the sentence must survive
    ("[smirk 你好呀，很高兴认识你。", "你好呀，很高兴认识你。", ["smirk"]),
    # two tokens in one sentence
    ("[joy] 好呀。[sadness] 不过有点累。", "好呀。 不过有点累。", ["joy", "sadness"]),
    # stray closing bracket only
    ("你好] 世界", "你好 世界", []),
    # token in the middle, not just the front
    ("你好呀 [smirk] 很高兴认识你。", "你好呀 很高兴认识你。", ["smirk"]),
    # model echoing the instruction list verbatim (worst case)
    ("[neutral] [anger] [joy] 我不该念出来", "我不该念出来",
     ["neutral", "anger", "joy"]),
    # no token at all: untouched
    ("今天天气不错。", "今天天气不错。", []),
    # repeats that used to stall the vocoder keep their text intact
    ("[fun] 我[= mm] 呃。", "我 呃。", ["fun", "= mm"]),
    # emoji are decoration, not speech (Qwen3.5-2B adds them ~7% of the time)
    ("晴天 ☀️", "晴天", []),
    ("[joy] 今天阳光正好 🌞 出门走走吧", "今天阳光正好 出门走走吧", ["joy"]),
    ("恭喜🎉🎉🎊", "恭喜", []),
    ("→往左走⬅️", "往左走", []),
]

failed = 0
for text, want_text, want_tokens in CASES:
    got_text, got_tokens = strip_control_tokens(text)
    ok = got_text == want_text and got_tokens == want_tokens
    status = "ok  " if ok else "FAIL"
    if not ok:
        failed += 1
    old = filter_brackets(text)
    print(f"{status} {text!r}")
    print(f"      strip_tokens -> {got_text!r}  tokens={got_tokens}")
    if not ok:
        print(f"      EXPECTED      -> {want_text!r}  tokens={want_tokens}")
    if old != got_text:
        print(f"      old filter_brackets would have produced {old!r}")

print()
print(f"{len(CASES) - failed}/{len(CASES)} passed")
sys.exit(1 if failed else 0)
