"""Dump per-tensor-type byte / MAC breakdown of a GGUF file.

Why this exists: llama-quantize does NOT quantize every tensor to the requested
type -- token_embd.weight and output.weight get a separate (higher-precision)
default. So "this is a q4_0 model" is false: a chunk of the decode bytes are
some other type, which caps how much a q4_0 kernel optimization can ever buy.

Usage: python ctest/gguf_types.py models/Qwen3-0.6B-q4_0.gguf [...]
"""
import struct
import sys
import collections

# ggml_type enum (ggml/include/ggml.h) -- NOT the gguf-py ordering.
GGUF_TYPE = {0: 'F32', 1: 'F16', 2: 'Q4_0', 3: 'Q4_1', 6: 'Q5_0', 7: 'Q5_1',
             8: 'Q8_0', 9: 'Q8_1', 10: 'Q2_K', 11: 'Q3_K', 12: 'Q4_K',
             13: 'Q5_K', 14: 'Q6_K', 15: 'Q8_K', 30: 'BF16'}
# block bytes / block elements. NOTE the K-quants use QK_K = 256, not 32 --
# getting this wrong makes every K-quant tensor look 8x too big.
BPE = {0: 4, 1: 2, 2: 18 / 32, 3: 20 / 32, 6: 22 / 32, 7: 24 / 32, 8: 34 / 32,
       9: 40 / 32, 10: 84 / 256, 11: 110 / 256, 12: 144 / 256, 13: 176 / 256,
       14: 210 / 256, 15: 292 / 256, 30: 2}
# GGUF metadata value sizes (STRING / ARRAY handled separately)
VSZ = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}


def rdstr(f):
    n = struct.unpack('<Q', f.read(8))[0]
    assert n < 1 << 20, 'implausible string length %d' % n
    return f.read(n).decode('utf-8', 'replace')


def skipval(f, t):
    if t == 8:                      # STRING
        rdstr(f)
    elif t == 9:                    # ARRAY: element_type (u32) THEN count (u64)
        inner = struct.unpack('<I', f.read(4))[0]
        n = struct.unpack('<Q', f.read(8))[0]
        for _ in range(n):
            skipval(f, inner)
    else:
        f.read(VSZ[t])


def dump(path):
    f = open(path, 'rb')
    _magic, ver, nt, nkv = struct.unpack('<IIQQ', f.read(24))
    for _ in range(nkv):
        rdstr(f)
        skipval(f, struct.unpack('<I', f.read(4))[0])

    infos = []
    for _ in range(nt):
        name = rdstr(f)
        nd = struct.unpack('<I', f.read(4))[0]
        dims = struct.unpack('<' + 'Q' * nd, f.read(8 * nd))
        ty = struct.unpack('<I', f.read(4))[0]
        off = struct.unpack('<Q', f.read(8))[0]
        ne = 1
        for d in dims:
            ne *= d
        infos.append((name, ty, ne, off))
    fsize = f.seek(0, 2)

    # Ground truth for byte size: the gap to the next tensor's offset.
    # (Using ne*BPE would trust my block-size table; offsets do not lie.)
    by_type = collections.Counter()
    macs = collections.Counter()
    head_bytes = 0.0
    for i, (name, ty, ne, off) in enumerate(infos):
        nxt = infos[i + 1][3] if i + 1 < nt else fsize
        real = nxt - off
        tn = GGUF_TYPE.get(ty, str(ty))
        by_type[tn] += real
        # exact match: blk.*.attn_output.weight / ffn_output.weight are body
        if name == 'output.weight':
            head_bytes += real          # the lm_head: a real GEMV, every token
            macs[tn] += ne
        elif name == 'token_embd.weight':
            pass                        # a lookup: 1 row read per token, ignore
        else:
            macs[tn] += ne
    total = sum(by_type.values())
    deq = sum(v for k, v in macs.items())
    # bytes actually streamed per generated token: everything token_embd is not
    # (it is one row lookup, ~2 KB, not the whole 87 MB tensor)
    embd = 0.0
    for i, (nm_i, _ty, _ne, off_i) in enumerate(infos):
        nxt = infos[i + 1][3] if i + 1 < nt else fsize
        if nm_i == 'token_embd.weight':
            embd = nxt - off_i
    decode_bytes = total - embd
    print('%-22s file %6.1f MB | tensors %d' % (
        path.replace('\\', '/').split('/')[-1], fsize / 1e6, nt))
    print('   bytes by type   :', {k: round(v / 1e6, 1) for k, v in
                                   sorted(by_type.items(), key=lambda x: -x[1])})
    print('   DECODE bytes/tok: %.1f MB  (file minus token_embd %.1f MB)'
          % (decode_bytes / 1e6, embd / 1e6))
    print('   output.weight   : %.1f MB (%.0f%% of decode traffic)' %
          (head_bytes / 1e6, 100 * head_bytes / decode_bytes))
    print('   decode MACs (M) :', {k: round(v / 1e6, 1) for k, v in
                                   sorted(macs.items(), key=lambda x: -x[1])},
          '| total %.0fM' % (deq / 1e6))
    print()


if __name__ == '__main__':
    for p in sys.argv[1:]:
        dump(p)
