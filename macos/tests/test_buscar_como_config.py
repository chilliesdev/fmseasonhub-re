"""Find-player defaults survive requests, restarts and rejected writes (issue #15)."""

from concurrent.futures import ThreadPoolExecutor
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
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import server
import settings


class BuscarComoConfigTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fmsh-search-preferences-")
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
        self.base = f"http://127.0.0.1:{port}/api/buscar-como/config"
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
                self.request()
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

    def request(self, body=None, status=200):
        request = urllib.request.Request(
            self.base, data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, status)
            return json.load(response)

    def test_reported_payload_and_every_option_survive_fresh_process(self):
        self.settings_path.write_text(json.dumps({"idioma": "en", "memoria_max_mb": 1536}))
        self.start()
        result = self.request({"tolIdx": 3, "pisoPct": 85, "minMinutos": 900})
        self.assertEqual(result, self.request())
        self.assertEqual({key: result[key] for key in ("tolIdx", "pisoPct", "minMinutos")},
                         {"tolIdx": 3, "pisoPct": 85, "minMinutos": 900})
        changed = {"tolIdx": 5, "modo": "pct", "fora": 4, "pisoPct": 95,
                   "minMinutos": 1300, "valor": False, "idade": True, "contrato12": True,
                   "top20": True, "pe": True, "melhor": False, "pct": False}
        result = self.request(changed)
        self.assertEqual({key: result[key] for key in changed}, changed)
        # The shipped Preferences client sends the entire GET result back on save.
        self.assertEqual(self.request(result), result)
        self.stop()
        self.start()
        self.assertEqual(self.request(), result)
        saved = json.loads(self.settings_path.read_text())
        self.assertEqual(saved["buscar_como"], result)
        self.assertEqual(saved["idioma"], "en")
        self.assertEqual(saved["memoria_max_mb"], 1536)
        adapter = Path(__file__).with_name("buscar_como_preferences_ui.mjs")
        checked = subprocess.run(["node", str(adapter), json.dumps(result)],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_partial_empty_and_null_updates_preserve_saved_fields(self):
        self.settings_path.write_text(json.dumps({"buscar_como": {
            "pisoPct": 75, "minMinutos": 1100, "idade": True, "future_option": "keep",
        }, "idioma": "en"}))
        self.start()
        result = self.request({"top20": True})
        self.assertEqual(result["pisoPct"], 75)
        self.assertEqual(result["minMinutos"], 1100)
        self.assertTrue(result["idade"])
        before = self.settings_path.read_bytes()
        self.assertEqual(self.request({}), result)
        self.assertEqual(self.request({key: None for key in result}), result)
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertEqual(json.loads(before)["buscar_como"]["future_option"], "keep")

    def test_missing_and_legacy_invalid_values_use_safe_defaults_without_rewrite(self):
        self.start()
        defaults = self.request()
        self.assertEqual(defaults["pisoPct"], 85)
        self.assertEqual(defaults["minMinutos"], 900)
        self.assertIs(defaults["pe"], False)
        self.stop()
        for saved in ({"pe": 1024, "pisoPct": 95, "minMinutos": "bad", "modo": "bad"},
                      None, [], "bad"):
            with self.subTest(saved=saved):
                self.settings_path.write_text(json.dumps({"buscar_como": saved}))
                before = self.settings_path.read_bytes()
                self.start()
                expected = dict(defaults, pisoPct=95) if isinstance(saved, dict) else defaults
                self.assertEqual(self.request(), expected)
                self.assertEqual(self.settings_path.read_bytes(), before)
                self.stop()

    def test_boundaries_modes_and_false_switches_are_retained(self):
        self.start()
        for values in ({"tolIdx": 0, "fora": 0, "pisoPct": 60, "minMinutos": 300},
                       {"tolIdx": 5, "fora": 4, "pisoPct": 100, "minMinutos": 2000}):
            result = self.request(values)
            self.assertEqual({key: result[key] for key in values}, values)
        for mode in ("faixa", "melhor", "pct"):
            self.assertEqual(self.request({"modo": mode})["modo"], mode)
        for enabled in (True, False):
            values = {key: enabled for key in ("valor", "idade", "contrato12", "top20", "pe")}
            result = self.request(values)
            self.assertEqual({key: result[key] for key in values}, values)

    def test_invalid_requests_are_rejected_without_mutation(self):
        self.start()
        self.request({"pisoPct": 90})
        before = self.settings_path.read_bytes()
        invalid = [
            {"tolIdx": -1}, {"tolIdx": 6}, {"fora": -1}, {"fora": 5},
            {"pisoPct": 59}, {"pisoPct": 101}, {"minMinutos": 299}, {"minMinutos": 2001},
            {"modo": "bad"}, {"faixa": {}}, {"unknown": True},
        ]
        for key in ("tolIdx", "fora", "pisoPct", "minMinutos"):
            invalid.extend({key: value} for value in (True, "85", 1.5, [], {}))
        for key in ("valor", "idade", "contrato12", "top20", "pe", "melhor", "pct"):
            invalid.extend({key: value} for value in (1, "true", [], {}))
        for body in invalid:
            with self.subTest(body=body):
                self.request(dict(body, pisoPct=body.get("pisoPct", 95)), status=422)
                self.assertEqual(self.settings_path.read_bytes(), before)

    def test_concurrent_partial_updates_keep_all_fields(self):
        self.start()
        values = {"tolIdx": 4, "modo": "melhor", "fora": 3, "pisoPct": 95,
                  "minMinutos": 1700, "valor": False, "idade": True, "contrato12": True,
                  "top20": True, "pe": True}
        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(self.request, ({key: value} for key, value in values.items())))
        self.stop()
        self.start()
        result = self.request()
        self.assertEqual({key: result[key] for key in values}, values)

    def test_failed_atomic_write_keeps_previous_settings_and_effective_defaults(self):
        with patch.object(settings, "SETTINGS_PATH", str(self.settings_path)):
            settings.save(idioma="en", buscar_como={"pisoPct": 75, "pe": False})
            before = self.settings_path.read_bytes()
            expected = server.get_buscar_como_config()
            with patch.object(settings.os, "replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    server.save_buscar_como_config(server.BuscarComoConfigBody(pisoPct=95))
            self.assertEqual(server.get_buscar_como_config(), expected)
            self.assertEqual(self.settings_path.read_bytes(), before)
            self.assertFalse(Path(str(self.settings_path) + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
