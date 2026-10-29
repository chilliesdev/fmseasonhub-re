"""Tests for moving seasons across careers (issue #91).

Verify that moving a nonexistent season returns HTTP 404 with error detail
rather than falsely reporting success.
"""

from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import carreiras
import db
import server
import settings
import uvicorn


class SeasonMoveTests(unittest.TestCase):
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
            raise RuntimeError("HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="fmsh-season-move-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / "test.db"
        for target, name, value in (
            (server, "get_db_path", lambda: self.database),
            (settings, "SETTINGS_PATH", str(self.root / "settings.json")),
        ):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        db.init_db(str(self.database))
        self.seed()

    def seed(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.executemany(
                "INSERT INTO snapshots(id, name, game_date, scope, carreira_id) VALUES (?, ?, ?, ?, ?)",
                [
                    (101, "Season 1", "2026-05-30", "squad", "career_a"),
                    (102, "Season 2", "2027-05-30", "full", "career_a"),
                    (201, "Season Beta", "2026-05-30", "squad", "career_b"),
                ],
            )

    def request(self, route, method="POST", body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"{self.base}{route}", data=data, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read().decode("utf-8"))

    def test_move_nonexistent_season_post_returns_404(self):
        status, payload = self.request("/api/carreiras/career_b/temporadas/9999999", method="POST")
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("detail"), "Temporada nao encontrada")

    def test_move_nonexistent_season_put_returns_404(self):
        status, payload = self.request("/api/carreiras/career_b/temporadas/9999999", method="PUT")
        self.assertEqual(status, 404)
        self.assertEqual(payload.get("detail"), "Temporada nao encontrada")

    def test_move_live_season_returns_400(self):
        status, payload = self.request(f"/api/carreiras/career_b/temporadas/{server.LIVE_SNAPSHOT_ID}", method="POST")
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("detail"), "Temporada ao vivo nao pode ser movida")

    def test_move_live_season_put_returns_400(self):
        status, payload = self.request(f"/api/carreiras/career_b/temporadas/{server.LIVE_SNAPSHOT_ID}", method="PUT")
        self.assertEqual(status, 400)
        self.assertEqual(payload.get("detail"), "Temporada ao vivo nao pode ser movida")

    def test_move_existing_season_success(self):
        status, payload = self.request("/api/carreiras/career_b/temporadas/101", method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})

        with closing(server.get_db_connection()) as conn:
            row = conn.execute("SELECT carreira_id FROM snapshots WHERE id = 101").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["carreira_id"], "career_b")

    def test_move_existing_season_same_career_success(self):
        status, payload = self.request("/api/carreiras/career_a/temporadas/101", method="PUT")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})

        with closing(server.get_db_connection()) as conn:
            row = conn.execute("SELECT carreira_id FROM snapshots WHERE id = 101").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["carreira_id"], "career_a")

    def test_carreiras_mover_temporada_helper_contract(self):
        with closing(server.get_db_connection()) as conn:
            self.assertTrue(carreiras.mover_temporada(conn, 102, "career_c"))
            row = conn.execute("SELECT carreira_id FROM snapshots WHERE id = 102").fetchone()
            self.assertEqual(row["carreira_id"], "career_c")

            self.assertFalse(carreiras.mover_temporada(conn, 88888, "career_c"))


if __name__ == "__main__":
    unittest.main()
