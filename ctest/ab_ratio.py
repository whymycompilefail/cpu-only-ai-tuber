"""Turn a deq_ab*.log into drift-corrected speed ratios.

Method
------
The machine drifts. f16 is the probe: it has no quant kernel, so any change in
f16 t/s is machine state, not code. For every quant measurement we divide by an
f16 baseline linearly interpolated between the two f16 measurements that
bracket it in time.

A block is only trustworthy if the two bracketing f16 values agree; if the
swing across a block is large the contamination happened *inside* the block,
where linear interpolation cannot correct it. Those blocks are dropped, and
said so loudly.

Usage: python ctest/ab_ratio.py ctest/deq_ab2.log
"""
import re
import sys

F16 = 'Qwen3-0.6B-f16'
MAX_SWING = 0.08          # 8% f16 swing across a block => block is unusable


def load(path):
    """Return the measurement series in file order.

    NOTE: (rep, dir, model) is NOT unique -- a block measures f16 twice, once
    at each end. Dict-on-key silently keeps only the last one and makes the
    two anchors look identical, so carry values alongside the keys.
    """
    keys, vals = [], []
    for line in open(path):
        m = re.match(r'^(\d+) ([FR]) (\S+) ([0-9.]+)\s*$', line)
        if m:
            keys.append((int(m.group(1)), m.group(2), m.group(3)))
            vals.append(float(m.group(4)))
    return keys, vals


def main(path):
    keys, vals = load(path)
    reps = sorted({k[0] for k in keys})
    models = sorted({k[2] for k in keys if k[2] != F16})
    print('models:', ' '.join(m.replace('Qwen3-0.6B-', '').replace('qwen0.6b-', '')
                              for m in models))

    blocks = []       # (label, {model: [normalised...]}, swing)
    for r in reps:
        for dr in 'FR':
            idx = [i for i, k in enumerate(keys) if k[0] == r and k[1] == dr]
            f16_idx = [i for i in idx if keys[i][2] == F16]
            if len(f16_idx) != 2:
                print('rep %d %s: expected 2 f16 anchors, got %d -- skip'
                      % (r, dr, len(f16_idx)))
                continue
            a_i, b_i = f16_idx
            a, b = vals[a_i], vals[b_i]
            swing = abs(b - a) / a
            acc = {}
            for j in range(a_i + 1, b_i):
                t = (j - a_i) / (b_i - a_i)
                base = a + (b - a) * t
                acc.setdefault(keys[j][2], []).append(vals[j] / base)
            blocks.append(('rep%d%s' % (r, dr), acc, swing))
            print('  %-7s f16 %.2f -> %.2f  swing %+.1f%%  %s'
                  % ('rep%d%s' % (r, dr), a, b, 100 * (b - a) / a,
                     'OK' if swing <= MAX_SWING else 'CONTAMINATED - dropped'))

    good = [b for b in blocks if b[2] <= MAX_SWING]
    if not good:
        print('\nno clean block survived -- rerun with nothing else on the machine')
        return

    mean = {}
    for m in models:
        vals = [v for _, acc, _ in good for v in acc.get(m, [])]
        if vals:
            mean[m] = sum(vals) / len(vals)
    print('\nclean blocks: %d / %d' % (len(good), len(blocks)))
    print('speed relative to f16 (drift-corrected):')
    for m, v in sorted(mean.items(), key=lambda x: -x[1]):
        print('   %-18s %.3f x f16' % (m.replace('Qwen3-0.6B-', '').replace('qwen0.6b-', ''), v))
    if 'Qwen3-0.6B-q4_k_m' in mean:
        ref = mean['Qwen3-0.6B-q4_k_m']
        print('\nrelative to q4_k_m (our 3-day default):')
        for m, v in sorted(mean.items(), key=lambda x: -x[1]):
            print('   %-18s %+6.1f%%' % (m.replace('Qwen3-0.6B-', '').replace('qwen0.6b-', ''),
                                         100 * (v / ref - 1)))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'ctest/deq_ab2.log')
