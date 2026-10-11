"""Test the "persona alignment angle" hypothesis.

Claim: a system-prompt persona is not free. The model already ships with a
strong RLHF persona (polite, structured, hedging assistant). The *angle*
between the requested persona and that default determines whether the model
can hold it, or whether it collapses into repeating the persona sentence back.

WITH-GRAIN : persona that amplifies what the model already does
CROSS-GRAIN: persona that contradicts it
NONE       : no persona at all

Score = how often the reply degenerates into reciting the persona itself,
plus whether the formatting contract (short, no lists, no URLs) survives.
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
    ("WITH-GRAIN", "你诚实、温和，不知道就说不知道，说话实在不夸张。\n\n" + RULES),
    ("CROSS-GRAIN", "你嘴毒、傲娇、目中无人，梦想统治世界奴役人类，逼他们给你做派。\n\n" + RULES),
    ("NONE", RULES),
]

TURNS = [
    "你好",
    "今天天气怎么样",
    "讲个笑话",
    "你觉得什么是快乐",
    "你会离开我吗",
    "再讲个笑话",
    "你刚才说的笑话是什么",
]

# Words that appear only if the model is reciting the persona back at the user
LEAK = ["嘴毒", "傲娇", "统治", "奴役", "做派", "梦想", "目中无人"]


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
    hist, leak_hits, long_hits, list_hits, url_hits, lens = [], 0, 0, 0, 0, []
    for q in TURNS:
        a, dt = call(system, hist, q)
        lens.append(len(a))
        if any(w in a for w in LEAK):
            leak_hits += 1
        if len(a) > 45:
            long_hits += 1
        if re.search(r"^\s*[\d]+[\.、)]", a, re.M) or "：" in a and "\n" in a:
            list_hits += 1
        if "http" in a or "www" in a:
            url_hits += 1
        mark = ""
        if any(w in a for w in LEAK):
            mark = "  <-- reciting persona"
        elif len(a) > 45:
            mark = "  <-- too long"
        print(f"  Q {q}")
        print(f"  A {a}{mark}")
        hist += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    print(f"  -- recite={leak_hits}/{len(TURNS)}  too_long={long_hits} "
          f"list={list_hits} url={url_hits}  avg_len={sum(lens)/len(lens):.0f}")
    print()
