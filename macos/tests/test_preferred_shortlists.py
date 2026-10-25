"""Native FM shortlist imports must survive file deletion and server restart."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zlib
from compression import zstd

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
import lista_fmf


def fmf_bytes(name, uids, extension='.slf', modern=False):
    """Build a real encrypted member and compressed native FM container index."""
    def text(value):
        data = value.encode()
        return struct.pack('<I', len(data)) + data

    plain = (lista_fmf.MARCA_LISTA + bytes(3) + struct.pack('<I', 123) + text(name)
             + struct.pack('<I', len(uids)) + struct.pack(f'<{len(uids)}I', *uids))
    iv, key = bytes(range(16)), bytes(range(16, 32))
    content = zstd.compress(plain) if modern else plain
    member = struct.pack('<II', 16, 16) + iv + key + lista_fmf.aes128_ctr(key, iv, content)
    index = (text('') + struct.pack('<II', 0, 1) + text(name) + text(extension)
             + struct.pack('<QQQ', 0, len(member), len(plain)) + bytes(16))
    header = bytearray(26)
    header[:6] = lista_fmf.MARCA_CONTEINER
    struct.pack_into('<H', header, 6, 7)
    struct.pack_into('<Q', header, 9, 26 + len(member) - 9)
    index_frame = zstd.compress(index) if modern else zlib.compress(index)
    return bytes(header) + member + lista_fmf.MARCA_INDICE + bytes(3) + index_frame


class PreferredShortlistTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='fmsh-shortlist-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.game = self.root / 'Football Manager 2026'
        self.shortlists = self.game / 'shortlists'
        self.shortlists.mkdir(parents=True)
        self.source = self.shortlists / 'first.fmf'
        self.source.write_bytes(fmf_bytes('São Paulo', [101, 202], modern=True))
        self.process = None
        self.log = (self.root / 'server.log').open('w+')
        self.addCleanup(self.log.close)
        self.addCleanup(self.stop)
        self.start()

    def start(self, picker=None):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.base = f'http://127.0.0.1:{port}'
        env = dict(os.environ, PYTHONPATH=str(SRC), FMSH_PASTA_DADOS=str(self.data),
                   FMSH_PASTA_LOCAL=str(self.root / 'local'))
        code = (
            'import lista_fmf, server, uvicorn\n'
            f'lista_fmf.pastas_dos_jogos = lambda: [{{"jogo":"Football Manager 2026", "pasta":{str(self.game)!r}}}]\n'
        )
        if picker is not None:
            # Mock only the OS dialog; the selected file is read and parsed for real.
            code += (
                'from unittest.mock import patch\n'
                'from subprocess import CompletedProcess\n'
                f'picker = patch.object(server.subprocess, "run", return_value=CompletedProcess([], {picker[0]!r}, {picker[1]!r}, {picker[2]!r}))\n'
                'picker.start()\n'
            )
        code += f'uvicorn.run(server.app, host="127.0.0.1", port={port}, log_level="error")\n'
        self.process = subprocess.Popen([sys.executable, '-c', code], cwd=SRC, env=env,
                                        stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self.process.poll() is None:
            try:
                if self.request()[0] == 200:
                    return
            except (OSError, urllib.error.URLError):
                time.sleep(.03)
        self.log.seek(0)
        self.fail('Server did not start: ' + self.log.read())

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)
        self.process = None

    def restart(self, picker=None):
        self.stop()
        self.start(picker)

    def request(self, endpoint='', body=None, method=None, raw=None):
        data = raw if raw is not None else None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + '/api/listas-preferenciais' + endpoint,
                                         data=data, method=method)
        if body is not None:
            request.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def import_folder(self, filename='first.fmf'):
        status, result = self.request('/da-pasta', {'arquivo': filename, 'jogo': 'Football Manager 2026'})
        self.assertEqual(status, 200, result)
        self.assertTrue(result['ok'])
        self.assertIn(result['lista'], result['listas'])
        return result['lista']

    def test_import_reads_native_bytes_and_survives_source_removal_and_restart(self):
        listing = self.request('/pasta')[1]['pastas'][0]
        self.assertEqual(listing['listas'][0]['nome'], 'São Paulo')
        self.assertEqual(listing['listas'][0]['quantidade'], 2)
        first = self.import_folder()
        self.assertEqual((first['nome'], first['uids'], first['total'], first['save']),
                         ('São Paulo', [101, 202], 2, 123))
        self.assertIn('T', first['arquivo_em'])
        self.assertTrue(first['carregada_em'])
        self.assertTrue(self.request('/pasta')[1]['pastas'][0]['listas'][0]['carregada'])
        second_path = self.shortlists / 'second.fmf'
        second_path.write_bytes(fmf_bytes('Second', [303]))
        second = self.import_folder('second.fmf')
        self.assertNotEqual(first['id'], second['id'])
        expected = self.request()[1]
        self.source.unlink()
        second_path.unlink()
        self.restart()
        self.assertEqual(self.request()[1], expected)
        stored = json.loads((self.data / 'fmsh_settings.json').read_text())['listas_preferenciais']
        for item in stored:
            copied = self.data / 'Biblioteca' / item['arquivo_biblioteca']
            self.assertEqual(lista_fmf.ler(copied.read_bytes())['uids'], item['uids'])
        self.assertEqual(self.request('/' + first['id'] + '/atualizar', method='POST')[0], 400)
        self.assertEqual(self.request()[1], expected)

    def test_bad_paths_formats_and_corrupt_compression_do_not_save_lists(self):
        (self.shortlists / 'invalid.fmf').write_bytes(b'not FM')
        (self.shortlists / 'view.fmf').write_bytes(fmf_bytes('View', [1], '.view'))
        broken = bytearray(fmf_bytes('Broken', [1]))
        at = broken.index(lista_fmf.MARCA_INDICE) + 9
        broken[at:] = b'x' + b'broken compressed index'
        (self.shortlists / 'compressed.fmf').write_bytes(broken)
        (self.shortlists / 'huge.fmf').write_bytes(bytes(lista_fmf.TAMANHO_MAXIMO_ARQUIVO + 1))
        (self.shortlists / 'directory.fmf').mkdir()
        (self.shortlists / 'list.lsh').write_text('{"nome":"Library","jogadores":[{"uid":1}]}')
        for filename in ('missing.fmf', 'missing.lsh', str(self.root / 'missing.lsh'),
                         '../first.fmf', 'bad\\first.fmf', 'null\0.fmf', str(self.root / 'null\0.fmf'), '', 'directory.fmf',
                         'invalid.fmf', 'view.fmf', 'compressed.fmf', 'huge.fmf', 'list.lsh'):
            with self.subTest(filename=filename):
                status, result = self.request('/da-pasta', {'arquivo': filename})
                self.assertEqual(status, 400, result)
                self.assertTrue(result['detail'])
                self.assertEqual(self.request()[1], {'listas': []})
        self.assertEqual([x['arquivo'] for x in self.request('/pasta')[1]['pastas'][0]['listas']], ['first.fmf'])

    def test_folder_dates_use_iso_while_stored_file_time_stays_seconds(self):
        modified = datetime(2026, 10, 25, 12, 34, 56, 125000, tzinfo=timezone.utc).timestamp()
        os.utime(self.source, (modified, modified))
        actual_mtime = self.source.stat().st_mtime
        expected = datetime.fromtimestamp(actual_mtime, timezone.utc).isoformat()
        status, result = self.request('/pasta')
        self.assertEqual(status, 200, result)
        self.assertEqual(result['pastas'][0]['listas'][0]['modificado'], expected)
        imported = self.import_folder()
        self.assertEqual(imported['arquivo_em'], expected)
        stored = json.loads((self.data / 'fmsh_settings.json').read_text())['listas_preferenciais']
        self.assertEqual(stored[0]['arquivo_em'], actual_mtime)

    def test_raw_upload_has_real_import_and_size_format_validation(self):
        payload = fmf_bytes('Uploaded', [404, 505])
        status, result = self.request('?arquivo=upload.fmf', raw=payload)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['lista']['uids'], [404, 505])
        self.assertIsNone(result['lista']['origem'])
        expected = self.request()[1]
        for filename, data, expected_status in (
            ('bad.fmf', b'bad', 400), ('wrong.lsh', payload, 400), ('../outside.fmf', payload, 400),
            ('huge.fmf', bytes(lista_fmf.TAMANHO_MAXIMO_ARQUIVO + 1), 413)):
            status, _ = self.request('?arquivo=' + urllib.parse.quote(filename), raw=data)
            self.assertEqual(status, expected_status)
            self.assertEqual(self.request()[1], expected)
        self.restart()
        self.assertEqual(self.request()[1], expected)

    def test_same_source_updates_same_id_but_same_name_new_source_is_retained(self):
        first = self.import_folder()
        self.source.write_bytes(fmf_bytes('São Paulo', [202, 303]))
        updated = self.import_folder(str(self.source))
        self.assertEqual(updated['id'], first['id'])
        self.assertEqual(updated['uids'], [202, 303])
        second_path = self.shortlists / 'second.fmf'
        second_path.write_bytes(fmf_bytes('São Paulo', [404]))
        second = self.import_folder('second.fmf')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(second['nome'], 'São Paulo (2)')
        self.assertEqual(self.import_folder('second.fmf')['id'], second['id'])
        self.assertEqual(self.request()[1]['listas'][-1]['nome'], 'São Paulo (2)')
        self.assertEqual(len(self.request()[1]['listas']), 2)

    def test_raw_reupload_keeps_suffixed_list_identity_after_restart(self):
        status, first = self.request('?arquivo=one.fmf', raw=fmf_bytes('Same', [1]))
        self.assertEqual(status, 200, first)
        status, second = self.request('?arquivo=two.fmf', raw=fmf_bytes('Same', [2]))
        self.assertEqual(status, 200, second)
        original = second['lista']
        self.assertNotEqual(original['id'], first['lista']['id'])
        self.assertEqual(original['nome'], 'Same (2)')
        self.restart()

        status, result = self.request('?arquivo=two.fmf', raw=fmf_bytes('Same', [2, 3]))
        self.assertEqual(status, 200, result)
        updated = result['lista']
        self.assertEqual((updated['id'], updated['nome'], updated['uids'], updated['total']),
                         (original['id'], 'Same (2)', [2, 3], 2))
        self.assertEqual(updated['adicionada_em'], original['adicionada_em'])
        self.assertEqual(len(result['listas']), 2)
        self.assertEqual(result['listas'][0], first['lista'])
        self.assertEqual(result['listas'][1], updated)
        self.restart()
        self.assertEqual(self.request()[1], {'listas': result['listas']})
        stored = json.loads((self.data / 'fmsh_settings.json').read_text())['listas_preferenciais']
        for item in stored:
            copied = self.data / 'Biblioteca' / item['arquivo_biblioteca']
            self.assertEqual(lista_fmf.ler(copied.read_bytes())['uids'], item['uids'])

    def test_refresh_keeps_unrelated_library_file_and_symlink_target(self):
        first = self.import_folder()
        mirror = self.data / 'Biblioteca' / first['arquivo_biblioteca']
        outside = self.root / 'outside.fmf'
        outside.write_bytes(b'Keep this file')
        mirror.unlink()
        mirror.symlink_to(outside)
        self.source.write_bytes(fmf_bytes('Updated', [303]))
        status, result = self.request('/' + first['id'] + '/atualizar', method='POST')
        self.assertEqual(status, 200, result)
        self.assertTrue(mirror.is_symlink())
        self.assertEqual(outside.read_bytes(), b'Keep this file')
        self.assertNotEqual(result['lista']['arquivo_biblioteca'], first['arquivo_biblioteca'])
        copied = self.data / 'Biblioteca' / result['lista']['arquivo_biblioteca']
        self.assertEqual(lista_fmf.ler(copied.read_bytes())['uids'], [303])

    def test_refresh_and_remove_return_current_collection_and_preserve_old_data_on_error(self):
        first = self.import_folder()
        route = '/' + first['id']
        self.source.write_bytes(fmf_bytes('Updated', [303]))
        status, result = self.request(route + '/atualizar', method='POST')
        self.assertEqual(status, 200, result)
        self.assertEqual((result['lista']['id'], result['lista']['nome'], result['lista']['uids']),
                         (first['id'], 'Updated', [303]))
        self.assertEqual(result['listas'], [result['lista']])
        self.source.write_bytes(b'bad')
        expected = self.request()[1]
        self.assertEqual(self.request(route + '/atualizar', method='POST')[0], 400)
        self.assertEqual(self.request()[1], expected)
        self.assertEqual(self.request('/unknown/atualizar', method='POST')[0], 404)
        self.assertEqual(self.request('/unknown', method='DELETE')[0], 404)
        self.assertEqual(self.request(route, method='DELETE'), (200, {'ok': True, 'listas': []}))
        self.restart()
        self.assertEqual(self.request()[1], {'listas': []})

    def test_native_picker_reads_selected_file_and_cancel_keeps_state(self):
        self.restart(picker=(0, str(self.source) + '\n', ''))
        status, result = self.request('/escolher', method='POST')
        self.assertEqual(status, 200, result)
        self.assertTrue(result['disponivel'])
        self.assertFalse(result['cancelado'])
        self.assertEqual(result['lista']['uids'], [101, 202])
        expected = self.request()[1]
        self.restart(picker=(1, '', 'User canceled. (-128)'))
        self.assertEqual(self.request('/escolher', method='POST'),
                         (200, {'disponivel': True, 'cancelado': True}))
        self.assertEqual(self.request()[1], expected)
        self.restart(picker=(1, '', 'Picker unavailable'))
        self.assertEqual(self.request('/escolher', method='POST'),
                         (200, {'disponivel': False, 'cancelado': False}))

    def test_shipped_ui_keeps_imported_list_controls_without_a_selected_season(self):
        self.import_folder()
        (self.shortlists / 'second.fmf').write_bytes(fmf_bytes('Second', [303]))
        self.import_folder('second.fmf')
        result = subprocess.run(['node', str(Path(__file__).with_name('preferred_shortlists_ui.mjs'))],
                                input=json.dumps(self.request()[1]), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Preferred shortlist renderer passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
