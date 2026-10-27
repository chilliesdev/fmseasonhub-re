"""Selected-player Library saves through real HTTP and the shipped list renderer."""

from contextlib import closing
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch
import unittest

import test_moneyball_data as fixtures
import server


class LibraryShortlistTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.MoneyballDataTests.tearDownClass.__func__)
    seed = fixtures.MoneyballDataTests.seed

    def setUp(self):
        fixtures.MoneyballDataTests.setUp(self)
        self.library = self.root / 'Biblioteca'
        self.library.mkdir()
        library = patch.object(server, '_get_biblioteca_dir', return_value=self.library)
        library.start()
        self.addCleanup(library.stop)
        with closing(server.get_db_connection()) as conn, conn:
            conn.execute("UPDATE snapshots SET fm_version='26' WHERE id=901")

    def request(self, endpoint='', body=None, raw=False, method=None):
        request = urllib.request.Request(self.base + '/api/biblioteca' + endpoint)
        if body is not None:
            request.data = json.dumps(body).encode()
            request.add_header('Content-Type', 'application/json')
        elif method == 'POST':
            request.data = b''
        if method:
            request.method = method
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read() if raw else json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def carregar(self, arquivo):
        encoded = '/' + urllib.parse.quote(arquivo, safe='') + '/carregar'
        return self.request(encoded, method='POST')

    def save(self, **changes):
        return self.request(body={'arquivo': 'Équipe.lsh', 'uids': [2, 1], 'snapshot': 901, **changes})

    def test_round_trip_contains_snapshot_identities_and_list_metadata(self):
        status, result = self.save(uids=[2, 1, 2])
        self.assertEqual((status, result), (200, {'ok': True, 'arquivo': 'Équipe.lsh'}))
        encoded = '/' + urllib.parse.quote(result['arquivo'], safe='')
        status, data = self.request(encoded)
        self.assertEqual(status, 200)
        self.assertEqual((data['nome'], data['snapshot'], data['carreira_id'], data['jogo']),
                         ('Équipe', 901, 'alpha', '26'))
        self.assertTrue(data['id'])
        self.assertTrue(data['app_versao'])
        self.assertTrue(data['criado'])
        self.assertEqual(data['jogadores'], [
            {'uid': 2, 'nome': 'Beta Forward'},
            {'uid': 1, 'nome': 'Alpha, "Old"', 'nascimento': '2000-06-01'}])
        status, raw = self.request(encoded + '/bruto', raw=True)
        self.assertEqual(status, 200)
        self.assertTrue(raw)
        self.assertEqual(json.loads(raw), data)
        self.assertEqual(raw, (self.library / result['arquivo']).read_bytes())

    def test_invalid_selection_never_creates_or_truncates_a_list(self):
        cases = [
            {'uids': []}, {'uids': None}, {'uids': [0]}, {'uids': [-1]},
            {'uids': [True]}, {'uids': ['1']}, {'uids': [1.0]}, {'uids': {}},
            {'uids': [1, 11]}, {'uids': [999]}, {'uids': [2], 'snapshot': 902},
            {'snapshot': None}, {'snapshot': 999}, {'snapshot': 904}, {'snapshot': -1},
            {'snapshot': True}, {'snapshot': '901'}, {'snapshot': 901.0},
            {'uids': [1 << 63]}, {'uids': [1 << 100]},
            {'snapshot': 1 << 63}, {'snapshot': 1 << 100},
            {'uids': [1] * 5001}, {'conteudo': {'nome': 'conflict'}},
        ]
        for changes in cases:
            with self.subTest(changes=str(changes)[:120]):
                status, _ = self.save(**changes)
                self.assertIn(status, (400, 422))
                self.assertEqual(list(self.library.iterdir()), [])
                target = self.library / 'Équipe.lsh'
                target.write_bytes(b'existing shortlist')
                status, _ = self.save(**changes)
                self.assertIn(status, (400, 422))
                self.assertEqual(target.read_bytes(), b'existing shortlist')
                target.unlink()
        self.assertEqual(self.save(arquivo='players.fsh')[0], 400)
        self.assertEqual(list(self.library.iterdir()), [])

    def test_missing_selection_rejected_but_valid_lsh_import_round_trips(self):
        for body in ({'arquivo': 'empty.lsh'}, {'arquivo': 'empty.lsh', 'conteudo': ''},
                     {'arquivo': 'empty.lsh', 'conteudo': {'nome': 'Empty', 'jogadores': []}}):
            self.assertEqual(self.request(body=body)[0], 400)
            self.assertEqual(list(self.library.iterdir()), [])
        self.assertEqual(self.save()[0], 200)
        saved = json.loads((self.library / 'Équipe.lsh').read_text())
        for content in (saved, json.dumps(saved)):
            status, _ = self.request(body={'arquivo': 'imported.lsh', 'conteudo': content})
            self.assertEqual(status, 200)
            self.assertEqual(self.request('/imported.lsh'), (200, saved))
        for content in ('bad JSON', [], {'nome': 'Bad', 'jogadores': [{'uid': True}]},
                        {'nome': 'Bad', 'jogadores': [{'uid': 1}, {'uid': 1}]},
                        {'nome': 'Bad', 'id': [], 'jogadores': [{'uid': 1}]}):
            self.assertEqual(self.request(body={'arquivo': 'imported.lsh', 'conteudo': content})[0], 400)
            self.assertEqual(json.loads((self.library / 'imported.lsh').read_text()), saved)

    def test_selected_snapshot_and_default_filename_are_explicit(self):
        self.assertEqual(self.save(arquivo=None, uids=[1], snapshot=902)[1]['arquivo'], 'salvo.lsh')
        saved = self.request('/salvo.lsh')[1]
        self.assertEqual(saved['snapshot'], 902)
        self.assertEqual(saved['jogadores'], [{'uid': 1, 'nome': 'Alpha New'}])

    def test_shortlist_save_keeps_symlink_target_unchanged(self):
        outside = self.root / 'outside.lsh'
        outside.write_bytes(b'outside')
        linked = self.library / 'Équipe.lsh'
        linked.symlink_to(outside)
        self.assertEqual(self.save()[0], 400)
        self.assertTrue(linked.is_symlink())
        self.assertEqual(outside.read_bytes(), b'outside')

    def test_library_lists_player_count_and_shipped_renderer_uses_raw_download(self):
        self.assertEqual(self.save()[0], 200)
        (self.library / 'broken.lsh').write_bytes(b'')
        listing = self.request()[1]
        saved = next(item for item in listing['arquivos'] if item['arquivo'] == 'Équipe.lsh')
        self.assertEqual((saved['tipo'], saved['nome'], saved['jogadores'], saved['carregada']),
                         ('lista', 'Équipe', 2, False))
        self.assertTrue(saved['listaId'])
        self.assertTrue(saved['criado'])
        broken = next(item for item in listing['arquivos'] if item['arquivo'] == 'broken.lsh')
        self.assertEqual(broken['tipo'], 'lista')
        self.assertTrue(broken['erro'])
        check = subprocess.run(['node', str(Path(__file__).with_name('library_shortlists_ui.mjs'))],
            input=json.dumps(listing), text=True, capture_output=True, check=False)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn('Library shortlist renderer passed', check.stdout)

    def test_carregar_unimported_lsh_creates_favorite_list_with_resolved_players(self):
        status, saved = self.save(uids=[2, 1])
        self.assertEqual(status, 200)
        status, res = self.carregar('Équipe.lsh')
        self.assertEqual(status, 200)
        self.assertEqual(res['destino'], 'favoritos')
        self.assertFalse(res['ja_estava'])
        self.assertEqual(res['importados'], 2)
        self.assertEqual(res['nao_conferem'], [])
        self.assertEqual(res['sem_captura'], 0)
        self.assertTrue(res['id'])

        with urllib.request.urlopen(self.base + '/api/favoritos', timeout=10) as response:
            favs = json.load(response)
        matching = [l for l in favs['listas'] if l['id'] == res['id']]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['nome'], 'Équipe')
        self.assertEqual(matching[0]['uids'], [2, 1])

    def test_carregar_already_imported_lsh_reports_ja_estava_without_duplication(self):
        self.assertEqual(self.save(uids=[2, 1])[0], 200)
        status1, res1 = self.carregar('Équipe.lsh')
        self.assertEqual(status1, 200)
        self.assertFalse(res1['ja_estava'])

        status2, res2 = self.carregar('Équipe.lsh')
        self.assertEqual(status2, 200)
        self.assertEqual(res2['destino'], 'favoritos')
        self.assertTrue(res2['ja_estava'])
        self.assertEqual(res2['id'], res1['id'])

        with urllib.request.urlopen(self.base + '/api/favoritos', timeout=10) as response:
            favs = json.load(response)
        matching = [l for l in favs['listas'] if l['id'] == res1['id']]
        self.assertEqual(len(matching), 1)

    def test_carregar_fmf_shortlist_loads_into_preferred_shortlists(self):
        from test_preferred_shortlists import fmf_bytes
        (self.library / 'Scouting.fmf').write_bytes(fmf_bytes('Scouting', [101, 202]))
        status, res = self.carregar('Scouting.fmf')
        self.assertEqual(status, 200)
        self.assertEqual(res['destino'], 'lista')
        self.assertFalse(res['ja_estava'])
        self.assertEqual(res['importados'], 2)
        self.assertTrue(res['id'])

        status2, res2 = self.carregar('Scouting.fmf')
        self.assertEqual(status2, 200)
        self.assertEqual(res2['destino'], 'lista')
        self.assertTrue(res2['ja_estava'])
        self.assertEqual(res2['id'], res['id'])

    def test_carregar_error_handling(self):
        self.assertEqual(self.carregar('missing.lsh')[0], 404)
        self.assertEqual(self.carregar('missing.fmf')[0], 404)

        (self.library / 'filter.fsh').write_text(json.dumps({'nome': 'Filter'}))
        self.assertEqual(self.carregar('filter.fsh')[0], 400)

        outside = self.root / 'outside.lsh'
        outside.write_text(json.dumps({'nome': 'Outside', 'jogadores': [{'uid': 1}]}))
        linked = self.library / 'linked.lsh'
        linked.symlink_to(outside)
        self.assertEqual(self.carregar('linked.lsh')[0], 400)

        (self.library / 'corrupt.lsh').write_text('bad json')
        self.assertEqual(self.carregar('corrupt.lsh')[0], 400)

    def test_library_listing_reflects_carregada_status(self):
        from test_preferred_shortlists import fmf_bytes
        self.assertEqual(self.save(uids=[2, 1])[0], 200)
        (self.library / 'Scouting.fmf').write_bytes(fmf_bytes('Scouting', [101, 202]))

        listing_before = self.request()[1]
        lsh_before = next(i for i in listing_before['arquivos'] if i['arquivo'] == 'Équipe.lsh')
        fmf_before = next(i for i in listing_before['arquivos'] if i['arquivo'] == 'Scouting.fmf')
        self.assertFalse(lsh_before['carregada'])
        self.assertFalse(fmf_before['carregada'])

        self.assertEqual(self.carregar('Équipe.lsh')[0], 200)
        self.assertEqual(self.carregar('Scouting.fmf')[0], 200)

        listing_after = self.request()[1]
        lsh_after = next(i for i in listing_after['arquivos'] if i['arquivo'] == 'Équipe.lsh')
        fmf_after = next(i for i in listing_after['arquivos'] if i['arquivo'] == 'Scouting.fmf')
        self.assertTrue(lsh_after['carregada'])
        self.assertTrue(fmf_after['carregada'])


if __name__ == '__main__':
    unittest.main()
