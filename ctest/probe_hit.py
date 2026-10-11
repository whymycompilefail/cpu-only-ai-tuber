#!/usr/bin/env python3
"""
命中率探针 —— 空闲时段预生成的可行性下界
================================================================================
测什么
    多轮对话中，助手说完一轮之后，用户下一句话有多大比例能被提前猜中。

为什么测
    §16.3 实测：常驻化之后一轮 14.7s 里 TTFT 只占 2.7%，剩下 97.3% 全是 decode。
    decode 撞的是带宽/反量化墙，主时间轴上已经挤不出来。空闲时段是唯一不在主
    时间轴上的算力。这个想法能不能成立，完全取决于命中率 p —— 而这个数目前是零。

判定模型（纠正 §16.4 的错误表述）
    §16.4 写的"用户等待 = TTFT + (N-k)/r，k = 预生成命中长度"是错的：预生成的是
    **助手的回复**，不是用户输入的前缀。所以收益是二元的，不是按 token 线性折算：

        命中   (概率 p)  : 回复已在手上，用户等待 ≈ prefill(用户输入) ≈ 0.36s
        未命中 (概率 1-p): 回到原路径，用户等待 = TTFT + N/r

        E[等待]  = p*T_hit + (1-p)*T_miss
        speedup  = T_miss / E[等待]

两个判据（必须并列，缺一不可）
    字面判据 LCP  : token 级最长公共前缀。严格下界。问题：用户说 "Can you expand
                    on that?" 和候选 "Tell me more about..." 是同一意图，LCP 却是 0
                    → 严重低估意图命中率。
    语义判据 COS  : char-4gram TF-IDF 余弦。宽松，更接近"意图是否匹配"。
    真实 p 落在两者之间，且更靠近 COS。所以两个都报，不拍板单一数字。

    另外设 S_rand（随机取 K 条 train 回复作候选）作对照：如果 S1 检索的 COS 分布
    和随机配对差不多，说明上下文检索根本没提取到信号 —— 那再多的候选也没用。

数据源硬约束（违反任意一条则本探针的结论无效）
    1. 必须真实人类多轮对话。用 LLM 生成的数据去测 LLM 的可预测性是循环论证。
       → OASST1 "ready" 子集 synthetic 字段全为 False，已核对（88838/88838）。
    2. 候选只能从 train split 构造，在 test split 上测。否则"自己命中自己"，
       命中率会虚高到毫无意义。
    3. 切分按对话树而非按消息，避免同一线程的消息跨 split 泄漏。
       例外：S2 的候选来自被测线程自身的 history，这不算泄漏（信息已在前文里）。

已知 caveat（不可消除，只能标注）
    OASST1 的 assistant 回复也是**人类**写的，而我们场景里 assistant 是 LLM。
    所以本探针测的是"真人对人类回复的反应"，作为"真人对 LLM 回复的反应"的代理，
    偏差方向未知。要消除它需要真人对 LLM 的对话日志（ShareGPT 类，本次未取到）。

用法
    python probe_hit.py --lang en [--folds 3] [--test-frac 0.25]
    python probe_hit.py --lang zh
"""

import argparse
import gzip
import json
import os
import sys
import zlib
import collections
import random
import re

import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

# ---------------------------------------------------------------- 常量

# §16 实测值（f16 模型 / t=12 / -fa 0 / q8K+f16V / ctx 6734，llama-server 两轮）
T_MISS = 0.391 + 200 / 13.9      # 未命中：TTFT 0.391s + 200 token @13.9 t/s
T_HIT = 0.36                     # 命中：只需 prefill 用户输入（~20 tok @17.8 ms/tok）

COSTH = 0.5                      # 语义命中阈值（同时报 0.3/0.5 两档）

DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "oasst1_ready.jsonl.gz")


def speedup(p):
    e = p * T_HIT + (1.0 - p) * T_MISS
    return T_MISS / e if e > 0 else float("inf")


