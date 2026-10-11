#!/usr/bin/env bash
# Wire the privacy checks into git itself, so they run on every future write
# rather than only on release day.
#
# Run this ONCE, right after `git init`:
#     bash ctest/install_hooks.sh
#
# It installs two hooks:
#   pre-commit  scans exactly what you staged   (fast; blocks the commit)
#   pre-push    rebuilds dist and scans it      (slow; blocks the push)
#
# Why this exists
# ---------------
# Scanning only before publishing protects one snapshot and nothing after it.
# Every later commit, every new log file and every new script is unscanned
# territory. Moving the same check into the commit and push steps means the
# guarantee is about *all future writes*, not about one well-chosen moment.
#
# Caveat: git does not push hooks to clones. These protect you locally; if this
# ever becomes a shared repo, put the same two commands in CI.

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$ROOT/.git" ]; then
    echo "no .git yet -- run this after 'git init':"
    echo "    cd $ROOT && git init"
    echo "    bash ctest/install_hooks.sh"
    exit 1
fi

HOOKS="$ROOT/.git/hooks"
mkdir -p "$HOOKS"

cat > "$HOOKS/pre-commit" <<'HOOK'
#!/usr/bin/env sh
# Installed by ctest/install_hooks.sh -- block personal data at commit time.
ROOT=$(git rev-parse --show-toplevel)
PY=""
for c in python python3 py; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
done
if [ -z "$PY" ]; then
    echo "pre-commit: no python found, skipping the privacy scan" >&2
    exit 0
fi
ROOM=""
LOCAL="$ROOT/ctest/live.local.sh"
[ -f "$LOCAL" ] && ROOM=$(sed -n 's/^BILI_ROOM_ID=\([0-9]\{1,\}\).*/\1/p' "$LOCAL" | head -1)
if [ -n "$ROOM" ]; then
    "$PY" "$ROOT/ctest/scrub_scan.py" --git-staged --room-id "$ROOM"
else
    "$PY" "$ROOT/ctest/scrub_scan.py" --git-staged
fi
if [ $? -ne 0 ]; then
    echo "" >&2
    echo "commit blocked: something above should not be published." >&2
    echo "bypass only if you are certain (you almost never are): git commit --no-verify" >&2
    exit 1
fi
HOOK

cat > "$HOOKS/pre-push" <<'HOOK'
#!/usr/bin/env sh
# Installed by ctest/install_hooks.sh -- prove dist is clean before it goes out.
ROOT=$(git rev-parse --show-toplevel)
PY=""
for c in python python3 py; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
done
if [ -z "$PY" ]; then
    echo "pre-push: no python found, skipping the dist scan" >&2
    exit 0
fi
"$PY" "$ROOT/ctest/make_release.py" || exit 1
ROOM=""
LOCAL="$ROOT/ctest/live.local.sh"
[ -f "$LOCAL" ] && ROOM=$(sed -n 's/^BILI_ROOM_ID=\([0-9]\{1,\}\).*/\1/p' "$LOCAL" | head -1)
if [ -n "$ROOM" ]; then
    "$PY" "$ROOT/ctest/scrub_scan.py" --root "$ROOT/dist" --room-id "$ROOM"
else
    "$PY" "$ROOT/ctest/scrub_scan.py" --root "$ROOT/dist"
fi
if [ $? -ne 0 ]; then
    echo "" >&2
    echo "push blocked: dist/ above public quality." >&2
    exit 1
fi
HOOK

chmod +x "$HOOKS/pre-commit" "$HOOKS/pre-push"
echo "installed:"
echo "  $HOOKS/pre-commit"
echo "  $HOOKS/pre-push"
echo
echo "test it with:"
echo "  git add -A && git commit -m 'test'   # pre-commit runs here"
