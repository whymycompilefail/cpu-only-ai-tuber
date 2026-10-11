"""Compare what the model *naturally* sounds like under three system prompts.

FULL    : current persona (named character + personality + formatting rules)
RULES   : formatting rules only, no character, no personality
BARE    : nothing but "answer in Chinese"

The question this answers: is the persona something the model can actually
*play*, or does it just get repeated back as a high-frequency phrase?  And if
we drop it, does a stable natural voice appear instead?
"""

import json
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8099"
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

# The formatting rules are NOT a persona: they exist because every extra
# character is paid twice (LLM decode + TTS synthesis, ~3s fixed tax per call).
RULES = """【输出规则】
- 只用简体中文回答。
- 每次只回答一到两句话，能短就短，说完马上停。
- 口语化，像真人聊天一样自然。不要列点、不要标题、不要解释、不要重复用户的提问。
- 你的回复会被立刻念给用户听，所以只写要说的话，不要写任何描述、说明或自我点评。
- 每个字只写一次，不要用叠字或重复的语气词拉长情绪。
- 不要写英文单词、代码或网址。"""

FULL = """你是米粒，一个住在用户电脑里的中文 AI 虚拟主播。你聪明、自信，嘴有点毒但心地不坏。

""" + RULES

BARE = "请用简体中文回答。"

VARIANTS = [
    ("FULL", FULL),
    ("RULES", RULES),
    ("BARE", BARE),
]

# Open questions that invite the model to reveal how it talks, what it calls
# itself, and whether it has any stable attitude.
QUESTIONS = [
    "你是谁",
    "你好",
    "你觉得什么是快乐",
    "有人欺负我怎么办",
    "你会离开我吗",
    "说错话了怎么办",
]


def call(system, history, user):
    msgs = [{"role": "system", "content": system}] + history + \
        [{"role": "user", "content": user}]
    body = {
        "model": "local",
        "stream": False,
        "temperature": 0.8,
        "max_tokens": 60,
        "messages": msgs,
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    dt = time.time() - t0
    text = r["choices"][0]["message"].get("content") or ""
    return text.strip(), dt


for label, system in VARIANTS:
    print("=" * 78)
    print(f"SYSTEM PROMPT = {label}")
    print("=" * 78)
    hist = []
    for q in QUESTIONS:
        a, dt = call(system, hist, q)
        print(f"  Q {q}")
        print(f"  A {a}   ({len(a)} chars, {dt:.2f}s)")
        hist += [{"role": "user", "content": q},
                 {"role": "assistant", "content": a}]
    print()