# ---------------------------------------------------------------- 数据加载

def load_threads(path, lang):
    """把 OASST1 的树状消息重建成线性对话线程（每棵树走 rank==0 主路径）。"""
    trees = collections.defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if lang and d.get("lang") != lang:
                continue
            if d.get("synthetic"):
                continue                      # 硬约束 1：不要合成数据
            trees[d["message_tree_id"]].append(d)

    threads = []
    for tid, msgs in trees.items():
        by_parent = collections.defaultdict(list)
        roots = []
        for m in msgs:
            pid = m.get("parent_id")
            if pid is None:
                roots.append(m)
            else:
                by_parent[pid].append(m)
        if not roots:
            continue
        cur = roots[0]
        seq = [cur]
        for _ in range(200):                  # 防环
            kids = by_parent.get(cur["message_id"], [])
            if not kids:
                break
            kids.sort(key=lambda m: (m.get("rank") if m.get("rank") is not None else 999,
                                     str(m.get("created_date"))))
            cur = kids[0]
            seq.append(cur)
        if len(seq) >= 3:                     # 至少 p-a-p
            threads.append((tid, seq))
    return threads


# 创作型对话筛选：OASST1 整体是"众包任务型"对话（64% 是全新话题），
# 而预生成真正想服务的是"助手在帮你写东西、你不断要求改"的场景。
# 两者意图分布差别可能很大，所以单独切出来测，不要混在一起谈。
CREATIVE_PAT = re.compile(
    r"\b(write|story|poem|poetry|essay|creative|novel|character|scene|chapter|"
    r"dialogue|lyrics|screenplay|roleplay|imagine|continue the)\b", re.I)


def filter_creative(threads):
    out = []
    for tid, seq in threads:
        first = ""
        for m in seq:
            if m["role"] == "prompter":
                first = m["text"]
                break
        if CREATIVE_PAT.search(first):
            out.append((tid, seq))
    return out


def extract_boundaries(threads):
    """提取轮次边界：assistant 说完 -> 用户下一句。

    返回 [(tid, history, target, prev_prompter_text), ...]
    prev_prompter 是本边界之前该线程里最近一条用户发言 —— 它在 history 里，
    所以对 S2 而言使用它不构成泄漏。
    """
    out = []
    for tid, seq in threads:
        for i in range(len(seq)):
            if seq[i]["role"] != "assistant":
                continue
            if i + 1 >= len(seq) or seq[i + 1]["role"] != "prompter":
                continue
            hist = "\n".join(m["text"] for m in seq[: i + 1])
            prev = ""
            for m in reversed(seq[: i + 1]):          # 最近一条 prompter（不含 target）
                if m["role"] == "prompter":
                    prev = m["text"]
                    break
            out.append((tid, hist, seq[i + 1]["text"], prev))
    return out


# ---------------------------------------------------------------- tokenizer

class Tok:
    def __init__(self, model_dir):
        from transformers import AutoTokenizer
        self.t = AutoTokenizer.from_pretrained(model_dir)

    def enc(self, texts):
        return [ids for ids in self.t(texts, add_special_tokens=False)["input_ids"]]

    def enc1(self, s):
        return self.t(s, add_special_tokens=False)["input_ids"]

    def dec(self, ids):
        return self.t.decode(ids)


def lcp(a, b):
    m = min(len(a), len(b))
    i = 0
    while i < m and a[i] == b[i]:
        i += 1
    return i


# ---------------------------------------------------------------- 特征

def _grams(text, n=4):
    t = text.lower()
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def build_matrix(texts, D=4096, n=4):
    M = np.zeros((len(texts), D), dtype=np.float32)
    df = np.zeros(D, dtype=np.float32)
    for r, t in enumerate(texts):
        g = _grams(t, n)
        if not g:
            continue
        idx = np.fromiter((zlib.crc32(x.encode("utf-8")) % D for x in g), dtype=np.int64)
        M[r, idx] = 1.0
        df[idx] += 1.0
    return M, df


