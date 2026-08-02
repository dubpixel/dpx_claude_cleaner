#!/usr/bin/env bash
# ================================================================================
# BASH SCRIPT - Deploy dpx_claude_cleaner to ~/scr and alias it as zazzle
# ================================================================================
# PROJECT: dpx_claude_cleaner (formerly cc-sessions)
# ================================================================================
#
# File: scripts/deploy_local.sh
# Purpose: Copy the current src/dpx_claude_Cleaner.py to ~/scr/zazzle,
#          mark it executable, and wire up a `zazzle` shell alias so
#          it's runnable from anywhere.
# Dependencies: bash; detects zsh or bash to pick an rc file for the alias
#
# ================================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$PROJECT_ROOT/src/dpx_claude_Cleaner.py"
DEST_DIR="$HOME/scr"
DEST="$DEST_DIR/zazzle"
ALIAS_LINE="alias zazzle=\"$DEST\""

# Pick an rc file based on the user's actual login shell, not the shell
# this script happens to be run under -- deploy_local.sh is always
# invoked via `bash scripts/deploy_local.sh` or `./scripts/deploy_local.sh`
# regardless of whether the user's daily shell is zsh or bash.
case "$(basename "${SHELL:-}")" in
    zsh)
        RC_FILE="$HOME/.zshrc"
        ;;
    bash)
        if [ -f "$HOME/.bashrc" ]; then
            RC_FILE="$HOME/.bashrc"
        else
            RC_FILE="$HOME/.bash_profile"
        fi
        ;;
    *)
        RC_FILE=""
        ;;
esac

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

if [ -z "$RC_FILE" ]; then
    echo "unrecognized shell (\$SHELL=${SHELL:-unset}) -- not adding an alias automatically."
    echo "add this line to your shell's rc file yourself:"
    echo "  $ALIAS_LINE"
elif grep -qF "alias zazzle=" "$RC_FILE" 2>/dev/null; then
    echo "alias zazzle already present in $RC_FILE (left as-is)"
else
    {
        echo ""
        echo "# dpx_claude_cleaner (added by scripts/deploy_local.sh)"
        echo "$ALIAS_LINE"
    } >> "$RC_FILE"
    echo "added alias to $RC_FILE"
fi

if [ -n "$RC_FILE" ]; then
    echo "run 'source $RC_FILE' (or open a new shell), then use: zazzle"
else
    echo "then open a new shell (or source your rc file), and use: zazzle"
fi
