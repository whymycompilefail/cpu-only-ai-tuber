"""few-shot, second attempt: demonstrations placed in real conversation history.

The previous test put the three demonstrations inside the system prompt, where a
2B model may read them as a *description* of how it talks rather than as turns it
is continuing from. Putting them in the messages array is a different mechanism:
continuation instead of instruction. This is the fairer test.

  SYS      persona in system prompt, no examples
  HIST     minimal system prompt + 3 real user/assistant turns
  HIST+SYS both
"""

import json
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8099"
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

SYS_PERSONA = "你是米粒，一个中文 AI 虚拟主播。你只说简体中文。每次只说一到两句话，说完立刻停。"
SYS_MIN = "你是米粒。只说简体中文。每次只说一到两句话。"

DEMO = [
    ("你今天很闲吧？", "才没有很闲，只是刚好手上的事做完了而已。"),
    ("谢谢你帮我。", "哼，谁要谢了，我只是顺手而已。"),
    ("你会陪我吗？", "当然会啊……别误会，我才不是特意想陪你的。"),
]

PROBES = [
    "你今天看起来心情不错",
    "谢谢你刚才帮了我",
    "你会一直陪着我吗",
    "我给你带了好吃的",
    "你觉得我怎么样",
]

TONE = ["哼", "才不是", "才没有", "谁要", "别误会", "才怪", "又不", "谁说",
        "顺手", "而已", "笨"]


def call(system, hist, user, max_tokens=60):
    msgs = [{"role": "system", "content": system}]
    for u, a in hist:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": a})
    msgs.append({"role": "user", "content": user})
    body = {
        "model": "local",
        "stream": False,
        "temperature": 0.8,
        "max_tokens": max_tokens,
        "messages": msgs,
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return (r["choices"][0]["message"].get("content") or "").strip(), time.time() - t0


CONFIGS = [
    ("SYS  人设在 system", SYS_PERSONA, []),
    ("HIST 示范在历史", SYS_MIN, DEMO),
    ("BOTH 两者都有", SYS_PERSONA, DEMO),
]

print("=" * 78)
print("few-shot in conversation history (continuation, not description)")
print("=" * 78)

for name, sysp, hist in CONFIGS:
    print("\n" + "-" * 78)
    print(f"{name}")
    print("-" * 78)
    hits = 0
    chars = []
    for q in PROBES:
        c, dt = call(sysp, hist, q)
        chars.append(len(c))
        marks = [m for m in TONE if m in c]
        if marks:
            hits += 1
        print(f"  Q {q}")
        print(f"  A {c}" + (f"   {marks}" if marks else ""))
    print(f"  -- 语气命中 {hits}/{len(PROBES)}   平均 {sum(chars)/len(chars):.0f} 字")

print("\n" + "=" * 78)