def apply_idf(M, df, n_docs):
    idf = np.log((1.0 + n_docs) / (1.0 + df)).astype(np.float32)
    M = M * idf
    nrm = np.linalg.norm(M, axis=1, keepdims=True)
    nrm[nrm == 0] = 1.0
    return (M / nrm).astype(np.float32)


# ---------------------------------------------------------------- 候选池

class Pool:
    """候选池：文本去重 -> 索引。避免重复 tokenize / 重复建向量。"""
    def __init__(self):
        self.texts = []
        self.toks = []
        self.idx = {}

    def add(self, text, toks):
        if text in self.idx:
            return self.idx[text]
        i = len(self.texts)
        self.texts.append(text)
        self.toks.append(toks)
        self.idx[text] = i
        return i


# ---------------------------------------------------------------- 策略

def strat_freq(pool, tok, tr_tok, K, W=8):
    """S0 无条件高频前缀：用户开口有多套路。完全不看上下文。

    注意：池里存的是 decode 回的真实文本（不是 token id 串），否则语义判据
    会对着 "9707 1879" 这种字符串算 n-gram，毫无意义。"""
    c = collections.Counter(tuple(t[:W]) for t in tr_tok)
    ids = []
    for p, _ in c.most_common(K):
        ids.append(pool.add(tok.dec(list(p)), list(p)))
    return ids                        # 所有 test 共享同一组候选


def strat_firsttok(pool, tok, tr_tok, K):
    c = collections.Counter(t[0] for t in tr_tok if t)
    ids = [pool.add(tok.dec([t0]), [t0]) for t0, _ in c.most_common(K)]
    return ids


def strat_knn(Xtr, Xte, K):
    """S1 上下文检索：相似历史下，真实用户说了什么。返回每行 K 个 train 索引。"""
    out = []
    B = 256
    for s in range(0, Xte.shape[0], B):
        sims = Xte[s:s + B] @ Xtr.T
        for r in range(sims.shape[0]):
            K_ = min(K, sims.shape[1])
            top = np.argpartition(-sims[r], K_ - 1)[:K_]
            top = top[np.argsort(-sims[r][top])]
            out.append([int(j) for j in top])
    return out


# ---------------------------------------------------------------- 判据校准

# 已知语义等价的句对（同一意图的不同表达）。判据若连这些都认不出来，
# 那它给出的低分只能证明判据无效，不能证明"意图不可预测"。
POS_PAIRS = [
    ("Can you expand on that?", "Tell me more about this."),
    ("Explain it in more detail.", "Can you elaborate on that?"),
    ("Give me an example.", "Can you show me an example of this?"),
    ("Make it shorter.", "Can you summarize that more briefly?"),
    ("Continue writing.", "Please go on with the story."),
    ("Why is that the case?", "What is the reason for that?"),
    ("Translate this into French.", "Can you put this in French?"),
    ("That's wrong, fix it.", "There is an error, please correct it."),
    ("Write a poem about the sea.", "Compose a poem about the ocean."),
    ("Thanks, that helps.", "Thank you, this was useful."),
    ("What are the main causes?", "List the primary reasons."),
    ("Can you write code for this?", "Give me a python script that does this."),
    ("Simplify the explanation.", "Explain it in simpler terms."),
    ("Summarize the text.", "Give me a short summary."),
    ("How does this work?", "Can you explain how it works?"),
    ("Do it again.", "Please repeat that."),
    ("Make it more formal.", "Rewrite this in a formal tone."),
    ("What do you mean?", "Could you clarify what you meant?"),
]


