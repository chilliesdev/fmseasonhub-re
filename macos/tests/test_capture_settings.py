"""Capture settings must reach their consumers and survive restarts (issue #16)."""

import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
from queue import Queue
import socket
import sqlite3
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

import db
import server
import settings


class CaptureSettingsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fmsh-capture-settings-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.settings_path = self.data / "fmsh_settings.json"
        self.database = self.root / "local" / "fm26_snapshots.db"
        self.database.parent.mkdir()
        db.init_db(str(self.database))
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executemany("""
                INSERT INTO snapshots(id,name,game_date,scope,carreira_id)
                VALUES(?,?,?,?,?)
            """, [(901, "Alpha", "2027-05-30", "squad", "qa_alpha"),
                  (902, "Beta", "2027-05-30", "full", "qa_beta")])
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
                   FMSH_PASTA_LOCAL=str(self.database.parent))
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
             "--port", str(port), "--log-level", "error"],
            cwd=SRC, env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self.process.poll() is None:
            try:
                self.request("/api/settings")
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

    def restart(self):
        self.stop()
        self.start()

    def request(self, route, body=None, status=200):
        request = urllib.request.Request(
            self.base + route, data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, status)
            return json.load(response)

    def test_issue_payloads_and_partial_updates_survive_restart(self):
        unrelated = {"idioma": "en", "carreiras": {"qa_alpha": {"nome": "Keep"}},
                     "favoritos_listas": [{"id": "keep", "uids": [77]}]}
        self.settings_path.write_text(json.dumps(unrelated))
        self.start()
        initial = self.request("/api/settings")
        self.assertTrue(initial["captura_som_ligado"])
        self.assertFalse(initial["auto_snapshot_ligado"])
        self.request("/api/settings/captura-som", {"ligado": False, "volume": 25})
        self.request("/api/settings/auto-snapshot", {
            "ligado": True, "nome": "QA {clube} {ano}", "vagas": "avisar",
        })
        expected = {"captura_som_ligado": False, "captura_som_volume": 25,
                    "auto_snapshot_ligado": True, "auto_snapshot_nome": "QA {clube} {ano}",
                    "auto_snapshot_vagas": "avisar", **unrelated}
        for values in (self.request("/api/settings"), json.loads(self.settings_path.read_text())):
            self.assertEqual({key: values[key] for key in expected}, expected)
            self.assertNotIn("captura_som", values)
            self.assertNotIn("auto_snapshot", values)
        self.request("/api/settings/auto-snapshot", {"vagas": "substituir"})
        self.request("/api/settings/captura-som", {"volume": 0})
        expected.update(auto_snapshot_vagas="substituir", captura_som_volume=0)
        self.restart()
        actual = self.request("/api/settings")
        self.assertEqual({key: actual[key] for key in expected}, expected)
        before = self.settings_path.read_bytes()
        for route in ("captura-som", "auto-snapshot"):
            self.request("/api/settings/" + route, {})
        self.assertEqual(self.settings_path.read_bytes(), before)

    def test_invalid_global_updates_leave_saved_values_unchanged(self):
        self.settings_path.write_text(json.dumps({"idioma": "en", "captura_som_volume": 25}))
        self.start()
        before = self.settings_path.read_bytes()
        invalid = {
            "captura-som": [{"volume": -1}, {"volume": 101}, {"volume": True},
                            {"volume": 25.5}, {"volume": "25"}, {"volume": None},
                            {"ligado": None}, {"ligado": "false"}, {"unknown": True}, []],
            "auto-snapshot": [{"ligado": None}, {"ligado": 1}, {"nome": None},
                              {"nome": 22}, {"nome": "x" * 61}, {"vagas": None},
                              {"vagas": "remove"}, {"modelo": "Unused"}, []],
        }
        for route, bodies in invalid.items():
            for body in bodies:
                with self.subTest(route=route, body=body):
                    self.request("/api/settings/" + route, body, status=422)
                    self.assertEqual(self.settings_path.read_bytes(), before)

    def test_career_dates_are_independent_and_reset_survives_restart(self):
        self.start()
        self.request("/api/settings/captura-som", {"volume": 25})
        for career, value in (("qa_alpha", "2028-06-01"), ("qa_beta", "2029-07-02")):
            self.assertEqual(self.request(f"/api/carreiras/{career}/auto-snapshot", {"data": value}),
                             {"ok": True, "data": value})
        expected = {"qa_alpha": "2028-06-01", "qa_beta": "2029-07-02"}
        self.restart()
        self.assertEqual(self.request("/api/settings")["auto_snapshot_datas"], expected)
        self.assertEqual(json.loads(self.settings_path.read_text())["auto_snapshot_datas"], expected)
        # An override is a preference, not proof that a game agenda was loaded.
        self.assertIsNone(self.request("/api/carreiras/qa_alpha/outras-ligas")["auto"])
        self.request("/api/carreiras/qa_alpha/auto-snapshot", {"data": None})
        self.restart()
        actual = self.request("/api/settings")
        self.assertEqual(actual["auto_snapshot_datas"], {"qa_beta": "2029-07-02"})
        self.assertEqual(actual["captura_som_volume"], 25)

    def test_bad_date_or_unknown_career_does_not_save(self):
        self.start()
        self.request("/api/settings/captura-som", {"ligado": False})
        before = self.settings_path.read_bytes()
        for value in ("", "2028-02-30", "20280601", "2028-06-01T00:00:00", 20280601, True):
            with self.subTest(value=value):
                self.request("/api/carreiras/qa_alpha/auto-snapshot", {"data": value}, status=422)
        self.request("/api/carreiras/qa_alpha/auto-snapshot", {}, status=422)
        self.request("/api/carreiras/missing/auto-snapshot", {"data": "2028-06-01"}, status=404)
        self.assertEqual(self.settings_path.read_bytes(), before)

    def test_parallel_partial_updates_preserve_all_settings_and_dates(self):
        self.start()
        updates = [
            ("/api/settings/auto-snapshot", {"ligado": True}),
            ("/api/settings/auto-snapshot", {"nome": "Parallel {ano}"}),
            ("/api/settings/auto-snapshot", {"vagas": "substituir"}),
            ("/api/settings/captura-som", {"ligado": False}),
            ("/api/settings/captura-som", {"volume": 15}),
            ("/api/carreiras/qa_alpha/auto-snapshot", {"data": "2028-06-01"}),
            ("/api/carreiras/qa_beta/auto-snapshot", {"data": "2029-07-02"}),
        ]
        with ThreadPoolExecutor(max_workers=len(updates)) as pool:
            list(pool.map(lambda item: self.request(*item), updates))
        self.restart()
        actual = self.request("/api/settings")
        expected = {"auto_snapshot_ligado": True, "auto_snapshot_nome": "Parallel {ano}",
                    "auto_snapshot_vagas": "substituir", "captura_som_ligado": False,
                    "captura_som_volume": 15,
                    "auto_snapshot_datas": {"qa_alpha": "2028-06-01", "qa_beta": "2029-07-02"}}
        self.assertEqual({key: actual[key] for key in expected}, expected)

    def test_failed_atomic_writes_do_not_publish_unsaved_settings(self):
        with patch.object(settings, "SETTINGS_PATH", str(self.settings_path)), patch.object(
            server, "get_db_path", return_value=self.database
        ):
            settings.save(idioma="en", auto_snapshot_datas={"qa_beta": "2029-07-02"})
            original = self.settings_path.read_bytes()
            expected = deepcopy(settings.load())
            defaults = deepcopy(settings.DEFAULTS)
            for mutation in (
                lambda: server.set_auto_snapshot(server.AutoSnapshotBody(ligado=True, nome="Unsaved")),
                lambda: server.set_captura_som(server.CapturaSomBody(ligado=False, volume=5)),
                lambda: server.set_carreira_auto_snapshot("qa_alpha", server.AutoSnapshotDataBody(data="2028-06-01")),
                lambda: server.set_carreira_auto_snapshot("qa_beta", server.AutoSnapshotDataBody(data=None)),
            ):
                with patch.object(settings.os, "replace", side_effect=OSError("disk unavailable")):
                    with self.assertRaises(OSError):
                        mutation()
                self.assertEqual(settings.load(), expected)
                self.assertEqual(self.settings_path.read_bytes(), original)
                self.assertEqual(settings.DEFAULTS, defaults)
                self.assertFalse(Path(str(self.settings_path) + ".tmp").exists())
            self.settings_path.unlink()
            with patch.object(settings.os, "replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    server.set_carreira_auto_snapshot("qa_alpha", server.AutoSnapshotDataBody(data="2028-06-01"))
            self.assertEqual(settings.DEFAULTS, defaults)
            self.assertEqual(settings.load()["auto_snapshot_datas"], {})

    def test_native_sound_consumer_reads_persisted_switch_and_volume(self):
        # Execute the real nested consumer without launching the desktop app/audio.
        tree = ast.parse((SRC / "app_main.py").read_text())
        function = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == "tocar_som")
        sounds = Queue()
        namespace = {"settings": settings, "fila_de_sons": sounds}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app_main.py", "exec"), namespace)
        with patch.object(settings, "SETTINGS_PATH", str(self.settings_path)):
            server.set_captura_som(server.CapturaSomBody(ligado=False, volume=25))
            namespace["tocar_som"]("captura")
            self.assertTrue(sounds.empty())
            namespace["tocar_som"]("preview", testar=True)
            self.assertEqual(sounds.get_nowait(), ("preview", 25))
            server.set_captura_som(server.CapturaSomBody(ligado=True))
            namespace["tocar_som"]("captura")
            self.assertEqual(sounds.get_nowait(), ("captura", 25))
            server.set_captura_som(server.CapturaSomBody(volume=0))
            namespace["tocar_som"]("captura")
            self.assertEqual(sounds.get_nowait(), ("captura", 0))


if __name__ == "__main__":
    unittest.main()
