"""Launch FM26 with the packaged read-only memory bridge on macOS."""

import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading

if sys.platform == "darwin":
    import fcntl

import paths

_LOCK = threading.Lock()
_STARTED = None
SOCKET_PATH = "/tmp/fmsh_mem_bridge.sock"


def game_running():
    result = subprocess.run(
        ["pgrep", "-x", "fm|Football Manager|Football Manager 26"],
        capture_output=True, text=True, timeout=3,
    )
    if result.returncode not in (0, 1):
        raise OSError("Cannot check whether Football Manager is running")
    return result.returncode == 0


def find_game():
    steam = Path.home() / "Library/Application Support/Steam"
    libraries = [steam]
    try:
        config = (steam / "steamapps/libraryfolders.vdf").read_text()
        libraries.extend(Path(value.replace("\\\\", "\\")) for value in
                         re.findall(r'"path"\s+"([^"\n]+)"', config))
    except OSError:
        pass
    for library in libraries:
        executable = library / "steamapps/common/Football Manager 26/fm.app/Contents/MacOS/Football Manager 26"
        if executable.is_file() and os.access(executable, os.X_OK):
            return executable
    return None


def find_bridge():
    for candidate in (Path(paths.resource_path("..", "native", "libfmsh_bridge.dylib")),
                      Path(paths.app_dir()) / "native/libfmsh_bridge.dylib"):
        if candidate.is_file():
            return candidate.resolve()
    return None


def bridge_active():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        try:
            client.connect(SOCKET_PATH)
            return True
        except (FileNotFoundError, ConnectionRefusedError):
            return False
        # Other errors are handled by launch_game: do not replace an unknown socket.


def launch_game():
    """Never quit FM or launch a second instance; preserve an active bridge."""
    if sys.platform != "darwin":
        return {"ok": False, "error_code": "unsupported_platform"}
    with _LOCK:
        try:
            with open(paths.local_data_path("game-launch.lock"), "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                return _launch_locked()
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "error_code": "launch_failed"}


def _launch_locked():
    global _STARTED
    try:
        if (_STARTED is not None and _STARTED.poll() is None) or game_running():
            return {"ok": False, "error_code": "game_running"}
        if bridge_active():
            return {"ok": False, "error_code": "bridge_busy"}
        game = find_game()
        if game is None:
            return {"ok": False, "error_code": "game_not_found"}
        bridge = find_bridge()
        if bridge is None:
            return {"ok": False, "error_code": "bridge_missing"}
        env = dict(os.environ, DYLD_INSERT_LIBRARIES=str(bridge))
        _STARTED = subprocess.Popen(
            [str(game)], env=env, cwd=str(game.parent), start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            _STARTED.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            return {"ok": True, "started": True, "pid": _STARTED.pid}
        return {"ok": False, "error_code": "launch_failed"}
    except (OSError, subprocess.SubprocessError):
        return {"ok": False, "error_code": "launch_failed"}


if __name__ == "__main__":
    import json
    result = launch_game()
    print(json.dumps(result))
    raise SystemExit(0 if result["ok"] else 1)