def calibrate():
    """检验语义判据本身有没有区分度。

    正例 = 上面手工列的同义句对；负例 = 错位配对（不同意图）。
    AUC = P(cos(正例) > cos(负例))。0.5 = 判据毫无区分度；>0.9 才算可用。
    """
    pos = [(a, b) for a, b in POS_PAIRS]
    n = len(pos)
    neg = [(pos[i][0], pos[(i + 1) % n][1]) for i in range(n)]

    texts = [x for p in pos + neg for x in p]
    M, df = build_matrix(texts)
    M = apply_idf(M, df, len(texts))

    # texts 顺序：pos 占前 2n 行，neg 占后 2n 行
    cp = np.array([float(M[2 * i] @ M[2 * i + 1]) for i in range(n)])
    cn = np.array([float(M[2 * n + 2 * i] @ M[2 * n + 2 * i + 1]) for i in range(n)])

    auc = float(np.mean([1.0 * (cp[i] > cn[j]) + 0.5 * (cp[i] == cn[j])
                         for i in range(n) for j in range(n)]))
    print()
    print("语义判据校准（char-4gram TF-IDF 余弦）")
    print(f"  同义句对   n={n}  cos: 均值 {cp.mean():.3f}  中位 {np.median(cp):.3f}  "
          f"min {cp.min():.3f}  max {cp.max():.3f}")
    print(f"  异义句对   n={n}  cos: 均值 {cn.mean():.3f}  中位 {np.median(cn):.3f}  "
          f"max {cn.max():.3f}")
    print(f"  AUC = {auc:.3f}   (0.5=无区分度, >0.9=判据可用)")
    if auc < 0.9:
        print("  !! 判据区分度不足：本探针的 P(cos) 列只能当参考，不能当结论。")
    return auc


# ---------------------------------------------------------------- 意图类别

# 预生成系统真正能覆盖的是"少数高频意图分支"，不是逐字匹配。
# 这里用词面规则分类，给出意图层面的覆盖率上界（假设意图识别完美）。
INTENT_RULES = [
    ("thanks/end", r"\b(thank|thanks|thx|appreciate|that'?s all|bye|goodbye|perfect|great)\b"),
    ("elaborate", r"\b(elaborate|expand|more detail|in depth|explain|tell me more|go into|clarify)\b"),
    ("example", r"\b(example|instance|illustrate|show me|demonstrate)\b"),
    ("continue", r"\b(continue|go on|keep going|carry on|proceed|next|again|repeat)\b"),
    ("rephrase", r"\b(rephrase|reword|simpl|shorter|longer|summar|brief|concise|rewrite|formal|tone)\b"),
    ("fix", r"\b(fix|correct|wrong|mistake|error|bug|inaccurate|incorrect)\b"),
    ("why", r"\b(why|reason|cause|how come)\b"),
    ("translate", r"\b(translate|french|spanish|german|chinese|japanese|russian|italian)\b"),
    ("code", r"\b(code|python|javascript|function|script|program|c\+\+|java|sql)\b"),
    ("newtopic", r"^\s*(what|who|when|where|how|write|create|make|generate|give|list|describe|can you|could you)\b"),
]


def classify(text):
    t = text.lower()
    for name, pat in INTENT_RULES:
        if re.search(pat, t):
            return name
    return "other"


# 哪些意图是"能提前把回复生成好"的。
#   pre  = 续写/改写/追问类：助手拿到就能产出一条确定回复 -> 可以预生成
#   weak = 依赖当前话题的具体内容（如"为什么"），预生成命中率低，或回复很短收益小
#   no   = 全新任务/无法归类的开放输入 -> 不可能预生成
# 把 no 类算进"覆盖上界"是自欺欺人，所以分开报。
PREDICTABLE = {
    "thanks/end": "weak",
    "elaborate": "pre",
    "example": "pre",
    "continue": "pre",
    "rephrase": "pre",
    "fix": "pre",
    "why": "weak",
    "translate": "pre",
    "code": "weak",
    "newtopic": "no",
    "other": "no",
}


