"""FM view imports parse native containers and never change state during review."""

from compression import zstd
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request
import zlib

import test_moneyball_data as fixtures
from test_preferred_shortlists import fmf_bytes
import lista_fmf
import paths
import server
import settings
import view_fmf


def view_bytes(columns=None, collection='PlayerSearchResultsViewCollection', *,
               outer=None, table=None, modern=False):
    """Build the real encrypted FM view member and compressed container index."""
    def text(value):
        data = value.encode()
        return struct.pack('<I', len(data)) + data

    if outer is None:
        if table is None:
            table = [{'m_columnID': column} for column in (columns if columns is not None else
                     ['name', 'age', 'goals', 'future-column'])]
        outer = {'SerialisedName': 'QA view', 'ViewSettingsCollectionName': collection,
                 'ViewData': json.dumps({'m_tableConfig': table})}
    raw = json.dumps(outer).encode()
    plain = view_fmf.MARCA_VIEW + bytes(2) + struct.pack('<I', len(raw)) + raw
    iv, key = bytes(range(16)), bytes(range(16, 32))
    content = zstd.compress(plain) if modern else plain
    member = struct.pack('<II', 16, 16) + iv + key + lista_fmf.aes128_ctr(key, iv, content)
    index = (text('') + struct.pack('<II', 0, 1) + text('QA view') + text('.view')
             + struct.pack('<QQQ', 0, len(member), len(plain)) + bytes(16))
    header = bytearray(26)
    header[:6] = lista_fmf.MARCA_CONTEINER
    struct.pack_into('<H', header, 6, 7)
    struct.pack_into('<Q', header, 9, 26 + len(member) - 9)
    compressed_index = zstd.compress(index) if modern else zlib.compress(index)
    return bytes(header) + member + lista_fmf.MARCA_INDICE + bytes(3) + compressed_index


class FMViewTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MoneyballDataTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.MoneyballDataTests.tearDownClass.__func__)

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='fmsh-view-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.game = self.root / 'Football Manager 2026'
        self.views = self.game / 'views'
        self.views.mkdir(parents=True)
        self.library = self.root / 'Biblioteca'
        self.library.mkdir()
        self.saved = self.root / 'settings.json'
        self.saved.write_text('{"existing_view": ["name", "goals"]}')
        (self.library / 'keep.vsh').write_bytes(b'unchanged view')
        self.source = self.views / 'search.fmf'
        self.source.write_bytes(view_bytes(modern=True))
        for target, name, value in (
            (lista_fmf, 'pastas_dos_jogos', lambda: [{'jogo': self.game.name, 'pasta': str(self.game)}]),
            (settings, 'SETTINGS_PATH', str(self.saved)),
            (paths, 'biblioteca_dir', lambda: str(self.library)),
        ):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def request(self, endpoint, body=None, raw=None):
        data = raw if raw is not None else None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + '/api/' + endpoint, data=data)
        if body is not None:
            request.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def state(self):
        return self.saved.read_bytes(), {p.name: p.read_bytes() for p in self.library.iterdir()}

    def folder(self, filename='search.fmf', destino='base', **extra):
        return self.request('views-fm/da-pasta', {'arquivo': filename, 'destino': destino, **extra})

    def test_all_entry_paths_return_same_populated_read_only_review(self):
        before = self.state()
        status, review = self.folder(jogo=self.game.name)
        self.assertEqual(status, 200, review)
        self.assertEqual((review['nome'], review['tela'], review['destino']), ('search', 'busca', 'base'))
        self.assertEqual(review['contagem'], {'ok': 3, 'desconhecida': 1})
        self.assertEqual([c['chave'] for c in review['colunas']], ['name', '_age', 'goals', None])
        self.assertIn('_uid', review['escondidas'])
        self.assertEqual(self.folder(str(self.source)), (200, review))
        self.assertEqual(self.request('views-fm?arquivo=search.fmf', raw=self.source.read_bytes()), (200, review))
        self.assertEqual(self.request('biblioteca-fmf?arquivo=search.fmf', raw=self.source.read_bytes()),
                         (200, {'tipo': 'view', 'review': review}))
        with patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, str(self.source), '')):
            self.assertEqual(self.request('views-fm/escolher', body={}),
                             (200, {'disponivel': True, 'cancelado': False, 'review': review}))
        self.assertEqual(self.state(), before)
        self.assertEqual(self.source.read_bytes(), view_bytes(modern=True))

    def test_shipped_apply_uses_reviewed_columns_and_hides_other_defaults(self):
        cases = []
        catalog = self.request('moneyball/columns?group=all')[1]
        for destination, collection, columns in (
            ('base', 'PlayerSearchResultsViewCollection', ['name', 'age', 'goals', 'future-column']),
            ('base', 'PlayerSearchResultsViewCollection',
             ['stats-overall-appearances', 'stats-minutes', 'overall-assists', 'expected-goals', 'expected-assists']),
            ('base', 'PlayerSearchResultsViewCollection', ['name', 'chalkboard-stats-passes-attempted']),
            ('meutime', 'FirstTeamSquadAndYouthTeamSquadCollection', ['name', 'age', 'goals']),
        ):
            data = view_bytes(columns, collection)
            status, review = self.request('views-fm?arquivo=apply.fmf&destino=' + destination, raw=data)
            self.assertEqual(status, 200, review)
            cases.append({'review': review, 'catalog': catalog})
        script = Path(__file__).with_name('fm_views_ui.mjs')
        checked = subprocess.run(['node', str(script)], input=json.dumps(cases),
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn('FM view Apply regressions passed: 4 cases', checked.stdout)

    def test_base_review_never_claims_unavailable_legacy_columns_are_supported(self):
        data = view_bytes(['name', 'condition', 'sharpness', 'stats-goals-per90'])
        status, review = self.request('views-fm?arquivo=unsupported.fmf', raw=data)
        self.assertEqual(status, 200, review)
        self.assertEqual(review['contagem'], {'ok': 1, 'sem': 3})
        for column in review['colunas'][1:]:
            self.assertIsNone(column['chave'])
            self.assertEqual(column['motivo'], 'nao_le')

    def test_folder_listing_uses_each_game_views_and_ignores_corrupt_files(self):
        (self.views / 'squad.FMF').write_bytes(view_bytes(collection='FirstTeamSquadAndYouthTeamSquadCollection'))
        (self.views / 'list.fmf').write_bytes(view_bytes(collection='PlayerSearchShortlistViewCollection'))
        (self.views / 'tactic.fmf').write_bytes(view_bytes(collection='TacticTeamSelection'))
        (self.views / 'bad.fmf').write_bytes(b'bad')
        (self.views / 'directory.fmf').mkdir()
        second_game = self.root / 'Football Manager 2025'
        (second_game / 'views').mkdir(parents=True)
        (second_game / 'views' / 'older.fmf').write_bytes(view_bytes())
        with patch.object(lista_fmf, 'pastas_dos_jogos', return_value=[
            {'jogo': self.game.name, 'pasta': str(self.game)},
            {'jogo': second_game.name, 'pasta': str(second_game)},
        ]):
            status, listing = self.request('views-fm/pasta')
            self.assertEqual(status, 200, listing)
            self.assertEqual(listing['pastas'][0]['pasta'], str(self.views))
            self.assertEqual([(v['arquivo'], v['tela']) for v in listing['pastas'][0]['views']],
                             [('list.fmf', 'lista'), ('search.fmf', 'busca'), ('squad.FMF', 'plantel'), ('tactic.fmf', 'tatica')])
            self.assertEqual(self.folder('older.fmf', jogo=second_game.name)[0], 200)

    def test_missing_invalid_paths_and_failed_reads_never_change_saved_data(self):
        (self.views / 'invalid.fmf').write_bytes(b'not FM')
        (self.views / 'empty.fmf').write_bytes(b'')
        (self.views / 'directory.fmf').mkdir()
        (self.views / 'huge.fmf').write_bytes(bytes(lista_fmf.TAMANHO_MAXIMO_ARQUIVO + 1))
        before = self.state()
        for filename in ('missing.fmf', str(self.root / 'missing.fmf'), '../search.fmf',
                         'bad\\search.fmf', 'null\0.fmf', str(self.root / 'null\0.fmf'), '',
                         'directory.fmf', 'invalid.fmf', 'empty.fmf', 'huge.fmf', 'wrong.txt'):
            with self.subTest(filename=filename):
                status, result = self.folder(filename)
                self.assertEqual(status, 400, result)
                self.assertTrue(result['detail'])
                self.assertEqual(self.state(), before)
        with patch('view_fmf.open', side_effect=PermissionError('unreadable')):
            self.assertEqual(self.folder()[0], 400)
        self.assertEqual(self.folder(jogo='missing game')[0], 400)
        self.assertEqual(self.state(), before)

    def test_upload_rejects_invalid_names_contents_and_size_without_side_effects(self):
        before = self.state()
        for endpoint in ('views-fm', 'biblioteca-fmf'):
            for filename, data, expected in (
                ('bad.fmf', b'bad', 400), ('empty.fmf', b'', 400), ('wrong.txt', self.source.read_bytes(), 400),
                ('../outside.fmf', self.source.read_bytes(), 400), ('a\\b.fmf', b'bad', 400),
                ('null\0.fmf', b'bad', 400), ('', b'bad', 400),
                ('huge.fmf', bytes(lista_fmf.TAMANHO_MAXIMO_ARQUIVO + 1), 413),
            ):
                with self.subTest(endpoint=endpoint, filename=filename):
                    status, result = self.request(endpoint + '?arquivo=' + urllib.parse.quote(filename), raw=data)
                    self.assertEqual(status, expected, result)
                    self.assertEqual(self.state(), before)
            self.assertEqual(self.request(endpoint, raw=self.source.read_bytes())[0], 422)

    def test_squad_destination_uses_my_team_mapping_and_library_detects_it(self):
        data = view_bytes(collection='FirstTeamSquadAndYouthTeamSquadCollection')
        (self.views / 'squad.fmf').write_bytes(data)
        before = self.state()
        status, review = self.folder('squad.fmf', 'meutime')
        self.assertEqual(status, 200, review)
        self.assertEqual((review['tela'], review['destino']), ('plantel', 'meutime'))
        self.assertEqual([c['chave'] for c in review['colunas']], ['name', 'age', 'goals', None])
        self.assertEqual(review['escondidas'], [])
        self.assertEqual(self.request('biblioteca-fmf?arquivo=squad.fmf', raw=data)[1]['review'], review)
        self.assertEqual(self.request('views-fm?arquivo=squad.fmf&destino=meutime', raw=data), (200, review))
        self.assertEqual(self.folder('squad.fmf', 'base')[0], 400)
        self.assertEqual(self.folder('search.fmf', 'meutime')[0], 400)
        for destino in ('unknown', ''):
            self.assertEqual(self.folder(destino=destino)[0], 400)
            self.assertEqual(self.request('views-fm?arquivo=search.fmf&destino=' + destino, raw=data)[0], 400)
        self.assertEqual(self.state(), before)

    def test_wrong_native_kinds_screens_and_malformed_view_shapes_are_errors(self):
        invalid = [fmf_bytes('List', [1]), view_bytes(collection='TacticTeamSelection'),
                   view_bytes(collection='PlayerSearchShortlistViewCollection'),
                   view_bytes(collection='UnknownViewCollection'), view_bytes(columns=[]),
                   view_bytes(columns=['age'] * 401), view_bytes(table=[{}]),
                   view_bytes(table=['age']), view_bytes(table={'m_columnID': 'age'}),
                   view_bytes(columns=[None]), view_bytes(columns=[42]), view_bytes(columns=['']),
                   view_bytes(outer=[]), view_bytes(outer={'ViewData': '[]'}),
                   view_bytes(outer={'ViewData': None}), view_bytes(outer={'ViewData': '{'})]
        before = self.state()
        for number, data in enumerate(invalid):
            with self.subTest(number=number):
                (self.views / 'bad.fmf').write_bytes(data)
                self.assertEqual(self.folder('bad.fmf')[0], 400)
                self.assertEqual(self.request('views-fm?arquivo=bad.fmf', raw=data)[0], 400)
                if number != 0:  # Library supports native shortlists as well as views.
                    self.assertEqual(self.request('biblioteca-fmf?arquivo=bad.fmf', raw=data)[0], 400)
                self.assertEqual(self.state(), before)

    def test_corrupt_member_and_compressed_index_are_rejected(self):
        broken_index = bytearray(view_bytes())
        at = broken_index.index(lista_fmf.MARCA_INDICE) + 9
        broken_index[at:] = b'xbroken compressed data'
        broken_member = bytearray(view_bytes())
        broken_member[26:30] = bytes(4)
        for data in (self.source.read_bytes()[:20], bytes(broken_index), bytes(broken_member)):
            self.assertEqual(self.request('views-fm?arquivo=bad.fmf', raw=data)[0], 400)
            self.assertEqual(self.request('biblioteca-fmf?arquivo=bad.fmf', raw=data)[0], 400)

    def test_native_picker_failure_cancellation_and_bad_selection_are_safe(self):
        before = self.state()
        for result, expected in (
            (subprocess.CompletedProcess([], 1, '', 'User canceled. (-128)'), {'disponivel': True, 'cancelado': True}),
            (subprocess.CompletedProcess([], 1, '', 'unavailable'), {'disponivel': False, 'cancelado': False}),
            (subprocess.CompletedProcess([], 0, '', ''), {'disponivel': True, 'cancelado': True}),
        ):
            with patch.object(server.subprocess, 'run', return_value=result):
                self.assertEqual(self.request('views-fm/escolher', body={}), (200, expected))
        with patch.object(server.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(self.request('views-fm/escolher', body={}),
                             (200, {'disponivel': False, 'cancelado': False}))
        with patch.object(server.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, str(self.root / 'missing.fmf'), '')):
            self.assertEqual(self.request('views-fm/escolher', body={})[0], 400)
        with patch.object(server.subprocess, 'run') as picker:
            self.assertEqual(self.request('views-fm/escolher?destino=unknown', body={})[0], 400)
            picker.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_review_keeps_unknown_unsupported_and_approximate_columns(self):
        data = view_bytes(['name', 'future-column', 'based', 'inf', 'current-ability-stars'])
        status, review = self.request('views-fm?arquivo=review.fmf', raw=data)
        self.assertEqual(status, 200, review)
        self.assertEqual(review['contagem'], {'ok': 1, 'desconhecida': 1, 'sem': 1, 'fm': 1, 'aprox': 1})
        self.assertEqual([c['estado'] for c in review['colunas']], ['ok', 'desconhecida', 'sem', 'fm', 'aprox'])
        self.assertEqual(review['colunas'][-1]['motivo'], 'olheiro')

    def test_library_keeps_native_shortlist_imports_and_rejects_other_fmf_kinds(self):
        status, result = self.request('biblioteca-fmf?arquivo=list.fmf', raw=fmf_bytes('List', [101, 202]))
        self.assertEqual(status, 200, result)
        self.assertEqual((result['tipo'], result['lista']['uids']), ('lista', [101, 202]))
        self.assertTrue((self.library / result['lista']['arquivo_biblioteca']).is_file())
        before = self.state()
        for ext in ('.pft', '.ssf'):
            self.assertEqual(self.request('biblioteca-fmf?arquivo=other.fmf', raw=fmf_bytes('Other', [1], ext))[0], 400)
            self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
