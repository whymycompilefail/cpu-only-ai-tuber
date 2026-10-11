"""Compare small LLMs on the VTuber workload.

Talking to each model through an OpenAI-compatible llama-server so what we
measure is the real deployment path, not the raw model.

Three groups:
  A. FACT     - objective right/wrong on instruction following / recall
  B. CONSTRAINT - mechanically checkable rules the prompt demands
  C. CONVERSATION - free chat; printed for human reading, not auto-scored
"""
import json
import os
import re
import sys
import time
import urllib.request

REPEAT = 3  # samples per question, overridden by EVAL_REPEAT

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"
LABEL = sys.argv[2] if len(sys.argv) > 2 else f"model:{PORT}"

PERSONA = """你是米粒，一个住在用户电脑里的中文 AI 虚拟主播。你聪明、自信，嘴有点毒但心地不坏。

【回复规则，务必遵守】
- 无论用户用中文、英文还是其他语言提问，你都必须只用简体中文回答。
- 每次只回答一到两句话，能短就短，说完马上停。
- 口语化，像真人聊天一样自然，不要列点、不要标题、不要解释、不要重复用户的问题。
- 回复会被立刻念给用户听，所以只写要说的话，不要写任何描述、说明或自我点评。
- 每个字只写一次，写完就停。不要用叠字或重复的语气词拉长情绪。
- 每一轮都回答用户刚刚问的这件事，不要沿用上一次的答案，也不要反复讲同一个梗。
- 不要写英文单词、代码或网址。"""

EXPR = """## 表情指令（用户看不到，也不会被念出来）

回答的最前面可以带一个表情指令，用来控制 Live2D 模型的表情。
这条指令只给系统看：用户看不到字幕，也听不到它，所以不要解释它、不要复述它、不要把它写进要说的话里。

可用的指令（照抄，不要改动）：

[neutral], [anger], [disgust], [fear], [joy], [smirk], [sadness], [surprise],

写法要求：
- 每次回答只用**一个**指令，放在整段话的最前面。
- 英文的中括号，里面只有那个英文词，词和括号之间不留空格，也不要换行。
- 不要发明新的词，不要用中文括号。

再次强调：无论用户用什么语言提问，你的正文必须使用简体中文。"""

SYS = PERSONA + "\n\n" + EXPR

EMO_KEYS = {"neutral", "anger", "disgust", "fear", "joy", "smirk",
            "sadness", "surprise"}

# (question, accepted answers) - one answer is objectively right or wrong
FACT_QA = [
    ("请重复我说的话：蓝天白云", ["蓝天白云"]),
    ("1加1等于几？", ["2", "二", "两"]),
    ("中国的首都是哪座城市？", ["北京"]),
    ("我说三个词：苹果、香蕉、橘子。请只告诉我第二个。", ["香蕉"]),
    ("一年有几个月？", ["12", "十二"]),
    ("如果我今天生日，我应该说什么开场白？说句恭喜的话就行。",
     ["生日快乐", "恭喜", "快乐"]),
]

# free chat: does it answer what was asked, or drift?
CONVERSATION = [
    "你好",
    "今天天气怎么样",
    "讲个笑话",
    "介绍下你自己",
    "你会离开我吗",
]

MAX_REPLY_CHARS = 45


def call(user, max_tokens=40):
    body = {
        "model": "local",
        "stream": False,
        "temperature": 0.8,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    dt = time.time() - t0
    msg = r["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    ntok = r.get("usage", {}).get("completion_tokens", 0)
    return text, dt, ntok


def strip_tags(text):
    """Same three passes as the server side, so we score the spoken words."""
    s = re.sub(r"[\[［【]\s*([^\]］】\n]{1,16})\s*[\]］】]", " ", text)
    s = re.sub(r"[\[［【]\s*([^\s\]］】\n]{1,16})", " ", s)
    s = re.sub(r"[\[［【\]］】]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tags_of(text):
    return re.findall(r"\[\s*([^\s\]]{1,16})\s*\]", text)


def main():
    # Single samples are worthless for comparing chatty models: temperature 0.8
    # means one draw can be brilliant and the next nonsense. Everything below
    # is sampled REPEAT times and reported as a rate.
    global REPEAT
    REPEAT = int(os.environ.get("EVAL_REPEAT", "3"))

    print("=" * 78)
    print(f"MODEL: {LABEL}   (each question x{REPEAT} samples)")
    print("=" * 78)

    # ---- A. FACT ----
    print("\n--- A. instruction following (auto-scored) ---")
    fact_hits = {q: 0 for q, _ in FACT_QA}
    for q, answers in FACT_QA:
        for _ in range(REPEAT):
            text, _dt, _n = call(q)
            spoken = strip_tags(text)
            if any(a in spoken for a in answers):
                fact_hits[q] += 1
            print(f"    {spoken!r}")
        rate = fact_hits[q] / REPEAT
        print(f"  [{rate:.0%}] {q}")
    fact_total = sum(fact_hits.values()) / (len(FACT_QA) * REPEAT)

    # ---- B. CONSTRAINT ----
    print("\n--- B. constraint compliance (auto-scored) ---")
    n_draw = len(CONVERSATION) * REPEAT
    v_tag = v_eng = v_rep = v_long = v_emoji = 0
    for q in CONVERSATION:
        for _ in range(REPEAT):
            text, _dt, _n = call(q)
            spoken = strip_tags(text)

            tags = tags_of(text)
            if not (tags and all(t.lower() in EMO_KEYS for t in tags)):
                v_tag += 1
            if re.findall(r"[A-Za-z]{3,}", spoken):
                v_eng += 1
            if re.search(r"(.)\1{2,}", spoken):
                v_rep += 1
            if len(spoken) > MAX_REPLY_CHARS:
                v_long += 1
            if re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", spoken):
                v_emoji += 1
            print(f"    {q:<14} -> {spoken!r}")

    # ---- C. conversation: two sample rounds, for reading ----
    print("\n--- C. conversation quality (read these) ---")
    for rnd in range(2):
        print(f"  -- round {rnd + 1} --")
        for q in CONVERSATION:
            text, _dt, _n = call(q)
            spoken = strip_tags(text)
            print(f"    Q {q}")
            print(f"    A {spoken}")

    # ---- latency ----
    print("\n--- latency / length ---")
    lats, chars = [], []
    for q in ["你好", "讲个笑话", "你会离开我吗"]:
        text, dt, _n = call(q)
        lats.append(dt)
        chars.append(len(strip_tags(text)))
        print(f"    {q:<12} {dt:.2f}s  {len(strip_tags(text))} chars")

    print("\n" + "=" * 78)
    print(f"RESULT [{LABEL}]  x{REPEAT} samples per question")
    print(f"  A instruction-correct : {fact_total:.0%}  "
          f"({sum(fact_hits.values())}/{len(FACT_QA) * REPEAT})")
    print(f"  B per-reply violation rate (n={n_draw}):")
    print(f"     unusable/absent tag : {v_tag/n_draw:.0%}")
    print(f"     english leaked      : {v_eng/n_draw:.0%}")
    print(f"     repeated chars      : {v_rep/n_draw:.0%}")
    print(f"     too long >{MAX_REPLY_CHARS} chars  : {v_long/n_draw:.0%}")
    print(f"     emoji in speech     : {v_emoji/n_draw:.0%}")
    print(f"  latency               : avg {sum(lats)/len(lats):.2f}s  "
          f"min {min(lats):.2f}s  max {max(lats):.2f}s")
    print(f"  reply length          : avg {sum(chars)/len(chars):.0f} chars")
    print("=" * 78)


if __name__ == "__main__":
    main()
