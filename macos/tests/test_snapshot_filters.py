"""HTTP regressions for snapshot-bound options and player summaries (issue #13)."""

from contextlib import closing
import json
import unittest
import urllib.error
import urllib.request

import test_moneyball_data as fixtures
import server


class SnapshotFilterTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.MoneyballDataTests.tearDownClass.__func__)
    setUp = fixtures.MoneyballDataTests.setUp
    request = fixtures.MoneyballDataTests.request

    options = (('/api/clubs', 'clubs'), ('/api/myteams', 'teams'),
               ('/api/youth-teams', 'youth_teams'))

    def seed(self):
        fixtures.MoneyballDataTests.seed(self)
        with closing(server.get_db_connection()) as conn, conn:
            conn.executemany('INSERT INTO snapshots(id,name,scope) VALUES(?,?,?)', [
                (905, 'Live', 'live'), (906, 'Temporary', 'live_temp')])
            conn.executemany('INSERT INTO youth_teams(snapshot_id,team_uid,club_uid,club_name,n_players) VALUES(?,?,?,?,?)', [
                (901, 772, 77, 'Old youth', 1), (902, 772, 77, 'New youth', 2),
                (903, 882, 88, 'Other youth', 3), (905, 992, 99, 'Live youth', 4),
                (906, 992, 99, 'Temporary youth', 5)])
            conn.executemany('INSERT INTO players(snapshot_id,uid,full_name,club_id,ca,pa) VALUES(?,?,?,?,?,?)', [
                (903, 1, 'Same UID in other career', 88, 130, 180),
                (905, 1, 'Live player', 99, 140, 190),
                (906, 1, 'Temporary player', 99, 150, 200)])
            for sid in (905, 906):
                conn.execute("INSERT INTO club_leagues(snapshot_id,club_uid,club_name) VALUES(?,99,'Live club')", (sid,))
                conn.execute("INSERT INTO teams(snapshot_id,team_uid,club_uid,label) VALUES(?,991,99,'Live team')", (sid,))

    def summary(self, uids, **params):
        request = urllib.request.Request(
            self.base + '/api/resumo-jogadores',
            data=json.dumps({'uids': uids, **params}).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def assert_empty_summary(self, uids, **params):
        status, result = self.summary(uids, **params)
        self.assertEqual(status, 200, result)
        self.assertEqual(result, {
            'qtd': len(set(uids)), 'na_carreira': 0, 'idade_media': None,
            'valor_somado': 0, 'salarios_semana': 0,
            'setores': {'gr': 0, 'def': 0, 'med': 0, 'ata': 0},
            'pa': [], 'idades': [],
            'destaques': {'maior_pa': None, 'barato_145': None, 'mais_valioso': None,
                         'contrato_ate': result['destaques']['contrato_ate'],
                         'emprestados': 0, 'nacionalidades': 0},
        })

    def test_options_stay_in_selected_season_and_career(self):
        expected = {901: (2, 1, 1), 902: (1, 1, 1), 903: (1, 1, 1)}
        for sid in (901, 902, 903, 901):
            for (endpoint, key), count in zip(self.options, expected[sid]):
                with self.subTest(snapshot=sid, endpoint=endpoint):
                    status, result = self.request(endpoint, snapshot=sid)
                    self.assertEqual(status, 200, result)
                    self.assertEqual(set(result), {key})
                    self.assertEqual(len(result[key]), count)
                    self.assertEqual({row['snapshot_id'] for row in result[key]}, {sid})
        self.assertEqual(self.request('/api/myteams', snapshot=901)[1]['teams'][0]['label'], 'Old Team')
        self.assertEqual(self.request('/api/myteams', snapshot=902)[1]['teams'][0]['label'], 'New Team')
        self.assertEqual(self.request('/api/youth-teams', snapshot=901)[1]['youth_teams'][0]['club_name'], 'Old youth')
        self.assertEqual(self.request('/api/youth-teams', snapshot=902)[1]['youth_teams'][0]['club_name'], 'New youth')

    def test_summaries_use_selected_season_and_career_for_each_uid(self):
        for sid, name, pa in ((901, 'Alpha, "Old"', 150),
                              (902, 'Alpha New', 160),
                              (903, 'Same UID in other career', 180),
                              (901, 'Alpha, "Old"', 150)):
            with self.subTest(snapshot=sid):
                status, result = self.summary([1, 999999], snapshot=sid)
                self.assertEqual(status, 200, result)
                self.assertEqual((result['qtd'], result['na_carreira']), (2, 1))
                player = result['pa'][0]
                self.assertEqual((player['uid'], player['sid'], player['nome'], player['pa']), (1, sid, name, pa))
        self.assert_empty_summary([11], snapshot=901)
        self.assertEqual(self.summary([1, 1], snapshot=902)[1], self.summary([1], snapshot=902)[1])
        self.assertEqual({row['uid'] for row in self.summary([1, 2, 11], snapshot=901)[1]['pa']}, {1, 2})

    def test_missing_or_empty_selection_never_falls_back_to_another_snapshot(self):
        for sid in (904, 999999, 0, -1):
            for endpoint, key in self.options:
                with self.subTest(snapshot=sid, endpoint=endpoint):
                    self.assertEqual(self.request(endpoint, snapshot=sid), (200, {key: []}))
            self.assert_empty_summary([1, 11], snapshot=sid)

    def test_omitted_selection_uses_latest_stored_snapshot_and_keeps_it_empty(self):
        for endpoint, key in self.options:
            self.assertEqual(self.request(endpoint), (200, {key: []}))
        self.assert_empty_summary([1, 11])
        self.assert_empty_summary([1, 11], snapshot=None)
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('DELETE FROM snapshots WHERE id=904')
        for endpoint, key in self.options:
            status, result = self.request(endpoint)
            self.assertEqual(status, 200)
            self.assertEqual({row['snapshot_id'] for row in result[key]}, {903})
        expected = self.summary([1, 11], snapshot=903)
        self.assertEqual(self.summary([1, 11]), expected)
        self.assertEqual(self.summary([1, 11], snapshot=None), expected)

    def test_explicit_live_selection_matches_related_option_apis(self):
        for sid in (905, 906):
            for endpoint, key in self.options:
                status, result = self.request(endpoint, snapshot=sid)
                self.assertEqual(status, 200)
                self.assertEqual({row['snapshot_id'] for row in result[key]}, {sid})
            expected = 'Live player' if sid == 905 else 'Temporary player'
            self.assertEqual(self.summary([1], snapshot=sid)[1]['pa'][0]['nome'], expected)

    def test_empty_uid_list_and_missing_players_return_empty_summary(self):
        self.assert_empty_summary([], snapshot=901)
        self.assert_empty_summary([])
        self.assert_empty_summary([999999], snapshot=901)

    def test_only_live_captures_and_empty_database_do_not_leak_rows(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('DELETE FROM snapshots WHERE id < 905')
        for endpoint, key in self.options:
            self.assertEqual(self.request(endpoint), (200, {key: []}))
        self.assert_empty_summary([1, 11])
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('DELETE FROM snapshots')
        for endpoint, key in self.options:
            self.assertEqual(self.request(endpoint), (200, {key: []}))
        self.assert_empty_summary([1, 11])

    def test_malformed_snapshot_is_rejected(self):
        for value in ('invalid', '901.5', ''):
            for endpoint, _ in self.options:
                with self.subTest(snapshot=value, endpoint=endpoint):
                    self.assertEqual(self.request(endpoint, snapshot=value)[0], 422)
            self.assertEqual(self.summary([1], snapshot=value)[0], 422)


if __name__ == '__main__':
    unittest.main()
