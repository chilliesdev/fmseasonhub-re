"""HTTP regressions for stored Moneyball data and shipped UI contracts."""

import csv
from contextlib import closing
import io
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import db
import moneyball_data
import server
import settings
import uvicorn


class MoneyballDataTests(unittest.TestCase):
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
            raise RuntimeError('Moneyball HTTP server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='fmsh-moneyball-test-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / 'captured.db'
        for target, name, value in ((server, 'get_db_path', lambda: self.database),
                                    (settings, 'SETTINGS_PATH', str(self.root / 'settings.json'))):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        db.init_db(str(self.database))
        self.seed()

    def seed(self, minimal=False):
        with closing(server.get_db_connection()) as conn, conn:
            conn.executemany('INSERT INTO snapshots(id,name,game_date,carreira_id,club_uid) VALUES(?,?,?,?,?)', [
                (901, 'Old', '2027-05-30', 'alpha', 77), (902, 'New', '2028-05-30', 'alpha', 77),
                (903, 'Other', '2027-05-30', 'beta', 88), (904, 'Empty', '2028-05-30', 'beta', 88)])
            players = [(901, 1, 'Alpha, "Old"', 77, 771, 100, 150), (901, 2, 'Beta Forward', 78, 781, 120, 160),
                       (901, 3, 'Keeper', 77, 771, 90, 140), (901, 4, 'Missing records', 77, 772, 80, 120),
                       (902, 1, 'Alpha New', 77, 771, 110, 160), (903, 11, 'Other career', 88, 881, 110, 160)]
            conn.executemany('INSERT INTO players(snapshot_id,uid,full_name,club_id,team_uid,ca,pa) VALUES(?,?,?,?,?,?,?)', players)
            conn.executemany('INSERT INTO player_stats(snapshot_id,uid,apps_total,minutes,goals,assists,avg_rating) VALUES(?,?,?,?,?,?,?)', [
                (901, 1, 20, 1800, 10, 5, 7.1), (901, 2, 5, 450, 5, 2, 7.5), (901, 3, 0, 0, 0, 0, 0),
                (902, 1, 20, 1800, 12, 6, 7.2), (903, 11, 20, 1800, 10, 5, 7.1)])
            if minimal:
                conn.execute("INSERT INTO player_profile(snapshot_id,uid,birth_date,value,wage) VALUES(901,1,'2000-06-01',1000000,10000)")
            else:
                conn.executemany('UPDATE players SET position=? WHERE snapshot_id=? AND uid=?', [
                    ('ST', 901, 1), ('ST', 901, 2), ('GK', 901, 3), ('DM', 901, 4), ('ST', 902, 1), ('ST', 903, 11)])
                conn.execute("INSERT INTO player_profile(snapshot_id,uid,birth_date,guide_value,contract_wage,pace,pos_st) VALUES(901,1,'2000-06-01',1000000,10000,12,20)")
                conn.execute('INSERT INTO player_teams(snapshot_id,player_uid,team_uid) VALUES(901,1,772)')
            conn.executemany('INSERT INTO teams(snapshot_id,team_uid,club_uid,label) VALUES(?,?,?,?)', [
                (901, 771, 77, 'Old Team'), (902, 771, 77, 'New Team'), (903, 881, 88, 'Other Team')])
            conn.executemany('INSERT INTO club_leagues(snapshot_id,club_uid,club_name,league_uid,league_name) VALUES(?,?,?,?,?)', [
                (901, 77, 'Alpha FC', 770, 'Alpha League'), (901, 78, 'Beta FC', 780, 'Beta League'),
                (902, 77, 'New Alpha FC', 770, 'Alpha League'), (903, 88, 'Other FC', 880, 'Other League')])

    def request(self, endpoint, **params):
        url = self.base + endpoint + '?' + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                body = response.read().decode('utf-8')
                return response.status, body if '/export' in endpoint else json.loads(body)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def browse(self, **params):
        status, data = self.request('/api/moneyball/browse', snapshot=901, **params)
        self.assertEqual(status, 200, data)
        return data

    def test_selected_snapshot_metrics_and_frontend_contract(self):
        result = self.browse(group='att', sort='goals_per90', dir='desc')
        self.assertEqual((result['group'], result['total'], result['total_db']), ('att', 2, 4))
        self.assertEqual([row['uid'] for row in result['rows']], [2, 1])
        row = result['rows'][1]
        self.assertEqual(row['vals']['goals_per90'], .5)
        self.assertEqual((row['name'], row['position'], row['club_name'], row['age']), ('Alpha, "Old"', 'ST', 'Alpha FC', 26))
        self.assertEqual((row['transfer_value'], row['wage']), (1000000, 10000))
        self.assertTrue(any(column['key'].startswith('att_') for column in result['columns']))
        self.assertEqual(result['rows'], result['players'])
        self.assertIn('att_N', row['vals'])
        for sid, expected, goals in ((902, 'Alpha New', .6), (903, 'Other career', .5)):
            status, data = self.request('/api/moneyball/browse', snapshot=sid, group='att')
            self.assertEqual(status, 200)
            self.assertEqual([row['name'] for row in data['rows']], [expected])
            self.assertAlmostEqual(data['rows'][0]['vals']['goals_per90'], goals)

    def test_ui_filters_legacy_search_sort_and_pagination(self):
        self.assertEqual([row['uid'] for row in self.browse(q='alpha OLD')['rows']], [1])
        self.assertEqual(self.browse(clubs='78')['total'], 1)
        self.assertEqual(self.browse(teams='772')['total'], 2)
        self.assertEqual(self.browse(leagues='780')['total'], 1)
        self.assertEqual(self.browse(uids='1,2', exclude='1')['rows'][0]['uid'], 2)
        self.assertEqual(self.browse(min_minutes=500, max_age=30, min_rating=7)['total'], 1)
        conditions = {'v': 2, 'conds': [
            {'field': 'name', 'op': 'contains', 'vt': 'forward'},
            {'field': '_age', 'op': 'between', 'v': 20, 'v2': 30, 'logic': 'or'}]}
        self.assertEqual(self.browse(search=json.dumps(conditions))['total'], 2)
        legacy = [{'col': 'goals_per90', 'op': 'gte', 'v': .7}]
        self.assertEqual(self.browse(conds=json.dumps(legacy))['rows'][0]['uid'], 2)
        self.assertEqual(self.browse(sort='name', offset=1, limit=1)['rows'][0]['uid'], 2)
        self.assertEqual(self.browse(sort='_rating', dir='desc', limit=1)['rows'][0]['uid'], 2)
        self.assertEqual(self.browse(group='gk')['rows'][0]['uid'], 3)
        self.assertIsNone(self.browse(group='all', q='Missing')['rows'][0]['vals']['goals_per90'])

    def test_shipped_quick_filter_aliases_and_search_metadata(self):
        condition = {'id': 'quick-minutes', 'on': True, 'logic': 'and', 'g': None,
                     'field': 'all_min', 'op': 'gte', 'v': 2000}
        search = json.dumps({'v': 2, 'conds': [condition]})
        result = self.browse(group='att', search=search)
        self.assertEqual((result['total'], result['total_db'], result['warnings']), (0, 4, []))
        status, exported = self.request('/api/moneyball/export.csv', snapshot=901, group='att',
                                        search=search, cols='name,all_min')
        self.assertEqual(status, 200)
        self.assertEqual(len(list(csv.reader(io.StringIO(exported)))), 1)
        for field, op, value, expected in (('all_min', 'gte', 1800, [1]),
                                           ('_age', 'lte', 26, [1]), ('_rating', 'gte', 7.4, [2])):
            with self.subTest(field=field):
                payload = {'v': 2, 'conds': [{'field': field, 'op': op, 'v': value}]}
                result = self.browse(group='att', search=json.dumps(payload))
                self.assertEqual([row['uid'] for row in result['rows']], expected)
                self.assertEqual(result['warnings'], [])
        status, metadata = self.request('/api/search/fields', group='att', snapshot=901)
        self.assertEqual(status, 200)
        fields = {field['key']: field for field in metadata['fields']}
        for key in ('all_min', '_age', '_rating'):
            self.assertEqual(fields[key]['type'], 'num')
            self.assertIn('gte', fields[key]['ops'])
        self.assertEqual(fields['all_min']['labelEn'], 'Minutes')
        selected = self.browse(group='att', extra='all_min')['rows']
        self.assertEqual(selected[0]['vals']['all_min'], 1800)
        self.assertTrue(set(moneyball_data.SEARCH_ALIASES) <= fields.keys())
        for key in moneyball_data.SEARCH_ALIASES:
            payload = {'v': 2, 'conds': [{'field': key, 'op': 'gte', 'v': 0}]}
            self.assertEqual(self.browse(group='att', search=json.dumps(payload))['warnings'], [])

    def test_shipped_position_quick_filter_and_familiarity_threshold(self):
        condition = {'field': 'f.positions', 'op': 'includes', 'vs': ['st'], 'thr': 20, 'v': None}
        result = self.browse(search=json.dumps({'v': 2, 'conds': [condition]}))
        self.assertEqual([row['uid'] for row in result['rows']], [1, 2])
        self.assertEqual(result['warnings'], [])
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute('UPDATE player_profile SET pos_st=16 WHERE snapshot_id=901 AND uid=1')
        result = self.browse(search=json.dumps({'v': 2, 'conds': [condition]}))
        self.assertEqual([row['uid'] for row in result['rows']], [2])
        condition['thr'] = 15
        self.assertEqual(self.browse(search=json.dumps({'v': 2, 'conds': [condition]}))['total'], 2)
        condition['op'] = 'excludes'
        self.assertEqual(self.browse(search=json.dumps({'v': 2, 'conds': [condition]}))['total'], 2)
        metadata = self.request('/api/search/fields', group='all')[1]
        field = next(field for field in metadata['fields'] if field['key'] == 'f.positions')
        self.assertEqual(field['ops'], ['includes', 'excludes'])
        self.assertIn({'code': 'st'}, field['options'])
        condition['thr'] = 21
        self.assertEqual(self.request('/api/moneyball/browse', snapshot=901,
                                      search=json.dumps({'v': 2, 'conds': [condition]}))[0], 400)

    def test_analytics_team_membership_and_option_snapshot_scope(self):
        status, data = self.request('/api/moneyball', snapshot=901, team=771)
        self.assertEqual(status, 200)
        self.assertEqual([row['uid'] for row in data['players']], [1, 3])
        self.assertEqual(data['players'][0]['full_name'], 'Alpha, "Old"')
        self.assertEqual(data['players'][0]['goals'], 10)
        self.assertTrue(data['columns'])
        self.assertEqual(self.request('/api/moneyball', snapshot=901, team=772)[1]['players'][0]['uid'], 1)
        self.assertEqual([row['label'] for row in self.request('/api/myteams', snapshot=902)[1]['teams']], ['New Team'])
        self.assertEqual([row['club_name'] for row in self.request('/api/clubs', snapshot=903)[1]['clubs']], ['Other FC'])

    def test_percentiles_use_full_pool_before_pagination_and_raw_rank_direction(self):
        data = self.browse(group='att', pct=1, pool='filtered', sort='goals_per90', limit=1)
        self.assertEqual(data['percentiles']['1']['goals_per90'], 25)
        self.assertEqual(data['percentiles']['1']['goals90'], 25)
        status, data = self.request('/api/moneyball/percentiles', snapshot=901, team=771, pool='save', min_minutes=1)
        self.assertEqual(status, 200)
        self.assertEqual(set(data['percentiles']), {'1', '3'})
        self.assertEqual(data['percentiles']['1']['goals90'], 25)
        status, position = self.request('/api/moneyball/percentiles', snapshot=901, pool='pos', min_minutes=1)
        self.assertEqual(position['percentiles']['1']['goals_per90'], 25)
        self.assertNotIn('NaN', json.dumps(data, allow_nan=False))
        self.assertEqual(self.request('/api/moneyball/percentiles', snapshot=901, pool='top20')[0], 200)

    def test_my_team_percentiles_keep_its_nonpenalty_column_formula(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute('UPDATE player_stats SET shots=50, penalties_scored=10 WHERE snapshot_id=901 AND uid=1')
            conn.execute('UPDATE player_stats SET shots=45, penalties_scored=0 WHERE snapshot_id=901 AND uid=2')
        status, data = self.request('/api/moneyball/percentiles', snapshot=901, pool='save', min_minutes=1)
        self.assertEqual(status, 200)
        self.assertEqual(data['percentiles']['1']['shots'], 25)
        browse = self.browse(group='att', pct=1, pool='filtered')
        self.assertEqual(browse['percentiles']['1']['shots'], 75)
        self.assertEqual(browse['rows'][0]['vals']['att_AJ'], .5)

    def test_csv_matches_all_filtered_rows_and_selected_columns(self):
        status, body = self.request('/api/moneyball/export.csv', snapshot=901, group='att',
                                    cols='uid,name,goals_per90', sort='goals_per90', dir='desc', limit=1)
        # Derived columns available through the metric catalog or core fields.
        self.assertEqual(status, 200, body)
        records = list(csv.reader(io.StringIO(body)))
        self.assertEqual([row[0] for row in records[1:]], ['2', '1'])
        self.assertEqual(records[2][1], 'Alpha, "Old"')
        self.assertEqual(records[2][2], '0.50')
        status, body = self.request('/api/moneyball/export', snapshot=901, group='att', cols='name,_rating',
                                    q='alpha', profile='excel-br', lang='pt')
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith('\ufeff'))
        self.assertEqual(list(csv.reader(io.StringIO(body.lstrip('\ufeff')), delimiter=';'))[1], ['Alpha, "Old"', '7,10'])
        status, body = self.request('/api/moneyball/export.csv', snapshot=901, group='att', q='absent')
        self.assertEqual(len(list(csv.reader(io.StringIO(body)))), 1)

    def test_incomplete_ui_conditions_do_not_filter_browse_or_csv(self):
        drafts = [
            {'field': 'all_min', 'op': 'gte', 'v': None},
            {'field': 'all_min', 'op': 'gte', 'v': ''},
            {'field': 'all_min', 'op': 'between', 'v': 0, 'v2': None},
            {'field': 'all_min', 'op': 'between', 'v': None, 'v2': 2000},
            {'field': 'all_min', 'op': 'field_gt', 'vf': None},
            {'field': 'all_min', 'op': 'field_gt', 'vf': ''},
            {'field': 'all_min', 'op': 'field_gt', 'vf': 'unknown'},
            {'field': 'name', 'op': 'contains', 'vt': ''},
            {'field': 'name', 'op': 'is_not', 'vt': '   '},
        ]
        for draft in drafts:
            with self.subTest(draft=draft):
                for logic, prefix, expected in (
                    ('and', [], [1, 2]),
                    ('and', [{'field': 'all_min', 'op': 'gte', 'v': 500}], [1]),
                    ('or', [{'field': 'all_min', 'op': 'gte', 'v': 500}], [1]),
                ):
                    payload = {'v': 2, 'conds': prefix + [
                        {'id': 'draft', 'on': True, 'logic': logic, 'g': None, **draft}]}
                    search = json.dumps(payload)
                    data = self.browse(group='att', sort='_uid', search=search)
                    self.assertEqual([row['uid'] for row in data['rows']], expected)
                    self.assertEqual(data['warnings'], [{'id': 'draft', 'field': draft['field'], 'why': 'unsupported'}])
                    status, exported = self.request('/api/moneyball/export.csv', snapshot=901, group='att',
                                                    sort='_uid', search=search, cols='uid,name', profile='intl')
                    self.assertEqual(status, 200)
                    self.assertEqual([int(row[0]) for row in list(csv.reader(io.StringIO(exported)))[1:]], expected)

    def test_complete_ui_conditions_preserve_zero_range_and_field_operands(self):
        conditions = [
            ({'field': 'all_min', 'op': 'gte', 'v': 0}, [1, 2]),
            ({'field': 'all_min', 'op': 'between', 'v': 0, 'v2': 450}, [2]),
            ({'field': 'all_min', 'op': 'field_gt', 'vf': 'goals'}, [1, 2]),
            ({'field': 'all_min', 'op': 'field_gt', 'vf': 'all_min'}, []),
            ({'field': 'name', 'op': 'contains', 'vt': 'old'}, [1]),
        ]
        for condition, expected in conditions:
            with self.subTest(condition=condition):
                search = json.dumps({'v': 2, 'conds': [condition]})
                data = self.browse(group='att', sort='_uid', search=search)
                self.assertEqual([row['uid'] for row in data['rows']], expected)
                self.assertEqual(data['warnings'], [])
                status, exported = self.request('/api/moneyball/export.csv', snapshot=901, group='att',
                                                sort='_uid', search=search, cols='uid,name', profile='intl')
                self.assertEqual(status, 200)
                self.assertEqual([int(row[0]) for row in list(csv.reader(io.StringIO(exported)))[1:]], expected)
        legacy = [{'col': 'all_min', 'op': 'between', 'val': [0, 450]}]
        self.assertEqual([row['uid'] for row in self.browse(group='att', conds=json.dumps(legacy))['rows']], [2])

    def test_default_ui_export_accepts_every_visible_identity_and_metric_column(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute('UPDATE player_profile SET foot_left=20, foot_right=5 WHERE snapshot_id=901 AND uid=1')
        # Exact query from the shipped Seasons export action, including foot.
        normal_columns = 'name,pos,nat,league,club,_age,_height,_ca,_pa,_value,_asking,_wage,contract,foot,_rating,minutes'
        status, exported = self.request('/api/moneyball/export.csv', snapshot=901, group='att',
                                        cols=normal_columns, profile='intl', lang='en')
        self.assertEqual(status, 200, exported)
        records = list(csv.reader(io.StringIO(exported)))
        self.assertEqual(records[0], normal_columns.split(','))
        self.assertEqual(records[1][records[0].index('foot')], 'left')
        self.assertEqual(len(records), 3)
        # Full shipped SV list (also test user-enabled identity columns), plus view metrics.
        identity = 'name,pos,nat,league,club,_age,_height,_ca,_pa,_value,_asking,_wage,contract,foot,_rating,birth,_lfoot,_rfoot,_uid'.split(',')
        metrics = [column['key'] for column in self.browse(group='att')['columns']]
        all_columns = identity + metrics
        status, exported = self.request('/api/moneyball/export.csv', snapshot=901, group='att',
                                        cols=','.join(all_columns), profile='excel-br', lang='pt')
        self.assertEqual(status, 200, exported)
        records = list(csv.reader(io.StringIO(exported.lstrip('\ufeff')), delimiter=';'))
        self.assertEqual(records[0], all_columns)
        self.assertTrue(all(len(row) == len(all_columns) for row in records))
        # My team makes its CSV in the client from these stored API player rows.
        status, team = self.request('/api/moneyball', snapshot=901, team=771)
        self.assertEqual(status, 200)
        first = next(row for row in team['players'] if row['uid'] == 1)
        self.assertEqual((first['full_name'], first['left_foot'], first['right_foot'], first['goals']),
                         ('Alpha, "Old"', 20, 5, 10))
        self.assertEqual(self.request('/api/moneyball/export.csv', snapshot=901,
                                      cols=normal_columns + ',unknown')[0], 400)

    def test_browse_and_csv_use_shipped_position_groups(self):
        positions = ('ST', 'AMR', 'AML', 'AMC', 'MC', 'MR', 'ML')
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO snapshots(id,name,game_date,carreira_id) VALUES(905,'Positions','2027-05-30','alpha')")
            conn.executemany('INSERT INTO players(snapshot_id,uid,full_name,position,team_uid) VALUES(905,?,?,?,9051)',
                             [(500 + index, 'Position ' + position, position) for index, position in enumerate(positions)])
            conn.executemany('INSERT INTO player_stats(snapshot_id,uid,minutes,goals) VALUES(905,?,900,?)',
                             [(500 + index, index + 1) for index in range(len(positions))])
        for group, expected in (('att', {'ST', 'AMR', 'AML'}), ('amc', {'AMC'}), ('b2b', {'MC', 'MR', 'ML'})):
            with self.subTest(group=group):
                status, data = self.request('/api/moneyball/browse', snapshot=905, group=group, sort='_uid')
                self.assertEqual(status, 200)
                self.assertEqual({row['position'] for row in data['rows']}, expected)
                status, exported = self.request('/api/moneyball/export.csv', snapshot=905, group=group,
                                                sort='_uid', cols='uid,pos', profile='intl', lang='en')
                self.assertEqual(status, 200)
                records = list(csv.reader(io.StringIO(exported)))
                self.assertEqual(records[1:], [[str(row['uid']), row['position']] for row in data['rows']])
        # A captured wide-midfielder profile still supplies its position if identity lacks it.
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute('UPDATE players SET position=NULL WHERE snapshot_id=905 AND uid=505')
            conn.execute('INSERT INTO player_profile(snapshot_id,uid,pos_mr) VALUES(905,505,20)')
        data = self.request('/api/moneyball/browse', snapshot=905, group='b2b')[1]
        self.assertEqual({row['position'] for row in data['rows']}, {'MC', 'MR', 'ML'})

    def test_empty_invalid_and_active_career_selection(self):
        for sid in (904, 999):
            data = self.request('/api/moneyball/browse', snapshot=sid)[1]
            self.assertEqual((data['total'], data['rows']), (0, []))
        settings.save(carreira_ativa='alpha')
        self.assertEqual(self.request('/api/moneyball/browse')[1]['snapshot'], 902)
        for params in ({'snapshot': 'bad'}, {'group': 'bad'}, {'limit': -1}, {'offset': -1},
                       {'search': '{'}, {'min_rating': 'NaN'}, {'dir': 'bad'}):
            with self.subTest(params=params):
                self.assertEqual(self.request('/api/moneyball/browse', **params)[0], 400)
        self.assertEqual(self.request('/api/moneyball/export.csv', cols='unknown')[0], 400)
        self.assertEqual(self.request('/api/moneyball/percentiles', pool='unknown')[0], 400)

    def test_minimal_startup_schema_and_missing_records_remain_readable(self):
        self.database = self.root / 'minimal.db'
        self.seed(minimal=True)
        result = self.browse()
        self.assertEqual((result['total'], result['total_db']), (4, 4))
        first = next(row for row in result['rows'] if row['uid'] == 1)
        self.assertEqual((first['transfer_value'], first['wage'], first['age']), (1000000, 10000, 26))
        self.assertEqual(first['vals']['goals_per90'], .5)
        self.assertEqual(self.request('/api/moneyball', snapshot=901)[0], 200)
        self.assertEqual(self.request('/api/moneyball/percentiles', snapshot=901)[0], 200)
        self.assertEqual(self.request('/api/moneyball/export.csv', snapshot=901)[0], 200)

    def test_shortlist_and_uid_selection_loads_only_requested_players_without_full_database_derivation(self):
        extra_players = [(901, uid, f'Extra Player {uid}', 77, 771, 100, 150) for uid in range(1000, 3000)]
        extra_players.append((901, 352, 'Target One', 77, 771, 110, 160))
        extra_players.append((901, 12315, 'Target Two', 78, 781, 120, 170))
        with closing(server.get_db_connection()) as conn, conn:
            conn.executemany('INSERT INTO players(snapshot_id,uid,full_name,club_id,team_uid,ca,pa) VALUES(?,?,?,?,?,?,?)', extra_players)
            conn.executemany('INSERT INTO player_profile(snapshot_id,uid,birth_date) VALUES(?,?,?)', [
                (901, 352, '2001-01-01'), (901, 12315, '2002-02-02')])

        settings.save(listas_preferenciais=[{
            'id': 'shortlist-two',
            'nome': 'Two Player List',
            'uids': [352, 12315],
        }])

        derived_sizes = []
        original_derive = moneyball_data._derive
        def spy_derive(rows, groups):
            derived_sizes.append(len(rows))
            return original_derive(rows, groups)

        with patch.object(moneyball_data, '_derive', side_effect=spy_derive):
            result = self.browse(group='all', uids='lista:shortlist-two')
            self.assertEqual(result['total'], 2)
            self.assertEqual({row['uid'] for row in result['rows']}, {352, 12315})
            self.assertEqual(derived_sizes[-1], 2)

            derived_sizes.clear()
            status, csv_data = self.request('/api/moneyball/export.csv', snapshot=901, group='all',
                                            uids='352,12315', cols='uid,name,age', profile='intl')
            self.assertEqual(status, 200)
            records = list(csv.reader(io.StringIO(csv_data)))
            self.assertEqual(len(records), 3)
            self.assertEqual(derived_sizes[-1], 2)

    def test_sex_filter_excludes_unknown_from_male_and_matches_specs(self):
        # 1. Direct unit test of moneyball_data.select()
        test_rows = [
            {'uid': 101, 'name': 'Male Player', 'position': 'ST', 'club_uid': 77, 'league_uid': 770, '_teams': {771}, 'is_female': 0},
            {'uid': 102, 'name': 'Female Player', 'position': 'ST', 'club_uid': 77, 'league_uid': 770, '_teams': {771}, 'is_female': 1},
            {'uid': 103, 'name': 'Unknown Player', 'position': 'ST', 'club_uid': 77, 'league_uid': 770, '_teams': {771}, 'is_female': None},
        ]
        res_m, _ = moneyball_data.select(test_rows, {'sex': 'm'})
        self.assertEqual([r['uid'] for r in res_m], [101])

        res_f, _ = moneyball_data.select(test_rows, {'sex': 'f'})
        self.assertEqual([r['uid'] for r in res_f], [102])

        res_u, _ = moneyball_data.select(test_rows, {'sex': 'u'})
        self.assertEqual([r['uid'] for r in res_u], [103])

        res_unknown, _ = moneyball_data.select(test_rows, {'sex': 'unknown'})
        self.assertEqual([r['uid'] for r in res_unknown], [103])

        res_all, _ = moneyball_data.select(test_rows, {'sex': 'all'})
        self.assertEqual([r['uid'] for r in res_all], [101, 102, 103])

        res_none, _ = moneyball_data.select(test_rows, {})
        self.assertEqual([r['uid'] for r in res_none], [101, 102, 103])

        # 2. HTTP API endpoints regression
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("UPDATE player_profile SET is_female=0 WHERE snapshot_id=901 AND uid=1")
            conn.execute("INSERT OR REPLACE INTO player_profile(snapshot_id,uid,pos_st,is_female) VALUES(901,2,20,1)")
            conn.execute("INSERT OR REPLACE INTO player_profile(snapshot_id,uid,pos_st,is_female) VALUES(901,3,20,NULL)")

        # /api/moneyball/browse
        status_m, data_m = self.request('/api/moneyball/browse', snapshot=901, sex='m')
        self.assertEqual(status_m, 200)
        uids_m = {row['uid'] for row in data_m['rows']}
        self.assertIn(1, uids_m)
        self.assertNotIn(2, uids_m)
        self.assertNotIn(3, uids_m)

        status_f, data_f = self.request('/api/moneyball/browse', snapshot=901, sex='f')
        self.assertEqual(status_f, 200)
        uids_f = {row['uid'] for row in data_f['rows']}
        self.assertEqual(uids_f, {2})

        status_u, data_u = self.request('/api/moneyball/browse', snapshot=901, sex='unknown')
        self.assertEqual(status_u, 200)
        uids_u = {row['uid'] for row in data_u['rows']}
        self.assertIn(3, uids_u)
        self.assertNotIn(1, uids_u)
        self.assertNotIn(2, uids_u)

        # /api/snapshots/901/players
        status_pm, data_pm = self.request('/api/snapshots/901/players', sex='m')
        self.assertEqual(status_pm, 200)
        pm_uids = {p['uid'] for p in data_pm['players']}
        self.assertEqual(pm_uids, {1})

        status_pf, data_pf = self.request('/api/snapshots/901/players', sex='f')
        self.assertEqual(status_pf, 200)
        pf_uids = {p['uid'] for p in data_pf['players']}
        self.assertEqual(pf_uids, {2})

        status_pu, data_pu = self.request('/api/snapshots/901/players', sex='unknown')
        self.assertEqual(status_pu, 200)
        pu_uids = {p['uid'] for p in data_pu['players']}
        self.assertIn(3, pu_uids)
        self.assertNotIn(1, pu_uids)
        self.assertNotIn(2, pu_uids)


if __name__ == '__main__':
    unittest.main()
