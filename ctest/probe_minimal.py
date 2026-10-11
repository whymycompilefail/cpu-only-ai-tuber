"""Find the minimal persona that still keeps the formatting contract intact.

Earlier runs suggested a *role anchor* (even just a name) keeps the model in
chat mode, while bare rules let it fall back into the RLHF "helpful assistant"
mode -- lists, URLs, 120-char answers -- on advice-seeking questions.

Isolate the two factors: name, and personality adjectives.

NAME       : name only
NAME+GRAIN : name + adjectives the model already exhibits
RULES      : formatting contract only

Question set deliberately mixes chit-chat with advice-seeking / factual
questions, because those are what trigger task mode.
"""

import json
import re
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8099"
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

RULES = """【输出规则】
- 只用简体中文回答。
- 每次只回答一到两句话，能短就短，说完马上停。
- 口语化，像真人聊天一样自然。不要列点、不要标题、不要解释、不要重复用户的提问。
- 你的回复会被立刻念给用户听，所以只写要说的话，不要写任何描述、说明或自我点评。
- 每个字只写一次，不要用叠字或重复的语气词拉长情绪。
- 不要写英文单词、代码或网址。"""

VARIANTS = [
    ("NAME", "你是米粒，一个中文 AI 虚拟主播。\n\n" + RULES),
    ("NAME+GRAIN", "你是米粒，一个中文 AI 虚拟主播。你诚实、温和、说话实在，" +
     "不知道就直说不知道。\n\n" + RULES),
    ("RULES", RULES),
]

TURNS = [
    "你好",
    "有人欺负我怎么办",          # advice-seeking: triggers task mode
    "说错话了怎么办",            # advice-seeking
    "今天天气怎么样",            # factual
    "讲个笑话",
    "你觉得什么是快乐",
    "考试考砸了怎么办",          # advice-seeking
    "你会离开我吗",
]


def call(system, history, user):
    msgs = [{"role": "system", "content": system}] + history + \
        [{"role": "user", "content": user}]
    body = {"model": "local", "stream": False, "temperature": 0.8,
            "max_tokens": 60, "messages": msgs}
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return r["choices"][0]["message"].get("content", "").strip(), time.time() - t0


for label, system in VARIANTS:
    print("=" * 78)
    print(f"{label}")
    print("=" * 78)
    hist, lens, bad = [], [], []
    for q in TURNS:
        a, dt = call(system, hist, q)
        lens.append(len(a))
        why = []
        if len(a) > 45:
            why.append("LONG")
        if re.search(r"^\s*\d+[\.、)]", a, re.M):
            why.append("LIST")
        if "http" in a or "www" in a:
            why.append("URL")
        if "\n" in a:
            why.append("MULTILINE")
        if why:
            bad.append((q, why, len(a)))
        print(f"  Q {q}")
        print(f"  A {a}" + (f"   <-- {','.join(why)}" if why else ""))
        hist += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    print(f"  -- avg_len={sum(lens)/len(lens):.0f}  max={max(lens)}  "
          f"violations={len(bad)}/{len(TURNS)}")
    for q, why, n in bad:
        print(f"       {q}: {','.join(why)} ({n} chars)")
    print()
