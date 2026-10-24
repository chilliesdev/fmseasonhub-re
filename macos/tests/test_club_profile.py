"""HTTP and shipped UI regressions for snapshot-bound club profiles (issue #12)."""

from contextlib import closing
from pathlib import Path
import subprocess
import unittest

import test_moneyball_data as fixtures
import server


class ClubProfileTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.MoneyballDataTests.tearDownClass.__func__)
    setUp = fixtures.MoneyballDataTests.setUp
    request = fixtures.MoneyballDataTests.request

    def seed(self):
        self.saved = {
            'snapshot_id': 901, 'club_uid': 77,
            'name_full': 'QA Club 77', 'name_short': 'QA77',
            'nickname': 'QA Reds', 'year_founded': 1907,
            'color_fg': '#ffffff', 'color_bg': '#c00000',
            'avg_attendance': 18000, 'min_attendance': 12000, 'max_attendance': 23000,
            'balance': -1200000, 'transfer_budget': 2500000,
            'wage_budget': 100000, 'wage_total': 85000,
            'training_facilities': 14, 'youth_facilities': 13,
            'youth_coaching': 12, 'youth_recruitment': 11, 'youth_importance': 10,
            'supporter_loyalty': 19, 'supporter_passion': 18,
        }
        with closing(server.get_db_connection()) as conn, conn:
            conn.executemany('INSERT INTO snapshots(id,name,scope,club_uid,carreira_id) VALUES(?,?,?,?,?)', [
                (901, 'QA 901', 'squad', 77, 'alpha'),
                (902, 'QA 902', 'squad', 77, 'alpha'),
                (903, 'QA 903', 'squad', 88, 'beta'),
                (904, 'QA live', 'live', 99, 'live'),
                (905, 'QA temporary', 'live_temp', 99, 'live'),
            ])
            columns = ','.join(self.saved)
            slots = ','.join('?' for _ in self.saved)
            conn.execute(f'INSERT INTO club_profile({columns}) VALUES({slots})', tuple(self.saved.values()))
            conn.execute("INSERT INTO club_profile(snapshot_id,club_uid,name_full,name_short,training_facilities,balance,transfer_budget,wage_budget,wage_total) VALUES(903,88,'QA Club 88','QA88',12,0,880000,88000,77000)")
            for sid in (904, 905):
                conn.execute("INSERT INTO club_profile(snapshot_id,club_uid,name_full,training_facilities) VALUES(?,99,'Live club',20)", (sid,))

    def test_selected_snapshot_returns_every_saved_field(self):
        self.assertEqual(self.request('/api/club_profile', snapshot=901), (200, self.saved))

    def test_switching_clubs_does_not_leak_prior_values(self):
        for sid, name, training, balance in ((901, 'QA Club 77', 14, -1200000),
                                             (903, 'QA Club 88', 12, 0),
                                             (901, 'QA Club 77', 14, -1200000)):
            with self.subTest(snapshot=sid):
                status, result = self.request('/api/club_profile', snapshot=sid)
                self.assertEqual(status, 200, result)
                self.assertEqual((result['snapshot_id'], result['name_full'],
                                  result['training_facilities'], result['balance']),
                                 (sid, name, training, balance))
        result = self.request('/api/club_profile', snapshot=903)[1]
        self.assertEqual((result['transfer_budget'], result['wage_budget'], result['wage_total']),
                         (880000, 88000, 77000))
        self.assertIsNone(result['youth_coaching'])
        self.assertIsNone(result['avg_attendance'])

    def test_same_club_in_another_season_has_its_own_values(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("INSERT INTO club_profile(snapshot_id,club_uid,name_full,training_facilities,balance) VALUES(902,77,'QA Club 77 next season',16,500000)")
        for sid, training, balance in ((901, 14, -1200000), (902, 16, 500000)):
            status, result = self.request('/api/club_profile', snapshot=sid)
            self.assertEqual(status, 200, result)
            self.assertEqual((result['club_uid'], result['training_facilities'], result['balance']),
                             (77, training, balance))

    def test_missing_profile_or_snapshot_returns_null_without_fallback(self):
        for sid in (902, 999999, 0, -1):
            with self.subTest(snapshot=sid):
                self.assertEqual(self.request('/api/club_profile', snapshot=sid), (200, None))

    def test_omitted_snapshot_uses_latest_stored_snapshot_not_live(self):
        status, result = self.request('/api/club_profile')
        self.assertEqual(status, 200, result)
        self.assertEqual((result['snapshot_id'], result['name_full']), (903, 'QA Club 88'))
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('DELETE FROM club_profile WHERE snapshot_id=903')
        self.assertEqual(self.request('/api/club_profile'), (200, None))

    def test_empty_database_and_only_live_captures_are_safe(self):
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("DELETE FROM snapshots WHERE scope='squad'")
        self.assertEqual(self.request('/api/club_profile'), (200, None))
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute('DELETE FROM snapshots')
        self.assertEqual(self.request('/api/club_profile'), (200, None))

    def test_invalid_snapshot_is_rejected(self):
        for value in ('invalid', '901.5', ''):
            with self.subTest(snapshot=value):
                self.assertEqual(self.request('/api/club_profile', snapshot=value)[0], 422)

    def test_shipped_club_renderer_preserves_zero_negative_and_missing_balances(self):
        script = Path(__file__).with_name('club_profile_ui.mjs')
        result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Club profile renderer regressions passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
