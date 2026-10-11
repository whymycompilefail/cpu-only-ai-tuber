#!/usr/bin/env python3
"""Find personal traces before this project goes public (or any time you like).

    python ctest/scrub_scan.py [--root DIR] [--show]

Why this exists
---------------
"Clean it up before publishing" assumes you can enumerate your own personal
data at that moment. In practice nobody can: the leaks accumulate silently in
log files, stack traces and absolute paths across hundreds of files, spread over
weeks. This turns a one-time act of memory into a repeatable check.

What it looks for
-----------------
  win-user      C:\\Users\\<name>  -- Windows account name. Leaks via temp paths
                and tracebacks, which you never typed by hand.
  bili-room     your room id (pass --room-id, or set once below)
  abs-root      the absolute project path -- machine layout + project identity
                (spelled out by the pattern itself, see (2) below; naming a real
                example here would make this file report on itself)
  sessdata      SESSDATA / bili_jct    -- actual credentials, never commit
  email         anything@domain

Binary files and anything over --max-mb are skipped, so it stays fast.

Two ways to point it at things
------------------------------
  --root DIR            walk a directory (what you run before publishing)
  --git-staged          check exactly what `git add` put in the index

The second one is what makes this hold up over time: if the scan only runs on
release day, it protects one snapshot and then goes stale the moment you commit
anything new. Wired into a pre-commit hook it covers every future write.

Exit code 1 when something is found, so you can wire it into whatever you run
before publishing.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# The tree this script sits in. Writing the path out here used to
# make the tool match its own scanner every single run, which is how you teach
# someone to ignore scanners (or worse, to use --no-verify on every commit).
DEFAULT_ROOT = os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))).replace("\\", "/")

PATTERNS = [
    # The (?!<) keeps this from re-flagging its own placeholders: after a scrub
    # run the text legitimately contains C:/Users/<you>, which otherwise shows
    # up as a finding every single time and trains you to ignore the output.
    ("win-user", re.compile(r"C:[\\/]Users[\\/](?!<)([^\\\/\s\"'<]+)", re.I)),
    # Same idea: <project-root> is what make_release.py substitutes in.
    ("abs-root", re.compile(r"(?<!<)[A-Za-z]:[\\/](?:[\\/]?)[^\s\"']*?Ai_edge_deployment")),
    # Real cookies are long opaque strings. The previous version flagged
    # `cookies={"SESSDATA": sessdata}`, i.e. the variable name standing in for
    # the value, every single time.
    ("sessdata", re.compile(r"(?i)(?:sessdata|bili_jct)\s*[=:]\s*[\"']?"
                            r"[A-Za-z0-9%_\-]{16,}")),
    # Alpha-only TLD, because the old `[\w.]{2,}` ending matched version pins in
    # vendored bundles (`https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/`)
    # and reported them as somebody's inbox. A scanner that cries wolf on every
    # run is the one people learn to silence with --no-verify.
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")),
]

# Directories that are pure machinery or someone else's checkout.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             "llama.cpp", "bitnet-b1.58-2B-4T-bf16", "glm-edge-4b-chat",
             "MiniCPM5-1B", "MiniCPM5-2B-gguf", "Nanbeige4.2-3B",
             "Qwen3-0.6B", "Qwen3-TTS-12Hz-0.6B-Base",
             "Qwen3-TTS-12Hz-1.7B-VoiceDesign", "Qwen3.5-0.8B",
             "Qwen3.5-2B-GGUF", "models", "舒芙蕾"}
SKIP_EXTS = {".exe", ".dll", ".bin", ".gguf", ".safetensors", ".moc3",
             ".png", ".jpg", ".wav", ".pdf", ".zip", ".gz", ".pyd", ".lib"}
CHECK_EXTS = {".py", ".sh", ".yaml", ".yml", ".json", ".md", ".txt", ".log",
              ".js", ".ts", ".cfg", ".ini", ".toml", ".template"}


# Some files are private by their very name, whatever their content says. This
# caught live.local.sh (holds the room id) after `ctest/*.sh` globbed it into a
# release build; content scanning would have been the wrong tool there.
BLOCKED_NAMES = {"live.local.sh"}
BLOCKED_DIRS = {"chat_history", "logs", "shots", "data"}
BLOCKED_EXTS = {".log"}


def _rel(path: str, root: str) -> str:
    """relpath that survives being pointed at a different drive."""
    try:
        return os.path.relpath(path, root)
    except ValueError:          # e.g. path on C:, root on D:
        return path


def _is_blocked(path: str) -> bool:
    fn = os.path.basename(path)
    if fn in BLOCKED_NAMES:
        return True
    if os.path.splitext(fn)[1].lower() in BLOCKED_EXTS:
        return True
    parts = set(os.path.normpath(path).replace("\\", "/").split("/"))
    return bool(parts & BLOCKED_DIRS)


def iter_files(root: str, paths: list[str] | None):
    """Yield candidate paths: either an explicit list, or everything under root."""
    if paths is not None:
        for p in paths:
            yield p
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def scan(root: str, room_id: str, max_mb: float, show: int,
         paths: list[str] | None = None) -> int:
    pats = list(PATTERNS)
    if room_id:
        pats.insert(0, ("bili-room", re.compile(re.escape(room_id))))

    hits: dict[str, list[tuple[str, int, str]]] = {k: [] for k, _ in pats}
    blocked: list[str] = []
    files = 0

    for path in iter_files(root, paths):
        fn = os.path.basename(path)
        if _is_blocked(path):
            blocked.append(path)
            continue
        if os.path.splitext(fn)[1].lower() in SKIP_EXTS:
            continue
        try:
            if os.path.getsize(path) > max_mb * 1024 * 1024:
                continue
        except OSError:
            continue
        if os.path.splitext(fn)[1].lower() not in CHECK_EXTS:
            continue
        try:
            with open(path, encoding="utf-8", errors="strict") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        files += 1
        for label, pat in pats:
            found = pat.findall(text)
            if not found:
                continue
            sample = str(found[0])
            hits[label].append((path, len(found), sample))

    scope = f"{len(paths)} staged files" if paths is not None else f"under {root}"
    how = f"scanned {files} text files {scope}\n"
    print(how)
    total = 0
    for label, _ in pats:
        rows = sorted(hits[label], key=lambda r: -r[1])
        if not rows:
            print(f"  {label:<10} clean")
            continue
        count = sum(r[1] for r in rows)
        total += count
        print(f"  {label:<10} {count} hits in {len(rows)} files")
        for path, n, sample in rows[:show]:
            rel = _rel(path, root)
            print(f"      {n:>5}  {rel}   e.g. {sample[:48]}")
        if len(rows) > show:
            print(f"      ... +{len(rows) - show} more files")

    if blocked:
        print(f"  {'by-name':<10} {len(blocked)} files that must never be published")
        for p in blocked[:show]:
            print(f"          {_rel(p, root)}")
    print()
    return 1 if (total or blocked) else 0


def staged_paths() -> tuple[list[str] | None, str | None]:
    """Files sitting in the git index. Returns (paths, error)."""
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        return None, "git not found on PATH"
    except subprocess.CalledProcessError as e:
        return None, f"git failed: {e.stderr.strip() or e}"
    cwd = os.getcwd()
    paths = [os.path.join(cwd, p) for p in out.splitlines() if p.strip()]
    return paths, None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=DEFAULT_ROOT)
    p.add_argument("--room-id", default="", help="your bilibili room id")
    p.add_argument("--max-mb", type=float, default=4.0)
    p.add_argument("--show", type=int, default=6)
    p.add_argument("--git-staged", action="store_true",
                   help="scan what is staged for commit instead of walking a tree")
    a = p.parse_args()

    root = a.root
    paths = None
    if a.git_staged:
        paths, err = staged_paths()
        if err:
            print(f"cannot read the git index: {err}")
            sys.exit(2)
        if not paths:
            print("nothing staged")
            sys.exit(0)
        # Print paths relative to the repo, not to wherever this script lives.
        try:
            top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True,
                                 check=True).stdout.strip()
            if top:
                root = top
        except Exception:
            pass

    sys.exit(scan(root, a.room_id, a.max_mb, a.show, paths))


if __name__ == "__main__":
    main()