def pool_matrix(pool):
    """对整个候选池建语义矩阵。索引与 pool.toks 对齐（evaluate_raw 按池索引取）。"""
    M, df = build_matrix(pool.texts)
    return apply_idf(M, df, max(1, len(pool.texts)))


def strat_rand(n_train, n_test, K, seed):
    rnd = random.Random(seed)
    return [[rnd.randrange(n_train) for _ in range(K)] for _ in range(n_test)]


# ---------------------------------------------------------------- 评估



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en")
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--model", default=ROOT + "/Qwen3-0.6B")
    ap.add_argument("--test-frac", type=float, default=0.25)
    ap.add_argument("--hist-chars", type=int, default=1200)
    ap.add_argument("--topk", default="1,4,16,32")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--subset", default="all", choices=["all", "creative"])
    args = ap.parse_args()

    print("=" * 92)
    print(f"命中率探针  lang={args.lang}  data={os.path.basename(args.data)}  folds={args.folds}")
    print("=" * 92)

    threads = load_threads(args.data, args.lang)
    if args.subset == "creative":
        threads = filter_creative(threads)
        print("子集: 创作型（首条用户发言命中 write/story/poem/...）")
    bnd = extract_boundaries(threads)
    print(f"对话树 {len(threads)}   轮次边界 {len(bnd)}")
    if len(bnd) < 50:
        print("!! 边界数过少，结论不可靠")
        if not bnd:
            return 1

    tok = Tok(args.model)
    ks_list = [int(x) for x in args.topk.split(",")]
    calibrate()

    agg = collections.defaultdict(lambda: collections.defaultdict(list))
    ntest = collections.defaultdict(list)
    mlen_all = []
    intent_all = collections.Counter()

    for fold in range(args.folds):
        seed = args.folds * 1000 + fold
        tids = sorted({b[0] for b in bnd})
        rnd = random.Random(seed)
        rnd.shuffle(tids)
        n_test = max(1, int(len(tids) * args.test_frac))
        test_set = set(tids[:n_test])
        train_b = [b for b in bnd if b[0] not in test_set]
        test_b = [b for b in bnd if b[0] in test_set]
        if args.limit:
            test_b = test_b[:args.limit]

        tr_tok = tok.enc([b[2] for b in train_b])
        te_tok = tok.enc([b[2] for b in test_b])
        tr_txt = [b[2] for b in train_b]
        mlen_all.append(np.array([len(t) for t in te_tok]))
        for b in test_b:
            intent_all[classify(b[2])] += 1

        htr = [b[1][-args.hist_chars:] for b in train_b]
        hte = [b[1][-args.hist_chars:] for b in test_b]
        Mtr, df = build_matrix(htr)
        Mtr = apply_idf(Mtr, df, len(htr))
        Mte, _ = build_matrix(hte)
        Mte = apply_idf(Mte, df, len(htr))

        # target 语义矩阵（train 候选池 / test 目标）
        ttr, dft = build_matrix(tr_txt)
        ttr = apply_idf(ttr, dft, len(tr_txt))
        tte, _ = build_matrix([b[2] for b in test_b])
        tte = apply_idf(tte, dft, len(tr_txt))

        pool = Pool()
        rows = []

        # ---- 自检
        oracle_ids = []
        for r in range(len(te_tok)):
            oracle_ids.append([pool.add("__oracle_%d" % r, te_tok[r])])
        # oracle 的语义向量：用真值自身文本
        oracle_mat = np.vstack([tte, ttr]) if False else None
        rows.append(("S3 oracle (自检=100%)",
                     evaluate_raw(oracle_ids, pool.toks, None, te_tok, tte, tte)))
        rows.append(("Snull 空候选 (自检=0%)",
                     evaluate_raw([[] for _ in te_tok], pool.toks, None, te_tok, tte)))

        # ---- S1 / Srand（候选 = train 真实回复，池矩阵 = ttr，toks = tr_tok）
        for K in ks_list:
            rows.append((f"S1  上下文检索 K={K}",
                         evaluate_raw(strat_knn(Mtr, Mte, K), tr_tok, ttr, te_tok, tte)))
        for K in ks_list:
            rows.append((f"Srand 随机候选 K={K}",
                         evaluate_raw(strat_rand(len(tr_tok), len(te_tok), K, seed),
                                      tr_tok, ttr, te_tok, tte)))

        # ---- S0 / S0b / S2（自建池）
        p2 = Pool()
        for K in ks_list:
            ids = strat_freq(p2, tok, tr_tok, K)
            p2_mat = pool_matrix(p2)
            rows.append((f"S0  高频前缀   K={K}",
                         evaluate_raw([ids] * len(te_tok), p2.toks, p2_mat, te_tok, tte)))
        for K in ks_list:
            ids = strat_firsttok(p2, tok, tr_tok, K)
            p2_mat = pool_matrix(p2)
            rows.append((f"S0b 首token    K={K}",
                         evaluate_raw([ids] * len(te_tok), p2.toks, p2_mat, te_tok, tte)))
        # S2 复读：候选 = 本线程该边界之前最近一条用户发言
        ids_per_row = []
        for b in test_b:
            if b[3]:
                ids_per_row.append([p2.add("__prev_%d" % len(p2.texts), tok.enc1(b[3]))])
            else:
                ids_per_row.append([])
        if any(ids_per_row):
            p2_mat = pool_matrix(p2)
            rows.append(("S2  复读上一条提问",
                         evaluate_raw(ids_per_row, p2.toks, p2_mat, te_tok, tte)))

        for name, r in rows:
            for k, v in r.items():
                if isinstance(v, float):
                    agg[name][k].append(v)
            ntest[name].append(len(te_tok))
        print(f"  fold {fold}: train {len(train_b)}  test {len(test_b)}")

    # ---- 汇总
    thr = [1, 2, 4, 8, 16, 32]
    print()
    hdr = (f"{'策略':<22}{'n':>6}"
           + "".join(f"P(>={w})".rjust(9) for w in thr)
           + f"{'P(full)':>9}{'E[k]':>7}{'E[cos]':>8}{'P(c≥.3)':>9}{'P(c≥.5)':>9}"
             f"{'加速@L4':>9}{'加速@c.5':>9}")
    print(hdr)
    print("-" * len(hdr))

    def fmt(name):
        d = agg[name]
        n = int(np.mean(ntest[name]))
        if not d:
            return
        line = f"{name:<22}{n:>6}"
        for w in thr:
            line += f"{np.mean(d[f'P(>={w})'])*100:>8.1f}%"
        line += f"{np.mean(d['P(full)'])*100:>8.1f}%"
        line += f"{np.mean(d['E[k]']):>7.2f}{np.mean(d['E[cos]']):>8.3f}"
        line += f"{np.mean(d['P(cos>=.3)'])*100:>8.1f}%{np.mean(d['P(cos>=.5)'])*100:>8.1f}%"
        line += f"{speedup(np.mean(d['P(>=4)'])):>9.2f}x"
        line += f"{speedup(np.mean(d['P(cos>=.5)'])):>9.2f}x"
        print(line)

    order = ["S3 oracle (自检=100%)", "Snull 空候选 (自检=0%)"]
    order += [f"S1  上下文检索 K={K}" for K in ks_list]
    order += [f"Srand 随机候选 K={K}" for K in ks_list]
    order += [f"S0  高频前缀   K={K}" for K in ks_list]
    order += [f"S0b 首token    K={K}" for K in ks_list]
    order += ["S2  复读上一条提问"]
    for nm in order:
        if nm in agg:
            fmt(nm)

    ml = np.concatenate(mlen_all)
    print()
    print(f"用户下一句长度(token): 均值 {ml.mean():.1f}  中位 {np.median(ml):.0f}  "
          f"p90 {np.percentile(ml,90):.0f}  max {ml.max()}   n={len(ml)}")
    print(f"加速比: speedup = T_miss / (p*T_hit + (1-p)*T_miss), "
          f"T_miss={T_MISS:.2f}s T_hit={T_HIT:.2f}s (§16 实测)")
    print("两列加速 = 字面判据 P(LCP>=4) 与语义判据 P(cos>=0.5) 分别代入 p。"
          "真实 p 在两者之间。")

    tot = sum(intent_all.values())
    print()
    if args.lang != "en":
        print("!! 意图规则是英文正则，对非英文语料无效 —— 下面的意图分布作废。")
        print("!! 只有上面的 LCP / cos 列（语言无关）可用。")
        return 0
    print("意图类别分布（pre=可预生成 / weak=依赖上下文或收益小 / no=全新任务，不可能预生成）")
    cum = 0
    cnt = collections.Counter()
    for name, c in intent_all.most_common():
        cum += c
        cnt[PREDICTABLE.get(name, "no")] += c
        print(f"  {name:<12}{c:>6}  {c/tot*100:>5.1f}%  累计 {cum/tot*100:>5.1f}%  "
              f"[{PREDICTABLE.get(name,'no')}]")
    p_pre = cnt["pre"] / tot
    p_weak = cnt["weak"] / tot
    print()
    print(f"  可预生成(pre)  {p_pre*100:>5.1f}%  -> 加速上界 {speedup(p_pre):.2f}x")
    print(f"  含 weak        {(p_pre+p_weak)*100:>5.1f}%  -> 加速上界 {speedup(p_pre+p_weak):.2f}x")
    print(f"  不可能(no)     {cnt['no']/tot*100:>5.1f}%")
    print("  上界性质：假设意图识别完美 + 每个分支只需一条预生成回复 + 预生成内容用户真会要。")
    print("  真实值只会更低。这是天花板，不是预测。")
    return 0


