#!/usr/bin/env python3
"""Build the publishable tree from an allow-list, then prove it is clean.

    python ctest/make_release.py            # writes ./dist
    python ctest/make_release.py --check    # scrub only, print offenders

Why an allow-list
-----------------
`.gitignore` is a *deny*-list: it requires you to have already thought of every
bad path. `git check-ignore ctest/bin-base` came back "not ignored" until the
rule was added by hand, and `.gitignore` cannot untrack a file once it is
committed. This script asks the opposite question -- "what is explicitly OK?" --
so anything nobody vouched for stays out by default.

Watch out for negations in vendored trees: hierarchy depth beats file order, so
a `!something` inside a third-party `.gitignore` silently overrides whatever the
root file says. That is how two Live2D sample models got published; see
`Open-LLM-VTuber/live2d-models/.gitignore`. `git check-ignore` hides it too --
it skips tracked files unless you pass `--no-index`.

What dist is now
----------------
The git repo became the release artifact, so dist mirrors it: same sources,
independently re-derived from this allow-list and re-scrubbed. The value is no
longer "a smaller copy" but a second opinion that can disagree with git, plus a
`MANIFEST.txt` whose diff between builds is the release review. `find_omitted()`
below checks *every tracked file*, not just `ctest/` and `specs/` -- otherwise a
new top-level directory ships without anybody noticing.

Files are read and written in BINARY mode. Text mode silently converts LF to
CRLF on Windows and produced a 1624-byte phantom diff in a bundle once already;
do not "fix" this back to open() defaults.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Derived, not written down. These two paths used to be literal constants, which
# meant every copy of this tool permanently tripped its own privacy scanner --
# a hook that fires on every commit is a hook everybody learns to bypass.
ROOT = os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))).replace("\\", "/")
OUT = ROOT + "/dist"
HOME = os.path.expanduser("~").replace("\\", "/")


def _variants(p: str) -> list[bytes]:
    """Every spelling one path can take: forward slashes, backslashes, MSYS."""
    p = p.replace("\\", "/")
    drive, rest = p.split("/", 1)
    return [f"{drive}/{rest}".encode("utf-8"),
            f"{drive}\\{rest}".encode("utf-8"),
            f"/{drive[0].lower()}/{rest}".encode("utf-8")]

# --- what may be published ------------------------------------------------- #

# Exact files at the repo root. Everything you would read first.
ROOT_FILES = ("README.md", "LICENSE", "ASSETS.md", "RELEASE.md",
              "LIVE_RUNBOOK.md", ".gitignore")

# Subtrees published whole, structure preserved. Per-tree deny list because we
# vendor two upstream projects and only ship their sources:
#   (source dir, directory names to drop anywhere inside, suffix to drop)
# The excluded names below are each a deliberate decision, not a convenience --
# if one of them stops matching reality, find_omitted() below will say so.
TREES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # Our own tooling. The interesting part of this whole repo.
    ("ctest", ("voice_ab", "spec_ab", "shots", "data"), ()),
    # The design specs: problem, measurement, verdict. Honest about what failed.
    ("specs", (), ()),
    # The fork diff and how to replay it upstream.
    ("patches", (), ()),
    # Upstream (MIT) + our documented changes. Kept: how Live2D/TTS/ASR are
    # wired. Dropped: everything that is somebody else's asset or downloadable.
    ("Open-LLM-VTuber", (".venv", ".idea",
                         "models", "cache", "live2d-models",
                         "logs", "chat_history"), ()),
    # Our CPU-tuned fork. Dropped: compiled output (also the only place a
    # Windows username ever appeared in this project) and downloaded weights.
    ("llama.cpp", (".git.fork-backup", "build", "models"), (".gguf",)),
]

# Runtime output that is deliberately never published -- do not report it.
IGNORE_EXTS = {".log", ".wav", ".mp3", ".png", ".bac", ".bak"}

# Directories never copied even if a rule above would reach them.
EXCLUDE_DIRS = {"__pycache__", "node_modules", "data", "shots",
                "bn", "bt", "bin-base", "bin-gqa", "bin-tq"}

# Files never copied even if a rule matches. A broad tree rule picks up
# live.local.sh along with everything else, and that file holds the room id --
# it leaked into dist on the first real run and the verifier caught it.
# conf.yaml.backup is the other way round: git has never tracked it (upstream
# ignores it), but it sits in the working tree with four absolute paths inside,
# so the tree walk found what the deny-list never had to consider.
# Keep this list paranoid: being listed here costs nothing, being absent leaks.
EXCLUDE_FILES = {
    "live.local.sh",
    "conf.yaml.backup",
    # Not shipped because its allow-list and rewrite table necessarily name the
    # machine layout they alias -- it cannot scrub itself without breaking.
    # Not true anymore of the paths (they are derived at import now), but the
    # EXCLUDE_FILES entry stays: its output is `dist`, not itself.
    "make_release.py",
}

# Built at import from the paths above rather than typed in, so this tool does
# not carry the very traces it removes.
REWRITES: list[tuple[bytes, bytes]] = (
    [(v, b"<project-root>") for v in _variants(ROOT)]
    + [(v, b"C:/Users/<you>") for v in _variants(HOME)]
)

# Anything left over means offline manual review is needed.
RESIDUAL = [
    (b" Ai_edge_deployment", "absolute project path"),
    (b"Users\\<you>", "ok (placeholder)"),
]


def belongs(path: str) -> str | None:
    """Return the destination path inside dist, or None if not allowed."""
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return None
    if parts[-1] in EXCLUDE_FILES or parts[-1] in FIXTURES:
        return None
    if rel in ROOT_FILES:
        return rel
    for tree, drop_dirs, drop_suffixes in TREES:
        if rel != tree and not rel.startswith(tree + "/"):
            continue
        # Deny-list applies to directories directly under the tree root, not at
        # any depth -- `llama.cpp/src/models/` is source code, and matching by
        # name alone threw away 200 files of it on the first run.
        if len(parts) > 2 and parts[1] in drop_dirs:
            return None
        if drop_suffixes and parts[-1].endswith(tuple(drop_suffixes)):
            return None
        return rel
    return None


def _tracked() -> list[str] | None:
    """Every file git would publish, or None outside a git checkout."""
    try:
        out = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files"],
                             cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8")
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def scrub(data: bytes) -> tuple[bytes, list[str]]:
    """Apply rewrites. Returns new bytes and which substitutions fired."""
    fired: list[str] = []
    for old, new in REWRITES:
        n = data.count(old)
        if n:
            data = data.replace(old, new)
            fired.append(f"{new.decode('ascii', 'replace')} x{n}")
    return data, fired


def build(check_only: bool) -> int:
    if not check_only:
        if os.path.exists(OUT):
            shutil.rmtree(OUT)
        os.makedirs(OUT)

    copied = 0
    dirty: list[tuple[str, list[str]]] = []
    manifest: list[tuple[str, str]] = []
    published: set[str] = set()
    # Pass 1 -- every file the allow-list vouches for.
    allowed: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDE_DIRS and d not in {".git", "dist"}]
        if os.path.abspath(dirpath).replace("\\", "/") == OUT:
            continue
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel_out = belongs(path)
            if rel_out is not None:
                allowed.append((path, rel_out))

    # Pass 2 -- Honour git's own deny list too. The allow-list is the strong
    # check, but there is no reason to publish something git already refuses:
    # that is how an untracked `conf.yaml`, its backup, and 40 background
    # images ended up in dist on the first run of this tree-wide allow-list.
    ignored = _ignored_by_git([rel for _, rel in allowed])

    for path, rel_out in allowed:
        if rel_out in ignored:
            continue
        with open(path, "rb") as f:
            data = f.read()
            cleaned, fired = scrub(data)
            if fired:
                dirty.append((rel_out, fired))
            published.add(rel_out)
            manifest.append((rel_out, hashlib.sha256(cleaned).hexdigest()[:12]))
            if not check_only:
                dst = os.path.join(OUT, rel_out.replace("/", os.sep))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(cleaned)
            copied += 1

    print(f"{'would copy' if check_only else 'copied'} {copied} files")
    if dirty:
        print(f"\nrewritten in {len(dirty)} files:")
        for name, fired in dirty:
            print(f"  {name}")
            for f in fired:
                print(f"      -> {f}")
    else:
        print("\nnothing needed rewriting")

    total = 0
    for name, fired in dirty:
        total += sum(int(f.split("x")[-1]) for f in fired)
    print(f"\n{total} personal traces removed")

    # Has the source tree drifted past the allow-list? Check the places new work
    # would land and name whatever the build left behind. Without this, adding a
    # file `ctest/foo.yaml` next month makes it silently absent from the public
    # version while the build still prints a cheerful success line.
    missing, extra = find_omitted(published)
    for label, rows, why in (
            ("git publishes but dist does NOT", missing,
             "new work nobody added to the allow-list yet"),
            ("dist ships but git does NOT track", extra,
             "usually local output that would leak outside the repo")):
        if not rows:
            continue
        print(f"\n{len(rows)} file(s) where {label}:")
        for rel in rows[:12]:
            print(f"  {rel}")
        if len(rows) > 12:
            print(f"  ... +{len(rows) - 12} more")
        print(f"  check: {why}")
    if not missing and not extra:
        print("\nno drift: dist and git agree on every file")

    if not check_only:
        write_manifest(manifest)
        print(f"\nwrote MANIFEST.txt ({len(manifest)} entries) "
              "-- its diff between releases is the release review")
        print(f"output: {OUT}")
        print(f"verify with: python ctest/scrub_scan.py --root {OUT}")
    return 0


# Excluded on purpose, so the drift report stays about surprises only.
DELIBERATE = set(EXCLUDE_FILES) | {"_ign.txt"}

# Evaluation fixtures. No script reads these three (checked), they are scraped
# upstream README text kept from an old perplexity experiment, and one of them
# embeds a maintainer's public contact address. Data nobody consumes is the one
# kind of file worth leaving behind rather than reasoning about.
FIXTURES = ("ppl_corpus.txt", "ppl_small.txt", "ppl_tiny.txt")


def _ignored_by_git(paths: list[str]) -> set[str]:
    """Which of these git considers ignored. Batch once -- per-file git calls
    made the older release build take minutes."""
    if not paths:
        return set()
    # Byte mode, not text=True: in text mode Python translates "\n" into CRLF on
    # Windows, and git then treats the stray \r as part of the path, so almost
    # nothing matches. This is the same trap that produced a 11,416%-of-1GB
    # "capacities" figure earlier in this repo's life.
    try:
        out = subprocess.run(["git", "-c", "core.quotePath=false",
                              "check-ignore", "--no-index", "--stdin"],
                             cwd=ROOT,
                             input="\n".join(paths).encode("utf-8"),
                             capture_output=True)
    except OSError:
        return set()
    text = out.stdout.decode("utf-8", "replace")
    # -v-less output still quotes paths containing spaces or non-ASCII.
    return {p.strip().strip('"').rstrip("\r")
            for p in text.splitlines() if p.strip()}


def find_omitted(published: set[str]) -> tuple[list[str], list[str]]:
    """Compare dist against what git actually publishes, in both directions.

    Checking against `git ls-files` rather than walking a few directories is the
    point: the repo publishes five top-level trees now, and checking only the
    two we used to own would let a whole new tree ship unseen.

    Returns (missing, extra):
      missing -- git tracks it, dist does not: someone forgot to allow new work
      extra   -- dist has it, git does not: usually untracked local output that
                 would ship to a reader even though the repo never had it
    """
    tracked = set(_tracked() or [])
    if not tracked:
        return [], []
    missing, extra = [], []
    for rel in sorted(tracked - published):
        if (os.path.basename(rel) in DELIBERATE
                or os.path.basename(rel) in FIXTURES
                or os.path.splitext(rel)[1].lower() in IGNORE_EXTS):
            continue
        missing.append(rel)
    for rel in sorted(published - tracked):
        if os.path.splitext(rel)[1].lower() in IGNORE_EXTS:
            continue
        extra.append(rel)
    return missing, extra


def write_manifest(entries: list[tuple[str, str]]) -> None:
    """Ship an inventory so each release can be diffed against the last one."""
    lines = ["# dist manifest -- regenerate with: python ctest/make_release.py",
             f"# files: {len(entries)}", ""]
    for rel, digest in sorted(entries):
        lines.append(f"{digest}  {rel}")
    with open(os.path.join(OUT, "MANIFEST.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true",
                   help="report what would change without writing anything")
    a = p.parse_args()
    sys.exit(build(a.check))


if __name__ == "__main__":
    main()
