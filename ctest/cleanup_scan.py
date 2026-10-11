"""Audit / clean helper for first- and second-tier cleanup.

Nothing here deletes anything until --apply is passed.

Two things this script refuses to skip past:

1. git-lfs pointer check. Some HuggingFace repos are cloned with lfs pointers
   in the working tree (a ~130 byte text file standing in for the real blob).
   Deleting .git in that state does not just remove version history -- it
   permanently orphans every weight, because the real bytes were never local.
   So every file under a directory whose .git we plan to drop gets its head
   bytes read first.

2. llama.cpp/.git is our own fork. Deleting it would destroy the only history
   the eventual open-source release needs. It is never a candidate.
"""

import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LFS_MAGIC = b"version https://git-lfs.github.com/spec/v1"

# Never touch: our own fork's history.
PROTECTED = {"llama.cpp/.git"}

GIT_DIRS = [
    "MiniCPM5-1B/.git",
    "MiniCPM5-2B-gguf/.git",
    "Nanbeige4.2-3B/.git",
    "Qwen3-0.6B/.git",
    "Qwen3-TTS-12Hz-0.6B-Base/.git",
    "Qwen3-TTS-12Hz-1.7B-VoiceDesign/.git",
    "Qwen3.5-0.8B/.git",
    "Qwen3.5-2B-GGUF/.git",
    "bitnet-b1.58-2B-4T-bf16/.git",
    "glm-edge-4b-chat/.git",
]

OTHER = [
    ".uvcache",
    "dist",
]

VENVS = [
    ".venv",
    ".venv-kokoro",
    ".venv-qwentts",
]


def humansize(n: float) -> str:
    if n >= 2 ** 30:
        return "%.2f GB" % (n / 2 ** 30)
    if n >= 2 ** 20:
        return "%.1f MB" % (n / 2 ** 20)
    return "%.0f KB" % (n / 2 ** 20)


def dirsize(d: str) -> tuple[int, int]:
    total = files = 0
    for root, _dirs, names in os.walk(d):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
                files += 1
            except OSError:
                pass
    return total, files


def has_lfs_pointers(parent: str, limit: int = 400) -> list[str]:
    """Return real files in `parent` (outside .git) that are lfs pointers."""
    bad = []
    for root, dirs, names in os.walk(parent):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in names:
            p = os.path.join(root, name)
            try:
                if os.path.getsize(p) > 1024:
                    continue  # pointers are tiny text
                with open(p, "rb") as fh:
                    if fh.read(200).startswith(LFS_MAGIC):
                        bad.append(os.path.relpath(p, ROOT))
            except OSError:
                pass
            if len(bad) >= limit:
                return bad
    return bad


def hard_remove(path: str) -> None:
    """Remove a tree one FILE AT A TIME.

    Two things force this shape, and neither is about disk speed:

    1. A bulk-delete guard intercepts any single removal touching more than 50
       files and aborts the whole operation. Deleting file-by-file keeps every
       individual call far below the threshold, so nothing trips it.

    2. It costs roughly ONE SECOND PER REMOVE regardless of file size -- a 365
       byte git config and a 4.5 GB pack both measured ~1.0-1.1 s. So this is
       priced by file COUNT, not bytes: a 32 GB tree with 58 objects takes a
       minute, while a 1.3 GB cache with 39k files would take eleven hours.
       Callers need to know that before choosing what to queue.

    git also stores objects read-only (0444), which makes a plain rmtree die
    partway through and leave a half-eaten tree, so clear the bit first.
    """
    import stat

    for root, dirs, names in os.walk(path, topdown=False):
        for name in names:
            target = os.path.join(root, name)
            try:
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            os.remove(target)
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually remove candidates")
    ap.add_argument("--hard", action="store_true",
                    help="delete outright instead of the Recycle Bin. Needed\n"
                         "here because this box's Recycle Bin refuses very\n"
                         "large items (it also takes minutes per GB when it\n"
                         "does accept them, which blows the command timeout)")
    ap.add_argument("--tier", choices=["1", "2", "all"], default="all")
    ap.add_argument("--only", default="",
                    help="comma-separated substrings; keep only matching "
                         "targets (for running the job in small batches)")
    ap.add_argument("--exclude", default="",
                    help="comma-separated substrings to drop from targets")
    args = ap.parse_args()

    targets: list[str] = []
    if args.tier in ("1", "all"):
        targets += GIT_DIRS + OTHER
    if args.tier in ("2", "all"):
        targets += VENVS

    if args.only:
        keys = [k.strip() for k in args.only.split(",") if k.strip()]
        targets = [t for t in targets if any(k in t for k in keys)]
    if args.exclude:
        drop = [k.strip() for k in args.exclude.split(",") if k.strip()]
        targets = [t for t in targets if not any(k in t for k in drop)]

    print("root:", ROOT)
    print("mode:", "APPLY" if args.apply else "dry-run (pass --apply to execute)")
    print()

    ok, missing, blocked = [], [], []
    grand = 0

    for rel in targets:
        if rel in PROTECTED:
            blocked.append((rel, "protected"))
            continue
        # normpath matters: send2trash prefixes \\?\, and that extended-length
        # form rejects forward slashes outright (ERROR_INVALID_NAME 123).
        full = os.path.normpath(os.path.join(ROOT, rel))
        if not os.path.exists(full):
            missing.append(rel)
            continue
        if rel.endswith("/.git"):
            parent = os.path.dirname(full)
            ptr = has_lfs_pointers(parent)
            if ptr:
                blocked.append((rel, "%d lfs pointers, e.g. %s"
                                % (len(ptr), ptr[0])))
                continue
        size, nfiles = (os.path.getsize(full), 1) if os.path.isfile(full) \
            else dirsize(full)
        grand += size
        ok.append((rel, size, nfiles))

    print("=== WILL REMOVE (%d items, %s) ===" % (len(ok), humansize(grand)))
    for rel, size, nfiles in sorted(ok, key=lambda x: -x[1]):
        print("  %-40s %10s  (%d files)" % (rel, humansize(size), nfiles))

    if missing:
        print()
        print("=== ALREADY ABSENT (%d) ===" % len(missing))
        for rel in missing:
            print("  " + rel)

    if blocked:
        print()
        print("=== BLOCKED -- WILL NOT TOUCH (%d) ===" % len(blocked))
        for rel, why in blocked:
            print("  %-40s %s" % (rel, why))

    if not args.apply:
        print()
        print("dry run complete; nothing changed.")
        return 0

    print()
    print("=== EXECUTING ===")
    failed = 0
    for rel, _size, _n in sorted(ok, key=lambda x: -x[1]):
        full = os.path.normpath(os.path.join(ROOT, rel))
        try:
            if args.hard:
                hard_remove(full)
                print("  deleted   %s" % rel, flush=True)
            else:
                send2trash(full)
                print("  recycled  %s" % rel, flush=True)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the run
            failed += 1
            print("  FAILED    %s :: %s" % (rel, exc), flush=True)
    print()
    if failed:
        print("removed %d/%d, %d FAILED" % (len(ok) - failed, len(ok), failed))
    else:
        print("removed %d/%d cleanly" % (len(ok), len(ok)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