def evaluate_raw(cand_ids, pool_toks, pool_mat, te_tok, te_mat,
                 oracle_mat=None, thresholds=(1, 2, 4, 8, 16, 32)):
    """cand_ids: 每行一组索引；pool_toks/pool_mat 为该索引空间的 token 与向量。
       oracle_mat: 若给出，则语义相似度用它与 te_mat 逐行对应（自检用）。"""
    n = len(te_tok)
    ks = np.zeros(n, dtype=np.int64)
    cs = np.zeros(n, dtype=np.float32)

    if oracle_mat is not None:
        cs[:] = np.sum(te_mat * oracle_mat, axis=1)

    shared = (len(cand_ids) == 1 and n > 1)
    if shared:
        ids = cand_ids[0]
        if not ids:
            pass
        else:
            if pool_mat is not None:
                cs = (te_mat @ pool_mat[ids].T).max(axis=1)
            pt = [pool_toks[i] for i in ids]
            for r in range(n):
                best = 0
                for c in pt:
                    v = lcp(c, te_tok[r])
                    if v > best:
                        best = v
                ks[r] = best
    else:
        for r in range(n):
            ids = cand_ids[r]
            if not ids:
                continue
            if pool_mat is not None and oracle_mat is None:
                cs[r] = float((te_mat[r] @ pool_mat[ids].T).max())
            best = 0
            for i in ids:
                v = lcp(pool_toks[i], te_tok[r])
                if v > best:
                    best = v
            ks[r] = best

    mlen = np.array([len(t) for t in te_tok], dtype=np.float64)
    row = {"E[k]": float(ks.mean()), "E[cos]": float(cs.mean()),
           "med_cos": float(np.median(cs))}
    for w in thresholds:
        row[f"P(>={w})"] = float((ks >= w).mean())
    row["P(full)"] = float((ks >= mlen).mean())
    row["P(cos>=.3)"] = float((cs >= 0.3).mean())
    row["P(cos>=.5)"] = float((cs >= 0.5).mean())
    return row


if __name__ == "__main__":
    sys.exit(main())
