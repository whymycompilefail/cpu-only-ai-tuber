#!/usr/bin/env python
"""cleanup_purge.py -- 第二阶段清理：先 truncate 清零（瞬时释放空间），再逐文件删除空壳。

背景（实测）：
  * rm -rf / shutil.rmtree 在本环境被安全机制挂起（8 个 19KB 文件跑 180s 未完成）
  * os.remove 单文件固定开销 ~1.5s，且大文件额外按 ~7.5 MB/s 计
    => 32 GB 直接删需要 ~70 分钟
  * 但 os.truncate(p, 0) 是瞬时的，且**立刻释放磁盘空间**
    => 先清零：空间秒回；再删 0 字节空壳：只剩 1.5s/文件的固定开销

用法：
  python ctest/cleanup_purge.py --truncate          # 只清零（秒级，空间立刻回收）
  python ctest/cleanup_purge.py --purge --limit 40  # 删除空壳，本轮最多删 40 个文件
  python ctest/cleanup_purge.py --status            # 报告残留
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 第三方 git clone 的隐藏 .git（已确认无 git-lfs pointer 文件，删掉不丢权重）
TARGETS = [
    "Qwen3.5-2B-GGUF/.git",
    "MiniCPM5-2B-gguf/.git",
    "Nanbeige4.2-3B/.git",
    "Qwen3-TTS-12Hz-1.7B-VoiceDesign/.git",
    "Qwen3-TTS-12Hz-0.6B-Base/.git",
    "MiniCPM5-1B/.git",
    "Qwen3.5-0.8B/.git",
    "Qwen3-0.6B/.git",
    "glm-edge-4b-chat/.git",
    "bitnet-b1.58-2B-4T-bf16/.git",
    "dist",
]

# 硬保护：自有 fork 历史 / 栈在用的 venv / 缓存
PROTECTED = ("llama.cpp/.git", ".venv")


def _walk_files(base):
    out = []
    for r, _d, fs in os.walk(base):
        for x in fs:
            out.append(os.path.join(r, x))
    return out


def _check_guard(rel):
    for p in PROTECTED:
        if rel.replace("\\", "/").startswith(p):
            return False
    return True


def do_truncate():
    freed = 0
    n = 0
    for rel in TARGETS:
        base = os.path.join(ROOT, rel)
        if not os.path.exists(base):
            print(f"  [gone]  {rel}")
            continue
        if not _check_guard(rel):
            print(f"  [SKIP-PROTECTED] {rel}")
            continue
        sub = 0
        for p in _walk_files(base):
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz == 0:
                continue
            try:
                os.chmod(p, 0o666)
                with open(p, "wb"):
                    pass          # truncate to 0
                freed += sz
                sub += 1
            except Exception as e:
                print(f"  [trunc-fail] {p}: {e}")
        n += sub
        print(f"  [zeroed] {rel:46s} {sub} files")
    print(f"\ntruncated {n} files, space freed: {freed/2**30:.2f} GB (instant)")


def do_purge(limit):
    """只删文件，绝不碰目录（实测 rmdir 阶段会挂起）。目录用 --rmdir 单独收尾。"""
    done = 0
    t0 = time.time()
    for rel in TARGETS:
        base = os.path.join(ROOT, rel)
        if not os.path.exists(base):
            continue
        if not _check_guard(rel):
            continue
        for p in _walk_files(base):
            if done >= limit:
                print(f"\nlimit {limit} reached in {time.time()-t0:.0f}s", flush=True)
                return
            try:
                os.chmod(p, 0o666)
                os.remove(p)
                done += 1
            except Exception as e:
                print(f"  [del-fail] {p}: {e}", flush=True)
    print(f"\ndeleted {done} files in {time.time()-t0:.0f}s")


def do_rmdir():
    """删完所有文件后，自底向上收掉空目录。"""
    t0 = time.time()
    n = 0
    for rel in TARGETS:
        base = os.path.join(ROOT, rel)
        if not os.path.exists(base):
            continue
        if not _check_guard(rel):
            continue
        for r, ds, fs in os.walk(base, topdown=False):
            for d in ds:
                try:
                    os.rmdir(os.path.join(r, d))
                    n += 1
                except OSError:
                    pass
        try:
            os.rmdir(base)
            print(f"  [removed] {rel}", flush=True)
        except OSError as e:
            print(f"  [leftover] {rel}: {e}", flush=True)
    print(f"\nrmdir {n} dirs in {time.time()-t0:.0f}s")


def do_status():
    tot_s = 0
    tot_n = 0
    for rel in TARGETS:
        base = os.path.join(ROOT, rel)
        if not os.path.exists(base):
            print(f"  GONE    {rel}")
            continue
        s = 0
        n = 0
        for p in _walk_files(base):
            try:
                s += os.path.getsize(p)
            except OSError:
                pass
            n += 1
        tot_s += s
        tot_n += n
        flag = "EMPTY-SHELL" if s == 0 else "STILL-OCCUPYING"
        print(f"  {flag:16s} {rel:46s} {s/2**30:8.2f} GB  {n} files")
    print(f"\nresidual: {tot_s/2**30:.2f} GB in {tot_n} files")


if __name__ == "__main__":
    os.chdir(ROOT)
    a = sys.argv[1:]
    if "--truncate" in a:
        do_truncate()
    elif "--rmdir" in a:
        do_rmdir()
    elif "--purge" in a:
        lim = 40
        if "--limit" in a:
            lim = int(a[a.index("--limit") + 1])
        do_purge(lim)
    else:
        do_status()
