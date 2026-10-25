"""Career settings must survive new requests and fresh server processes (issue #14)."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
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


class CareerPreferencesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fmsh-career-preferences-")
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
            """, [(901, "Alpha old", "2027-05-30", "squad", "qa_alpha"),
                  (902, "Alpha new", "2028-05-30", "full", "qa_alpha"),
                  (903, "Beta", "2027-05-30", "leagues", "qa_beta")])
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
                self.request("/api/carreiras")
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

    def request(self, route, body=None, method=None, status=200):
        request = urllib.request.Request(
            self.base + route, data=None if body is None else json.dumps(body).encode(),
            method=method, headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, status)
            return json.load(response)

    def update(self, career, **prefs):
        return self.request(f"/api/carreiras/{career}", prefs, "PUT")

    def select(self, career):
        result = self.request("/api/carreiras/ativa", {"id": career})
        self.assertEqual(result["ativa"], career)
        self.assertEqual([row["id"] for row in result["carreiras"] if row["ativa"]], [career])
        return result

    def test_defaults_and_existing_saved_preferences(self):
        self.start()
        initial = self.request("/api/carreiras")
        self.assertEqual(initial["ativa"], "qa_alpha")
        self.assertEqual(initial["prefs"], {"moeda": 1, "periodo_salario": "week"})
        self.assertEqual({row["id"]: row["nome"] for row in initial["carreiras"]},
                         {"qa_alpha": "Qa Alpha", "qa_beta": "Qa Beta"})
        self.stop()
        self.settings_path.write_text(json.dumps({
            "carreira_ativa": "qa_beta", "carreiras": {
                "qa_beta": {"nome": "Saved beta", "moeda": 3, "periodo_salario": "year"},
            },
        }))
        self.start()
        result = self.request("/api/carreiras")
        self.assertEqual(result["ativa"], "qa_beta")
        self.assertEqual(result["prefs"], {"moeda": 3, "periodo_salario": "year"})
        self.assertEqual(next(row["nome"] for row in result["carreiras"]
                              if row["id"] == "qa_beta"), "Saved beta")

    def test_names_active_selection_and_independent_preferences_survive_restart(self):
        self.start()
        self.request("/api/settings/memoria", {"mb": 1536})
        self.update("qa_alpha", nome="QA Renamed · São Paulo", moeda=2, periodo_salario="month")
        self.assertEqual(self.request("/api/carreiras")["prefs"],
                         {"moeda": 2, "periodo_salario": "month"})
        self.assertEqual(self.select("qa_beta")["prefs"],
                         {"moeda": 1, "periodo_salario": "week"})
        self.update("qa_beta", nome="Other career", moeda=3, periodo_salario="year")
        expected = self.request("/api/carreiras")
        self.assertEqual(expected["prefs"], {"moeda": 3, "periodo_salario": "year"})
        self.assertEqual({row["id"]: row["nome"] for row in expected["carreiras"]},
                         {"qa_alpha": "QA Renamed · São Paulo", "qa_beta": "Other career"})
        self.restart()
        self.assertEqual(self.request("/api/carreiras"), expected)
        self.assertEqual(self.select("qa_alpha")["prefs"],
                         {"moeda": 2, "periodo_salario": "month"})
        self.restart()
        self.assertEqual(self.request("/api/carreiras")["ativa"], "qa_alpha")
        saved = json.loads(self.settings_path.read_text())
        self.assertEqual(saved["memoria_max_mb"], 1536)
        self.assertEqual(saved["carreiras"]["qa_alpha"],
                         {"nome": "QA Renamed · São Paulo", "moeda": 2, "periodo_salario": "month"})

    def test_partial_null_and_empty_updates_preserve_other_fields_and_settings(self):
        self.settings_path.write_text(json.dumps({"idioma": "en", "carreiras": {
            "qa_alpha": {"colunas": ["name"], "moeda": 2, "periodo_salario": "month"},
            "qa_beta": {"nome": "Keep beta", "moeda": 3},
        }}))
        self.start()
        self.update("qa_alpha", nome="Name only")
        expected = json.loads(self.settings_path.read_text())
        self.update("qa_alpha")
        self.update("qa_alpha", nome=None, moeda=None, periodo_salario=None)
        self.assertEqual(json.loads(self.settings_path.read_text()), expected)
        self.assertEqual(expected["carreiras"]["qa_alpha"], {
            "nome": "Name only", "colunas": ["name"], "moeda": 2, "periodo_salario": "month",
        })
        self.assertEqual(expected["carreiras"]["qa_beta"], {"nome": "Keep beta", "moeda": 3})
        self.assertEqual(expected["idioma"], "en")

    def test_unknown_career_mutations_do_not_change_saved_settings(self):
        self.start()
        self.update("qa_alpha", nome="Keep")
        before = self.settings_path.read_bytes()
        self.request("/api/carreiras/missing", {"nome": "Lost"}, "PUT", status=404)
        self.request("/api/carreiras/ativa", {"id": "missing"}, status=404)
        self.assertEqual(self.settings_path.read_bytes(), before)

    def test_parallel_partial_updates_do_not_erase_each_other(self):
        self.start()
        updates = [(career, {field: value}) for career in ("qa_alpha", "qa_beta")
                   for field, value in (("nome", career), ("moeda", 2), ("periodo_salario", "month"))]
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda item: self.update(item[0], **item[1]), updates))
        self.restart()
        for career in ("qa_alpha", "qa_beta"):
            self.assertEqual(self.select(career)["prefs"], {"moeda": 2, "periodo_salario": "month"})
        saved = json.loads(self.settings_path.read_text())
        for career in ("qa_alpha", "qa_beta"):
            self.assertEqual(saved["carreiras"][career],
                             {"nome": career, "moeda": 2, "periodo_salario": "month"})

    def test_failed_write_does_not_publish_unsaved_preferences_or_selection(self):
        with patch.object(settings, "SETTINGS_PATH", str(self.settings_path)), patch.object(
            server, "get_db_path", return_value=self.database
        ):
            settings.save(carreira_ativa="qa_alpha", idioma="en")
            before = server.get_carreiras()
            original = self.settings_path.read_bytes()
            for mutation in (
                lambda: server.salvar_carreira_prefs("qa_alpha", server.CarreiraPrefsBody(
                    nome="Unsaved", moeda=2, periodo_salario="month")),
                lambda: server.ativar_carreira(server.CarreiraAtivaBody(id="qa_beta")),
            ):
                with patch.object(settings.os, "replace", side_effect=OSError("disk unavailable")):
                    with self.assertRaises(OSError):
                        mutation()
                self.assertEqual(server.get_carreiras(), before)
                self.assertEqual(self.settings_path.read_bytes(), original)
                self.assertFalse(Path(str(self.settings_path) + ".tmp").exists())

    def test_shipped_career_switch_updates_formatting_before_render(self):
        script = Path(__file__).with_name("career_preferences_ui.mjs")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Career preference renderer regressions passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
