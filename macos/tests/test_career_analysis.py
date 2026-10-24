"""HTTP regressions for saved career totals and player history (issue #10)."""

from contextlib import closing
import unittest

import test_moneyball_data as fixtures
import server


class CareerAnalysisTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.MoneyballDataTests.tearDownClass.__func__)
    seed = fixtures.MoneyballDataTests.seed
    request = fixtures.MoneyballDataTests.request

    def setUp(self):
        fixtures.MoneyballDataTests.setUp(self)
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("UPDATE snapshots SET fm_version='26',in_game_season='2026/27'")
            conn.execute("UPDATE snapshots SET in_game_season='2027/28' WHERE id IN (902,904)")
            conn.execute('INSERT INTO player_profile(snapshot_id,uid,finishing,contract_wage,guide_value) VALUES(902,1,13,12000,2000000)')

    def test_career_and_player_return_both_seasons_and_measured_totals(self):
        status, career = self.request('/api/carreiras/alpha/alltime')
        self.assertEqual(status, 200, career)
        self.assertEqual(career['seasons'], career['temporadas'])
        self.assertEqual([item['temporada'] for item in career['seasons']], ['2026/27', '2027/28'])
        self.assertEqual([item['sid'] for item in career['seasons']], [901, 902])
        row = next(row for row in career['players'] if row['uid'] == 1)
        self.assertEqual((row['apps_total'], row['minutes'], row['goals'], row['assists']), (40, 3600, 22, 11))
        status, player = self.request('/api/players/1/alltime', carreira='alpha')
        self.assertEqual(status, 200, player)
        self.assertEqual([item['sid'] for item in player['temporadas']], [901, 902])
        self.assertEqual([item['stats']['goals'] for item in player['temporadas']], [10, 12])
        self.assertEqual(player['stats']['goals'], row['goals'])
        self.assertAlmostEqual(player['stats']['avg_rating'], 7.15)
        self.assertEqual((player['identity']['full_name'], player['identity']['ca']), ('Alpha New', 110))
        self.assertEqual((player['profile']['finishing'], player['profile']['wage']), (13, 12000))
        self.assertEqual(player['profile']['value'], 2000000)
        self.assertEqual(player['goals'], player['stats']['goals'])
        status, history = self.request('/api/players/1/temporadas')
        self.assertEqual(status, 200, history)
        self.assertEqual([item['sid'] for item in history], [902, 901])
        self.assertEqual([item['stats']['goals'] for item in history], [12, 10])

    def test_same_uid_in_other_career_does_not_change_totals_or_percentiles(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO players(snapshot_id,uid,full_name,position,club_id) VALUES(903,1,'Other save','ST',88)")
            conn.execute('INSERT INTO player_stats(snapshot_id,uid,apps_total,minutes,goals,assists,avg_rating) VALUES(903,1,30,2700,99,40,9)')
        for career, goals in (('alpha', 22), ('beta', 99)):
            with self.subTest(career=career):
                status, player = self.request('/api/players/1/alltime', carreira=career)
                self.assertEqual(status, 200, player)
                self.assertEqual(player['stats']['goals'], goals)
                status, percentiles = self.request('/api/players/1/alltime/percentis', carreira=career, coorte='att')
                self.assertEqual(status, 200, percentiles)
                self.assertEqual(percentiles['metricas']['goals']['v'], goals)
                self.assertEqual(percentiles['carreira'], career)
        self.assertEqual(self.request('/api/players/1/alltime')[1]['carreira'], 'alpha')

    def test_percentiles_use_aggregate_measured_values_and_same_career_peers(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET minutes=1800 WHERE snapshot_id=901 AND uid=2')
        status, result = self.request('/api/players/1/alltime/percentis', carreira='alpha', coorte='att')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['n'], 2)
        self.assertEqual(result['metricas']['g90']['v'], .55)
        self.assertEqual(result['metricas']['a90']['v'], .275)
        self.assertEqual(result['metricas']['g90']['pct'], 75)
        self.assertEqual(result['percentis']['pizza:goals'], 75)
        self.assertNotIn('xg90', result['metricas'])
        self.assertNotIn('pizza:xg', result['metricas'])

    def test_repeated_season_capture_is_not_added_twice(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO snapshots(id,name,game_date,in_game_season,carreira_id,fm_version) VALUES(905,'Later capture','2028-06-01','2027/28','alpha','26')")
            conn.execute("INSERT INTO players(snapshot_id,uid,full_name,position,ca) VALUES(905,1,'Latest identity','ST',120)")
            conn.execute('INSERT INTO player_stats(snapshot_id,uid,apps_total,minutes,goals,assists,avg_rating) VALUES(905,1,10,900,4,2,8)')
        status, player = self.request('/api/players/1/alltime', carreira='alpha')
        self.assertEqual(status, 200, player)
        self.assertEqual(player['stats']['goals'], 22)
        self.assertEqual(player['stats']['minutes'], 3600)
        self.assertEqual([item['sid'] for item in player['temporadas']], [901, 902])
        self.assertEqual(player['identity']['full_name'], 'Latest identity')
        career = self.request('/api/carreiras/alpha/alltime')[1]
        self.assertEqual(len(career['temporadas']), 2)
        self.assertEqual(career['capturas_base'], 3)

    def test_sparse_values_stay_missing_and_recorded_zero_stays_zero(self):
        status, missing = self.request('/api/players/4/alltime', carreira='alpha')
        self.assertEqual(status, 200, missing)
        self.assertIsNone(missing['stats']['goals'])
        status, zero = self.request('/api/players/3/alltime', carreira='alpha')
        self.assertEqual(status, 200, zero)
        self.assertEqual((zero['stats']['goals'], zero['stats']['minutes']), (0, 0))
        self.assertIsNone(zero['stats']['avg_rating'])
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET xg=3,avg_rating=NULL WHERE snapshot_id=902 AND uid=1')
        player = self.request('/api/players/1/alltime', carreira='alpha')[1]
        self.assertIsNone(player['stats']['xg'])
        self.assertIsNone(player['stats']['avg_rating'])
        metrics = self.request('/api/players/1/alltime/percentis', carreira='alpha')[1]['metricas']
        self.assertNotIn('xg90', metrics)

    def test_rating_is_weighted_by_appearances_not_summed(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET apps_total=10,avg_rating=8 WHERE snapshot_id=902 AND uid=1')
        player = self.request('/api/players/1/alltime', carreira='alpha')[1]
        self.assertAlmostEqual(player['stats']['avg_rating'], 7.4)

    def test_live_and_other_fm_versions_do_not_enter_recorded_career(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.executemany('INSERT INTO snapshots(id,name,game_date,in_game_season,scope,carreira_id,fm_version) VALUES(?,?,?,?,?,?,?)', [
                (905, 'Live', '2029-05-30', '2028/29', 'live', 'alpha', '26'),
                (906, 'FM24', '2026-05-30', '2025/26', 'full', 'alpha', '24')])
            for sid in (905, 906):
                conn.execute("INSERT INTO players(snapshot_id,uid,full_name,position) VALUES(?,1,'Unrelated','ST')", (sid,))
                conn.execute('INSERT INTO player_stats(snapshot_id,uid,apps_total,minutes,goals) VALUES(?,1,100,9000,100)', (sid,))
        player = self.request('/api/players/1/alltime', carreira='alpha')[1]
        self.assertEqual(player['stats']['goals'], 22)
        self.assertEqual([item['sid'] for item in player['temporadas']], [901, 902])

    def test_unknown_player_career_and_invalid_cohort_are_explicit(self):
        status, empty = self.request('/api/carreiras/missing/alltime')
        self.assertEqual(status, 200, empty)
        self.assertEqual((empty['players'], empty['seasons'], empty['temporadas']), ([], [], []))
        for route in ('alltime', 'alltime/percentis'):
            self.assertEqual(self.request(f'/api/players/999/{route}', carreira='alpha')[0], 404)
            self.assertEqual(self.request(f'/api/players/1/{route}', carreira='missing')[0], 404)
            self.assertEqual(self.request(f'/api/players/999/{route}')[0], 404)
        self.assertEqual(self.request('/api/players/1/alltime/percentis', carreira='alpha', coorte='invalid')[0], 422)


if __name__ == '__main__':
    unittest.main()
