"""HTTP and shipped-renderer regressions for Favorites list summaries."""

from contextlib import closing
import json
from pathlib import Path
import subprocess
import unittest
import urllib.error
import urllib.request

import test_moneyball_data as fixtures
import server


class ListSummaryTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.MoneyballDataTests.tearDownClass.__func__)
    setUp = fixtures.MoneyballDataTests.setUp

    def seed(self):
        fixtures.MoneyballDataTests.seed(self)
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("UPDATE player_profile SET contract_end='2028-06-30',nationality_code='GB' WHERE snapshot_id=901 AND uid=1")
            conn.execute("INSERT INTO player_profile(snapshot_id,uid,birth_date,guide_value,wage_weekly,nationality_code,contract_end,loan_end) VALUES(901,2,'2005-01-01',2000000,20000,'BR','2029-06-30','2027-08-01')")
            conn.execute("INSERT INTO player_profile(snapshot_id,uid,guide_value,wage_weekly,nationality_code,contract_end) VALUES(901,3,0,0,'GB','2026-06-30')")
            conn.executemany('INSERT INTO snapshots(id,name,game_date,carreira_id,scope,fm_version) VALUES(?,?,?,?,?,?)', [
                (899, 'Recent old season', '2026-06-01', 'alpha', 'full', '26.3'),
                (900, 'Older imported season', '2025-06-01', 'alpha', 'squad', '24'),
                (907, 'Old live', '2026-07-01', 'alpha', 'live', '26'),
                (908, 'Old temporary', '2026-07-02', 'alpha', 'live_temp', '26'),
                (909, 'No career', '2027-05-30', None, 'squad', '26')])
            conn.executemany('INSERT INTO players(snapshot_id,uid,full_name,position,pa) VALUES(?,?,?,?,?)', [
                (899, 30, 'Recent former player', None, 199),
                (900, 30, 'Older imported player', 'ST', 198),
                (902, 31, 'Future only', 'GK', 197),
                (907, 33, 'Live only', 'GK', 196),
                (908, 34, 'Temporary only', 'GK', 195),
                (899, 35, 'Older missing date', 'ST', 194)])
            conn.execute('INSERT INTO player_profile(snapshot_id,uid,pos_dc) VALUES(899,30,20)')

    def post(self, endpoint, uids, **params):
        request = urllib.request.Request(self.base + endpoint,
            data=json.dumps({'uids': uids, **params}).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def summary(self, uids, **params):
        status, result = self.post('/api/resumo-jogadores', uids, **params)
        self.assertEqual(status, 200, result)
        return result

    def outside(self, uids, **params):
        status, result = self.post('/api/jogadores-fora-da-captura', uids, **params)
        self.assertEqual(status, 200, result)
        return result

    def test_measured_summary_totals_and_highlights_use_selected_records(self):
        result = self.summary([1, 2, 3, 4, 30, 31, 11, 999, 1], snapshot=901)
        self.assertEqual((result['qtd'], result['na_carreira']), (8, 4))
        self.assertEqual(result['idade_media'], 24)
        self.assertEqual(result['valor_somado'], 3000000)
        self.assertEqual(result['salarios_semana'], 30000)
        self.assertEqual(result['setores'], {'gr': 1, 'def': 0, 'med': 1, 'ata': 2})
        self.assertEqual({row['uid'] for row in result['pa']}, {1, 2, 3, 4})
        self.assertEqual({row['sid'] for row in result['pa']}, {901})
        self.assertEqual({row['idade'] for row in result['idades']}, {22, 26})
        highlights = result['destaques']
        self.assertEqual(highlights['maior_pa']['uid'], 2)
        self.assertEqual(highlights['barato_145']['uid'], 1)
        self.assertEqual(highlights['mais_valioso']['uid'], 2)
        self.assertEqual(highlights['contrato_ate'], {'ano': 2028, 'qtd': 1})
        self.assertEqual(highlights['emprestados'], 1)
        self.assertEqual(highlights['nacionalidades'], 2)

    def test_sparse_measurements_are_missing_and_zero_money_is_valid(self):
        sparse = self.summary([4], snapshot=901)
        self.assertIsNone(sparse['idade_media'])
        self.assertIsNone(sparse['valor_somado'])
        self.assertIsNone(sparse['salarios_semana'])
        self.assertEqual(sparse['idades'], [])
        self.assertIsNone(sparse['destaques']['barato_145'])
        self.assertIsNone(sparse['destaques']['mais_valioso'])
        zero = self.summary([3], snapshot=901)
        self.assertEqual((zero['valor_somado'], zero['salarios_semana']), (0, 0))
        self.assertEqual(zero['destaques']['mais_valioso']['valor'], 0)
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE players SET pa=-7 WHERE snapshot_id=901 AND uid=4')
        self.assertEqual(self.summary([4], snapshot=901)['pa'], [])

    def test_empty_unknown_and_missing_snapshot_shapes_do_not_crash_the_panel(self):
        for uids, sid in (([], 901), ([999], 901), ([1, 30], 999999), ([1, 30], 904)):
            with self.subTest(uids=uids, snapshot=sid):
                result = self.summary(uids, snapshot=sid)
                self.assertEqual((result['qtd'], result['na_carreira']), (len(uids), 0))
                self.assertEqual((result['pa'], result['idades']), ([], []))
                self.assertEqual(sum(result['setores'].values()), 0)
                self.assertEqual(self.outside(uids, snapshot=sid), {
                    'uids': sorted(uids), 'linhas': [], 'sem_dado': len(uids)})

    def test_outside_capture_uses_older_same_career_provenance_only(self):
        result = self.outside([1, 30, 30, 31, 11, 33, 34, 999], snapshot=901)
        self.assertEqual(result['uids'], [11, 30, 31, 33, 34, 999])
        self.assertEqual(result['sem_dado'], 5)
        self.assertEqual(result['linhas'], [{
            'uid': 30, 'snapshot': 899, 'nome': 'Recent former player', 'posicao': 'DC',
            'dado_de': 'Recent old season', 'versao_fm': '26.3'}])
        self.assertEqual(self.summary([30], snapshot=901)['pa'], [])
        self.assertEqual(self.summary([30], snapshot=899)['pa'][0]['pa'], 199)
        self.assertEqual(self.outside([30], snapshot=899), {'uids': [], 'linhas': [], 'sem_dado': 0})

    def test_no_career_or_date_cannot_borrow_another_snapshot(self):
        self.assertEqual(self.outside([30], snapshot=909), {'uids': [30], 'linhas': [], 'sem_dado': 1})
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE snapshots SET game_date=NULL WHERE id=901')
        self.assertEqual(self.outside([30], snapshot=901), {'uids': [30], 'linhas': [], 'sem_dado': 1})

    def test_outside_rejects_missing_malformed_and_impossible_source_dates(self):
        dates = [None, '', '2027-02-30', 'not-a-date', '2027-02-28junk', '20270228', '2027-W01-1']
        uids = [501 + index for index in range(len(dates))]
        with closing(server.get_db_connection()) as conn, conn:
            for index, invalid in enumerate(dates):
                sid, uid = 880 + index, uids[index]
                conn.execute('INSERT INTO snapshots(id,name,game_date,carreira_id,scope) VALUES(?,?,?,?,?)',
                             (sid, 'Invalid date', invalid, 'alpha', 'squad'))
                conn.execute('INSERT INTO players(snapshot_id,uid,full_name) VALUES(?,?,?)', (sid, uid, 'Invalid source'))
        result = self.outside(uids, snapshot=901)
        self.assertEqual(result, {'uids': uids, 'linhas': [], 'sem_dado': len(uids)})
        status, table = fixtures.MoneyballDataTests.request(self, '/api/moneyball/browse',
            snapshot=901, group='all', uids=','.join(map(str, uids)), fora=1)
        self.assertEqual((status, table['total'], table['rows']), (200, 0, []))
        current = self.summary(uids, snapshot=901)
        self.assertEqual((current['qtd'], current['na_carreira'], current['pa']), (len(uids), 0, []))

    def test_invalid_newest_source_does_not_hide_valid_older_duplicate(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("UPDATE snapshots SET game_date='2027-02-30' WHERE id=899")
        result = self.outside([30, 35], snapshot=901)
        self.assertEqual((result['linhas'][0]['uid'], result['linhas'][0]['snapshot']), (30, 900))
        self.assertEqual(result['sem_dado'], 1)
        status, table = fixtures.MoneyballDataTests.request(self, '/api/moneyball/browse',
            snapshot=901, group='all', uids='30,35', fora=1)
        self.assertEqual((status, table['total']), (200, 1))
        self.assertEqual((table['rows'][0]['uid'], table['rows'][0]['fora']['sid']), (30, 900))
        self.assertEqual(table['rows'][0]['fora']['data_jogo'], '2025-06-01')

    def test_date_and_id_boundaries_keep_latest_valid_same_day_source(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.executemany('INSERT INTO snapshots(id,name,game_date,carreira_id,scope) VALUES(?,?,?,?,?)', [
                (897, 'Earlier same day', '2027-05-30', 'alpha', 'squad'),
                (898, 'Latest earlier same day', '2027-05-30', 'alpha', 'squad'),
                (910, 'Later same day', '2027-05-30', 'alpha', 'squad'),
                (896, 'Future date earlier ID', '2027-05-31', 'alpha', 'squad')])
            conn.executemany('INSERT INTO players(snapshot_id,uid,full_name) VALUES(?,?,?)', [
                (897, 30, 'Earlier same-day record'), (898, 30, 'Latest earlier same-day record'),
                (910, 30, 'Later record'), (910, 501, 'Later-only record'),
                (896, 30, 'Future record'), (896, 502, 'Future-only record')])
        result = self.outside([30, 501, 502], snapshot=901)
        self.assertEqual([(row['uid'], row['snapshot']) for row in result['linhas']], [(30, 898)])
        self.assertEqual(result['sem_dado'], 2)
        # Existing source 899 remains the nearest valid source for another UID.
        self.assertEqual(self.outside([35], snapshot=901)['linhas'][0]['snapshot'], 899)

    def test_omitted_snapshot_stays_latest_stored_and_bad_input_is_rejected(self):
        self.assertEqual(self.summary([1, 30]), self.summary([1, 30], snapshot=909))
        self.assertEqual(self.outside([1, 30]), self.outside([1, 30], snapshot=909))
        for endpoint in ('/api/resumo-jogadores', '/api/jogadores-fora-da-captura'):
            self.assertEqual(self.post(endpoint, [1], snapshot='bad')[0], 422)

    def test_real_shipped_summary_and_outside_capture_renderers(self):
        cases = []
        for uids, sid in (([], 901), ([1, 2], 901), ([4], 901), ([1, 30, 999], 901), ([1], 999999)):
            cases.append({'uids': uids, 'snapshot': sid,
                          'summary': self.summary(uids, snapshot=sid),
                          'outside': self.outside(uids, snapshot=sid)})
        script = Path(__file__).with_name('list_summary_ui.mjs')
        result = subprocess.run(['node', str(script)], input=json.dumps(cases),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('List renderer regressions passed: 5 cases', result.stdout)


if __name__ == '__main__':
    unittest.main()
