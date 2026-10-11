BW = 31.0          # GB/s 实测有效带宽
W  = 325/1024.0    # GB   Qwen3-0.6B Q2_K 权重
kv = 112/1024/1024 # GB   每 token 的 KV 字节（f16）

# ctest/benchmark_results.md §8 的实测（Qwen3-0.6B Q2_K, t=12, n=128）
fa = {512: 78.7, 1024: 64.1, 2048: 46.2, 4096: 25.0, 8192: 12.3}
lg = {512: 69.3, 1024: 62.2, 2048: 52.2, 4096: 36.4, 8192: 23.5}

print("FA 的「KV 流量放大系数 α」= 反推 FA 每 token 实际读的 KV 字节 / 名义 KV 字节")
print()
print(f"{'ctx':>6} {'legacy实测':>10} {'屋顶线预测':>10} | {'FA实测':>7} {'反推α':>7}")
for c in sorted(fa):
    kvb = c*kv
    pred = BW/(W+kvb)
    alpha = (BW/fa[c] - W)/kvb
    tag = "KV 仍在缓存内" if alpha < 1.2 else ("超出缓存，重读开始显现" if alpha < 1.9 else "完全 GQA 重读")
    print(f"{c:>6} {lg[c]:>10.1f} {pred:>10.1f} | {fa[c]:>7.1f} {alpha:>7.2f}   {tag}")

print()
print("GQA 比：Qwen3-0.6B = 16 Q头 / 8 KV头 = 2")
print("        Qwen3-4B   = 32 Q头 / 8 KV头 = 4")
W4, kv4 = 2272/1024.0, 144/1024/1024
a4 = (BW/5.1 - W4)/(8192*kv4)
print(f"        4B @8192 FA=5.1 -> 反推 α = {a4:.2f}（0.6B 同条件 α = 2.26）")

print()
print("若把 α 修回 1（每份 K/V 只读一次），FA 的屋顶线：")
for c in [2048, 4096, 8192, 16384]:
    cur = fa.get(c)
    s = f"{BW/(W+c*kv):5.1f}"
    print(f"  ctx {c:>5}: {s} tok/s" + (f"   （现在 {cur}）" if cur else ""))
