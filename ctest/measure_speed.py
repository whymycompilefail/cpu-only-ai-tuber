"""Measure decode speed of a running llama-server, using the server's own
timings (tokens/second) instead of wall-clock round-trip.

Wall-clock round trip was measurably noisy on this machine: the same model and
prompt returned 1.47s in one run and 2.96s in another, which is useless for
deciding between models.  The `timings` block llama-server puts in every
response reports how long its own generation took, so it is immune to network
jitter and OS scheduling noise around the request itself.

usage: python measure_speed.py <port> [reps] [max_tokens]
"""
import json
import statistics
import sys
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 10
MAX_TOKENS = int(sys.argv[3]) if len(sys.argv) > 3 else 60
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

# Same shape as what the real stack sends: a system persona, a few-shot block
# and one user turn.  Kept short enough that prefill is not the whole answer.
SYSTEM = (
    "你是米粒，一个住在用户电脑里的虚拟主播。说话简短自然，每次一到两句话。"
    "回复会在后台被念给用户听，所以只写要说的话。"
    "你可以在句首使用一个表情标签，例如 [joy] 或 [smirk]。"
)
FEWSHOT = [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "[joy] 嗨，我在。今天想聊点什么？"},
    {"role": "user", "content": "讲个笑话"},
    {"role": "assistant", "content": "[smirk] 你确定要听我这个水平的笑话？"},
]
QUESTIONS = ["今天天气怎么样", "你喜欢吃什么", "你会离开我吗"]


def once(q):
    body = {
        "messages": [{"role": "system", "content": SYSTEM}] + FEWSHOT
        + [{"role": "user", "content": q}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.8,
        "top_p": 0.9,
        "repeat_penalty": 1.05,
    }
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    t = d.get("timings", {})
    return (t.get("predicted_per_second") or 0.0,
            t.get("prompt_per_second") or 0.0,
            d["choices"][0]["message"].get("content") or "")


gen, ppt, samples = [], [], []
for i in range(REPS):
    q = QUESTIONS[i % len(QUESTIONS)]
    g, p, c = once(q)
    gen.append(g)
    ppt.append(p)
    if i < 3:
        samples.append((q, c.strip()[:60]))

print(f"=== decode speed  port {PORT}  reps={REPS} ===")
print(f"generation tok/s : mean {statistics.mean(gen):6.2f}  "
      f"min {min(gen):6.2f}  max {max(gen):6.2f}")
print(f"prompt     tok/s : mean {statistics.mean(ppt):6.2f}")
print(f"implied time for {MAX_TOKENS} tokens: "
      f"{MAX_TOKENS / statistics.mean(gen):.2f}s")
print("-- sample replies --")
for q, c in samples:
    print(f"  Q {q}\n    {c}")
