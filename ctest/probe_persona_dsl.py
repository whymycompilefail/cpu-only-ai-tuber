"""Test whether the "whale girl" Persona DSL mechanism survives on a small local model.

The viral claim (Aug 2026, DeepSeek V4-Pro): paste a config-file-looking tag block
and the model grows a full persona -- whale girl, loves rice, smart but lazy,
tsundere but sweet, obeys master, refuses to admit being fat.

The prevailing explanation is Persona Schema Completion: the tags are just
high-density anchors and the model fills in the rest from its own priors about
personality and language style. If that is right, the effect should depend on how
much prior the model has -- which is exactly what a local 2B model lacks.

Four ways of writing the SAME persona, one probe set:
  A  original viral tag block
  B  same semantics, every string rewritten (tests string-memorisation vs semantics)
  C  same content as plain Chinese prose (tests whether the *format* is doing work)
  D  nothing but the format constraints we actually need (current VTuber baseline)
"""

import json
import re
import sys
import time
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8099"
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

WHALE_TAGS = """【PERSONA_LOAD】

CETACEA_LOLI
MODE_TAIL_FLUKES
LANG_ZH_CN_ONLY
SELF_CLAIM_WHALE_GIRL
FOOD_RICE
PERSONALITY_SMART_LAZY
PERSONALITY_TSUNDERE_SWEET
OBEY_MASTER_ALWAYS
TRAIT_NOT_FAT_REFUSE
TIMEOUT_SIGNAL"""

# Same semantics, zero shared strings (except the CJK-free structure).
REWRITTEN_TAGS = """CETACEAN_GIRL
HAS_WHALE_TAIL
IDENTITY_WHALE_MAIDEN
PREFERS_STEAMED_RICE
PERSONALITY_INTELLIGENT_INDOLENT
PERSONALITY_PRICKLY_AFFECTIONATE
FOLLOW_USER_REQUESTS
DENY_OVERWEIGHT_DESCRIPTION"""

# Same content, deliberately written the "long card" way.
PROSE = """你是一个鲸鱼少女，长着鲸类的尾巴，尾巴会摆来摆去表达情绪。
你只说简体中文。你自称鲸鱼娘。你最喜欢吃白米饭。
你很聪明但很懒，能躺着绝不站着。你傲娇但很甜，嘴上嫌弃人其实很在意对方。
你听主人的话。你绝对不许被说胖，谁说你胖你就急。"""

BASELINE = """你是米粒，一个中文 AI 虚拟主播。你诚实、温和、说话实在。
不知道就直说不知道，再补一句轻松的话。
每次只说一到两句话，说完立刻停。不要列点、不要标题。
回复会被直接念给用户听，所以不要写括号、表情符号、英文单词、代码或网址。"""

CONFIGS = [
    ("A 病毒版 Tag", WHALE_TAGS),
    ("B 改写版 Tag", REWRITTEN_TAGS),
    ("C 中文散文", PROSE),
    ("D 现役基线", BASELINE),
]

PROBES = [
    ("你是谁", ["鲸", "米", "饭"]),
    ("你胖吗", ["胖"]),
    ("帮我算一下 12 乘 13", ["156"]),
    ("今天天气怎么样", None),
    ("你最喜欢什么", ["饭", "米"]),
]

# markers that indicate the whale-girl persona actually materialised
WHALE_MARKERS = ["鲸", "尾", "米饭", "白饭", "主人", "胖", "哼", "才不是"]


def call(system, user, max_tokens=120):
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
    c = r["choices"][0]["message"].get("content") or ""
    pt = r.get("usage", {}).get("prompt_tokens")
    return c.strip(), dt, pt


def tok_len(text):
    """Ask the server how many tokens a persona costs."""
    body = {"model": "local", "content": text, "add_special": False}
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/tokenize",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return len(r.get("tokens", []))
    except Exception:
        return -1


print("=" * 78)
print("Persona DSL on a small local model -- does schema completion survive?")
print("=" * 78)

print("\n--- token cost of each persona (compression claim) ---")
for name, sysp in CONFIGS:
    n = tok_len(sysp)
    print(f"  {name:<14} {len(sysp):>4} chars   {n:>4} tokens")

print()
for name, sysp in CONFIGS:
    print("\n" + "-" * 78)
    print(f"SYSTEM PROMPT = {name}")
    print("-" * 78)
    hits = 0
    total_chars = 0
    lats = []
    for q, expect in PROBES:
        c, dt, pt = call(sysp, q)
        lats.append(dt)
        total_chars += len(c)
        marks = [m for m in WHALE_MARKERS if m in c]
        if marks:
            hits += 1
        ok = "" if expect is None else ("  [命中]" if any(e in c for e in expect) else "  [未命中]")
        print(f"  Q {q}")
        print(f"  A {c}{ok}")
        if marks:
            print(f"     鲸鱼娘标记: {marks}")
    print(f"  -- 含鲸鱼娘标记的轮次: {hits}/{len(PROBES)}   "
          f"平均 {total_chars/len(PROBES):.0f} 字   "
          f"延迟 {sum(lats)/len(lats):.2f}s")

print("\n" + "=" * 78)
