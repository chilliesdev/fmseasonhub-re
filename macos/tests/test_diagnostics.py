"""Issue #29: measured diagnostics, error evidence and the shipped page contract."""

from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
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

import diagnostics
import paths
import server
import settings
import uvicorn


class DiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listener = socket.socket()
        cls.listener.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.listener.getsockname()[1]}"
        cls.srv = uvicorn.Server(uvicorn.Config(server.app, log_level="critical"))
        cls.thread = threading.Thread(target=cls.srv.run, kwargs={"sockets": [cls.listener]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while not cls.srv.started and cls.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not cls.srv.started:
            raise RuntimeError("Diagnostics test server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fmsh-diagnostics-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / "fm26_snapshots.db"
        self.log = self.root / "fmsh.log"
        for module, name, value in (
            (paths, "_DATA_ROOT", str(self.root)), (paths, "_LOCAL_ROOT", str(self.root)),
            (settings, "SETTINGS_PATH", str(self.root / "settings.json")),
            (server, "_LIVE_STATUS", dict(server._EMPTY_LIVE_STATUS)),
        ):
            mocked = patch.object(module, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        diagnostics.ERROR_HANDLER.recent.clear()
        self.addCleanup(diagnostics.ERROR_HANDLER.recent.clear)

    def request(self, route="/api/diagnostico", body=None):
        request = urllib.request.Request(self.base + route,
                                         data=None if body is None else json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read().decode()
            try:
                return response.status, json.loads(content)
            except ValueError:
                return response.status, content

    def fixture(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO snapshots(name) VALUES ('QA season')")
            conn.execute("INSERT INTO players(snapshot_id,uid,full_name) VALUES (1,42,'QA player')")
        self.log.write_text("2026-10-25 App started\n", encoding="utf-8")

    def run_report(self, lang="en"):
        status, started = self.request(f"/api/diagnostico/completo?lang={lang}", {})
        self.assertEqual(status, 200)
        self.assertTrue(started["ok"])
        status, result = self.request("/api/diagnostico/completo")
        self.assertEqual(status, 200)
        self.assertEqual(result["em"], started["em"])
        return result

    def test_status_measures_environment_database_and_live_state_without_writes(self):
        self.fixture()
        before = self.database.read_bytes()
        server._LIVE_STATUS.update(ready=True, save_name="QA save")
        settings.save(fm_origem="epic", fm_origem_em="2026-10-25")
        status, result = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(result["python"], diagnostics.platform.python_version())
        self.assertIn(diagnostics.platform.system(), result["so"])
        self.assertEqual(result["pasta_dados"], str(self.root))
        self.assertTrue(result["fm_conectado"])
        self.assertEqual(result["save"], "QA save")
        self.assertEqual(result["fm_origem"], "epic")
        bank = result["banco"]
        self.assertEqual(bank["caminho"], str(self.database))
        self.assertEqual(bank["tamanho"], len(before))
        self.assertTrue(bank["ok"])
        self.assertEqual(bank["snapshots"], 1)
        self.assertEqual(bank["jogadores"], 1)
        self.assertEqual(bank["integridade"], "ok")
        self.assertEqual(result["log"]["linhas"], ["2026-10-25 App started"])
        self.assertEqual(self.database.read_bytes(), before)
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO snapshots(name) VALUES ('QA next')")
        self.assertEqual(self.request()[1]["banco"]["snapshots"], 2)

    def test_missing_corrupt_and_incomplete_databases_are_not_created_or_repaired(self):
        settings.save(db_dir=str(self.root / "missing-folder"))
        result = self.request()[1]
        self.assertFalse(result["banco"]["ok"])
        self.assertIn("FileNotFoundError", result["banco"]["erro"])
        self.assertFalse((self.root / "missing-folder").exists())
        self.assertFalse(self.run_report()["ok"])
        settings.save(db_dir=None)
        self.database.write_bytes(b"broken SQLite database")
        before = self.database.read_bytes()
        self.assertFalse(self.request()[1]["banco"]["ok"])
        report = self.run_report()
        self.assertIn("file is not a database", report["texto"])
        self.assertFalse(report["ok"])
        self.assertEqual(self.database.read_bytes(), before)
        self.database.unlink()
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("CREATE TABLE snapshots(id INTEGER)")
        before = self.database.read_bytes()
        result = self.request()[1]
        self.assertIn("missing columns", result["banco"]["erro"])
        self.assertEqual(self.database.read_bytes(), before)

    def test_locked_database_returns_a_failure_instead_of_crashing(self):
        self.fixture()
        with closing(sqlite3.connect(self.database)) as conn:
            conn.execute("BEGIN EXCLUSIVE")
            status, result = self.request()
            self.assertEqual(status, 200)
            self.assertFalse(result["banco"]["ok"])
            self.assertIn("locked", result["banco"]["erro"])

    def test_reports_retain_measured_results_and_survive_a_new_process(self):
        self.fixture()
        initial = self.request("/api/diagnostico/completo")[1]
        self.assertIsNone(initial["em"])
        self.assertEqual(initial["estado"], "idle")
        report = self.run_report()
        self.assertTrue(report["ok"])
        self.assertEqual(Path(report["arquivo"]).read_text(), report["texto"])
        self.assertEqual(report["relatorio"], report["texto"])
        self.assertEqual("\n".join(line["t"] for line in report["linhas"]), report["texto"])
        self.assertIn("Snapshots: 1; players: 1", report["texto"])
        self.log.write_text("ERROR persisted SQL failure\n", encoding="utf-8")
        self.assertEqual(self.request("/api/diagnostico/completo")[1], report)
        env = dict(os.environ, FMSH_PASTA_DADOS=str(self.root), FMSH_PASTA_LOCAL=str(self.root),
                   PYTHONPATH=str(Path(server.__file__).parent))
        completed = subprocess.run([sys.executable, "-c", "import diagnostics,json; print(json.dumps(diagnostics.load_report()))"],
                                   env=env, capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(json.loads(completed.stdout), report)
        new = self.run_report("pt")
        self.assertNotEqual(new["em"], report["em"])
        self.assertFalse(new["ok"])
        self.assertIn("BANCO DE DADOS", new["texto"])
        self.assertIn("ERROR persisted SQL failure", new["texto"])

    def test_real_sql_exception_is_logged_and_reported_after_http_failure(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY,name TEXT)")
        self.assertEqual(self.request("/api/snapshots")[0], 500)
        result = self.request()[1]
        self.assertTrue(any("no such column: created_at" in line for line in result["log"]["linhas"]))
        self.assertIn("Request failed: GET /api/snapshots", self.log.read_text())
        report = self.run_report()
        self.assertFalse(report["ok"])
        self.assertIn("OperationalError", report["texto"])
        self.assertTrue(any(line["e"] == "erro" for line in report["linhas"]))

    def test_existing_missing_unreadable_and_large_logs_are_truthful(self):
        self.fixture()
        self.log.write_text("Old line\n" * 300 + "ERROR prior launch failure\n")
        log = self.request()[1]["log"]
        self.assertEqual(len(log["linhas"]), 200)
        self.assertEqual(log["erros"], 1)
        self.assertFalse(self.run_report()["ok"])
        self.log.unlink()
        log = self.request()[1]["log"]
        self.assertIn("FileNotFoundError", log["erro"])
        self.assertFalse(self.run_report()["ok"])
        self.log.mkdir()
        log = self.request()[1]["log"]
        self.assertIn("IsADirectoryError", log["erro"])
        self.assertFalse(self.run_report()["ok"])
        try:
            raise sqlite3.OperationalError("QA failed write while log unavailable")
        except sqlite3.Error:
            server.logger.exception("QA database operation failed")
        self.assertIn("QA failed write while log unavailable", self.run_report()["texto"])

    def test_failed_report_save_returns_error_and_preserves_previous_result(self):
        self.fixture()
        report = self.run_report()
        with patch.object(Path, "replace", side_effect=PermissionError("QA report folder is read-only")):
            self.assertEqual(self.request("/api/diagnostico/completo?lang=en", {})[0], 500)
        self.assertEqual(self.request("/api/diagnostico/completo")[1], report)
        self.assertEqual(len(list(self.root.glob("diagnostico-*.txt"))), 1)

    def test_shipped_renderer_accepts_real_status_and_report(self):
        self.fixture()
        self.log.write_text("ERROR QA existing failure\n")
        payload = {"status": self.request()[1], "report": self.run_report()}
        script = Path(__file__).with_name("diagnostics_ui.mjs")
        completed = subprocess.run(["node", str(script)], input=json.dumps(payload),
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Diagnostics renderer regressions passed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
