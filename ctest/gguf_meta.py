"""Dump tokenizer metadata from a GGUF so we can see whether a chat template
is baked in. A missing template means llama-server falls back to a generic one
and the model's replies come out malformed.
"""
import struct
import sys


def read_kv(path, want=("tokenizer.chat_template", "general.name",
                        "general.architecture", "general.file_type")):
    out = {}
    with open(path, "rb") as f:
        # header: magic(u32) version(u32) tensor_count(u64) metadata_kv_count(u64)
        magic, version, n_tensor, n_kv = struct.unpack("<IIQQ", f.read(24))
        if magic != 0x46554747:  # "GGUF"
            return {"error": "not a gguf"}

        def rd(t):
            if t == 0:  # UINT8
                return struct.unpack("<B", f.read(1))[0]
            if t == 1:  # INT8
                return struct.unpack("<b", f.read(1))[0]
            if t == 2:  # UINT16
                return struct.unpack("<H", f.read(2))[0]
            if t == 3:  # INT16
                return struct.unpack("<h", f.read(2))[0]
            if t == 4:  # UINT32
                return struct.unpack("<I", f.read(4))[0]
            if t == 5:  # INT32
                return struct.unpack("<i", f.read(4))[0]
            if t == 6:  # FLOAT32
                return struct.unpack("<f", f.read(4))[0]
            if t == 7:  # BOOL
                return struct.unpack("<?", f.read(1))[0]
            if t == 8:  # STRING
                n = struct.unpack("<Q", f.read(8))[0]
                return f.read(n).decode("utf-8", "replace")
            if t == 10:  # UINT64
                return struct.unpack("<Q", f.read(8))[0]
            raise ValueError(f"unhandled value type {t} at {f.tell()}")

        for _ in range(n_kv):
            n = struct.unpack("<Q", f.read(8))[0]
            key = f.read(n).decode("utf-8", "replace")
            vtype = struct.unpack("<I", f.read(4))[0]
            if vtype == 9:  # ARRAY: element_type(u32) then count(u64)
                etype = struct.unpack("<I", f.read(4))[0]
                cnt = struct.unpack("<Q", f.read(8))[0]
                for _ in range(cnt):
                    rd(etype)
                continue
            val = rd(vtype)
            if key in want:
                out[key] = val
    return out


for p in sys.argv[1:]:
    print("=" * 70)
    print(p)
    try:
        meta = read_kv(p)
        for k, v in meta.items():
            s = str(v)
            if len(s) > 160:
                s = s[:160] + " ..."
            print(f"  {k} = {s}")
        has = "tokenizer.chat_template" in meta
        print(f"  >>> chat template embedded: {has}"
              f"{'' if has else '   <-- llama-server will fall back'}")
    except Exception as e:
        print(f"  error: {e}")
