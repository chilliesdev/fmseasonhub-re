#!/bin/bash
# ==============================================================================
# launch_fm26_with_hub.sh - Easy Launcher for Football Manager 26 with FMSH Hub
# ==============================================================================
# Injects universal libfmsh_bridge.dylib into FM26 using DYLD_INSERT_LIBRARIES.
# Since fm.app has allow-dyld-environment-variables and disable-library-validation,
# injection works directly without sudo or disabling macOS SIP.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DYLIB_PATH="${SCRIPT_DIR}/native/libfmsh_bridge.dylib"
FM_PATH="/Users/apple/Library/Application Support/Steam/steamapps/common/Football Manager 26/fm.app/Contents/MacOS/Football Manager 26"
HUB_APP="${SCRIPT_DIR}/dist/FM Season Hub.app"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"
SOCK_PATH="/tmp/fmsh_mem_bridge.sock"

echo "=== Football Manager 26 + FM Season Hub Launcher ==="

# Check bridge dylib
if [ ! -f "$DYLIB_PATH" ]; then
    echo "[-] libfmsh_bridge.dylib not found at $DYLIB_PATH"
    echo "[*] Compiling universal dylib..."
    clang -arch arm64 -arch x86_64 -shared -O3 "${SCRIPT_DIR}/native/libfmsh_bridge.c" -o "$DYLIB_PATH"
fi

# Clean previous socket
rm -f "$SOCK_PATH"

# Check if FM26 is already running
FM_PID=$(pgrep -f "Football Manager 26" || true)

if [ -n "$FM_PID" ] && [ "$1" != "--launch-fm" ]; then
    echo "[+] Football Manager 26 is already running (PID: $FM_PID)."
    if [ -S "$SOCK_PATH" ]; then
        echo "[+] Memory bridge socket is active at $SOCK_PATH."
    else
        echo "[!] Memory bridge socket not found. To enable zero-privilege in-process bridge,"
        echo "    please restart FM26 using: $0 --launch-fm"
    fi
else
    echo "[*] Launching Football Manager 26 with in-process memory bridge..."
    if [ ! -f "$FM_PATH" ]; then
        echo "[-] FM26 executable not found at: $FM_PATH"
        exit 1
    fi

    # Launch FM26 with DYLD_INSERT_LIBRARIES
    DYLD_INSERT_LIBRARIES="$DYLIB_PATH" "$FM_PATH" &
    FM_LAUNCHED_PID=$!
    echo "[+] FM26 launched (PID: $FM_LAUNCHED_PID)."

    # Wait for memory bridge socket to initialize
    echo "[*] Waiting for memory bridge socket..."
    for i in {1..50}; do
        if [ -S "$SOCK_PATH" ]; then
            echo "[+] Memory bridge active at $SOCK_PATH!"
            break
        fi
        sleep 0.2
    done
fi

# Launch Hub Server / UI
if [ "$1" != "--fm-only" ]; then
    echo "[*] Launching FM Season Hub..."
    if [ -d "$HUB_APP" ]; then
        open "$HUB_APP"
    elif [ -f "${SCRIPT_DIR}/run_mac.sh" ]; then
        "${SCRIPT_DIR}/run_mac.sh" &
    else
        "$VENV_PYTHON" "${SCRIPT_DIR}/src/app_main.py" &
    fi
fi

echo "[+] Done. FM Season Hub is ready."
