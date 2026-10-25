"""Issue #30: Settings must describe the native macOS capabilities."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import bandeja_estado
import inicio_windows
import server
import settings
import uvicorn


class MacOSAppSettingsTests(unittest.TestCase):
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
            raise RuntimeError("Settings test HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fmsh-app-settings-")
        self.addCleanup(folder.cleanup)
        self.config = Path(folder.name) / "settings.json"
        mocked = patch.object(settings, "SETTINGS_PATH", str(self.config))
        mocked.start()
        self.addCleanup(mocked.stop)

    def request(self, body=None):
        request = urllib.request.Request(self.base + "/api/settings/bandeja",
                                         data=None if body is None else json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_macos_reports_effective_capabilities_without_rewriting_legacy_preferences(self):
        settings.save(ao_fechar="perguntar", bandeja={"ao_fechar": "bandeja",
                      "icone_ativo": True, "iniciar_com_windows": True, "keep": "value"})
        before = self.config.read_bytes()
        with patch.object(server.sys, "platform", "darwin"):
            status, result = self.request()
            self.assertEqual(status, 200)
            self.assertEqual(result["plataforma"], "darwin")
            self.assertEqual(result["ao_fechar"], "fechar")
            for key in ("icone_ativo", "iniciar_com_windows", "iniciar_disponivel"):
                self.assertIs(result[key], False)
            self.assertFalse(inicio_windows.disponivel())
        for mode in ("perguntar", "bandeja", "fechar"):
            self.assertEqual(bandeja_estado.decidir_fechamento(False, False, False, mode), "fechar")
        self.assertEqual(result["keep"], "value")
        self.assertEqual(self.config.read_bytes(), before)

    def test_unsupported_macos_controls_reject_writes_without_side_effects(self):
        settings.save(bandeja={"keep": True}, idioma="pt")
        before = self.config.read_bytes()
        with patch.object(server.sys, "platform", "darwin"):
            for body in ({"ao_fechar": "bandeja"}, {"ao_fechar": "fechar"},
                         {"iniciar_com_windows": True}, {"iniciar_com_windows": False, "keep": False}):
                with self.subTest(body=body):
                    status, result = self.request(body)
                    self.assertEqual(status, 400)
                    self.assertIn("macOS", result["detail"])
                    self.assertEqual(self.config.read_bytes(), before)

    def test_windows_contract_and_other_tray_preferences_remain_compatible(self):
        settings.save(bandeja={"keep": True, "ao_fechar": "perguntar"})
        with patch.object(server.sys, "platform", "win32"):
            status, result = self.request()
            self.assertEqual(status, 200)
            self.assertEqual(result["plataforma"], "win32")
            self.assertEqual(result["ao_fechar"], "perguntar")
            self.assertEqual(self.request({"ao_fechar": "bandeja", "iniciar_com_windows": True})[0], 200)
            self.assertTrue(self.request()[1]["iniciar_com_windows"])
        with patch.object(server.sys, "platform", "darwin"):
            self.assertEqual(self.request({"ligado": False})[0], 200)
        self.assertEqual(settings.load()["bandeja"], {"keep": True, "ao_fechar": "bandeja",
                         "iniciar_com_windows": True, "ligado": False})

    def test_shipped_settings_renderer_uses_host_capabilities_in_every_locale(self):
        with patch.object(server.sys, "platform", "darwin"):
            status, payload = self.request()
        self.assertEqual(status, 200)
        script = Path(__file__).with_name("macos_app_settings_ui.mjs")
        completed = subprocess.run(["node", str(script)], input=json.dumps(payload),
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("macOS Settings renderer regressions passed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
