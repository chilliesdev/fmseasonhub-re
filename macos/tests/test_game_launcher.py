"""Safe recovery launch: no user game, save or bridge is changed."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import game_launcher
import server


class GameLauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="fmsh-launch-")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.mock("_STARTED", None)
        self.mock("game_running", Mock(return_value=False))
        self.mock("bridge_active", Mock(return_value=False))
        self.mock("find_game", Mock(return_value=self.root / "Game with spaces"))
        self.mock("find_bridge", Mock(return_value=self.root / "libfmsh_bridge.dylib"))
        setting = patch.object(game_launcher.paths, "local_data_path", side_effect=lambda name: str(self.root / name))
        setting.start()
        self.addCleanup(setting.stop)

    def mock(self, name, value):
        setting = patch.object(game_launcher, name, value)
        setting.start()
        self.addCleanup(setting.stop)
        return value

    def test_open_game_is_not_closed_or_launched_and_socket_is_not_touched(self):
        game_launcher.game_running.return_value = True
        with patch.object(game_launcher.subprocess, "Popen") as spawn:
            self.assertEqual(game_launcher.launch_game()["error_code"], "game_running")
        spawn.assert_not_called()
        game_launcher.bridge_active.assert_not_called()

    def test_active_bridge_is_preserved(self):
        game_launcher.bridge_active.return_value = True
        with patch.object(game_launcher.subprocess, "Popen") as spawn:
            self.assertEqual(game_launcher.launch_game()["error_code"], "bridge_busy")
        spawn.assert_not_called()
        game_launcher.find_game.assert_not_called()

    def test_missing_game_bridge_and_spawn_error_are_actionable(self):
        for name, code in (("find_game", "game_not_found"), ("find_bridge", "bridge_missing")):
            with self.subTest(code=code), patch.object(game_launcher, name, return_value=None):
                self.assertEqual(game_launcher.launch_game()["error_code"], code)
        with patch.object(game_launcher.subprocess, "Popen", side_effect=OSError("denied")):
            self.assertEqual(game_launcher.launch_game()["error_code"], "launch_failed")

    def test_launch_uses_argument_array_and_packaged_bridge_only(self):
        process = Mock(pid=9876)
        process.wait.side_effect = subprocess.TimeoutExpired("game", 0.3)
        process.poll.return_value = None
        with patch.object(game_launcher.subprocess, "Popen", return_value=process) as spawn:
            self.assertEqual(game_launcher.launch_game(), {"ok": True, "started": True, "pid": 9876})
            args, options = spawn.call_args
            self.assertEqual(args, ([str(self.root / "Game with spaces")],))
            self.assertEqual(options["env"]["DYLD_INSERT_LIBRARIES"], str(self.root / "libfmsh_bridge.dylib"))
            self.assertTrue(options["start_new_session"])
            self.assertNotIn("shell", options)
            self.assertEqual(game_launcher.launch_game()["error_code"], "game_running")
            spawn.assert_called_once()

    def test_early_exit_and_process_discovery_failure_do_not_claim_success(self):
        with patch.object(game_launcher.subprocess, "Popen", return_value=Mock(pid=9876)):
            self.assertEqual(game_launcher.launch_game()["error_code"], "launch_failed")
        game_launcher._STARTED = None
        game_launcher.game_running.side_effect = OSError("cannot inspect processes")
        self.assertEqual(game_launcher.launch_game()["error_code"], "launch_failed")

    def test_windows_is_unchanged_and_never_launches(self):
        with patch.object(game_launcher.sys, "platform", "win32"), patch.object(game_launcher.subprocess, "Popen") as spawn:
            self.assertFalse(server.game_launcher_capabilities()["available"])
            self.assertEqual(game_launcher.launch_game()["error_code"], "unsupported_platform")
            spawn.assert_not_called()

    def test_additional_steam_library_path_with_spaces(self):
        library = self.root / "External Games"
        executable = library / "steamapps/common/Football Manager 26/fm.app/Contents/MacOS/Football Manager 26"
        executable.parent.mkdir(parents=True)
        executable.write_text("test")
        executable.chmod(0o755)
        config = self.root / "Library/Application Support/Steam/steamapps/libraryfolders.vdf"
        config.parent.mkdir(parents=True)
        config.write_text(f'"libraryfolders" {{ "1" {{ "path" "{library}" }} }}')
        with patch.object(game_launcher.Path, "home", return_value=self.root):
            # Bypass the per-test launch stub; exercise actual discovery below.
            from importlib.util import module_from_spec, spec_from_file_location
            spec = spec_from_file_location("launcher_discovery", game_launcher.__file__)
            module = module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.find_game(), executable)

    def test_packaged_bridge_paths_work_after_relocation(self):
        bridge = self.root / "New App.app/Contents/Frameworks/native/libfmsh_bridge.dylib"
        bridge.parent.mkdir(parents=True)
        bridge.write_bytes(b"fixture")
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("launcher_packaged", game_launcher.__file__)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.paths, "resource_path", return_value=str(bridge)), patch.object(module.paths, "app_dir", return_value=str(self.root)):
            self.assertEqual(module.find_bridge(), bridge.resolve())

    @unittest.skipUnless(sys.platform == "darwin", "Requires macOS injection")
    def test_launch_starts_real_injected_bridge_on_isolated_socket(self):
        with tempfile.TemporaryDirectory(prefix="fmsh-launch-native-", dir="/tmp") as folder:
            root = Path(folder)
            bridge = root / "libfmsh_bridge.dylib"
            address = str(root / "bridge.sock")
            native = Path(__file__).resolve().parents[1] / "native/libfmsh_bridge.c"
            subprocess.run(["clang", "-shared", "-O2", f'-DFMSH_SOCKET_PATH="{address}"',
                            str(native), "-o", str(bridge)], check=True, capture_output=True)
            executable = root / "Game with spaces"
            subprocess.run(["clang", "-x", "c", "-", "-o", str(executable)],
                           input=b"#include <unistd.h>\nint main(){sleep(15);return 0;}",
                           check=True, capture_output=True)
            game_launcher.find_game.return_value = executable
            game_launcher.find_bridge.return_value = bridge
            result = game_launcher.launch_game()
            process = game_launcher._STARTED
            try:
                self.assertTrue(result["ok"], result)
                deadline = time.monotonic() + 3
                while not Path(address).exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(2)
                    client.connect(address)
                    client.sendall(b"PING\n")
                    self.assertEqual(client.recv(32), b"PONG\n")
                    client.sendall(f"ATTACH {process.pid}\n".encode())
                    self.assertEqual(client.recv(32), b"OK\n")
            finally:
                if process is not None:
                    process.terminate()
                    process.wait(timeout=3)

    def test_shipped_renderer(self):
        result = subprocess.run(["node", str(Path(__file__).with_name("game_launcher_ui.mjs"))], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
