"""Real HTTP connection contracts; controlled memory fixtures never read user saves."""

from datetime import date
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fm_memory
import fm_reader
import server
import uvicorn


class GameConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listener = socket.socket()
        cls.listener.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.listener.getsockname()[1]}"
        cls.srv = uvicorn.Server(uvicorn.Config(server.app, log_level="error"))
        cls.thread = threading.Thread(target=cls.srv.run, kwargs={"sockets": [cls.listener]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while not cls.srv.started and cls.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not cls.srv.started:
            raise RuntimeError("Connection test HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        server.parar_leitura_viva()
        self.addCleanup(server.parar_leitura_viva)
        self.mem = SimpleNamespace(process_id=1234, base=0x12340000,
                                   build="steam_macos_arm64", is_alive=Mock(return_value=True), close=Mock())
        self.reader = SimpleNamespace(save_session=Mock(return_value=("778899", 42)),
                                      game_date=Mock(return_value=date(2027, 6, 30)),
                                      save_loaded=Mock(return_value=True), save_name=Mock(return_value="QA career"))
        memory_patch = patch.object(server, "FmMemory", return_value=self.mem)
        self.memory_class = memory_patch.start()
        self.addCleanup(memory_patch.stop)
        reader_patch = patch.object(server, "FmReader", return_value=self.reader)
        self.reader_class = reader_patch.start()
        self.addCleanup(reader_patch.stop)

    def request(self, path, body=None):
        request = urllib.request.Request(self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def assert_disconnected(self, code=None):
        for route in ("/api/live", "/api/status"):
            status = self.request(route)
            self.assertFalse(status["ready"])
            for key in ("pid", "build", "savegame_id", "session_nonce", "read_at", "game_date", "club", "manager", "save_name"):
                self.assertIsNone(status[key], key)
            if code:
                self.assertEqual(status["error_code"], code)

    def test_packaged_game_launch_routes(self):
        self.assertEqual(self.request("/api/game/launcher"), {"platform": sys.platform, "available": sys.platform == "darwin"})
        with patch.object(server.game_launcher, "launch_game", return_value={"ok": False, "error_code": "game_running"}) as launch:
            self.assertEqual(self.request("/api/game/launch", {}), {"ok": False, "error_code": "game_running"})
            launch.assert_called_once_with()

    def test_closed_game_rejects_even_a_supplied_date(self):
        self.memory_class.side_effect = fm_memory.FmNotRunning("Open Football Manager and load a save.")
        result = self.request("/api/connect", {"game_date": "2030-01-01"})
        self.assertFalse(result["ok"])
        self.assertFalse(result["connected"])
        self.assertEqual(result["error_code"], "fm_closed")
        self.assertIn("load a save", result["error"])
        self.assert_disconnected("fm_closed")
        self.assertFalse(self.request("/api/status")["fm_running"])
        self.assertEqual(self.request("/api/job")["state"], "error")
        self.reader_class.assert_not_called()

    def test_missing_process_id_is_not_a_connection(self):
        self.mem.process_id = None
        self.assertEqual(self.request("/api/connect", {})["error_code"], "fm_closed")
        self.assert_disconnected("fm_closed")
        self.mem.close.assert_called_once_with()

    def test_attachment_errors_are_actionable(self):
        for error, code in ((fm_memory.FmAccessDenied("Use the Hub launcher."), "access_denied"),
                            (fm_memory.FmElevado("Restart FM without elevation."), "fm_elevated"),
                            (fm_memory.FmUnsupportedBuild("Use a supported FM build."), "unsupported_build")):
            with self.subTest(code=code):
                self.memory_class.side_effect = error
                result = self.request("/api/connect", {})
                self.assertFalse(result["connected"])
                self.assertEqual(result["error_code"], code)
                self.assertEqual(result["error"], str(error))
                self.assert_disconnected(code)

    def test_unreadable_memory_and_missing_base_are_rejected(self):
        self.mem.is_alive.return_value = False
        self.assertEqual(self.request("/api/connect", {})["error_code"], "access_denied")
        self.assert_disconnected("access_denied")
        self.mem.base = 0
        self.assertEqual(self.request("/api/connect", {})["error_code"], "unsupported_build")
        self.assert_disconnected("unsupported_build")

    def test_running_game_requires_a_loaded_save(self):
        for session, game_date, loaded in (((None, 0), date(2027, 6, 30), True),
                                          (("778899", 42), None, True),
                                          (("778899", 42), "2027-06-30", True),
                                          (("778899", 42), date(1999, 1, 1), True),
                                          (("778899", 42), date(2027, 6, 30), False)):
            with self.subTest(session=session, game_date=game_date, loaded=loaded):
                self.reader.save_session.return_value = session
                self.reader.game_date.return_value = game_date
                self.reader.save_loaded.return_value = loaded
                result = self.request("/api/connect", {"game_date": "2030-01-01"})
                self.assertEqual(result["error_code"], "no_save")
                self.assertFalse(result["connected"])
                self.assert_disconnected("no_save")
                self.assertTrue(self.request("/api/status")["fm_running"])

    def test_session_must_be_stable_during_connection(self):
        self.reader.save_session.side_effect = [("778899", 42), ("other", 99)]
        self.assertEqual(self.request("/api/connect", {})["error_code"], "no_save")
        self.assert_disconnected("no_save")

    def test_loaded_save_reports_verified_metadata_without_fake_identity(self):
        result = self.request("/api/connect", {"game_date": "2030-01-01"})
        self.assertEqual(result, {"ok": True, "connected": True, "started": False})
        self.reader_class.assert_called_once_with(self.mem)
        status = self.request("/api/live")
        self.assertTrue(status["ready"])
        self.assertTrue(status["fm_running"])
        self.assertEqual(status["pid"], 1234)
        self.assertEqual(status["build"], "steam_macos_arm64")
        self.assertEqual(status["game_date"], "2027-06-30")
        self.assertEqual(status["savegame_id"], "778899")
        self.assertEqual(status["session_nonce"], 42)
        self.assertEqual(status["save_name"], "QA career")
        self.assertTrue(status["read_at"])
        self.assertIsNone(status["club"])
        self.assertIsNone(status["manager"])
        self.assertIsNone(status["fm_version"])
        self.assertEqual(self.request("/api/job")["state"], "done")

    def test_failure_after_success_closes_and_clears_old_session(self):
        self.request("/api/connect", {})
        self.memory_class.side_effect = fm_memory.FmNotRunning("Open FM.")
        self.request("/api/connect", {})
        self.mem.close.assert_called_once_with()
        self.assert_disconnected("fm_closed")
        self.request("/api/connect", {})
        self.assert_disconnected("fm_closed")

    def test_disconnect_releases_memory_and_all_session_data(self):
        self.request("/api/connect", {})
        self.assertTrue(self.request("/api/disconnect", {})["disconnected"])
        self.mem.close.assert_called_once_with()
        self.assert_disconnected()
        self.assertEqual(self.request("/api/job")["state"], "idle")

    def test_status_detects_game_exit(self):
        self.request("/api/connect", {})
        self.mem.is_alive.return_value = False
        self.assert_disconnected()
        self.assertFalse(self.request("/api/status")["fm_running"])
        self.mem.close.assert_called_once_with()

    def test_status_detects_save_unload_and_save_change(self):
        for session, game_date in (((None, 0), None), (("other", 99), date(2027, 6, 30))):
            with self.subTest(session=session):
                self.reader.save_session.return_value = ("778899", 42)
                self.reader.game_date.return_value = date(2027, 6, 30)
                self.request("/api/connect", {})
                self.reader.save_session.return_value = session
                self.reader.game_date.return_value = game_date
                self.assert_disconnected()
                status = self.request("/api/status")
                self.assertTrue(status["fm_running"])
                self.assertTrue(status["save_changed"])

    def test_refresh_verifies_again_instead_of_fabricating_read_time(self):
        self.memory_class.side_effect = fm_memory.FmNotRunning("Open FM.")
        result = self.request("/api/refresh", {"game_date": "2030-01-01"})
        self.assertFalse(result["refreshed"])
        self.assertFalse(result["started"])
        self.assert_disconnected("fm_closed")
        self.memory_class.side_effect = None
        result = self.request("/api/refresh", {})
        self.assertTrue(result["refreshed"])
        self.assertFalse(result["started"])
        self.assertEqual(self.request("/api/status")["game_date"], "2027-06-30")
        self.assertIsNone(self.request("/api/job")["error_code"])

    def test_unknown_failure_is_not_success_and_releases_memory(self):
        self.reader_class.side_effect = RuntimeError("broken reader")
        self.assertEqual(self.request("/api/connect", {})["error_code"], "read_failed")
        self.assert_disconnected("read_failed")
        self.mem.close.assert_called_once_with()


class RealMemoryProbeRegressionTests(unittest.TestCase):
    def test_macos_detects_exact_game_executable_names(self):
        for executable in ("fm", "Football Manager", "Football Manager 26"):
            with self.subTest(executable=executable):
                def pgrep(command, timeout):
                    self.assertEqual(command[:2], ["pgrep", "-x"])
                    self.assertEqual(timeout, 3)
                    if command[2] == executable:
                        return b"82076\n"
                    raise subprocess.CalledProcessError(1, command)

                with patch.object(fm_memory.sys, "platform", "darwin"), \
                        patch.object(fm_memory.FmMemory, "_init_bridge_backend"), \
                        patch.object(fm_memory.FmMemory, "_try_socket_connect", return_value=False), \
                        patch.object(fm_memory.FmMemory, "_ensure_native_attached", return_value=True) as attach, \
                        patch.object(fm_memory.FmMemory, "_resolve_macos_module_base") as resolve, \
                        patch.object(fm_memory, "_log"), \
                        patch.object(fm_memory.subprocess, "check_output", side_effect=pgrep):
                    mem = fm_memory.FmMemory()
                    self.assertEqual(mem.process_id, 82076)
                    attach.assert_called_once_with()
                    resolve.assert_called_once_with()
                    mem.close()

    def test_macos_rejects_game_helpers_and_launchers(self):
        running_names = {"Football Manager 26 Helper", "launch_fm26_with_hub.sh"}

        def pgrep(command, timeout):
            self.assertEqual(command[:2], ["pgrep", "-x"])
            if command[2] in running_names:
                return b"82077\n"
            raise subprocess.CalledProcessError(1, command)

        with patch.object(fm_memory.sys, "platform", "darwin"), \
                patch.object(fm_memory.FmMemory, "_init_bridge_backend"), \
                patch.object(fm_memory.FmMemory, "_ensure_native_attached") as attach, \
                patch.object(fm_memory, "_log"), \
                patch.object(fm_memory.subprocess, "check_output", side_effect=pgrep):
            with self.assertRaises(fm_memory.FmNotRunning):
                fm_memory.FmMemory()
            attach.assert_not_called()

    def test_installed_plugin_does_not_count_as_running_game(self):
        with patch.object(fm_memory.sys, "platform", "darwin"), \
                patch.object(fm_memory.FmMemory, "_init_bridge_backend"), \
                patch.object(fm_memory, "_log"), \
                patch.object(fm_memory.os.path, "isfile", return_value=True), \
                patch.object(fm_memory.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, "pgrep")):
            with self.assertRaises(fm_memory.FmNotRunning):
                fm_memory.FmMemory()

    def test_missing_module_does_not_receive_a_guessed_address(self):
        mem = fm_memory.FmMemory.__new__(fm_memory.FmMemory)
        mem._bridge_socket = None
        mem.process_id = 1234
        mem.base = 0
        with patch.object(fm_memory.os.path, "isfile", return_value=False), \
                patch.object(fm_memory.subprocess, "check_output", return_value=b"no game module"), \
                patch.object(fm_memory, "_log"):
            with self.assertRaises(fm_memory.FmUnsupportedBuild):
                mem._resolve_macos_module_base()
        self.assertEqual(mem.base, 0)

    def test_unknown_save_name_stays_empty(self):
        reader = fm_reader.FmReader.__new__(fm_reader.FmReader)
        reader.cfg = {}
        self.assertIsNone(reader.save_name())
