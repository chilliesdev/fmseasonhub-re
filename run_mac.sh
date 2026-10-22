#!/usr/bin/env bash
# ==============================================================================
# FM Season Hub - macOS Launcher Script
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/macos" ]; then
    MACOS_DIR="$SCRIPT_DIR/macos"
else
    MACOS_DIR="$SCRIPT_DIR"
fi
SRC_DIR="$MACOS_DIR/src"

echo "=== Launching FM Season Hub on macOS ==="

# 1. Locate Python 3.14 runtime
PYTHON_BIN=""

if [ -f "$MACOS_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$MACOS_DIR/.venv/bin/python"
elif [ -f "/opt/homebrew/bin/python3.14" ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3.14"
elif command -v python3.14 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.14)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: Python 3.14 executable not found."
    echo "Please install Python 3.14 via: brew install python@3.14"
    exit 1
fi

echo "Using Python runtime: $PYTHON_BIN ($($PYTHON_BIN --version))"

# 2. Configure Python Path
export PYTHONPATH="$SRC_DIR:$PYTHONPATH"
export PYTHONUNBUFFERED=1

# 3. Determine Entrypoint
TARGET_SCRIPT="$SRC_DIR/app_main.py"
echo "Starting FM Season Hub: $TARGET_SCRIPT"

# 4. Execute
exec "$PYTHON_BIN" "$TARGET_SCRIPT" "$@"
