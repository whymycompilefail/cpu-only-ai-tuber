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

It also rewrites the two things that leaked hardest, because the only finding
that survived the "source code only" boundary was inside a shell script:

    ctest/eval_model.sh:12
      PY="C:/Users/<you>/.workbuddy/binaries/python/versions/3.13.12/python.exe"

Files are read and written in BINARY mode. Text mode silently converts LF to
CRLF on Windows and produced a 1624-byte phantom diff in a bundle once already;
do not "fix" this back to open() defaults.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import shutil
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
# (source glob, destination subdir). Anything not matched is left behind.
INCLUDE: list[tuple[str, str]] = [
    # Our own tooling. The interesting part of this whole repo.
    ("ctest/*.py", "ctest"),
    ("ctest/*.sh", "ctest"),
    ("ctest/*.js", "ctest"),
    # The design specs: problem, measurement, verdict. Honest about what failed.
    ("specs/*.md", "specs"),
    # How to obtain every large asset without shipping one byte of them.
    ("ASSETS.md", "."),
    # The gate: nothing gets published until a real stream proved it works.
    ("RELEASE.md", "."),
    # Wiring/notes that make our fork of Open-LLM-VTuber reproducible.
    ("ctest/live.local.example.sh", "ctest"),
    # Referenced by ASSETS.md, so shipping without it ships a dead link. The
    # omission report below is what surfaced this.
    ("ctest/benchmark_model_choice.md", "ctest"),
    (".gitignore", "."),
]

# Sources worth asking about when they do NOT make it into dist. An allow-list
# fails closed, which is right for privacy but means new work silently stops
# shipping; this list is what turns that silence into a printed question.
WATCH_EXTS = {".py", ".sh", ".js", ".md", ".json", ".yaml", ".yml", ".txt"}
# Runtime output that is deliberately never published -- do not report it.
IGNORE_EXTS = {".log", ".wav", ".mp3", ".png", ".bac", ".bak"}

# Directories never copied even if a glob above would reach them.
EXCLUDE_DIRS = {"__pycache__", "data", "shots", "bn", "bt",
                "bin-base", "bin-gqa", "bin-tq"}

# Files never copied even if a glob matches. A broad `ctest/*.sh` picks up
# live.local.sh along with everything else, and that file holds the room id --
# it leaked into dist on the first real run and the verifier caught it.
# Keep this list paranoid: being listed here costs nothing, being absent leaks.
EXCLUDE_FILES = {
    "live.local.sh",
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
    """Return destination subdir if this file is allowed, else None."""
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return None
    if parts[-1] in EXCLUDE_FILES:
        return None
    for glob, dest in INCLUDE:
        if fnmatch.fnmatch(rel, glob):
            return dest
    return None


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
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDE_DIRS and d not in {".git", "dist"}]
        if os.path.abspath(dirpath).replace("\\", "/") == OUT:
            continue
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            dest = belongs(path)
            if dest is None:
                continue
            with open(path, "rb") as f:
                data = f.read()
            cleaned, fired = scrub(data)
            if fired:
                dirty.append((os.path.relpath(path, ROOT), fired))
            rel_out = f"{dest}/{fn}" if dest != "." else fn
            manifest.append((rel_out, hashlib.sha256(cleaned).hexdigest()[:12]))
            if not check_only:
                out_dir = os.path.join(OUT, dest)
                os.makedirs(out_dir, exist_ok=True)
                with open(os.path.join(out_dir, fn), "wb") as f:
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
    omitted = find_omitted()
    if omitted:
        print(f"\n{len(omitted)} source file(s) did NOT make it into dist:")
        for rel in omitted[:15]:
            print(f"  {rel}")
        if len(omitted) > 15:
            print(f"  ... +{len(omitted) - 15} more")
        print("  (expected for anything you deliberately excluded; intended for "
              "new work you forgot to allow)")

    if not check_only:
        write_manifest(manifest)
        print(f"\nwrote MANIFEST.txt ({len(manifest)} entries) "
              "-- its diff between releases is the release review")
        print(f"output: {OUT}")
        print(f"verify with: python ctest/scrub_scan.py --root {OUT}")
    return 0


def find_omitted() -> list[str]:
    """Source-looking files under ctest/ and specs/ that no allow rule matched."""
    out: list[str] = []
    for base in ("ctest", "specs"):
        d = os.path.join(ROOT, base)
        if not os.path.isdir(d):
            continue
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames[:] = [x for x in dirnames
                           if x not in EXCLUDE_DIRS and x != "__pycache__"]
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                ext = os.path.splitext(fn)[1].lower()
                if ext in IGNORE_EXTS or ext not in WATCH_EXTS:
                    continue
                if belongs(path) is None:
                    out.append(os.path.relpath(path, ROOT).replace("\\", "/"))
    return sorted(out)


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
