#!/usr/bin/env python3
"""Unit tests for the danmaku filter in danmaku_bridge.py.

These decide what the AI actually says on stream, so they are worth pinning:
a filter bug here is not a crash, it is the AI reading "66666" out loud and
burning 7 seconds of TTS on it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NO_PROXY", "*")

from danmaku_bridge import Danmaku, normalize, score  # noqa: E402

CHAR = "米粒"

# (text, kind, should_be_kept)
CASES = [
    # --- must be dropped: no information, or actively harmful to read aloud ---
    ("", "chat", False),
    ("1", "chat", False),
    ("哈", "chat", False),
    ("哈哈哈哈哈", "chat", False),
    ("66666", "chat", False),
    ("666", "chat", False),
    ("！！！！！", "chat", False),
    ("awsl", "chat", True),          # real slang, keep
    ("https://example.com/x", "chat", False),
    ("来看看 www.bilibili.com", "chat", False),
    ("。。。。。", "chat", False),

    # --- must be kept: questions, name-calls, substance ---
    ("你好呀", "chat", True),
    ("米粒你会唱歌吗", "chat", True),
    ("今天天气怎么样？", "chat", True),
    ("主播用的什么显卡", "chat", True),
    ("讲个笑话吧", "chat", True),

    # --- paid events always win ---
    ("辣条", "gift", True),
    ("舰长", "guard", True),
    ("老板大气", "superchat", True),
]


def main() -> int:
    failed = 0
    for text, kind, keep in CASES:
        d = Danmaku(user="viewer", text=text, kind=kind)
        s = score(d, CHAR)
        got = s > 0
        ok = got == keep
        if not ok:
            failed += 1
        print(f"[{'ok  ' if ok else 'FAIL'}] {text!r:<28} kind={kind:<9} "
              f"score={s:<4} -> {'keep' if got else 'drop'}")

    # ranking: gift beats question beats chatter
    g = score(Danmaku(user="a", text="一个辣条", kind="gift"), CHAR)
    q = score(Danmaku(user="a", text="米粒你几岁了？"), CHAR)
    c = score(Danmaku(user="a", text="来了来了"), CHAR)
    print(f"\nranking: gift={g} named_question={q} chatter={c}")
    if not (g > q > c):
        failed += 1
        print("[FAIL] ranking order broken")
    else:
        print("[ok  ] ranking order: gift > named question > chatter")

    # dedup normalisation: repeated chars must collapse
    print()
    for a, b in [("哈哈哈", "哈哈哈哈哈"),
                 ("你好 你好", "你好你好"),
                 ("6666", "66666666")]:
        same = normalize(a) == normalize(b)
        print(f"[{'ok  ' if same else 'FAIL'}] normalize {a!r} == {b!r} "
              f"-> {normalize(a)!r}")
        if not same:
            failed += 1

    print(f"\n{'ALL PASS' if failed == 0 else str(failed) + ' FAILURE(S)'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
