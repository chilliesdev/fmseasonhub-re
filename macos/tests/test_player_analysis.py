"""HTTP checks for stored player analysis and similar-player search (issue #9)."""

from contextlib import closing
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import unittest

import test_moneyball_data as moneyball_tests
import server


class PlayerAnalysisTests(unittest.TestCase):
    setUpClass = classmethod(moneyball_tests.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(moneyball_tests.MoneyballDataTests.tearDownClass.__func__)
    setUp = moneyball_tests.MoneyballDataTests.setUp
    seed = moneyball_tests.MoneyballDataTests.seed

    def request(self, path, body=None, **params):
        url = self.base + path + '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def player(self, suffix, uid=1, sid=901, **params):
        return self.request(f'/api/snapshots/{sid}/players/{uid}/{suffix}', **params)

    def populated(self):
        with closing(server.get_db_connection()) as conn, conn:
            for uid, goals, shots, xg in ((1, 10, 50, 8), (2, 10, 50, 8)):
                conn.execute('UPDATE player_stats SET minutes=1800,shots=?,shots_on_target=25,xg=?,npxg=?,xa=4,key_passes=20,goals=? WHERE snapshot_id=901 AND uid=?',
                             (shots, xg, xg, goals, uid))
            conn.execute("INSERT INTO players(snapshot_id,uid,full_name,position,club_id,ca,pa) VALUES(901,5,'Distant','ST',78,100,150)")
            conn.execute('INSERT INTO player_stats(snapshot_id,uid,minutes,goals,shots,shots_on_target,xg,npxg,xa,key_passes) VALUES(901,5,1800,2,10,5,2,2,1,5)')

    def test_original_issue_fixture_returns_measured_analysis(self):
        status, full = self.request('/api/snapshots/901/players/1')
        self.assertEqual(status, 200, full)
        self.assertEqual(full['identity']['full_name'], 'Alpha, \"Old\"')
        self.assertEqual(full['stats']['goals'], full['goals'])
        self.assertEqual(full['profile']['age'], 26)
        self.assertEqual(full['profile']['wage'], 10000)
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        self.assertEqual((result['totais']['minutes'], result['totais']['goals'], result['totais']['assists']), (1800, 10, 5))
        self.assertEqual(result['metricas']['g90']['v'], .5)
        self.assertEqual(result['metricas']['a90']['v'], .25)
        self.assertNotIn('xg90', result['metricas'])
        self.assertIsNone(result['partidas'])
        self.assertEqual(result['contexto']['snapshot_id'], 901)
        self.assertFalse(result['contexto']['partidas_disponiveis'])

    def test_player_seasons_supports_profile_snapshot_selection(self):
        status, seasons = self.request('/api/players/1/temporadas')
        self.assertEqual(status, 200, seasons)
        self.assertIsInstance(seasons, list)
        self.assertEqual([season['sid'] for season in seasons], [902, 901])
        self.assertEqual([season['carreira_id'] for season in seasons], ['alpha', 'alpha'])
        self.assertEqual([season['stats']['goals'] for season in seasons], [12, 10])
        self.assertEqual([season['stats']['snapshot_id'] for season in seasons], [902, 901])
        current = next(season for season in seasons if season['sid'] == 901)
        self.assertEqual(current['stats']['minutes'], 1800)
        self.assertEqual(current['game_date'], '2027-05-30')
        self.assertFalse(current['is_live'])
        status, sparse = self.request('/api/players/4/temporadas')
        self.assertEqual(status, 200, sparse)
        self.assertEqual((sparse[0]['sid'], sparse[0]['stats']), (901, {}))
        self.assertEqual(self.request('/api/players/999999/temporadas'), (200, []))
        status, composition = self.request('/api/carreiras/alpha/alltime')
        self.assertEqual(status, 200, composition)
        self.assertIsInstance(composition['temporadas'], list)
        self.assertEqual(composition['temporadas'], composition['seasons'])

    def test_exact_midrank_percentiles_and_client_ids(self):
        status, result = self.player('percentis', min_minutes=0)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['metricas']['g90']['pct'], 25)
        self.assertEqual(result['metricas']['g90']['rank'], 2)
        self.assertEqual(result['metricas']['g90']['n'], 2)
        self.assertEqual(result['metricas']['pizza:goals']['v'], .5)
        self.assertEqual(result['percentis']['pizza:goals'], 25)
        self.assertNotIn('pizza:xg', result['metricas'])
        self.assertEqual(result['n'], 2)

    def test_ties_lower_better_and_league_scope(self):
        self.populated()
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET possession_lost=20 WHERE snapshot_id=901 AND uid=1')
            conn.execute('UPDATE player_stats SET possession_lost=40 WHERE snapshot_id=901 AND uid=2')
        status, result = self.player('percentis', regua='liga')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['n'], 1)
        status, result = self.player('percentis')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['metricas']['g90']['pct'], 66.7)
        self.assertEqual(result['metricas']['pl90']['pct'], 25)
        self.assertEqual(result['metricas']['pl90']['p'], 75)

    def test_snapshot_and_career_isolation(self):
        for sid, expected in ((901, .5), (902, .6), (903, .5)):
            status, result = self.player('analise', uid=11 if sid == 903 else 1, sid=sid)
            self.assertEqual(status, 200, result)
            self.assertEqual(result['metricas']['g90']['v'], expected)
            self.assertEqual(result['n'], 1)
        for route in ('analise', 'percentis', 'buscar-como'):
            self.assertEqual(self.player(route, sid=999)[0], 404)
            self.assertEqual(self.player(route, uid=11)[0], 404)

    def test_missing_and_zero_minutes_do_not_create_measurements(self):
        self.assertEqual(self.player('analise', uid=4, min_minutes=0)[0], 422)
        status, result = self.player('percentis', uid=3, min_minutes=0)
        self.assertEqual(status, 200, result)
        self.assertNotIn('g90', result['metricas'])
        self.assertNotIn('pizza:goals', result['metricas'])
        self.assertEqual(result['metricas']['goals']['v'], 0)
        self.assertEqual(self.player('percentis', min_minutes=10000)[0], 422)

    def test_analysis_parameter_validation(self):
        for params in ({'coorte': 'unknown'}, {'regua': 'unknown'}, {'min_minutes': -1}):
            with self.subTest(params=params):
                self.assertEqual(self.player('analise', **params)[0], 422)
                self.assertEqual(self.player('percentis', **params)[0], 422)

    def test_real_saved_match_and_team_result(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO player_match_stats(snapshot_id,uid,match_id,match_date,team_uid,opp_uid,home,started,minutes,rating,goals,assists,xg) VALUES(901,1,80,'2027-05-20',771,781,1,1,90,8.1,2,1,.8)")
            conn.execute("INSERT INTO team_match_stats(snapshot_id,team_uid,match_id,match_date,goals_for,goals_against,xg_for,xg_against) VALUES(901,771,80,'2027-05-20',3,1,2,.5)")
            conn.execute("INSERT INTO player_match_stats(snapshot_id,uid,match_id,match_date,minutes) VALUES(902,1,90,'2028-05-20',90)")
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        matches = result['partidas']
        self.assertEqual((matches['jogos'], matches['cobertura']), (1, 'parcial'))
        self.assertEqual((matches['serie'][0]['g'], matches['serie'][0]['n'], matches['serie'][0]['res']), (2, 8.1, 'V'))
        self.assertEqual(matches['peso']['campos']['goals'], {'v': 2, 't': 3, 'p': 66.67})
        self.assertNotIn('shots', matches['peso']['campos'])
        self.assertTrue(result['contexto']['partidas_disponiveis'])

    def test_insufficient_reference_returns_useful_validation(self):
        status, result = self.player('buscar-como')
        self.assertEqual(status, 422)
        self.assertIn('3 metricas', result['detail'])
        status, result = self.request('/api/snapshots/901/buscar-como-receita', {'metricas': ['att_N']})
        self.assertEqual(status, 422)
        self.assertIn('ref', result['detail'])

    def test_similar_player_result_uses_measured_same_snapshot_peers(self):
        self.populated()
        status, result = self.player('buscar-como', metricas='g90,xg90,sh90', fora=0, tol=10)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['uids'], [2])
        self.assertEqual(result['semelhanca'], [100])
        self.assertEqual(result['valores'], [[.5, .4, 2.5]])
        self.assertEqual(result['ligadas'], ['g90', 'xg90', 'sh90'])
        self.assertEqual((result['total'], result['referencia']['uid']), (1, 1))
        self.assertEqual(self.player('buscar-como', metricas='g90,xg90,sh90', fora=0, excluir_clube=78)[1]['uids'], [])

    def test_shipped_recipe_contract(self):
        self.populated()
        body = {'ref': {'nome': 'QA Recipe', 'posicao': 'ST', 'coorte': 'att', 'grupo': 'att',
                        'valores': {'g90': .5, 'xg90': .4, 'sh90': 2.5}},
                'metricas': ['g90', 'xg90', 'sh90'], 'tol': 10, 'fora': 0, 'min_minutes': 900}
        status, result = self.request('/api/snapshots/901/buscar-como-receita', body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['uids'], [1, 2])
        self.assertTrue(result['referencia']['receita'])
        self.assertEqual(result['semelhanca'], [100, 100])
        self.assertEqual(self.request('/api/snapshots/999/buscar-como-receita', body)[0], 404)

    def test_invalid_search_is_not_silently_ignored(self):
        self.populated()
        for params in ({'metricas': 'att_N'}, {'tol': 'nan'}, {'fora': -1}, {'limite': 0},
                       {'min_minutes': 1.5}, {'modo': 'bad'}, {'pe': 'bad'}, {'mais': 11},
                       {'unknown': 1}, {'nivel': 'overall', 'piso_ca': 70}, {'contrato_ate': 'bad'}):
            with self.subTest(params=params):
                status, result = self.player('buscar-como', **params)
                self.assertEqual(status, 422, result)
        self.assertEqual(self.player('buscar-como', metricas='g90,xg90,sh90', modo='pct', tol=100)[0], 200)

    def test_partial_candidates_and_nonfinite_values_are_excluded(self):
        self.populated()
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET xg=NULL WHERE snapshot_id=901 AND uid=2')
        status, result = self.player('buscar-como', metricas='g90,xg90,sh90', fora=0, tol=100)
        self.assertEqual(status, 200, result)
        self.assertNotIn(2, result['uids'])
        status, loose = self.player('buscar-como', metricas='g90,xg90,sh90', fora=2, tol=100)
        self.assertEqual(status, 200, loose)
        self.assertNotIn(2, loose['uids'])
        status, result = self.player('percentis')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['metricas']['xg90']['n'], 2)
        body = {'ref': {'coorte': 'att', 'grupo': 'att', 'valores': {'g90': 'nan'}}, 'metricas': ['g90']}
        self.assertEqual(self.request('/api/snapshots/901/buscar-como-receita', body)[0], 422)

    def test_keeper_measured_values_and_cohort(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET minutes=1800,apps_total=20,gk_saves_held=30,gk_saves_parried=10,gk_saves_tipped=10,goals_conceded_gk=10,clean_sheets_gk=8,xg_prevented_gk=4 WHERE snapshot_id=901 AND uid=3')
        status, result = self.player('analise', uid=3)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['coorte'], 'gk')
        self.assertAlmostEqual(result['goleiro']['metricas']['gksv']['v'], 83.3333)
        self.assertEqual(result['goleiro']['metricas']['gkcs']['v'], 40)
        status, result = self.player('percentis', uid=3)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['metricas']['i:defesas90']['v'], 2.5)
        self.assertEqual(result['metricas']['g:gk_semgol']['v'], .4)

    def test_complete_saved_match_context(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO player_match_stats(snapshot_id,uid,match_id,match_date,team_uid,home,started,minutes,rating,goals,assists,shots,xg,xa,presses_completed,tackles_completed,interceptions,sprints) VALUES(901,1,80,'2027-05-20',771,1,1,90,8.1,2,1,5,.8,.4,5,2,1,10)")
            conn.execute("INSERT INTO team_match_stats(snapshot_id,team_uid,match_id,match_date,goals_for,goals_against,xg_against) VALUES(901,771,80,'2027-05-20',3,1,.5)")
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        context = result['partidas']['contexto']
        self.assertEqual(context['casa']['min'], 90)
        self.assertEqual(context['casa']['g'], 2)
        self.assertEqual(context['casa']['sh90'], 5)
        self.assertEqual(context['casa']['nota'], 8.1)
        self.assertNotIn('kp90', context['casa'])
        self.assertIsNone(context['fora'])

    def test_preview_aliases_have_measured_values_and_ratio_units(self):
        self.populated()
        status, result = self.player('percentis')
        self.assertEqual(status, 200, result)
        metrics = result['metricas']
        self.assertEqual(metrics['i:xg90']['v'], .4)
        self.assertEqual(metrics['i:xgover']['v'], 2)
        self.assertEqual(metrics['i:convfin']['v'], .2)
        self.assertEqual(metrics['i:convfin']['mediana'], .2)
        self.assertEqual(metrics['i:xg90']['pct'], metrics['xg90']['pct'])
        self.assertEqual(metrics['i:convfin']['pct'], metrics['conv']['pct'])
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET clear_cut_chances=10 WHERE snapshot_id=901 AND uid IN (1,2,5)')
        status, analysis = self.player('analise')
        self.assertEqual(status, 200, analysis)
        points = analysis['dispersao']['criador_finalizador']
        self.assertEqual(len(points), 3)
        self.assertEqual({point[2] for point in points}, {1, 2, 5})
        reference = next(point for point in points if point[2] == 1)
        self.assertEqual(reference[:2], analysis['criador_finalizador_eu'])

    def test_sparse_analysis_does_not_create_preview_or_similarity_data(self):
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['totais']['goals'], 10)
        self.assertNotIn('xg', result['totais'])
        for key in ('i:xg90', 'i:xgover', 'i:convfin'):
            self.assertNotIn(key, result['metricas'])
        self.assertTrue(all(not peers for peers in result['similares'].values()))
        self.assertTrue(all(not points for points in result['dispersao'].values()))
        self.assertEqual(result['histograma'], {})
        self.assertNotIn('poisson', result)

    def test_keeper_response_has_the_rendered_cohort_and_distribution_contract(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET minutes=1800,apps_total=20,goals_conceded_gk=0,clean_sheets_gk=20,xg_prevented_gk=2 WHERE snapshot_id=901 AND uid=3')
        status, result = self.player('analise', uid=3)
        self.assertEqual(status, 200, result)
        keeper = result['goleiro']
        self.assertEqual(keeper['n'], 1)
        self.assertEqual(keeper['totais']['goals_conceded_gk'], 0)
        self.assertEqual(keeper['metricas']['ga90']['v'], 0)
        self.assertIn('ga90', keeper['distribuicao'])
        self.assertEqual(sum(keeper['distribuicao']['ga90']['caixas']), 1)
        self.assertNotIn('gksv', keeper['metricas'])
        self.assertNotIn('histograma', keeper)
        self.assertEqual(result['dispersao']['trabalho_eficiencia'], [])

    def test_shipped_renderers_distinguish_missing_values_and_known_zero(self):
        script = Path(__file__).with_name('player_analysis_ui.mjs')
        result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('renderer regressions passed', result.stdout)

    def test_newer_national_match_does_not_replace_club_window(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO youth_teams(snapshot_id,team_uid,club_uid,nation) VALUES(901,999,999,10)")
            conn.execute("INSERT INTO player_match_stats(snapshot_id,uid,match_id,match_date,team_uid,home,started,minutes,goals,assists,shots) VALUES(901,1,80,'2027-05-20',771,1,1,90,2,1,5)")
            conn.execute("INSERT INTO player_match_stats(snapshot_id,uid,match_id,match_date,team_uid,home,started,minutes,goals,assists,shots) VALUES(901,1,90,'2027-05-29',999,1,1,90,8,3,15)")
            conn.execute("INSERT INTO team_match_stats(snapshot_id,team_uid,match_id,match_date,goals_for) VALUES(901,771,80,'2027-05-20',3)")
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        matches = result['partidas']
        self.assertEqual([match['d'] for match in matches['serie']], ['2027-05-20'])
        self.assertEqual(matches['contexto']['casa']['g'], 2)
        self.assertEqual(matches['peso']['campos']['goals']['v'], 2)
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('DELETE FROM player_match_stats WHERE snapshot_id=901 AND team_uid=771')
        self.assertIsNone(self.player('analise')[1]['partidas'])

    def test_incomplete_match_duration_keeps_totals_but_not_rates(self):
        for missing in (None, float('inf'), float('-inf')):
            with self.subTest(minutes=missing):
                with closing(server.get_db_connection()) as conn, conn:
                    conn.execute('DELETE FROM player_match_stats WHERE snapshot_id=901 AND uid=1')
                    conn.execute('DELETE FROM team_match_stats WHERE snapshot_id=901')
                    for match_id, minutes in ((80, 90), (81, missing)):
                        conn.execute("INSERT INTO player_match_stats(snapshot_id,uid,match_id,match_date,team_uid,home,started,minutes,goals,assists,shots) VALUES(901,1,?,'2027-05-20',771,1,1,?,2,1,5)", (match_id, minutes))
                        conn.execute("INSERT INTO team_match_stats(snapshot_id,team_uid,match_id,match_date,goals_for,goals_against,xg_against) VALUES(901,771,?,'2027-05-20',3,1,.5)", (match_id,))
                status, result = self.player('analise')
                self.assertEqual(status, 200, result)
                matches = result['partidas']
                home = matches['contexto']['casa']
                self.assertEqual((home['jogos'], home['g'], home['a']), (2, 4, 2))
                self.assertIsNone(home['min'])
                self.assertEqual((home['min_conhecidos'], home['jogos_com_minutos']), (90, 1))
                for key in ('sh90', 'ga90', 'gs90', 'xgc90'):
                    self.assertNotIn(key, home)
                self.assertIsNone(matches['minutos'])
                self.assertIsNone(matches['serie'][1]['m'])
                self.assertIsNone(matches['peso']['fatia_justa'])
                self.assertEqual(matches['peso']['campos']['goals']['v'], 4)
                self.assertEqual(matches['cobertura'], 'parcial')

    def test_zero_match_duration_is_known_but_has_no_per90(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO player_match_stats(snapshot_id,uid,match_id,match_date,team_uid,home,started,minutes,goals,assists,shots) VALUES(901,1,80,'2027-05-20',771,1,1,0,0,0,0)")
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        matches = result['partidas']
        self.assertEqual(matches['minutos'], 0)
        self.assertEqual(matches['jogos_com_minutos'], 1)
        self.assertEqual(matches['contexto']['casa']['min'], 0)
        self.assertEqual(matches['contexto']['casa']['g'], 0)
        self.assertNotIn('sh90', matches['contexto']['casa'])
        self.assertEqual(matches['peso']['fatia_justa'], 0)

    def test_analysis_keeper_peers_use_keeper_metrics_and_snapshot_bounds(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("UPDATE players SET position='GK' WHERE uid IN (1,2,11)")
            for sid, uid in ((901,1), (901,2), (903,11)):
                conn.execute('UPDATE player_stats SET minutes=1800,apps_total=20,gk_saves_held=30,gk_saves_parried=10,gk_saves_tipped=10,goals_conceded_gk=10,clean_sheets_gk=8,xg_prevented_gk=4 WHERE snapshot_id=? AND uid=?', (sid,uid))
            conn.execute("INSERT INTO players(snapshot_id,uid,full_name,position) VALUES(901,5,'Sparse keeper','GK')")
            conn.execute('INSERT INTO player_stats(snapshot_id,uid,minutes,apps_total,xg_prevented_gk) VALUES(901,5,1800,20,4)')
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['goleiro']['similares'], [{'uid': 2, 'sim': 100}])
        self.assertEqual(result['similares']['gk'], result['goleiro']['similares'])
        status, search = self.player('buscar-como', metricas='gksv,gkxgp,gkcs', tol=10, fora=0)
        self.assertEqual(status, 200, search)
        self.assertEqual(search['uids'], [2])
        self.assertEqual(search['semelhanca'], [100])

    def chart_fixture(self, keeper=False):
        with closing(server.get_db_connection()) as conn, conn:
            for uid, shots, expected, goals, assists, xa, passes, completed, progressive, tackles, interceptions, clearances, blocks, pressures, lost, won in (
                    (1, 50, 8, 10, 5, 4, 1000, 800, 100, 30, 20, 10, 5, 60, 50, 50),
                    (2, 60, 12, 12, 6, 5, 1200, 900, 180, 40, 30, 20, 10, 80, 80, 100)):
                conn.execute('UPDATE player_stats SET minutes=1800,apps_total=20,shots=?,shots_on_target=25,xg=?,goals=?,assists=?,xa=?,passes_attempted=?,passes_completed=?,passes_progressive=?,tackles_completed=?,interceptions=?,clearances=?,blocks=?,presses_completed=?,possession_lost=?,possession_won=?,key_passes=20,clear_cut_chances=10 WHERE snapshot_id=901 AND uid=?',
                             (shots,expected,goals,assists,xa,passes,completed,progressive,tackles,interceptions,clearances,blocks,pressures,lost,won,uid))
                if keeper:
                    conn.execute("UPDATE players SET position='GK' WHERE snapshot_id=901 AND uid=?", (uid,))
                    conn.execute('UPDATE player_stats SET gk_saves_held=?,gk_saves_parried=10,gk_saves_tipped=10,goals_conceded_gk=?,clean_sheets_gk=8,xg_prevented_gk=?,gk_xg_faced=?,gk_penalties_faced=5,gk_penalties_saved=2 WHERE snapshot_id=901 AND uid=?',
                                 (30 if uid==1 else 40, 10 if uid==1 else 20, 4 if uid==1 else 6, 14 if uid==1 else 20, uid))
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        return result

    def test_every_consumed_chart_has_exact_measured_values(self):
        result = self.chart_fixture()
        plots = result['dispersao']
        self.assertEqual(plots['volume_qualidade'], [[2.5,.16,1],[3,.2,2]])
        self.assertEqual(plots['progressao_seguranca'], [[80,12.5,1],[75,20,2]])
        self.assertEqual(plots['reativo_proativo'], [[3.25,3,1],[5,4,2]])
        self.assertEqual(plots['posse'], [[2.5,2.5,1],[4,5,2]])
        for name, low, high in (('gols_menos_xg',0,.4), ('assist_menos_xa',.05,1.05)):
            histogram = result['histograma'][name]
            self.assertEqual(len(histogram['caixas']), 22)
            self.assertEqual(sum(histogram['caixas']), 2)
            self.assertAlmostEqual(histogram['min'], low)
            self.assertAlmostEqual(histogram['max'], high)
        self.assertEqual(result['poisson']['gols'], 28)
        self.assertEqual(result['dispersao']['trabalho_eficiencia'], [])
        self.assertEqual(result['dispersao']['esperado_evitado'], [])
        keeper = self.chart_fixture(keeper=True)
        self.assertEqual(keeper['dispersao']['trabalho_eficiencia'], [[3,83.333,1],[4,75,2]])
        self.assertEqual(keeper['dispersao']['esperado_evitado'], [[.7,.2,1],[1,.3,2]])
        histogram = keeper['goleiro']['histograma']
        self.assertEqual(len(histogram['caixas']), 22)
        self.assertEqual(sum(histogram['caixas']), 2)
        self.assertAlmostEqual(histogram['min'], 2/3)
        self.assertAlmostEqual(histogram['max'], .75)
        with tempfile.TemporaryDirectory(prefix='fmsh-chart-contract-') as directory:
            fixture = Path(directory) / 'payload.json'
            fixture.write_text(json.dumps({'outfield':result, 'keeper':keeper}))
            script = Path(__file__).with_name('player_analysis_charts.mjs')
            rendered = subprocess.run(['node', str(script), str(fixture)], capture_output=True, text=True, timeout=15)
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            self.assertIn('All consumed chart payloads', rendered.stdout)

    def test_chart_cohort_scope_thresholds_and_sparse_exclusions(self):
        self.chart_fixture()
        status, league = self.player('analise', regua='liga')
        self.assertEqual(status, 200, league)
        self.assertEqual(league['dispersao']['volume_qualidade'], [[2.5,.16,1]])
        self.assertNotIn('gols_menos_xg', league['histograma'])
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET passes_attempted=150 WHERE snapshot_id=901 AND uid=2')
        status, result = self.player('analise')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['dispersao']['progressao_seguranca'], [[80,12.5,1]])
        self.assertEqual([point[2] for point in result['dispersao']['volume_qualidade']], [1,2])
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET xg=NULL,passes_completed=NULL,tackles_completed=NULL,possession_won=NULL WHERE snapshot_id=901 AND uid=1')
        status, sparse = self.player('analise')
        self.assertEqual(status, 200, sparse)
        for name in ('volume_qualidade','progressao_seguranca','reativo_proativo','posse'):
            self.assertEqual(sparse['dispersao'][name], [])
        self.assertNotIn('gols_menos_xg', sparse['histograma'])
        self.assertNotIn('poisson', sparse)
        self.assertEqual(sparse['totais']['goals'], 10)

    def test_probability_zero_sparse_and_stable_large_counts(self):
        self.chart_fixture()
        for goals, expected, probability in ((0,0,100), (1,0,0), (10,8,28), (1000,1000,50)):
            with self.subTest(goals=goals,expected=expected):
                with closing(server.get_db_connection()) as conn, conn:
                    conn.execute('UPDATE player_stats SET goals=?,xg=? WHERE snapshot_id=901 AND uid=1', (goals,expected))
                status, result = self.player('analise')
                self.assertEqual(status, 200, result)
                self.assertEqual(result['poisson']['gols'], probability)
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('UPDATE player_stats SET xg=? WHERE snapshot_id=901 AND uid=1', (float('inf'),))
        self.assertNotIn('poisson', self.player('analise')[1])

    def test_scatter_sampling_is_bounded_and_keeps_extremes(self):
        import numpy as np
        import player_analysis
        rows = [{'uid':uid} for uid in range(1000)]
        x = np.arange(1000,dtype=float)
        values = {'x':x,'y':x.copy()}
        points = player_analysis.scatter_points(rows,values,('x','y'),np.ones(1000,dtype=bool))
        self.assertLessEqual(len(points),650)
        self.assertEqual(points[0],[0,0,0])
        self.assertEqual(points[-1],[999,999,999])
        self.assertEqual(len({point[2] for point in points}),len(points))


if __name__ == '__main__':
    unittest.main()
