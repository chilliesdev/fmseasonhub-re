"""Unit and contract tests for live season snapshot handling (Issue #95)."""

from contextlib import closing
from datetime import date
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

import db
import portal_data
import server
import settings
import uvicorn


class LiveSnapshotTests(unittest.TestCase):
    LIVE_ID = portal_data.LIVE_SNAPSHOT_ID

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
            raise RuntimeError("Live snapshot test HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        server.parar_leitura_viva()
        self.addCleanup(server.parar_leitura_viva)

        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.settings_path = self.root / "fmsh_settings.json"
        self.database = self.root / "fm26_snapshots.db"

        self.settings_patch = patch.object(settings, "SETTINGS_PATH", str(self.settings_path))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

        self.database_patch = patch.object(server, "get_db_path", return_value=self.database)
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)

        db.init_db(str(self.database))

    def request(self, route, body=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + route,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def test_get_snapshot_live_connected_returns_metadata(self):
        live_data = dict(
            server._EMPTY_LIVE_STATUS,
            ready=True,
            fm_running=True,
            save_name="Chelsea - Maresca",
            game_date="2027-06-30",
            club="Chelsea",
            club_uid=630,
            manager="Enzo Maresca",
            savegame_id="save_chelsea_123",
            read_at="2027-06-30T12:00:00",
            build="steam_arm64",
        )
        with patch.object(server, "_LIVE_STATUS", live_data):
            status, snapshot = self.request(f"/api/snapshots/{self.LIVE_ID}")
            self.assertEqual(status, 200)
            self.assertEqual(snapshot["id"], self.LIVE_ID)
            self.assertTrue(snapshot["is_live"])
            self.assertTrue(snapshot["ready"])
            self.assertEqual(snapshot["club"], "Chelsea")
            self.assertEqual(snapshot["club_uid"], 630)
            self.assertEqual(snapshot["manager"], "Enzo Maresca")
            self.assertEqual(snapshot["save_name"], "Chelsea - Maresca")
            self.assertEqual(snapshot["game_date"], "2027-06-30")
            self.assertEqual(snapshot["n_players"], 0)

    def test_get_snapshot_live_disconnected_returns_404(self):
        with patch.object(server, "_LIVE_STATUS", dict(server._EMPTY_LIVE_STATUS, ready=False)):
            status, response = self.request(f"/api/snapshots/{self.LIVE_ID}")
            self.assertEqual(status, 404)
            self.assertIn("detail", response)

    def test_list_snapshots_includes_live_season_when_ready(self):
        live_data = dict(
            server._EMPTY_LIVE_STATUS,
            ready=True,
            save_name="Arsenal Career",
            game_date="2027-08-15",
            club="Arsenal",
            manager="Mikel Arteta",
            read_at="2027-08-15T10:00:00",
        )
        with patch.object(server, "_LIVE_STATUS", live_data):
            status, snapshots = self.request("/api/snapshots")
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(snapshots), 1)
            live_item = snapshots[0]
            self.assertEqual(live_item["id"], self.LIVE_ID)
            self.assertTrue(live_item["is_live"])
            self.assertEqual(live_item["club"], "Arsenal")

            # include_live=false excludes it
            status, no_live = self.request("/api/snapshots?include_live=false")
            self.assertEqual(status, 200)
            self.assertNotIn(self.LIVE_ID, [s["id"] for s in no_live])

    def test_live_snapshot_player_search_and_list_with_data(self):
        live_data = dict(
            server._EMPTY_LIVE_STATUS,
            ready=True,
            save_name="Chelsea - Cole Palmer",
            game_date="2027-06-30",
            club="Chelsea",
            club_uid=630,
            manager="Enzo Maresca",
            read_at="2027-06-30T12:00:00",
        )
        with patch.object(server, "_LIVE_STATUS", live_data):
            # Seed live season rows in database
            with closing(sqlite3.connect(self.database)) as conn, conn:
                conn.execute(
                    "INSERT INTO snapshots (id, name, scope, club_uid, game_date) VALUES (?, 'Live Season', 'live', 630, '2027-06-30')",
                    (self.LIVE_ID,),
                )
                conn.execute(
                    "INSERT INTO players (snapshot_id, uid, full_name, common_name, club_id, position) VALUES (?, 1001, 'Cole Palmer', 'Palmer', 630, 'AM (RC), ST')",
                    (self.LIVE_ID,),
                )
                conn.execute(
                    "INSERT INTO player_profile (snapshot_id, uid, guide_value, wage_weekly, contract_end) VALUES (?, 1001, 85000000, 150000, '2033-06-30')",
                    (self.LIVE_ID,),
                )
                conn.execute(
                    "INSERT INTO player_stats (snapshot_id, uid, apps_total, goals, assists, avg_rating) VALUES (?, 1001, 38, 22, 11, 7.65)",
                    (self.LIVE_ID,),
                )
                conn.execute(
                    "INSERT INTO players (snapshot_id, uid, full_name, common_name, club_id, position) VALUES (?, 1002, 'Enzo Fernandez', 'Enzo', 630, 'DM, M (C)')",
                    (self.LIVE_ID,),
                )

            # 1. Snapshot detail reports updated n_players
            status, snap = self.request(f"/api/snapshots/{self.LIVE_ID}")
            self.assertEqual(status, 200)
            self.assertEqual(snap["n_players"], 2)

            # 2. Snapshot list reports n_players=2
            status, snaps = self.request("/api/snapshots")
            self.assertEqual(status, 200)
            self.assertEqual(snaps[0]["n_players"], 2)

            # 3. List players
            status, players_resp = self.request(f"/api/snapshots/{self.LIVE_ID}/players")
            self.assertEqual(status, 200)
            self.assertIsInstance(players_resp, dict)
            self.assertIn("players", players_resp)
            self.assertEqual(len(players_resp["players"]), 2)

            # 4. Search for "Cole Palmer"
            status, search_resp = self.request(f"/api/snapshots/{self.LIVE_ID}/players?search=Cole%20Palmer")
            self.assertEqual(status, 200)
            self.assertEqual(len(search_resp["players"]), 1)
            player = search_resp["players"][0]
            self.assertEqual(player["uid"], 1001)
            self.assertEqual(player["full_name"], "Cole Palmer")
            self.assertEqual(player["goals"], 22)
            self.assertEqual(player["assists"], 11)
            self.assertEqual(player["value"], 85000000)
            self.assertEqual(player["wage"], 150000)

            # 5. Search for non-existent player
            status, empty_search = self.request(f"/api/snapshots/{self.LIVE_ID}/players?search=NonexistentPlayer")
            self.assertEqual(status, 200)
            self.assertEqual(empty_search["players"], [])

            # 6. Get single player detail
            status, p_detail = self.request(f"/api/snapshots/{self.LIVE_ID}/players/1001")
            self.assertEqual(status, 200)
            self.assertEqual(p_detail["full_name"], "Cole Palmer")
            self.assertEqual(p_detail["stats"]["goals"], 22)
            self.assertEqual(p_detail["identity"]["uid"], 1001)

            # 7. Get non-existent player
            status, not_found_p = self.request(f"/api/snapshots/{self.LIVE_ID}/players/999999")
            self.assertEqual(status, 404)

    def test_live_snapshot_players_disconnected_returns_404(self):
        with patch.object(server, "_LIVE_STATUS", dict(server._EMPTY_LIVE_STATUS, ready=False)):
            status, _ = self.request(f"/api/snapshots/{self.LIVE_ID}/players")
            self.assertEqual(status, 404)
            status, _ = self.request(f"/api/snapshots/{self.LIVE_ID}/players/1001")
            self.assertEqual(status, 404)

    def test_delete_live_snapshot_is_rejected(self):
        # Connected: HTTP 400
        live_data = dict(server._EMPTY_LIVE_STATUS, ready=True)
        with patch.object(server, "_LIVE_STATUS", live_data):
            status, resp = self.request(f"/api/snapshots/{self.LIVE_ID}", method="DELETE")
            self.assertEqual(status, 400)
            self.assertIn("nao pode ser apagada", resp["detail"])

        # Disconnected: HTTP 404
        with patch.object(server, "_LIVE_STATUS", dict(server._EMPTY_LIVE_STATUS, ready=False)):
            status, _ = self.request(f"/api/snapshots/{self.LIVE_ID}", method="DELETE")
            self.assertEqual(status, 404)

    def test_cannot_move_live_season_to_career(self):
        status, _ = self.request(f"/api/carreiras/career_alpha/temporadas/{self.LIVE_ID}", method="POST")
        self.assertEqual(status, 400)

    def test_stored_snapshots_unaffected_by_live_season(self):
        # Create stored season
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                "INSERT INTO snapshots (id, name, scope, carreira_id, game_date) VALUES (101, 'Season 2026/27', 'squad', 'qa_c', '2027-05-30')"
            )
            conn.execute(
                "INSERT INTO players (snapshot_id, uid, full_name, club_id) VALUES (101, 555, 'Stored Legend', 10)"
            )

        live_data = dict(server._EMPTY_LIVE_STATUS, ready=True, club="Live Club", game_date="2029-06-30")
        with patch.object(server, "_LIVE_STATUS", live_data):
            # Stored snapshot details
            status, snap = self.request("/api/snapshots/101")
            self.assertEqual(status, 200)
            self.assertEqual(snap["name"], "Season 2026/27")
            self.assertEqual(snap["n_players"], 1)

            # Stored snapshot players
            status, players_resp = self.request("/api/snapshots/101/players")
            self.assertEqual(status, 200)
            self.assertEqual(len(players_resp["players"]), 1)
            self.assertEqual(players_resp["players"][0]["full_name"], "Stored Legend")

            # Snapshots list includes both live and stored
            status, snaps = self.request("/api/snapshots")
            self.assertEqual(status, 200)
            ids = [s["id"] for s in snaps]
            self.assertEqual(ids, [self.LIVE_ID, 101])

        # Delete stored snapshot succeeds
        status, del_resp = self.request("/api/snapshots/101", method="DELETE")
        self.assertEqual(status, 200)
        status, not_found = self.request("/api/snapshots/101")
        self.assertEqual(status, 404)

    def test_clear_connection_cleans_up_live_database_rows(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO snapshots (id, name, scope) VALUES (?, 'Live Season', 'live')", (self.LIVE_ID,))
            conn.execute("INSERT INTO players (snapshot_id, uid, full_name) VALUES (?, 999, 'Temp Player')", (self.LIVE_ID,))

        server._clear_live_snapshot()

        with closing(sqlite3.connect(self.database)) as conn:
            snap_count = conn.execute("SELECT COUNT(*) FROM snapshots WHERE id=?", (self.LIVE_ID,)).fetchone()[0]
            player_count = conn.execute("SELECT COUNT(*) FROM players WHERE snapshot_id=?", (self.LIVE_ID,)).fetchone()[0]
            self.assertEqual(snap_count, 0)
            self.assertEqual(player_count, 0)

    def test_live_snapshot_sync_from_reader(self):
        mem = SimpleNamespace(
            process_id=9876,
            base=0x10000,
            build="steam_macos_arm64",
            fm_version="26.0.0",
            is_alive=Mock(return_value=True),
            close=Mock(),
        )
        reader = SimpleNamespace(
            save_session=Mock(return_value=("session_qa", 42)),
            save_loaded=Mock(return_value=True),
            game_date=Mock(return_value=date(2027, 6, 30)),
            save_name=Mock(return_value="Chelsea - Cole Palmer"),
            manager_club=Mock(return_value=(0x5000, 0x6000, "Chelsea FC", "CHE")),
            human_manager=Mock(return_value={"full_name": "Enzo Maresca"}),
            u32=Mock(return_value=630),
            roster=Mock(return_value=[0x20000]),
            jogador_do_elenco=Mock(return_value=0x20000),
            player_block=Mock(return_value=b"\x00" * 512),
            player_identity=Mock(return_value={
                "uid": 1001,
                "full_name": "Cole Palmer",
                "name_first": "Cole",
                "name_last": "Palmer",
                "common_name": "Palmer",
                "ca": 165,
                "pa": 180,
                "height_cm": 189,
                "club_uid": 630,
                "team_uid": 0x6000,
            }),
            player_profile=Mock(return_value={
                "guide_value": 85000000,
                "wage_weekly": 150000,
                "contract_end": "2033-06-30",
            }),
            player_season_stats=Mock(return_value={
                "apps_total": 38,
                "goals": 22,
                "assists": 11,
                "avg_rating": 7.65,
            }),
            player_form=Mock(return_value=[]),
        )

        with patch.object(server, "FmMemory", return_value=mem), \
             patch.object(server, "FmReader", return_value=reader):
            res = self.request("/api/connect", {})
            self.assertEqual(res[0], 200)
            self.assertTrue(res[1]["ok"])

            # 1. Snapshots list reports 1 live player
            status, snaps = self.request("/api/snapshots")
            self.assertEqual(status, 200)
            self.assertEqual(snaps[0]["id"], self.LIVE_ID)
            self.assertEqual(snaps[0]["n_players"], 1)
            self.assertEqual(snaps[0]["club"], "Chelsea FC")
            self.assertEqual(snaps[0]["manager"], "Enzo Maresca")

            # 2. Get live snapshot detail
            status, snap = self.request(f"/api/snapshots/{self.LIVE_ID}")
            self.assertEqual(status, 200)
            self.assertEqual(snap["n_players"], 1)
            self.assertEqual(snap["club"], "Chelsea FC")

            # 3. Search Cole Palmer in live snapshot
            status, p_list = self.request(f"/api/snapshots/{self.LIVE_ID}/players?search=Cole%20Palmer")
            self.assertEqual(status, 200)
            self.assertEqual(len(p_list["players"]), 1)
            self.assertEqual(p_list["players"][0]["full_name"], "Cole Palmer")

            # 4. Moneyball endpoint with live snapshot
            status, mb = self.request(f"/api/moneyball?snapshot={self.LIVE_ID}")
            self.assertEqual(status, 200)
            self.assertEqual(len(mb["players"]), 1)
            self.assertEqual(mb["players"][0]["name"], "Cole Palmer")

            # 5. Disconnect cleans up
            status, d_res = self.request("/api/disconnect", {})
            self.assertEqual(status, 200)
            self.assertTrue(d_res["disconnected"])

            # 6. Snapshot 999999999 returns 404 after disconnect
            status, _ = self.request(f"/api/snapshots/{self.LIVE_ID}")
            self.assertEqual(status, 404)
            status, _ = self.request(f"/api/snapshots/{self.LIVE_ID}/players")
            self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
