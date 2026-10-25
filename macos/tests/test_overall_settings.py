"""Only supported Overall calculation modes can reach saved settings (issue #32)."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

SRC = Path(__file__).resolve().parents[1] / "src"


class OverallSettingsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fmsh-overall-settings-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.settings_path = self.data / "fmsh_settings.json"
        self.process = None
        self.addCleanup(self.stop)
        self.log = (self.root / "server.log").open("w+")
        self.addCleanup(self.log.close)

    def start(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        env = dict(os.environ, PYTHONPATH=str(SRC), FMSH_PASTA_DADOS=str(self.data),
                   FMSH_PASTA_LOCAL=str(self.root / "local"))
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
             "--port", str(port), "--log-level", "error"],
            cwd=SRC, env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self.process.poll() is None:
            try:
                self.request("/api/overall/modos")
                return
            except (OSError, urllib.error.URLError):
                time.sleep(0.03)
        self.log.seek(0)
        self.fail("Server did not start: " + self.log.read())

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None

    def request(self, route, body=None, method="GET", status=200):
        request = urllib.request.Request(
            self.base + route, method=method,
            data=json.dumps(body).encode() if method == "POST" else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, status)
            return json.load(response)

    def invalid_bodies(self):
        return [
            {"modo": value} for value in (
                "invalid-qa-mode", "", "MISTO", " misto ", "ca", None,
                0, 1.5, True, False, [], {},
            )
        ] + [{}, [], None, "misto"]

    def test_supported_modes_save_and_survive_restart_with_other_settings(self):
        unrelated = {"idioma": "en", "carreiras": {"qa": {"nome": "Keep"}},
                     "favoritos_listas": [{"id": "keep", "uids": [77]}]}
        self.settings_path.write_text(json.dumps(unrelated))
        self.start()
        modes = self.request("/api/overall/modos")
        self.assertEqual(modes, {"modos": ["atributos", "estatistica", "misto"],
                                 "padrao": "misto"})
        for mode in modes["modos"]:
            with self.subTest(mode=mode):
                self.assertEqual(self.request("/api/settings/overall", {"modo": mode}, "POST"),
                                 {"ok": True, "modo": mode})
                self.stop()
                self.start()
                expected = dict(unrelated, overall_modo=mode)
                for actual in (self.request("/api/settings"),
                               json.loads(self.settings_path.read_text())):
                    self.assertEqual({key: actual[key] for key in expected}, expected)

    def test_invalid_requests_keep_previous_valid_mode_and_saved_bytes(self):
        self.settings_path.write_text(json.dumps({"idioma": "en", "custom": {"keep": True}}))
        self.start()
        self.request("/api/settings/overall", {"modo": "estatistica"}, "POST")
        before = self.settings_path.read_bytes()
        for body in self.invalid_bodies():
            with self.subTest(body=body):
                result = self.request("/api/settings/overall", body, "POST", status=422)
                self.assertTrue(result["detail"])
                self.assertEqual(self.request("/api/settings")["overall_modo"], "estatistica")
                self.assertEqual(self.settings_path.read_bytes(), before)
        self.stop()
        self.start()
        self.assertEqual(self.request("/api/settings")["overall_modo"], "estatistica")
        self.assertEqual(self.settings_path.read_bytes(), before)

    def test_invalid_requests_do_not_create_settings_file(self):
        self.start()
        self.assertFalse(self.settings_path.exists())
        for body in self.invalid_bodies():
            with self.subTest(body=body):
                self.request("/api/settings/overall", body, "POST", status=422)
                self.assertFalse(self.settings_path.exists())
                self.assertEqual(self.request("/api/settings")["overall_modo"], "misto")


if __name__ == "__main__":
    unittest.main()
