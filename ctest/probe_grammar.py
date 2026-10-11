"""Does grammar-constrained decoding actually fix the malformed-tag problem?

Last round we wrote three regex passes to clean up `[smirk` (unclosed),
`【开心】` (full-width) and invented keys. That is *post-hoc repair*.

A GBNF grammar instead forbids the malformed token at sampling time: the
model physically cannot emit it. Compare the two on the same model.
"""

import json
import re
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8099"
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

EMO = ["neutral", "anger", "disgust", "fear", "joy", "smirk",
       "sadness", "surprise"]

# The whole reply must be: one bracketed emotion key, a space, then text that
# contains no brackets at all. Nothing else is expressible.
GRAMMAR = (
    'root ::= "[" emo "] " body\n'
    'emo ::= ' + ' | '.join(f'"{e}"' for e in EMO) + '\n'
    'body ::= [^\\x5B\\x5D]+'
)

SYS = ("你是米粒，一个中文 AI 虚拟主播。\n"
       "回答必须以一个英文中括号包裹的情绪词开头，后面空一格再写要说的话。\n"
       "可用情绪词：" + " ".join(EMO) + "\n"
       "只用简体中文，一到两句话，能短就短。")

QUESTIONS = ["你好", "讲个笑话", "你觉得什么是快乐", "你会离开我吗",
             "有人欺负我怎么办", "今天天气怎么样"]


def call(user, grammar=None):
    body = {"model": "local", "stream": False, "temperature": 0.8,
            "max_tokens": 60,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": user}]}
    if grammar:
        body["grammar"] = grammar
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    except Exception as e:
        return None, time.time() - t0, f"ERROR {e}"
    msg = r["choices"][0]["message"]
    return (msg.get("content") or "").strip(), time.time() - t0, ""


VALID = re.compile(r"^\[(" + "|".join(EMO) + r")\] (.*)$", re.S)

for label, gram in (("RAW (no grammar)", None), ("GBNF grammar", GRAMMAR)):
    print("=" * 78)
    print(label)
    print("=" * 78)
    ok = 0
    times = []
    for q in QUESTIONS:
        a, dt, err = call(q, gram)
        times.append(dt)
        if err:
            print(f"  Q {q}\n    {err}")
            continue
        m = VALID.match(a)
        ok += bool(m)
        verdict = "ok" if m else "MALFORMED"
        print(f"  Q {q}")
        print(f"  A {a!r}   [{verdict}]")
    print(f"  -- well-formed {ok}/{len(QUESTIONS)}   "
          f"avg {sum(times)/len(times):.2f}s")
    print()
