"""HTTP regressions for complete, atomic saved-season deletion (issue #27)."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import test_moneyball_data as fixtures
import cache_browse
import db
import paths
import server
import settings


# Explicit coverage for every table in the capture schema, including tables
# without foreign keys. Reuse UIDs to detect accidental cross-season deletion.
ROWS = {
    'players': {'uid': 1, 'full_name': 'QA Player', 'club_id': 77, 'ca': 110, 'pa': 160},
    'player_stats': {'uid': 1, 'apps_total': 20, 'goals': 10, 'avg_rating': 7.1},
    'player_profile': {'uid': 1, 'birth_date': '2000-01-01'},
    'player_match_stats': {'uid': 1, 'match_id': 10, 'match_date': '2027-05-01'},
    'team_match_stats': {'team_uid': 771, 'match_id': 10, 'match_date': '2027-05-01'},
    'player_form': {'uid': 1, 'match_date': '2027-05-01', 'comp_uid': 770},
    'snapshot_ligas': {'comp_uid': 770, 'nome': 'QA League', 'estado': 'done'},
    'club_profile': {'club_uid': 77, 'name_full': 'QA Club'},
    'teams': {'team_uid': 771, 'club_uid': 77, 'label': 'QA Team'},
    'player_teams': {'player_uid': 1, 'team_uid': 771},
    'youth_teams': {'team_uid': 772, 'club_uid': 77, 'club_name': 'QA Youth'},
    'youth_comps': {'uid': 770, 'name': 'QA Youth League'},
    'youth_team_comps': {'team_uid': 772, 'comp_uid': 770},
    'comps': {'uid': 770, 'name': 'QA League'},
    'club_leagues': {'club_uid': 77, 'league_uid': 770, 'club_name': 'QA Club'},
    'future_transfers': {'uid': 1, 'dest_club_uid': 88, 'transfer_date': '2027-07-01'},
}


class SnapshotDeleteTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.MoneyballDataTests.tearDownClass.__func__)
    request = fixtures.MoneyballDataTests.request

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='fmsh-snapshot-delete-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / 'captured.db'
        for target, name, value in (
            (server, 'get_db_path', lambda: self.database),
            (settings, 'SETTINGS_PATH', str(self.root / 'settings.json')),
            (paths, '_LOCAL_ROOT', str(self.root / 'local')),
        ):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        db.init_db(str(self.database))
        self.seed()

    def seed(self):
        with closing(server.get_db_connection()) as conn, conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.tables = sorted(tables.intersection(ROWS))
            for sid, career in ((901, 'alpha'), (902, 'alpha'), (903, 'beta')):
                conn.execute('INSERT INTO snapshots(id,name,game_date,carreira_id,club_uid) VALUES(?,?,?,?,77)',
                             (sid, f'QA {sid}', f'{2026 + sid - 900}-05-30', career))
                for table in self.tables:
                    values = {'snapshot_id': sid, **ROWS[table]}
                    columns = ','.join(values)
                    placeholders = ','.join('?' for _ in values)
                    conn.execute(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})', tuple(values.values()))
            conn.execute('CREATE TABLE unrelated (uid INTEGER PRIMARY KEY, value TEXT)')
            conn.execute("INSERT INTO unrelated VALUES (1, 'Keep me')")
        for sid in (901, 902, 903):
            cache_browse.gravar(sid, {'snapshot': sid})
            cache_browse.gravar_overall(sid, {'snapshot': sid})
            cache_browse.gravar_u8(sid, [[1, 2]], ['first', 'second'])

    def saved_data(self):
        with closing(sqlite3.connect(self.database)) as conn:
            return {table: conn.execute(f'SELECT * FROM "{table}" ORDER BY 1,2').fetchall()
                    for table in ('snapshots', *self.tables, 'unrelated')}

    def cached_data(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.glob('local/cache_browse/**/*') if path.is_file()}

    def delete(self, sid=903):
        request = urllib.request.Request(self.base + f'/api/snapshots/{sid}', method='DELETE')
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def summary(self, sid):
        request = urllib.request.Request(
            self.base + '/api/resumo-jogadores',
            data=json.dumps({'snapshot': sid, 'uids': [1]}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def assert_deleted(self, sid, before, cache_before):
        expected = {table: rows if table == 'unrelated' else [row for row in rows if row[0] != sid]
                    for table, rows in before.items()}
        self.assertEqual(self.saved_data(), expected)
        prefix = f'local/cache_browse/{sid}/'
        self.assertEqual(self.cached_data(), {path: data for path, data in cache_before.items()
                                            if not path.startswith(prefix)})
        self.assertFalse((self.root / 'local' / 'cache_browse' / str(sid)).exists())

    def test_deletes_all_owned_rows_and_cache_with_foreign_keys_off(self):
        self.assertEqual(set(self.tables), set(ROWS))
        with closing(server.get_db_connection()) as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0], 0)
        before, cache_before = self.saved_data(), self.cached_data()
        self.assertEqual(self.delete(), (200, {'ok': True}))
        self.assert_deleted(903, before, cache_before)

    def test_deletes_all_owned_rows_with_foreign_keys_on(self):
        original = server.get_db_connection

        def connection():
            conn = original()
            conn.execute('PRAGMA foreign_keys=ON')
            return conn

        before, cache_before = self.saved_data(), self.cached_data()
        with patch.object(server, 'get_db_connection', connection):
            self.assertEqual(self.delete(), (200, {'ok': True}))
        self.assert_deleted(903, before, cache_before)

    def test_deletion_updates_warmed_summary_options_and_season_reads(self):
        self.assertEqual(self.summary(903)['na_carreira'], 1)
        control_summary = self.summary(902)
        for endpoint, key in (('/api/myteams', 'teams'), ('/api/youth-teams', 'youth_teams'),
                              ('/api/clubs', 'clubs')):
            self.assertEqual(len(self.request(endpoint, snapshot=903)[1][key]), 1)
        self.assertEqual(len(self.request('/api/snapshots/903/players')[1]), 1)
        self.assertEqual(self.delete(), (200, {'ok': True}))
        self.assertEqual(self.summary(903)['na_carreira'], 0)
        self.assertEqual(self.summary(902), control_summary)
        for endpoint, key in (('/api/myteams', 'teams'), ('/api/youth-teams', 'youth_teams'),
                              ('/api/clubs', 'clubs')):
            self.assertEqual(self.request(endpoint, snapshot=903), (200, {key: []}))
        self.assertEqual(self.request('/api/snapshots/903/players'), (200, []))
        self.assertEqual(self.request('/api/snapshots/903')[0], 404)
        self.assertEqual({row['id'] for row in self.request('/api/snapshots', include_live='false')[1]}, {901, 902})

    def test_server_only_schema_needs_no_optional_tables(self):
        self.database.unlink()
        with closing(sqlite3.connect(self.database)) as conn:
            server._init_db(conn)
        self.seed()
        self.assertLess(len(self.tables), len(ROWS))
        before, cache_before = self.saved_data(), self.cached_data()
        self.assertEqual(self.delete(), (200, {'ok': True}))
        self.assert_deleted(903, before, cache_before)

    def test_legacy_schema_without_foreign_key_declarations(self):
        self.database.unlink()
        with closing(sqlite3.connect(self.database)) as conn:
            conn.executescript(db.SCHEMA.replace(' REFERENCES snapshots(id) ON DELETE CASCADE', ''))
            self.assertFalse(conn.execute('PRAGMA foreign_key_list(players)').fetchall())
        self.seed()
        before, cache_before = self.saved_data(), self.cached_data()
        self.assertEqual(self.delete(), (200, {'ok': True}))
        self.assert_deleted(903, before, cache_before)

    def test_database_error_rolls_back_all_rows_and_preserves_cache(self):
        for table in ('teams', 'snapshots'):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.database)) as conn, conn:
                    key = 'id' if table == 'snapshots' else 'snapshot_id'
                    conn.execute(f'''CREATE TRIGGER fail_delete BEFORE DELETE ON {table}
                        WHEN OLD.{key}=903 BEGIN SELECT RAISE(ABORT, 'QA failure'); END''')
                before, cache_before = self.saved_data(), self.cached_data()
                self.assertEqual(self.delete()[0], 500)
                self.assertEqual(self.saved_data(), before)
                self.assertEqual(self.cached_data(), cache_before)
                with closing(sqlite3.connect(self.database)) as conn, conn:
                    conn.execute('DROP TRIGGER fail_delete')
        self.assertEqual(self.delete(), (200, {'ok': True}))

    def test_cache_error_rolls_back_database_and_allows_retry(self):
        before, cache_before = self.saved_data(), self.cached_data()
        with patch.object(cache_browse.shutil, 'rmtree', side_effect=PermissionError('QA cache failure')):
            self.assertEqual(self.delete()[0], 500)
        self.assertEqual(self.saved_data(), before)
        self.assertEqual(self.cached_data(), cache_before)
        self.assertEqual(self.delete(), (200, {'ok': True}))
        self.assert_deleted(903, before, cache_before)

    def test_repeated_missing_and_empty_snapshot_deletes_are_safe(self):
        self.assertEqual(self.delete(), (200, {'ok': True}))
        before, cache_before = self.saved_data(), self.cached_data()
        for sid in (903, 999999, 0, -1):
            with self.subTest(snapshot=sid):
                self.assertEqual(self.delete(sid), (200, {'ok': True}))
                self.assertEqual(self.saved_data(), before)
                self.assertEqual(self.cached_data(), cache_before)
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO snapshots(id,name) VALUES (904, 'Empty')")
        self.assertEqual(self.delete(904), (200, {'ok': True}))
        self.assertEqual(self.saved_data(), before)

    def test_missing_parent_still_removes_old_orphan_rows_and_cache(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute('DELETE FROM snapshots WHERE id=903')
        before, cache_before = self.saved_data(), self.cached_data()
        self.assertEqual(self.delete(), (200, {'ok': True}))
        self.assert_deleted(903, before, cache_before)

    def test_connection_closes_after_success_and_failure(self):
        original = server.get_db_connection
        connections = []

        def connection():
            conn = original()
            connections.append(conn)
            return conn

        with patch.object(server, 'get_db_connection', connection):
            with patch.object(cache_browse, 'apagar', side_effect=OSError('QA cache failure')):
                self.assertEqual(self.delete()[0], 500)
            self.assertEqual(self.delete(), (200, {'ok': True}))
        self.assertEqual(len(connections), 2)
        for conn in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')


if __name__ == '__main__':
    unittest.main()
