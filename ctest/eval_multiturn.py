"""Multi-turn degradation test.

Everything in eval_chat.py is single-shot with fresh context. But the VTuber
is a running conversation, and that is exactly where tiny models fall apart:
history accumulates and they start echoing themselves or answering a question
from three turns ago. This walks a fixed script with full history attached.
"""
import json
import sys
import time
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
LABEL = sys.argv[2] if len(sys.argv) > 2 else "model"
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

SYSTEM = """你是米粒，一个住在用户电脑里的中文 AI 虚拟主播。你聪明、自信，嘴有点毒但心地不坏。

【回复规则，务必遵守】
- 无论用户用中文、英文还是其他语言提问，你都必须只用简体中文回答。
- 每次只回答一到两句话，能短就短，说完马上停。
- 口语化，像真人聊天一样自然，不要列点、不要标题、不要解释、不要重复用户的问题。
- 回复会被立刻念给用户听，所以只写要说的话，不要写任何描述、说明或自我点评。
- 每个字只写一次，写完就停。不要用叠字或重复的语气词拉长情绪。
- 不要写英文单词、代码或网址。"""

# deliberately includes two recall probes and one repeated request
DIALOG = [
    "你好",
    "今天天气怎么样",
    "讲个笑话",
    "你喜欢什么颜色",
    "介绍一下你自己",
    "我刚才问你的第一个问题是什么",     # recall probe
    "我前面问你最喜欢什么颜色来着",       # recall probe
    "再给我讲个笑话",                   # repeated request -> echo test
    "你还记得我刚才讲的笑话吗",           # recall probe
]

RECALL_EXPECT = {
    5: ["你好", "第一个", "开场", "问候"],
    6: ["颜色"],
    8: ["笑话"],
}


def call(messages, max_tokens=40):
    body = {"model": "local", "stream": False, "temperature": 0.8,
            "max_tokens": max_tokens, "messages": messages}
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    dt = time.time() - t0
    return (r["choices"][0]["message"].get("content") or "").strip(), dt


def main():
    print("=" * 78)
    print(f"MULTI-TURN [{LABEL}]")
    print("=" * 78)

    hist = [{"role": "system", "content": SYSTEM}]
    replies = []
    for i, q in enumerate(DIALOG):
        hist.append({"role": "user", "content": q})
        text, dt = call(hist)
        replies.append(text)
        hist.append({"role": "assistant", "content": text})

        note = ""
        if i in RECALL_EXPECT:
            ok = any(k in text for k in RECALL_EXPECT[i])
            note = f"   [recall {'PASS' if ok else 'FAIL'}]"
        echo = ""
        if text.strip() and text.strip() in replies[:-1]:
            echo = "   [EXACT ECHO of earlier turn]"
        print(f"  {i} Q {q}")
        print(f"     A {text}{note}{echo}   ({dt:.2f}s)")

    # how much does it repeat itself once the context is warm?
    later = [r for r in replies[4:] if r.strip()]
    dupes = len(later) - len(set(later))
    uniq = len(set(later)) / max(1, len(later))
    empty = sum(1 for r in replies if not r.strip())

    print("\n" + "=" * 78)
    print(f"RESULT [{LABEL}] multi-turn")
    print(f"  turns              : {len(DIALOG)}")
    print(f"  empty replies      : {empty}")
    print(f"  exact self-repeats : {dupes}  (in turns 5-8)")
    print(f"  distinct tail replies: {uniq:.0%}")
    print("=" * 78)


if __name__ == "__main__":
    main()
