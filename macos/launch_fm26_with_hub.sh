#!/bin/bash
# Development entrypoint. The installed app provides the same safe launch action.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    echo "Prepare macos/.venv as described in macos/README.md." >&2
    exit 1
fi
# The service refuses an open game and preserves any active bridge socket.
"$PYTHON_BIN" "$SCRIPT_DIR/src/game_launcher.py"
if [ "${1:-}" != "--fm-only" ]; then
    if [ -d "$SCRIPT_DIR/dist/FM Season Hub.app" ]; then
        open "$SCRIPT_DIR/dist/FM Season Hub.app"
    else
        "$SCRIPT_DIR/run_mac.sh" &
    fi
fi
