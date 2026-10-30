"""Regression and benchmark tests for full database player loading (issue: endless loading)."""

from contextlib import closing
from pathlib import Path
import sqlite3
import time
import unittest

import career_analysis
import moneyball_data
import player_analysis
import server


class FullDatabasePlayerLoadTests(unittest.TestCase):
    def setUp(self):
        # Create a synthetic full-scale benchmark database with 1,000 players and wide tables
        # (matches schema of FMSeasonHub captured.db/fm26_snapshots.db).
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self._init_benchmark_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        moneyball_data.clear_cache()

    def _init_benchmark_schema(self, conn):
        conn.execute("""
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY,
                carreira_id TEXT,
                name TEXT,
                save_name TEXT,
                game_date TEXT,
                in_game_season TEXT,
                scope TEXT,
                is_active INTEGER DEFAULT 0,
                player_count INTEGER DEFAULT 0,
                fm_version TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO snapshots VALUES (
                100, 'bench_career', 'Season 25/26', 'Benchmark Save', '2026-02-07',
                '2025/26', 'full', 1, 1000, '26.3.2', '2026-10-30 08:00:00'
            )
        """)
        conn.execute("""
            CREATE TABLE players (
                snapshot_id INTEGER,
                uid INTEGER,
                full_name TEXT,
                common_name TEXT,
                position TEXT,
                club_id INTEGER,
                ca INTEGER,
                pa INTEGER,
                PRIMARY KEY (snapshot_id, uid)
            )
        """)
        # Create wide player_stats table (30+ columns)
        stats_cols = [
            'snapshot_id INTEGER', 'uid INTEGER', 'apps_total INTEGER', 'minutes INTEGER',
            'goals INTEGER', 'assists INTEGER', 'avg_rating REAL', 'xg REAL', 'xa REAL',
            'shots INTEGER', 'shots_on_target INTEGER', 'passes_completed INTEGER',
            'passes_attempted INTEGER', 'tackles_completed INTEGER', 'tackles_attempted INTEGER',
            'interceptions INTEGER', 'clearances INTEGER', 'blocks INTEGER',
            'crosses_completed INTEGER', 'crosses_attempted INTEGER', 'dribbles INTEGER',
            'distance_km REAL', 'errors_leading_to_goal INTEGER', 'fouls_committed INTEGER',
            'fouls_won INTEGER', 'yellow_cards INTEGER', 'red_cards INTEGER',
            'headers_won INTEGER', 'headers_attempted INTEGER', 'clean_sheets_gk INTEGER',
            'goals_conceded_gk INTEGER', 'gk_saves_held INTEGER', 'gk_saves_parried INTEGER',
            'gk_saves_tipped INTEGER', 'xg_prevented_gk REAL', 'PRIMARY KEY (snapshot_id, uid)'
        ]
        conn.execute(f"CREATE TABLE player_stats ({', '.join(stats_cols)})")

        # Create wide player_profile table (30+ columns)
        profile_cols = [
            'snapshot_id INTEGER', 'uid INTEGER', 'birth_date TEXT', 'age INTEGER',
            'height_cm INTEGER', 'guide_value REAL', 'asking_price REAL', 'contract_wage REAL',
            'foot_left INTEGER', 'foot_right INTEGER', 'corners INTEGER', 'crossing INTEGER',
            'dribbling INTEGER', 'finishing INTEGER', 'first_touch INTEGER', 'free_kicks INTEGER',
            'heading INTEGER', 'long_shots INTEGER', 'passing INTEGER', 'penalty_taking INTEGER',
            'tackling INTEGER', 'technique INTEGER', 'aggression INTEGER', 'anticipation INTEGER',
            'bravery INTEGER', 'composure INTEGER', 'concentration INTEGER', 'decisions INTEGER',
            'determination INTEGER', 'flair INTEGER', 'leadership INTEGER', 'off_the_ball INTEGER',
            'positioning INTEGER', 'teamwork INTEGER', 'vision INTEGER', 'work_rate INTEGER',
            'acceleration INTEGER', 'agility INTEGER', 'balance INTEGER', 'jumping_reach INTEGER',
            'natural_fitness INTEGER', 'pace INTEGER', 'stamina INTEGER', 'strength INTEGER',
            'PRIMARY KEY (snapshot_id, uid)'
        ]
        conn.execute(f"CREATE TABLE player_profile ({', '.join(profile_cols)})")
        conn.execute("CREATE TABLE player_teams (snapshot_id INTEGER, player_uid INTEGER, team_uid INTEGER)")
        conn.execute("CREATE TABLE club_leagues (snapshot_id INTEGER, club_uid INTEGER, club_name TEXT, league_uid INTEGER, league_name TEXT)")
        conn.execute("CREATE TABLE club_profile (snapshot_id INTEGER, club_uid INTEGER, name_full TEXT)")
        conn.execute("CREATE TABLE comps (snapshot_id INTEGER, uid INTEGER, reputation REAL)")

        # Seed 1000 players
        players_data = [(100, i, f"Player {i}", f"P{i}", "ST" if i % 2 == 0 else "MC", 1, 120, 150) for i in range(1, 1001)]
        conn.executemany("INSERT INTO players VALUES (?,?,?,?,?,?,?,?)", players_data)

        stats_data = [(100, i, 20, 1800, 10, 5, 7.15, 8.5, 4.2, 40, 20, 300, 350, 25, 30,
                       15, 5, 3, 10, 20, 15, 10.5, 0, 10, 12, 2, 0, 15, 20, 0, 0, 0, 0, 0, 0.0)
                      for i in range(1, 1001)]
        stats_placeholders = ','.join('?' for _ in range(35))
        conn.executemany(f"INSERT INTO player_stats VALUES ({stats_placeholders})", stats_data)

        profile_data = [(100, i, '2000-01-01', 26, 182, 1000000.0, 1200000.0, 50000.0, 10, 18,
                         10, 10, 12, 14, 13, 9, 11, 10, 13, 12, 8, 13, 10, 12, 10, 13, 12, 13,
                         14, 11, 8, 12, 10, 13, 12, 13, 14, 13, 12, 12, 14, 14, 13, 12)
                        for i in range(1, 1001)]
        profile_placeholders = ','.join('?' for _ in range(44))
        conn.executemany(f"INSERT INTO player_profile VALUES ({profile_placeholders})", profile_data)
        conn.commit()

    def test_table_rows_uses_fast_tuple_mapping(self):
        t0 = time.perf_counter()
        rows = moneyball_data.table_rows(self.conn, 'player_stats', 100)
        elapsed = time.perf_counter() - t0
        self.assertEqual(len(rows), 1000)
        self.assertLess(elapsed, 0.5, f"table_rows took too long: {elapsed:.3f}s")
        self.assertEqual(rows[0]['uid'], 1)
        self.assertEqual(rows[0]['goals'], 10)

    def test_single_player_table_rows_is_sub_millisecond(self):
        t0 = time.perf_counter()
        rows = moneyball_data.table_rows(self.conn, 'player_profile', 100, uids=[42])
        elapsed = time.perf_counter() - t0
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['uid'], 42)
        self.assertLess(elapsed, 0.05, f"Single player lookup took too long: {elapsed:.3f}s")

    def test_moneyball_load_and_caching(self):
        moneyball_data.clear_cache()
        t0 = time.perf_counter()
        sid, rows = moneyball_data.load(self.conn, 100)
        initial_time = time.perf_counter() - t0
        self.assertEqual(len(rows), 1000)

        # Subsequent call must hit cache and return significantly faster (< 15ms)
        t0 = time.perf_counter()
        sid2, rows2 = moneyball_data.load(self.conn, 100)
        cached_time = time.perf_counter() - t0
        self.assertEqual(len(rows2), 1000)
        self.assertLess(cached_time, 0.02, f"Cached load took too long: {cached_time:.4f}s")
        self.assertEqual(rows[0]['uid'], rows2[0]['uid'])

    def test_career_analysis_player_with_uids_filter(self):
        t0 = time.perf_counter()
        result = career_analysis.player(self.conn, uid=42, career='bench_career')
        elapsed = time.perf_counter() - t0
        self.assertEqual(result['uid'], 42)
        self.assertEqual(result['carreira'], 'bench_career')
        self.assertEqual(result['snapshot_id'], 100)
        self.assertEqual(len(result['temporadas']), 1)
        self.assertEqual(result['stats']['goals'], 10)
        self.assertLess(elapsed, 0.1, f"career_analysis.player took too long: {elapsed:.3f}s")

    def test_player_analysis_load_with_bisect(self):
        snapshot, rows, index = player_analysis.load(self.conn, 100, uid=500)
        self.assertEqual(snapshot['id'], 100)
        self.assertEqual(rows[index]['uid'], 500)
        with self.assertRaises(LookupError):
            player_analysis.load(self.conn, 100, uid=99999)


if __name__ == '__main__':
    unittest.main()
