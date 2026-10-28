"""Tests for GitHub Issue #77: Undefined player rates must not show fabricated values.

When underlying values are 0 or unavailable (e.g. 0 minutes or 0 shots), rate columns
must show unavailable (null/None/dash) rather than fabricated numeric defaults
(such as 5000.00, 100, 300.00). Rates require recorded minutes.
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
import urllib.parse
import urllib.request
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import db
import moneyball as mb
import moneyball_data as data
import server
import settings
import uvicorn


class UndefinedPlayerRatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listener = socket.socket()
        cls.listener.bind(('127.0.0.1', 0))
        cls.base = f'http://127.0.0.1:{cls.listener.getsockname()[1]}'
        cls.srv = uvicorn.Server(uvicorn.Config(server.app, log_level='error'))
        cls.thread = threading.Thread(target=cls.srv.run, kwargs={'sockets': [cls.listener]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while not cls.srv.started and cls.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not cls.srv.started:
            raise RuntimeError('HTTP server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='fmsh-issue-77-test-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / 'test.db'
        for target, name, value in ((server, 'get_db_path', lambda: self.database),
                                    (settings, 'SETTINGS_PATH', str(self.root / 'settings.json'))):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        db.init_db(str(self.database))
        self.seed()

    def get_json(self, path):
        req = urllib.request.Request(f'{self.base}{path}')
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))

    def seed(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO snapshots(id,name,game_date,carreira_id,club_uid) VALUES(770,'Rates Season','2027-05-30','c77',10)")
            # Player 1: Zero minutes played (0 minutes, 0 shots, 0 goals, 0 POM)
            # Player 2: 900 minutes, 0 shots, 0 goals, 0 POM
            # Player 3: 900 minutes, 15 shots, 0 goals, 0 POM, 0 assists (zero denominator for shots per goal and POM)
            # Player 4: 900 minutes, 20 shots, 4 goals, 2 assists, 2 POM (valid nonzero stats)
            # Player 5: Missing / unverified records (all NULL in player_stats)
            players = [
                (770, 1, 'Zero Minutes', 'ST', 10, 101, 100, 150),
                (770, 2, 'Zero Shots Striker', 'ST', 10, 101, 110, 150),
                (770, 3, 'Zero Goals Striker', 'ST', 10, 101, 120, 160),
                (770, 4, 'Valid Striker', 'ST', 10, 101, 130, 170),
                (770, 5, 'Unverified Forward', 'ST', 10, 101, 90, 130),
            ]
            conn.executemany("INSERT INTO players(snapshot_id,uid,full_name,position,club_id,team_uid,ca,pa) VALUES(?,?,?,?,?,?,?,?)", players)

            conn.execute("""
                INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, shots, shots_on_target, goals, assists, man_of_the_match, penalties_taken, penalties_scored, avg_rating)
                VALUES(770, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0)
            """)
            conn.execute("""
                INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, shots, shots_on_target, goals, assists, man_of_the_match, penalties_taken, penalties_scored, avg_rating)
                VALUES(770, 2, 10, 900, 0, 0, 0, 0, 0, 0, 0, 6.5)
            """)
            conn.execute("""
                INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, shots, shots_on_target, goals, assists, man_of_the_match, penalties_taken, penalties_scored, avg_rating)
                VALUES(770, 3, 10, 900, 15, 8, 0, 0, 0, 0, 0, 6.7)
            """)
            conn.execute("""
                INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, shots, shots_on_target, goals, assists, man_of_the_match, penalties_taken, penalties_scored, avg_rating)
                VALUES(770, 4, 10, 900, 20, 10, 4, 2, 2, 0, 0, 7.4)
            """)
            conn.execute("""
                INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, shots, shots_on_target, goals, assists, man_of_the_match, penalties_taken, penalties_scored, avg_rating)
                VALUES(770, 5, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """)

            conn.execute("INSERT INTO teams(snapshot_id,team_uid,club_uid,label) VALUES(770,101,10,'First Team')")
            conn.execute("INSERT INTO club_leagues(snapshot_id,club_uid,club_name,league_uid,league_name) VALUES(770,10,'FC Rates',7700,'Rates League')")

    def test_derive_catalog_handles_undefined_zero_denominator_and_zero_minutes(self):
        """derive_catalog evaluates undefined rates to NaN without fabricated numeric values."""
        fields = set(mb.RAW_FIELDS)
        for group in ("att", "b2b", "gk", "def", "wing", "dm", "amc"):
            for col in mb.CATALOG.get(group, []):
                fields.update(mb.column_fields(col["key"]))

        # 1. 0 minutes -> rates evaluate to NaN
        raw_0min = {k: np.array([0.0]) for k in fields}
        raw_0min["minutes"] = np.array([0.0])
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            d_att = mb.derive_catalog(raw_0min, "att")
            d_b2b = mb.derive_catalog(raw_0min, "b2b")
            d_amc = mb.derive_catalog(raw_0min, "amc")
            d_gk = mb.derive_catalog(raw_0min, "gk")
            d_def = mb.derive_catalog(raw_0min, "def")

        self.assertTrue(np.isnan(d_att["att_X"][0]))
        self.assertTrue(np.isnan(d_att["att_CI"][0]))
        self.assertTrue(np.isnan(d_att["att_BW"][0]))
        self.assertTrue(np.isnan(d_b2b["b2b_BB"][0]))
        self.assertTrue(np.isnan(d_b2b["b2b_AH"][0]))
        self.assertTrue(np.isnan(d_amc["amc_V"][0]))
        self.assertTrue(np.isnan(d_gk["gk_P"][0]))
        self.assertTrue(np.isnan(d_def["def_AF"][0]))

        # 2. 0 shots or 0 goals -> Shots per Goal evaluates to NaN, not 100
        raw_0shots = {k: np.array([0.0]) for k in fields}
        raw_0shots["minutes"] = np.array([900.0])
        raw_0shots["shots"] = np.array([0.0])
        raw_0shots["goals"] = np.array([0.0])
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            d_att = mb.derive_catalog(raw_0shots, "att")
        self.assertTrue(np.isnan(d_att["att_BW"][0]))

        raw_shots_no_goals = {k: np.array([0.0]) for k in fields}
        raw_shots_no_goals["minutes"] = np.array([900.0])
        raw_shots_no_goals["shots"] = np.array([15.0])
        raw_shots_no_goals["goals"] = np.array([0.0])
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            d_att = mb.derive_catalog(raw_shots_no_goals, "att")
        self.assertTrue(np.isnan(d_att["att_BW"][0]))

        # 3. Missing / unavailable (NaN) stats -> rates evaluate to NaN
        raw_nan = {k: np.array([np.nan]) for k in fields}
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            d_att = mb.derive_catalog(raw_nan, "att")
        self.assertTrue(np.isnan(d_att["att_X"][0]))
        self.assertTrue(np.isnan(d_att["att_CI"][0]))
        self.assertTrue(np.isnan(d_att["att_BW"][0]))

        # 4. Valid nonzero minutes and stats -> rates compute correctly
        raw_valid = {k: np.array([0.0]) for k in fields}
        raw_valid["minutes"] = np.array([900.0])
        raw_valid["shots"] = np.array([20.0])
        raw_valid["goals"] = np.array([4.0])
        raw_valid["assists"] = np.array([2.0])
        raw_valid["man_of_the_match"] = np.array([2.0])
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            d_att = mb.derive_catalog(raw_valid, "att")
        self.assertEqual(d_att["att_BW"][0], 5.0)    # 20 shots / 4 goals = 5.0
        self.assertEqual(d_att["att_CI"][0], 150.0)  # 900 min / (4+2 contrib) = 150.0
        self.assertEqual(d_att["att_X"][0], 450.0)   # 900 min / 2 POM = 450.0

    def test_moneyball_browse_returns_null_not_fabricated_values(self):
        """GET /api/moneyball/browse returns null (not 5000.00, 100, 300.00) for undefined rates."""
        status, data = self.get_json('/api/moneyball/browse?snapshot=770&group=att')
        self.assertEqual(status, 200)
        rows_by_uid = {r['uid']: r for r in data['rows']}

        # Player 1: Zero minutes -> undefined rates are None / null
        p1_vals = rows_by_uid[1]['vals']
        self.assertIsNone(p1_vals.get('att_X'))
        self.assertIsNone(p1_vals.get('att_CI'))
        self.assertIsNone(p1_vals.get('att_BW'))
        self.assertNotEqual(p1_vals.get('att_X'), 5000.0)
        self.assertNotEqual(p1_vals.get('att_CI'), 300.0)
        self.assertNotEqual(p1_vals.get('att_BW'), 100.0)

        # Player 2: 900 min, 0 shots, 0 goals, 0 POM -> undefined rates are None / null
        p2_vals = rows_by_uid[2]['vals']
        self.assertIsNone(p2_vals.get('att_X'))
        self.assertIsNone(p2_vals.get('att_CI'))
        self.assertIsNone(p2_vals.get('att_BW'))
        self.assertNotEqual(p2_vals.get('att_X'), 5000.0)
        self.assertNotEqual(p2_vals.get('att_CI'), 300.0)
        self.assertNotEqual(p2_vals.get('att_BW'), 100.0)

        # Player 3: 900 min, 15 shots, 0 goals, 0 POM -> undefined rates are None / null
        p3_vals = rows_by_uid[3]['vals']
        self.assertIsNone(p3_vals.get('att_X'))
        self.assertIsNone(p3_vals.get('att_CI'))
        self.assertIsNone(p3_vals.get('att_BW'))
        self.assertNotEqual(p3_vals.get('att_BW'), 100.0)

        # Player 4: Valid stats -> correct rates computed
        p4_vals = rows_by_uid[4]['vals']
        self.assertEqual(p4_vals.get('att_BW'), 5.0)
        self.assertEqual(p4_vals.get('att_CI'), 150.0)
        self.assertEqual(p4_vals.get('att_X'), 450.0)

        # Player 5: Unverified stats -> None / null
        p5_vals = rows_by_uid[5]['vals']
        self.assertIsNone(p5_vals.get('att_X'))
        self.assertIsNone(p5_vals.get('att_CI'))
        self.assertIsNone(p5_vals.get('att_BW'))

    def test_snapshot_players_apis_return_null_in_vals_for_undefined_rates(self):
        """GET /api/snapshots/{sid}/players and /api/snapshots/{sid}/players/{uid} return null in vals."""
        # 1. Player list endpoint
        status, list_data = self.get_json('/api/snapshots/770/players')
        self.assertEqual(status, 200)
        players = {p['uid']: p for p in list_data['players']}

        # Player 1 (0 min): vals must have null for rate columns
        self.assertIn('vals', players[1])
        p1_vals = players[1]['vals']
        self.assertIsNone(p1_vals.get('att_X'))
        self.assertIsNone(p1_vals.get('att_CI'))
        self.assertIsNone(p1_vals.get('att_BW'))

        # Player 3 (15 shots, 0 goals): vals must have null for shots per goal
        p3_vals = players[3]['vals']
        self.assertIsNone(p3_vals.get('att_BW'))
        self.assertIsNone(p3_vals.get('att_X'))

        # Player 4 (valid): correct values
        p4_vals = players[4]['vals']
        self.assertEqual(p4_vals.get('att_BW'), 5.0)
        self.assertEqual(p4_vals.get('att_CI'), 150.0)
        self.assertEqual(p4_vals.get('att_X'), 450.0)

        # 2. Individual player endpoint
        status1, d1 = self.get_json('/api/snapshots/770/players/1')
        self.assertEqual(status1, 200)
        self.assertIn('vals', d1)
        self.assertIsNone(d1['vals'].get('att_X'))
        self.assertIsNone(d1['vals'].get('att_CI'))
        self.assertIsNone(d1['vals'].get('att_BW'))

        status3, d3 = self.get_json('/api/snapshots/770/players/3')
        self.assertEqual(status3, 200)
        self.assertIn('vals', d3)
        self.assertIsNone(d3['vals'].get('att_BW'))
        self.assertNotEqual(d3['vals'].get('att_BW'), 100.0)

        status4, d4 = self.get_json('/api/snapshots/770/players/4')
        self.assertEqual(status4, 200)
        self.assertIn('vals', d4)
        self.assertEqual(d4['vals'].get('att_BW'), 5.0)
        self.assertEqual(d4['vals'].get('att_CI'), 150.0)
        self.assertEqual(d4['vals'].get('att_X'), 450.0)


if __name__ == '__main__':
    unittest.main()
