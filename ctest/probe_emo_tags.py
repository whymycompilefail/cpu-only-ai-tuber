"""Grab raw LLM output with the Live2D expression prompt enabled.

Goal: see exactly what shape emotion tags come out in, instead of guessing.
Then push each reply through the real pipeline (SentenceDivider -> tts_filter)
to find which stage lets a tag survive into the audio.
"""
import json
import sys
import time
import urllib.request

URL = "http://127.0.0.1:8099/v1/chat/completions"

PERSONA = """你是米粒，一个住在用户电脑里的中文 AI 虚拟主播。你聪明、自信、嘴有点毒但心地不坏。

【回复规则，务必遵守】
- 无论用户用中文、英文还是其他语言提问，你都必须只用简体中文回答。
- 每次只说一到两句话，说完立刻停。口语化，像真人聊天。
- 不要列点、不要标题、不要重复用户的提问。
- 回复会被立刻念给用户听，所以只写要说的话。
- 绝对不要输出连续重复的字，例如"哈哈哈""呵呵呵""哦哦哦"。"""

EXPR = """## 表情与动作
回答里用下列关键词表达情绪，每次回答都要用：
[neutral] [anger] [joy] [smirk] [sadness] [surprise]
只能使用上面列出的关键词。关键词必须带英文中括号，紧跟一个关键词本身，不要加空格。

## 示例
"[neutral] 你好呀，很高兴认识你。"
"[joy] 这个问题问得好！让我想想。"

注意：你的回答正文必须使用简体中文。"""

SYS = PERSONA + "\n\n" + EXPR

QUESTIONS = [
    "你好，介绍一下你自己",
    "今天天气怎么样",
    "讲个笑话",
    "你喜欢什么颜色",
    "你会离开我吗",
    "讲讲你最大的愿望",
]


def call(user):
    body = {
        "model": "qwen-local",
        "stream": False,
        "temperature": 0.8,
        "max_tokens": 40,
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
    r = json.loads(urllib.request.urlopen(req).read())
    dt = time.time() - t0
    return r["choices"][0]["message"].get("content") or "", dt


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else len(QUESTIONS)
    for q in QUESTIONS[:n]:
        text, dt = call(q)
        print("=" * 60)
        print("Q: %s  (%.2fs)" % (q, dt))
        print("RAW: %r" % text)
        # byte-level look at what actually sits inside / around brackets
        for i, ch in enumerate(text):
            if ch in "[]【】[]":
                print("     bracket %r at %d -> context %r"
                      % (ch, i, text[max(0, i - 2):i + 8]))


if __name__ == "__main__":
    main()
