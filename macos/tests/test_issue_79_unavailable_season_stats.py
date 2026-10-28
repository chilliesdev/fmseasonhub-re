"""Tests for GitHub Issue #79: Preserving NULL season statistics across browse and player APIs."""

import json
from contextlib import closing
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import db
import server
import settings
import uvicorn


class UnavailableSeasonStatsTests(unittest.TestCase):
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
        folder = tempfile.TemporaryDirectory(prefix='fmsh-issue-79-test-')
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
            conn.execute("INSERT INTO snapshots(id,name,game_date,carreira_id,club_uid) VALUES(950,'Season 26','2026-06-01','car1',100)")
            # Player 101: Unverified ARM64 season stats (all NULL in player_stats)
            # Player 102: Measured zeros (0 apps, 0 minutes, 0 goals, etc.)
            # Player 103: Measured positive minutes with 0 goals (900 min, 0 goals, 15 shots)
            players = [
                (950, 101, 'Unverified Forward', 'Forward', 'ST', 100, 1001, 130, 150),
                (950, 102, 'Zero Appearances', 'Zero', 'ST', 100, 1001, 120, 140),
                (950, 103, 'Measured Striker', 'Striker', 'ST', 100, 1001, 140, 160),
            ]
            conn.executemany("INSERT INTO players(snapshot_id,uid,full_name,common_name,position,club_id,team_uid,ca,pa) VALUES(?,?,?,?,?,?,?,?,?)", players)

            # Insert player_stats:
            # 101: all season statistics NULL
            conn.execute("""
                INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, goals, assists, avg_rating, shots, passes_attempted, passes_completed)
                VALUES(950, 101, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """)
            # 102: measured zero
            conn.execute("""
                INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, goals, assists, avg_rating, shots, passes_attempted, passes_completed)
                VALUES(950, 102, 0, 0, 0, 0, 0.0, 0, 0, 0)
            """)
            # 103: played 900 minutes, 0 goals, 15 shots
            conn.execute("""
                INSERT INTO player_stats(snapshot_id, uid, apps_total, minutes, goals, assists, avg_rating, shots, passes_attempted, passes_completed)
                VALUES(950, 103, 10, 900, 0, 3, 6.85, 15, 100, 80)
            """)

            conn.execute("INSERT INTO teams(snapshot_id,team_uid,club_uid,label) VALUES(950,1001,100,'First Team')")
            conn.execute("INSERT INTO club_leagues(snapshot_id,club_uid,club_name,league_uid,league_name) VALUES(950,100,'Test FC',9000,'Test League')")

    def test_snapshot_players_browse_api_preserves_null_stats_and_measured_zero(self):
        """GET /api/snapshots/{sid}/players preserves null stats vs measured zeros."""
        status, data = self.get_json('/api/snapshots/950/players')
        self.assertEqual(status, 200)
        players_by_uid = {p['uid']: p for p in data['players']}

        # Player 101 (unverified NULL stats)
        p101 = players_by_uid[101]
        self.assertIsNone(p101['apps_total'])
        self.assertIsNone(p101['goals'])
        self.assertIsNone(p101['assists'])
        self.assertIsNone(p101['avg_rating'])

        # Player 102 (measured zeros)
        p102 = players_by_uid[102]
        self.assertEqual(p102['apps_total'], 0)
        self.assertEqual(p102['goals'], 0)
        self.assertEqual(p102['assists'], 0)
        self.assertEqual(p102['avg_rating'], 0.0)

        # Player 103 (measured 0 goals, 10 apps)
        p103 = players_by_uid[103]
        self.assertEqual(p103['apps_total'], 10)
        self.assertEqual(p103['goals'], 0)
        self.assertEqual(p103['assists'], 3)

    def test_player_detail_api_preserves_null_stats_and_measured_zero(self):
        """GET /api/snapshots/{sid}/players/{uid} preserves null stats vs measured zeros."""
        # Player 101 (NULL stats)
        status101, d101 = self.get_json('/api/snapshots/950/players/101')
        self.assertEqual(status101, 200)
        self.assertIsNone(d101['stats']['apps_total'])
        self.assertIsNone(d101['stats']['minutes'])
        self.assertIsNone(d101['stats']['goals'])
        self.assertIsNone(d101['stats']['assists'])
        self.assertIsNone(d101['apps_total'])
        self.assertIsNone(d101['goals'])

        # Player 102 (measured zeros)
        status102, d102 = self.get_json('/api/snapshots/950/players/102')
        self.assertEqual(status102, 200)
        self.assertEqual(d102['stats']['apps_total'], 0)
        self.assertEqual(d102['stats']['minutes'], 0)
        self.assertEqual(d102['stats']['goals'], 0)
        self.assertEqual(d102['stats']['assists'], 0)
        self.assertEqual(d102['apps_total'], 0)
        self.assertEqual(d102['goals'], 0)

    def test_moneyball_browse_preserves_nulls_in_vals_and_derived_rates(self):
        """GET /api/moneyball/browse preserves null values and derived rates without coercing to 0."""
        # Browse group 'att' (Forwards analysis)
        status, data = self.get_json('/api/moneyball/browse?snapshot=950&group=att')
        self.assertEqual(status, 200)
        rows_by_uid = {r['uid']: r for r in data['rows']}

        # Player 101: unverified season stats
        r101 = rows_by_uid[101]
        vals101 = r101['vals']
        self.assertIsNone(vals101['goals'])
        self.assertIsNone(vals101['minutes'])
        self.assertIsNone(vals101['apps_total'])
        self.assertIsNone(vals101['goals_per90'])
        self.assertIsNone(vals101['conv'])
        self.assertIsNone(vals101['passPct'])
        # Catalog forward columns
        self.assertIsNone(vals101.get('att_O'))
        self.assertIsNone(vals101.get('att_Z'))
        self.assertIsNone(vals101.get('att_T'))

        # Player 102: measured zero appearances & minutes
        r102 = rows_by_uid[102]
        vals102 = r102['vals']
        self.assertEqual(vals102['goals'], 0.0)
        self.assertEqual(vals102['minutes'], 0.0)
        self.assertEqual(vals102['apps_total'], 0.0)
        # With 0 minutes, per90 derived rate should be None (not misleading 0.0)
        self.assertIsNone(vals102['goals_per90'])
        self.assertIsNone(vals102['conv'])

        # Player 103: played 900 minutes, 0 goals, 15 shots
        r103 = rows_by_uid[103]
        vals103 = r103['vals']
        self.assertEqual(vals103['goals'], 0.0)
        self.assertEqual(vals103['minutes'], 900.0)
        self.assertEqual(vals103['apps_total'], 10.0)
        # Measured rate of 0 goals in 900 minutes:
        self.assertEqual(vals103['goals_per90'], 0.0)
        # 0 goals out of 15 shots:
        self.assertEqual(vals103['conv'], 0.0)

    def test_player_temporadas_api_preserves_null_stats(self):
        """GET /api/players/{uid}/temporadas preserves null stats for seasons with unverified data."""
        status101, t101 = self.get_json('/api/players/101/temporadas')
        self.assertEqual(status101, 200)
        self.assertEqual(len(t101), 1)
        self.assertIsNone(t101[0]['stats']['apps_total'])
        self.assertIsNone(t101[0]['stats']['minutes'])
        self.assertIsNone(t101[0]['stats']['goals'])

        status102, t102 = self.get_json('/api/players/102/temporadas')
        self.assertEqual(status102, 200)
        self.assertEqual(len(t102), 1)
        self.assertEqual(t102[0]['stats']['apps_total'], 0)
        self.assertEqual(t102[0]['stats']['minutes'], 0)
        self.assertEqual(t102[0]['stats']['goals'], 0)


if __name__ == '__main__':
    unittest.main()
