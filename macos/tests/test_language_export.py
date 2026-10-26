"""Language export must create editable files consumed by Preferences (issue #25)."""

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import idiomas
import server
import uvicorn


class LanguageExportTests(unittest.TestCase):
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
            raise RuntimeError('Language test HTTP server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='fmsh-language-export-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.shipped = self.root / 'shipped'
        self.user = self.root / 'user'
        self.user.mkdir()
        english = self.shipped / 'en'
        english.mkdir(parents=True)
        (english / 'interface.txt').write_text(
            '_idioma.nome = English\nhello = Hello {{name}}\nbye = Goodbye\n', encoding='utf-8')
        (english / 'colunas.txt').write_text('goals.nome = Goals\ngoals.sigla = G\n', encoding='utf-8')
        for name, value in (('idiomas_dir', self.user), ('idiomas_embarcados', self.shipped)):
            mocked = patch.object(idiomas.paths, name, return_value=str(value))
            mocked.start()
            self.addCleanup(mocked.stop)
        idiomas._CACHE.clear()
        self.addCleanup(idiomas._CACHE.clear)

    def request(self, route='/api/idiomas/exportar', body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + route, data=data,
                                         headers={'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def export(self, code='zz', base='en', name=None):
        return self.request(body={'codigo': code, 'base': base, 'nome': name})

    def test_language_cards_report_actual_numeric_coverage(self):
        for code, text in (
            ('pt', '_idioma.nome = Português\nhello = Olá\n'),
            ('full', '_idioma.nome = Full\nhello = Hi\nbye = Bye\n'),
            ('partial', '_idioma.nome = Partial\nhello = Hi\nbye = \nextra = Ignore\n'),
            ('empty', '_idioma.nome = Empty\nhello = \nbye = \n'),
        ):
            target = self.user / code
            target.mkdir()
            (target / 'interface.txt').write_text(text, encoding='utf-8')
            (target / 'colunas.txt').write_text('goals.nome = Goals\n', encoding='utf-8')
        status, result = self.request('/api/idiomas')
        self.assertEqual(status, 200)
        cards = {item['codigo']: item for item in result['idiomas']}
        for code, translated, percent in (
            ('en', 2, 100), ('pt', 1, 50), ('full', 2, 100),
            ('partial', 1, 50), ('empty', 0, 0),
        ):
            with self.subTest(code=code):
                card = cards[code]
                for key in ('completo', 'cobertura', 'traduzidos', 'total'):
                    self.assertIs(type(card[key]), int)
                self.assertEqual((card['completo'], card['cobertura']), (percent, percent))
                self.assertEqual((card['traduzidos'], card['total']), (translated, 2))
                self.assertEqual(card['n_problemas'], 0)

    def test_language_cards_have_zero_counts_without_base_keys(self):
        (self.shipped / 'en' / 'interface.txt').write_text(
            '_idioma.nome = English\n', encoding='utf-8')
        status, result = self.request('/api/idiomas')
        self.assertEqual(status, 200)
        card = result['idiomas'][0]
        self.assertEqual((card['completo'], card['traduzidos'], card['total']), (0, 0, 0))

    def test_language_card_fallback_keeps_numeric_contract(self):
        for module_available in (False, True):
            for scanned in (False, True):
                with self.subTest(module_available=module_available, scanned=scanned):
                    root = self.root / ('scan' if scanned else 'no-scan')
                    if scanned:
                        (root / 'idiomas' / 'zz').mkdir(parents=True, exist_ok=True)
                    with patch.object(server, 'FMSH_DIR', root):
                        if module_available:
                            with patch.object(idiomas, 'disponiveis', side_effect=OSError('QA')):
                                status, result = self.request('/api/idiomas')
                        else:
                            with patch.object(server, 'idiomas', None):
                                status, result = self.request('/api/idiomas')
                    self.assertEqual(status, 200)
                    self.assertEqual({item['codigo'] for item in result['idiomas']},
                                     {'zz'} if scanned else {'en', 'pt'})
                    for card in result['idiomas']:
                        for key in ('completo', 'cobertura', 'traduzidos', 'total'):
                            self.assertIs(type(card[key]), int)
                            self.assertEqual(card[key], 0)

    def test_new_language_files_and_frontend_metadata(self):
        status, result = self.export(name='QA language')
        self.assertEqual(status, 200)
        self.assertTrue(result['ok'])
        self.assertEqual(Path(result['pasta']), self.user / 'zz')
        self.assertEqual(result['arquivos'], [
            {'arquivo': 'interface.txt', 'total': 2, 'faltando': 2},
            {'arquivo': 'colunas.txt', 'total': 2, 'faltando': 2},
        ])
        self.assertEqual(sorted(p.name for p in (self.user / 'zz').iterdir()),
                         ['colunas.txt', 'interface.txt'])
        text = (self.user / 'zz' / 'interface.txt').read_text(encoding='utf-8')
        self.assertIn('_idioma.codigo = zz', text)
        self.assertIn('_idioma.nome = QA language', text)
        self.assertIn('# en: Hello {{name}}\nhello = ', text)
        self.assertIn('goals.nome = ', (self.user / 'zz' / 'colunas.txt').read_text())
        self.assertEqual(idiomas.analisar_texto(text)[1], [])
        self.assertFalse((self.shipped / 'zz').exists())

    def test_edits_are_read_and_preserved_on_regeneration(self):
        self.export()
        target = self.user / 'zz'
        (target / 'interface.txt').write_text(
            '_idioma.nome = QA language\nhello = Bonjour {{name}}\\nC:\\\\QA\ncustom = Keep\n', encoding='utf-8')
        (target / 'colunas.json').write_text(json.dumps({'goals': {'nome': 'Buts'}}), encoding='utf-8')
        os.utime(target / 'interface.txt', (time.time() + 1, time.time() + 1))
        status, loaded = self.request('/api/idiomas/zz')
        self.assertEqual(status, 200)
        self.assertEqual(loaded['interface']['hello'], 'Bonjour {{name}}\nC:\\QA')
        self.assertEqual(loaded['colunas']['goals.nome'], 'Buts')
        status, result = self.export()
        self.assertEqual(status, 200)
        self.assertEqual(result['arquivos'][0], {'arquivo': 'interface.txt', 'total': 3, 'faltando': 1})
        self.assertEqual(result['arquivos'][1]['faltando'], 1)
        parsed, errors = idiomas.analisar_texto((target / 'interface.txt').read_text())
        self.assertEqual(errors, [])
        self.assertEqual(parsed['hello'], 'Bonjour {{name}}\nC:\\QA')
        self.assertEqual(parsed['custom'], 'Keep')
        self.assertEqual(parsed['_idioma.nome'], 'QA language')
        self.assertEqual(json.loads((target / 'colunas.json').read_text()), {'goals': {'nome': 'Buts'}})
        self.assertEqual(self.request('/api/idiomas/zz')[1]['interface']['hello'], parsed['hello'])

    def test_json_backed_language_text_edits_survive_reload_and_regeneration(self):
        target = self.user / 'zz'
        target.mkdir()
        original_json = {
            'interface.json': {'_idioma': {'nome': 'Old name', 'autor': 'QA author'},
                               'hello': 'Old greeting', 'custom': 'Keep custom'},
            'colunas.json': {'goals': {'nome': 'Old goals', 'sigla': 'OG'}},
        }
        for filename, data in original_json.items():
            (target / filename).write_text(json.dumps(data), encoding='utf-8')
        original_bytes = {filename: (target / filename).read_bytes() for filename in original_json}
        shipped = self.shipped / 'zz'
        shipped.mkdir()
        (shipped / 'interface.txt').write_text('hello = Shipped greeting\n', encoding='utf-8')
        shipped_before = (shipped / 'interface.txt').read_bytes()

        status, _ = self.export(name='Requested name')
        self.assertEqual(status, 200)
        self.assertIn('hello = Old greeting', (target / 'interface.txt').read_text())
        edits = {
            'interface.txt': [('hello = Old greeting', 'hello = Edited greeting'),
                              ('_idioma.nome = Requested name', '_idioma.nome = Edited name')],
            'colunas.txt': [('goals.nome = Old goals', 'goals.nome = Edited goals'),
                            ('goals.sigla = OG', 'goals.sigla = EG')],
        }
        for filename, replacements in edits.items():
            path = target / filename
            text = path.read_text(encoding='utf-8')
            for before, after in replacements:
                self.assertIn(before, text)
                text = text.replace(before, after)
            path.write_text(text, encoding='utf-8')
            os.utime(path, (time.time() + 1, time.time() + 1))

        for regenerated in (False, True):
            with self.subTest(regenerated=regenerated):
                if regenerated:
                    self.assertEqual(self.export()[0], 200)
                status, loaded = self.request('/api/idiomas/zz')
                self.assertEqual(status, 200)
                self.assertEqual(loaded['interface']['hello'], 'Edited greeting')
                self.assertEqual(loaded['interface']['_idioma.nome'], 'Edited name')
                self.assertEqual(loaded['interface']['_idioma.autor'], 'QA author')
                self.assertEqual(loaded['interface']['custom'], 'Keep custom')
                self.assertEqual(loaded['colunas']['goals.nome'], 'Edited goals')
                self.assertEqual(loaded['colunas']['goals.sigla'], 'EG')
                languages = self.request('/api/idiomas')[1]['idiomas']
                self.assertEqual(next(item for item in languages if item['codigo'] == 'zz')['nome'],
                                 'Edited name')
        for filename, before in original_bytes.items():
            self.assertEqual((target / filename).read_bytes(), before)
        self.assertEqual((shipped / 'interface.txt').read_bytes(), shipped_before)

    def test_fix_shipped_language_creates_user_copy_only(self):
        originals = {p: p.read_bytes() for p in (self.shipped / 'en').iterdir()}
        status, result = self.export('en')
        self.assertEqual(status, 200)
        self.assertTrue(all(item['faltando'] == 0 for item in result['arquivos']))
        self.assertEqual(idiomas.carregar('en')[0]['hello'], 'Hello {{name}}')
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertTrue((self.user / 'en' / 'colunas.txt').is_file())

    def test_invalid_codes_do_not_create_files(self):
        for code in ('', '.', '..', '../outside', '/tmp/outside', 'en/../../out', 'en\\out',
                     '.hidden', 'en\nother', 'a' * 36):
            with self.subTest(code=code):
                self.assertEqual(self.export(code)[0], 422)
        self.assertEqual(self.export(base='../outside')[0], 422)
        self.assertEqual(list(self.user.iterdir()), [])
        self.assertEqual(self.export('pt-br')[0], 200)

    def test_conflicts_and_symlinks_do_not_change_other_files(self):
        outside = self.root / 'outside'
        outside.mkdir()
        sentinel = outside / 'interface.txt'
        sentinel.write_text('hello = Keep me\n')
        (self.user / 'zz').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.export()[0], 422)
        self.assertEqual(sentinel.read_text(), 'hello = Keep me\n')
        (self.user / 'zz').unlink()
        (self.user / 'zz').mkdir()
        for suffix in ('txt', 'json'):
            path = self.user / 'zz' / ('interface.' + suffix)
            path.symlink_to(sentinel)
            self.assertEqual(self.export()[0], 422)
            self.assertEqual(sentinel.read_text(), 'hello = Keep me\n')
            path.unlink()
        (self.user / 'zz' / 'colunas.txt').mkdir()
        self.assertEqual(self.export()[0], 422)
        self.assertFalse((self.user / 'zz' / 'interface.txt').exists())

    def test_staging_write_failure_preserves_existing_files(self):
        self.export('en')
        target = self.user / 'en'
        before = {p: p.read_bytes() for p in target.iterdir()}
        original_write = Path.write_text

        def fail_columns(path, *args, **kwargs):
            if path.name == 'colunas.txt':
                raise PermissionError('QA write failure')
            return original_write(path, *args, **kwargs)

        with patch.object(Path, 'write_text', fail_columns):
            status, result = self.export('en')
        self.assertEqual(status, 500)
        self.assertIn('detail', result)
        for path, value in before.items():
            self.assertEqual(path.read_bytes(), value)
        self.assertEqual(sorted(p.name for p in self.user.iterdir()), ['en'])

    def test_open_folder_uses_writable_language_directory(self):
        with patch.object(server.subprocess, 'Popen') as opening:
            status, result = self.request('/api/idiomas/abrir-pasta', {})
        self.assertEqual(status, 200)
        self.assertTrue(result['ok'])
        opening.assert_called_once_with(['open', str(self.user)])


if __name__ == '__main__':
    unittest.main()
