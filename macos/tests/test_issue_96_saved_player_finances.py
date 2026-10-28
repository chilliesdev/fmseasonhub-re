"""Unit and integration tests for Issue #96:
Distinguish unmeasured ARM64 financial fields from measured zeros in saved-player APIs.
"""

from contextlib import closing
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import db
import server
import settings
import uvicorn


class Issue96SavedPlayerFinancesTests(unittest.TestCase):
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
            raise RuntimeError("Test HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.settings_path = self.root / "fmsh_settings.json"
        self.database = self.root / "fm26_snapshots.db"
        self.settings_patch = patch.object(settings, "SETTINGS_PATH", str(self.settings_path))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        database_patch = patch.object(server, "get_db_path", return_value=self.database)
        database_patch.start()
        self.addCleanup(database_patch.stop)
        db.init_db(str(self.database))

    def request(self, route):
        request = urllib.request.Request(self.base + route, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def _setup_players(self):
        sid = 901
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute(
                "INSERT INTO snapshots(id, name, game_date, carreira_id, scope, fm_version) "
                "VALUES(?, 'QA Season', '2027-05-30', 'career_issue96', 'squad', '26')",
                (sid,),
            )
            players = [
                (sid, 1, "Unmeasured Profile", 100, 150),
                (sid, 2, "Measured Zero", 110, 160),
                (sid, 3, "Measured Positive", 120, 170),
                (sid, 4, "No Profile Row", 90, 130),
            ]
            conn.executemany(
                "INSERT INTO players(snapshot_id, uid, full_name, ca, pa) VALUES(?, ?, ?, ?, ?)",
                players,
            )
            # uid 1: Profile row exists, but ARM64 finance fields were not measured (NULL)
            conn.execute(
                "INSERT INTO player_profile(snapshot_id, uid, birth_date, guide_value, transfer_value, contract_wage) "
                "VALUES(?, 1, '2001-01-01', NULL, NULL, NULL)",
                (sid,),
            )
            # uid 2: Profile row with measured zero finances
            conn.execute(
                "INSERT INTO player_profile(snapshot_id, uid, birth_date, guide_value, transfer_value, contract_wage) "
                "VALUES(?, 2, '2002-02-02', 0, 0, 0)",
                (sid,),
            )
            # uid 3: Profile row with measured positive finances
            conn.execute(
                "INSERT INTO player_profile(snapshot_id, uid, birth_date, guide_value, transfer_value, contract_wage) "
                "VALUES(?, 3, '2003-03-03', 4500000, 4500000, 35000)",
                (sid,),
            )
            # uid 4: Has no row in player_profile at all
            conn.executemany(
                "INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, goals, assists, avg_rating) "
                "VALUES(?, ?, 10, 900, 2, 1, 7.0)",
                [(sid, uid) for uid in (1, 2, 3, 4)],
            )
        return sid

    def test_list_apis_unmeasured_finances_return_null(self):
        """Test Case 1: Unmeasured finance fields return null in list APIs."""
        sid = self._setup_players()

        # 1. /api/snapshots/{sid}/players
        status, resp = self.request(f"/api/snapshots/{sid}/players")
        self.assertEqual(status, 200)
        by_uid = {p["uid"]: p for p in resp["players"]}

        for uid in (1, 4):
            player = by_uid[uid]
            self.assertIsNone(player["value"], f"uid {uid} value must be null")
            self.assertIsNone(player["transfer_value"], f"uid {uid} transfer_value must be null")
            self.assertIsNone(player["asking_price"], f"uid {uid} asking_price must be null")
            self.assertIsNone(player["wage"], f"uid {uid} wage must be null")

        # 2. /api/moneyball/browse
        status, mb_browse = self.request(f"/api/moneyball/browse?snapshot={sid}")
        self.assertEqual(status, 200)
        by_uid_mb = {p["uid"]: p for p in mb_browse["rows"]}

        for uid in (1, 4):
            player = by_uid_mb[uid]
            self.assertIsNone(player["value"], f"moneyball browse uid {uid} value must be null")
            self.assertIsNone(player["transfer_value"], f"moneyball browse uid {uid} transfer_value must be null")
            self.assertIsNone(player["asking_price"], f"moneyball browse uid {uid} asking_price must be null")
            self.assertIsNone(player["wage"], f"moneyball browse uid {uid} wage must be null")
            self.assertIsNone(player["vals"].get("value"), f"moneyball browse uid {uid} vals.value must be null")
            self.assertIsNone(player["vals"].get("asking"), f"moneyball browse uid {uid} vals.asking must be null")
            self.assertIsNone(player["vals"].get("wage"), f"moneyball browse uid {uid} vals.wage must be null")

        # 3. /api/moneyball
        status, mb_resp = self.request(f"/api/moneyball?snapshot={sid}")
        self.assertEqual(status, 200)
        by_uid_m = {p["uid"]: p for p in mb_resp["players"]}

        for uid in (1, 4):
            player = by_uid_m[uid]
            self.assertIsNone(player["value"], f"moneyball uid {uid} value must be null")
            self.assertIsNone(player["transfer_value"], f"moneyball uid {uid} transfer_value must be null")
            self.assertIsNone(player["asking_price"], f"moneyball uid {uid} asking_price must be null")
            self.assertIsNone(player["wage"], f"moneyball uid {uid} wage must be null")

    def test_detail_apis_unmeasured_finances_return_null(self):
        """Test Case 2: Unmeasured finance fields return null in detail APIs."""
        sid = self._setup_players()

        for uid in (1, 4):
            # 1. /api/snapshots/{sid}/players/{uid}
            status, detail = self.request(f"/api/snapshots/{sid}/players/{uid}")
            self.assertEqual(status, 200)
            self.assertIsNone(detail["value"], f"detail uid {uid} value must be null")
            self.assertIsNone(detail["transfer_value"], f"detail uid {uid} transfer_value must be null")
            self.assertIsNone(detail["asking_price"], f"detail uid {uid} asking_price must be null")
            self.assertIsNone(detail["wage"], f"detail uid {uid} wage must be null")

            prof = detail["profile"]
            self.assertIsNone(prof["value"], f"profile uid {uid} value must be null")
            self.assertIsNone(prof["transfer_value"], f"profile uid {uid} transfer_value must be null")
            self.assertIsNone(prof["asking_price"], f"profile uid {uid} asking_price must be null")
            self.assertIsNone(prof["wage"], f"profile uid {uid} wage must be null")

            # 2. /api/players/{uid}/alltime
            status, alltime = self.request(f"/api/players/{uid}/alltime")
            self.assertEqual(status, 200)
            self.assertIsNone(alltime["value"], f"alltime uid {uid} value must be null")
            self.assertIsNone(alltime["transfer_value"], f"alltime uid {uid} transfer_value must be null")
            self.assertIsNone(alltime["asking_price"], f"alltime uid {uid} asking_price must be null")
            self.assertIsNone(alltime["wage"], f"alltime uid {uid} wage must be null")

            prof_all = alltime["profile"]
            self.assertIsNone(prof_all["value"], f"alltime profile uid {uid} value must be null")
            self.assertIsNone(prof_all["transfer_value"], f"alltime profile uid {uid} transfer_value must be null")
            self.assertIsNone(prof_all["asking_price"], f"alltime profile uid {uid} asking_price must be null")
            self.assertIsNone(prof_all["wage"], f"alltime profile uid {uid} wage must be null")

    def test_measured_zero_values_preserved(self):
        """Test Case 3: Measured zero values remain 0 across list and detail APIs."""
        sid = self._setup_players()
        uid = 2

        # 1. List: /api/snapshots/{sid}/players
        status, resp = self.request(f"/api/snapshots/{sid}/players")
        self.assertEqual(status, 200)
        p = next(x for x in resp["players"] if x["uid"] == uid)
        self.assertEqual(p["value"], 0)
        self.assertEqual(p["transfer_value"], 0)
        self.assertEqual(p["asking_price"], 0)
        self.assertEqual(p["wage"], 0)

        # 2. List: /api/moneyball/browse
        status, mb_browse = self.request(f"/api/moneyball/browse?snapshot={sid}")
        self.assertEqual(status, 200)
        p_mb = next(x for x in mb_browse["rows"] if x["uid"] == uid)
        self.assertEqual(p_mb["value"], 0)
        self.assertEqual(p_mb["transfer_value"], 0)
        self.assertEqual(p_mb["asking_price"], 0)
        self.assertEqual(p_mb["wage"], 0)
        self.assertEqual(p_mb["vals"]["value"], 0)
        self.assertEqual(p_mb["vals"]["asking"], 0)
        self.assertEqual(p_mb["vals"]["wage"], 0)

        # 3. List: /api/moneyball
        status, mb = self.request(f"/api/moneyball?snapshot={sid}")
        self.assertEqual(status, 200)
        p_m = next(x for x in mb["players"] if x["uid"] == uid)
        self.assertEqual(p_m["value"], 0)
        self.assertEqual(p_m["transfer_value"], 0)
        self.assertEqual(p_m["asking_price"], 0)
        self.assertEqual(p_m["wage"], 0)

        # 4. Detail: /api/snapshots/{sid}/players/{uid}
        status, detail = self.request(f"/api/snapshots/{sid}/players/{uid}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["value"], 0)
        self.assertEqual(detail["transfer_value"], 0)
        self.assertEqual(detail["asking_price"], 0)
        self.assertEqual(detail["wage"], 0)
        self.assertEqual(detail["profile"]["value"], 0)
        self.assertEqual(detail["profile"]["transfer_value"], 0)
        self.assertEqual(detail["profile"]["asking_price"], 0)
        self.assertEqual(detail["profile"]["wage"], 0)

        # 5. Detail: /api/players/{uid}/alltime
        status, alltime = self.request(f"/api/players/{uid}/alltime")
        self.assertEqual(status, 200)
        self.assertEqual(alltime["value"], 0)
        self.assertEqual(alltime["transfer_value"], 0)
        self.assertEqual(alltime["asking_price"], 0)
        self.assertEqual(alltime["wage"], 0)
        self.assertEqual(alltime["profile"]["value"], 0)
        self.assertEqual(alltime["profile"]["transfer_value"], 0)
        self.assertEqual(alltime["profile"]["asking_price"], 0)
        self.assertEqual(alltime["profile"]["wage"], 0)

    def test_measured_positive_values_preserved(self):
        """Test Case 4: Measured positive values remain accurate across list and detail APIs."""
        sid = self._setup_players()
        uid = 3

        # 1. List: /api/snapshots/{sid}/players
        status, resp = self.request(f"/api/snapshots/{sid}/players")
        self.assertEqual(status, 200)
        p = next(x for x in resp["players"] if x["uid"] == uid)
        self.assertEqual(p["value"], 4500000)
        self.assertEqual(p["transfer_value"], 4500000)
        self.assertEqual(p["asking_price"], 4500000)
        self.assertEqual(p["wage"], 35000)

        # 2. List: /api/moneyball/browse
        status, mb_browse = self.request(f"/api/moneyball/browse?snapshot={sid}")
        self.assertEqual(status, 200)
        p_mb = next(x for x in mb_browse["rows"] if x["uid"] == uid)
        self.assertEqual(p_mb["value"], 4500000)
        self.assertEqual(p_mb["transfer_value"], 4500000)
        self.assertEqual(p_mb["asking_price"], 4500000)
        self.assertEqual(p_mb["wage"], 35000)
        self.assertEqual(p_mb["vals"]["value"], 4500000)
        self.assertEqual(p_mb["vals"]["asking"], 4500000)
        self.assertEqual(p_mb["vals"]["wage"], 35000)

        # 3. Detail: /api/snapshots/{sid}/players/{uid}
        status, detail = self.request(f"/api/snapshots/{sid}/players/{uid}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["value"], 4500000)
        self.assertEqual(detail["transfer_value"], 4500000)
        self.assertEqual(detail["asking_price"], 4500000)
        self.assertEqual(detail["wage"], 35000)
        self.assertEqual(detail["profile"]["value"], 4500000)
        self.assertEqual(detail["profile"]["transfer_value"], 4500000)
        self.assertEqual(detail["profile"]["asking_price"], 4500000)
        self.assertEqual(detail["profile"]["wage"], 35000)

        # 4. Detail: /api/players/{uid}/alltime
        status, alltime = self.request(f"/api/players/{uid}/alltime")
        self.assertEqual(status, 200)
        self.assertEqual(alltime["value"], 4500000)
        self.assertEqual(alltime["transfer_value"], 4500000)
        self.assertEqual(alltime["asking_price"], 4500000)
        self.assertEqual(alltime["wage"], 35000)
        self.assertEqual(alltime["profile"]["value"], 4500000)
        self.assertEqual(alltime["profile"]["transfer_value"], 4500000)
        self.assertEqual(alltime["profile"]["asking_price"], 4500000)
        self.assertEqual(alltime["profile"]["wage"], 35000)


if __name__ == "__main__":
    unittest.main()
