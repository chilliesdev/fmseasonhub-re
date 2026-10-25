"""Favorites current/outside browsing and shipped list-cache contracts."""

from contextlib import closing
import json
from pathlib import Path
import subprocess
import unittest
import urllib.request

import test_list_summary as summaries
import test_moneyball_data as fixtures
import server
import settings


class FavoritesFlowTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.MoneyballDataTests.tearDownClass.__func__)
    setUp = fixtures.MoneyballDataTests.setUp
    seed = summaries.ListSummaryTests.seed
    request = fixtures.MoneyballDataTests.request

    def browse(self, **params):
        status, result = self.request('/api/moneyball/browse', **{'snapshot': 901, 'group': 'all', **params})
        self.assertEqual(status, 200, result)
        return result

    def mutate(self, endpoint, body=None, method='POST'):
        req = urllib.request.Request(self.base + endpoint,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'}, method=method)
        with urllib.request.urlopen(req, timeout=10) as response:
            self.assertEqual(response.status, 200)
            return json.load(response)

    def test_current_and_outside_sets_never_overlap(self):
        settings.save(favoritos_listas=[{'id': 'test', 'uids': [1, 2]}])
        normal = self.browse(uids='favlista:test')
        self.assertEqual(normal, self.browse(uids='favlista:test', fora=0))
        self.assertEqual([row['uid'] for row in normal['rows']], [1, 2])
        for params in ({'uids': 'favlista:test'}, {'uids': '1,2'}, {}):
            outside = self.browse(fora=1, **params)
            self.assertEqual((outside['total'], outside['rows']), (0, []))

    def test_outside_preserves_membership_filters_and_source_snapshot(self):
        settings.save(favoritos_listas=[{'id': 'test', 'uids': [1, 30, 31, 11, 999]}])
        result = self.browse(uids='favlista:test', fora=1)
        self.assertEqual((result['snapshot'], result['total']), (901, 1))
        row = result['rows'][0]
        self.assertEqual((row['uid'], row['name'], row['snapshot_id'], row['position']), (30, 'Recent former player', 899, 'DC'))
        self.assertEqual(row['fora'], {'sid': 899, 'dado_de': 'Recent old season',
                                      'data_jogo': '2026-06-01', 'versao_fm': '26.3'})
        self.assertEqual(self.browse(uids='favlista:test', fora=1, group='def', q='former')['total'], 1)
        for params in ({'group': 'att'}, {'q': 'no-match'}, {'exclude': '30'}, {'clubs': '77'}):
            self.assertEqual(self.browse(uids='favlista:test', fora=1, **params)['rows'], [])
        self.assertEqual(self.browse(uids='favlista:test', fora=1, offset=1, limit=1)['rows'], [])
        self.assertEqual(self.browse(uids='favlista:unknown', fora=1)['rows'], [])
        self.assertEqual(self.browse(uids='30', fora=1)['rows'], result['rows'])
        self.assertFalse(any(row.get('fora') for row in self.browse(uids='favlista:test')['rows']))

    def test_missing_career_or_selected_snapshot_cannot_leak_outside_rows(self):
        for sid in (909, 999999, 0):
            self.assertEqual(self.browse(snapshot=sid, uids='30,31,11', fora=1)['rows'], [])
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE snapshots SET game_date=NULL WHERE id=901')
        self.assertEqual(self.browse(uids='30', fora=1)['rows'], [])

    def test_shipped_browse_modes_header_dates_and_mutation_cache(self):
        events = []
        state = self.mutate('/api/favoritos/listas', {'nome': 'Flow test', 'cor': '#cbb668', 'uids': [1, 2]})
        target = state['lista']['id']
        events.append({'method': 'criar', 'response': state})
        current_only = {'current': self.browse(uids='favlista:' + target),
                        'outside': self.browse(uids='favlista:' + target, fora=1)}
        route = '/api/favoritos/listas/' + target
        for method, endpoint, body, verb in (
            ('editar', route, {'nome': 'Renamed flow'}, 'PATCH'),
            ('marcar', route + '/jogadores', {'uids': [30, 999]}, 'POST'),
            ('duplicar', route + '/duplicar', {'nome': 'Copy flow'}, 'POST'),
        ):
            state = self.mutate(endpoint, body, verb)
            events.append({'method': method, 'response': state})
        mixed = {'current': self.browse(uids='favlista:' + target),
                 'outside': self.browse(uids='favlista:' + target, fora=1)}
        state = self.mutate(route, {'esvaziar': True}, 'PATCH')
        events.append({'method': 'editar', 'response': state})
        state = self.mutate(route, method='DELETE')
        events.append({'method': 'apagar', 'response': state})
        for event in events:
            self.assertTrue({'listas', 'padrao', 'paleta', 'aviso'} <= event['response'].keys())
        result = subprocess.run(['node', str(Path(__file__).with_name('favorites_flow_ui.mjs'))],
            input=json.dumps({'browse': [current_only, mixed], 'events': events}),
            text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Favorites flow renderer regressions passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
