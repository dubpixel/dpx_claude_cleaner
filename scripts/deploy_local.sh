#!/usr/bin/env bash
# ================================================================================
# BASH SCRIPT - Deploy dpx_claude_cleaner to ~/scr and alias it as dpx_ccleaner
# ================================================================================
# PROJECT: dpx_claude_cleaner (formerly cc-sessions)
# ================================================================================
#
# File: scripts/deploy_local.sh
# Purpose: Copy the current src/dpx_claude_Cleaner.py to ~/scr/dpx_ccleaner,
#          mark it executable, and wire up a `dpx_ccleaner` shell alias so
#          it's runnable from anywhere.
# Dependencies: bash, zsh (for the alias line)
#
# ================================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$PROJECT_ROOT/src/dpx_claude_Cleaner.py"
DEST_DIR="$HOME/scr"
DEST="$DEST_DIR/dpx_ccleaner"
RC_FILE="$HOME/.zshrc"
ALIAS_LINE="alias dpx_ccleaner=\"$DEST\""

if [ ! -f "$SRC" ]; then
    echo "error: $SRC not found" >&2
    exit 1
fi

VERSION="$(cat "$PROJECT_ROOT/VERSION" 2>/dev/null || echo "unknown")"

mkdir -p "$DEST_DIR"
cp "$SRC" "$DEST"
chmod +x "$DEST"

# The source script resolves __version__ from a sibling VERSION file two
# directories up (src/../VERSION) -- that path doesn't exist once deployed
# standalone to ~/scr, so bake the resolved version in as a literal instead.
python3 - "$DEST" "$VERSION" <<'PYEOF'
import re
import sys

dest, version = sys.argv[1], sys.argv[2]
text = open(dest).read()
pattern = re.compile(
    r"try:\n"
    r"    __version__ = .*?\n"
    r"except FileNotFoundError:\n"
    r"    __version__ = \"0\.0\.0-unknown\"\n",
    re.DOTALL,
)
patched, n = pattern.subn(f'__version__ = "{version}"  # baked in by deploy_local.sh\n', text)
if n != 1:
    print("warning: version block not patched (source format changed?) -- --version may be wrong", file=sys.stderr)
else:
    open(dest, "w").write(patched)
PYEOF

echo "deployed dpx_claude_cleaner v$VERSION -> $DEST"

if grep -qF "alias dpx_ccleaner=" "$RC_FILE" 2>/dev/null; then
    echo "alias dpx_ccleaner already present in $RC_FILE (left as-is)"
else
    {
        echo ""
        echo "# dpx_claude_cleaner (added by scripts/deploy_local.sh)"
        echo "$ALIAS_LINE"
    } >> "$RC_FILE"
    echo "added alias to $RC_FILE"
fi

echo "run 'source $RC_FILE' (or open a new shell), then use: dpx_ccleaner"
