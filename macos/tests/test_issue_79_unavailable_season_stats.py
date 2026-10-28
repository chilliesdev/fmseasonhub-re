"""Tests for GitHub Issue #79: Preserving NULL season statistics across browse and player APIs."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

import db
import server
import settings


class UnavailableSeasonStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.app.dependency_overrides = {}

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
        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        res = client.get('/api/snapshots/950/players')
        self.assertEqual(res.status_code, 200)
        data = res.json()
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
        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        # Player 101 (NULL stats)
        res101 = client.get('/api/snapshots/950/players/101')
        self.assertEqual(res101.status_code, 200)
        d101 = res101.json()
        self.assertIsNone(d101['stats']['apps_total'])
        self.assertIsNone(d101['stats']['minutes'])
        self.assertIsNone(d101['stats']['goals'])
        self.assertIsNone(d101['stats']['assists'])
        self.assertIsNone(d101['apps_total'])
        self.assertIsNone(d101['goals'])

        # Player 102 (measured zeros)
        res102 = client.get('/api/snapshots/950/players/102')
        self.assertEqual(res102.status_code, 200)
        d102 = res102.json()
        self.assertEqual(d102['stats']['apps_total'], 0)
        self.assertEqual(d102['stats']['minutes'], 0)
        self.assertEqual(d102['stats']['goals'], 0)
        self.assertEqual(d102['stats']['assists'], 0)
        self.assertEqual(d102['apps_total'], 0)
        self.assertEqual(d102['goals'], 0)

    def test_moneyball_browse_preserves_nulls_in_vals_and_derived_rates(self):
        """GET /api/moneyball/browse preserves null values and derived rates without coercing to 0."""
        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        # Browse group 'att' (Forwards analysis)
        res = client.get('/api/moneyball/browse?snapshot=950&group=att')
        self.assertEqual(res.status_code, 200)
        data = res.json()
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
        from fastapi.testclient import TestClient
        client = TestClient(server.app)

        res101 = client.get('/api/players/101/temporadas')
        self.assertEqual(res101.status_code, 200)
        t101 = res101.json()
        self.assertEqual(len(t101), 1)
        self.assertIsNone(t101[0]['stats']['apps_total'])
        self.assertIsNone(t101[0]['stats']['minutes'])
        self.assertIsNone(t101[0]['stats']['goals'])

        res102 = client.get('/api/players/102/temporadas')
        self.assertEqual(res102.status_code, 200)
        t102 = res102.json()
        self.assertEqual(len(t102), 1)
        self.assertEqual(t102[0]['stats']['apps_total'], 0)
        self.assertEqual(t102[0]['stats']['minutes'], 0)
        self.assertEqual(t102[0]['stats']['goals'], 0)


if __name__ == '__main__':
    unittest.main()
