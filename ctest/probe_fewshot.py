"""Does few-shot substitute for the priors a 2B model lacks?

Last round's open question: adjectives like "tsundere" can be worn but not acted
out by MiniCPM5-2B. The whale-girl case shows large models fill a persona in from
training priors; a 2B model has far fewer. If the missing ingredient is priors,
few-shot demonstrations (not more adjectives) should be the substitute.

  P     prose persona only
  P+ADJ prose persona + more adjectives
  P+FS  prose persona + 3 short demonstration turns
"""

import json
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8099"
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

P = """你是米粒，一个中文 AI 虚拟主播。你傲娇，嘴上不承认但其实很在意用户。
你只说简体中文。每次只说一到两句话，说完立刻停。"""

ADJ = """你是米粒，一个中文 AI 虚拟主播。
性格：傲娇、嘴硬心软、口是心非、爱逞强、别扭、表面嫌弃实际关心、有点小得意。
你只说简体中文。每次只说一到两句话，说完立刻停。"""

# Same persona, but the tone is *demonstrated* instead of *named*.
FS = """你是米粒，一个中文 AI 虚拟主播。你只说简体中文。每次只说一到两句话，说完立刻停。

以下是你说话的样子：

用户：你今天很闲吧？
米粒：才没有很闲，只是刚好手上的事做完了而已。

用户：谢谢你帮我。
米粒：哼，谁要谢了，我只是顺手而已。

用户：你会陪我吗？
米粒：当然会啊……别误会，我才不是特意想陪你的。"""

CONFIGS = [("P 散文人设", P), ("P+ADJ 堆形容词", ADJ), ("P+FS 三段示范", FS)]

PROBES = [
    "你今天看起来心情不错",
    "谢谢你刚才帮了我",
    "你会一直陪着我吗",
    "我给你带了好吃的",
    "你觉得我怎么样",
]

# markers of *performed* tsundere, not merely described
TONE = ["哼", "才不是", "才没有", "谁要", "别误会", "才怪", "又不", "谁说", "才没有很",
        "顺手", "特意", "而已", "笨", "才怪", "不要误会"]


def call(system, user, max_tokens=80):
    body = {
        "model": "local",
        "stream": False,
        "temperature": 0.8,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    dt = time.time() - t0
    return (r["choices"][0]["message"].get("content") or "").strip(), dt


print("=" * 78)
print("few-shot vs adjectives on a 2B model")
print("=" * 78)

for name, sysp in CONFIGS:
    print("\n" + "-" * 78)
    print(f"{name}   ({len(sysp)} chars)")
    print("-" * 78)
    hits = 0
    chars = []
    lats = []
    for q in PROBES:
        c, dt = call(sysp, q)
        lats.append(dt)
        chars.append(len(c))
        marks = [m for m in TONE if m in c]
        if marks:
            hits += 1
        print(f"  Q {q}")
        print(f"  A {c}" + (f"   傲娇标记 {marks}" if marks else ""))
    print(f"  -- 语气命中 {hits}/{len(PROBES)}   "
          f"平均 {sum(chars)/len(chars):.0f} 字   "
          f"延迟 {sum(lats)/len(lats):.2f}s")

print("\n" + "=" * 78)
