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


def fmf_bytes(name, uids, extension='.slf', modern=False, extra_members=None, folders=None):
    """Build a real encrypted member and compressed native FM container index."""
    def text(value):
        data = value.encode()
        return struct.pack('<I', len(data)) + data

    def build_member(content_bytes):
        iv, key = bytes(range(16)), bytes(range(16, 32))
        content = zstd.compress(content_bytes) if modern else content_bytes
        encrypted = struct.pack('<II', 16, 16) + iv + key + lista_fmf.aes128_ctr(key, iv, content)
        return encrypted, len(content_bytes)

    plain = (lista_fmf.MARCA_LISTA + bytes(3) + struct.pack('<I', 123) + text(name)
             + struct.pack('<I', len(uids)) + struct.pack(f'<{len(uids)}I', *uids))
    main_member, main_plain_len = build_member(plain)

    members_bytes = bytearray()
    root_records = []

    if extra_members:
        for em_name, em_ext, em_content in extra_members:
            em_enc, em_len = build_member(em_content)
            root_records.append((em_name, em_ext, len(members_bytes), len(em_enc), em_len))
            members_bytes.extend(em_enc)

    root_records.append((name, extension, len(members_bytes), len(main_member), main_plain_len))
    members_bytes.extend(main_member)

    folder_records = []
    if folders:
        for f_name, f_members in folders:
            f_recs = []
            for fm_name, fm_ext, fm_content in f_members:
                fm_enc, fm_len = build_member(fm_content)
                f_recs.append((fm_name, fm_ext, len(members_bytes), len(fm_enc), fm_len))
                members_bytes.extend(fm_enc)
            folder_records.append((f_name, f_recs))

    index_parts = [text(''), struct.pack('<I', len(root_records))]
    for m_name, m_ext, m_off, m_sz, m_plain_sz in root_records:
        index_parts.append(text(m_name) + text(m_ext) + struct.pack('<QQQ', m_off, m_sz, m_plain_sz) + bytes(16))
    index_parts.append(struct.pack('<I', len(folder_records)))
    for f_name, f_recs in folder_records:
        index_parts.append(text(f_name) + struct.pack('<I', len(f_recs)))
        for fm_name, fm_ext, fm_off, fm_sz, fm_plain_sz in f_recs:
            index_parts.append(text(fm_name) + text(fm_ext) + struct.pack('<QQQ', fm_off, fm_sz, fm_plain_sz) + bytes(16))

    index = b''.join(index_parts)
    header = bytearray(26)
    header[:6] = lista_fmf.MARCA_CONTEINER
    struct.pack_into('<H', header, 6, 8 if modern else 7)
    struct.pack_into('<Q', header, 9, 26 + len(members_bytes) - 9)
    index_frame = zstd.compress(index) if modern else zlib.compress(index)
    return bytes(header) + bytes(members_bytes) + lista_fmf.MARCA_INDICE + bytes(3) + index_frame


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

    def test_fm26_multi_member_shortlist_with_img_and_slf_imports_correctly(self):
        multi_path = self.shortlists / 'fm26_wonderkids.fmf'
        extra = [('thumbnail', '.img', b'\x89PNG\r\n\x1a\nfakeimagebytes12345678')]
        multi_data = fmf_bytes('FM26 Wonderkids', [5001, 5002, 5003], modern=True, extra_members=extra)
        multi_path.write_bytes(multi_data)

        # 1. Folder view lists multi-member FM26 shortlist with correct name and count
        status, folder_res = self.request('/pasta')
        self.assertEqual(status, 200, folder_res)
        target = next((x for x in folder_res['pastas'][0]['listas'] if x['arquivo'] == 'fm26_wonderkids.fmf'), None)
        self.assertIsNotNone(target)
        self.assertEqual(target['nome'], 'FM26 Wonderkids')
        self.assertEqual(target['quantidade'], 3)
        self.assertFalse(target['carregada'])

        # 2. Import from folder succeeds with 200 and loads player UIDs
        imported = self.import_folder('fm26_wonderkids.fmf')
        self.assertEqual(imported['nome'], 'FM26 Wonderkids')
        self.assertEqual(imported['uids'], [5001, 5002, 5003])
        self.assertEqual(imported['total'], 3)
        self.assertEqual(imported['formato'], '26')

        # 3. Direct upload also succeeds
        upload_data = fmf_bytes('Direct Upload', [7001, 7002], modern=True, extra_members=extra)
        status, upload_res = self.request('?arquivo=direct.fmf', raw=upload_data)
        self.assertEqual(status, 200, upload_res)
        self.assertEqual(upload_res['lista']['nome'], 'Direct Upload')
        self.assertEqual(upload_res['lista']['uids'], [7001, 7002])

    def test_folder_view_identifies_unreadable_file_when_folder_has_corrupt_files(self):
        (self.shortlists / 'corrupt_shortlist.fmf').write_bytes(b'CORRUPTED_BYTES_NOT_FM')
        status, result = self.request('/pasta')
        self.assertEqual(status, 200, result)
        pasta = result['pastas'][0]
        # Valid shortlist is still listed
        self.assertIn('first.fmf', [x['arquivo'] for x in pasta['listas']])
        # Unreadable file is identified in invalidas and arquivos_invalidos
        invalid_names = [x['arquivo'] for x in pasta.get('invalidas', [])]
        self.assertIn('corrupt_shortlist.fmf', invalid_names)
        self.assertIn('corrupt_shortlist.fmf', [x['arquivo'] for x in pasta.get('arquivos_invalidos', [])])
        corrupt_entry = next(x for x in pasta['invalidas'] if x['arquivo'] == 'corrupt_shortlist.fmf')
        self.assertTrue(corrupt_entry['erro'])


class FmfIndexParserTests(unittest.TestCase):
    def test_parser_multi_member_root_and_subfolder(self):
        extra = [
            ('icon', '.img', b'thumbnail_data'),
            ('notes', '.txt', b'wonderkids shortlist notes'),
        ]
        folders = [
            ('subfolder', [('tactical', '.slf', b'tactical_notes')])
        ]
        data = fmf_bytes('Main Shortlist', [99, 100, 101], modern=True, extra_members=extra, folders=folders)
        membros = lista_fmf._ler_indice(data)
        # Should contain icon, notes, main shortlist, and subfolder member
        exts = [m[1] for m in membros]
        self.assertIn('.img', exts)
        self.assertIn('.txt', exts)
        self.assertIn('.slf', exts)
        parsed = lista_fmf.ler(data)
        self.assertEqual(parsed['nome'], 'Main Shortlist')
        self.assertEqual(parsed['uids'], [99, 100, 101])
        self.assertEqual(parsed['formato'], '26')

    def test_parser_handles_legacy_mock_structure(self):
        # Explicitly construct legacy mock format: pastas = 0, quantidade = 1
        name = 'Legacy List'
        uids = [42]
        def text(value):
            data = value.encode()
            return struct.pack('<I', len(data)) + data

        plain = (lista_fmf.MARCA_LISTA + bytes(3) + struct.pack('<I', 123) + text(name)
                 + struct.pack('<I', len(uids)) + struct.pack(f'<{len(uids)}I', *uids))
        iv, key = bytes(range(16)), bytes(range(16, 32))
        member = struct.pack('<II', 16, 16) + iv + key + lista_fmf.aes128_ctr(key, iv, plain)
        index = (text('') + struct.pack('<II', 0, 1) + text(name) + text('.slf')
                 + struct.pack('<QQQ', 0, len(member), len(plain)) + bytes(16))
        header = bytearray(26)
        header[:6] = lista_fmf.MARCA_CONTEINER
        struct.pack_into('<H', header, 6, 7)
        struct.pack_into('<Q', header, 9, 26 + len(member) - 9)
        index_frame = zlib.compress(index)
        legacy_data = bytes(header) + member + lista_fmf.MARCA_INDICE + bytes(3) + index_frame

        parsed = lista_fmf.ler(legacy_data)
        self.assertEqual(parsed['nome'], 'Legacy List')
        self.assertEqual(parsed['uids'], [42])

    def test_parser_rejects_corrupted_container_and_index(self):
        with self.assertRaises(lista_fmf.NaoEhFmf):
            lista_fmf._ler_indice(b'NOT_A_CONTAINER')
        with self.assertRaises(lista_fmf.ArquivoCorrompido):
            # Header valid (len >= 35) but container claims huge member size beyond file length
            hdr = bytearray(lista_fmf.MARCA_CONTEINER + bytes(40))
            struct.pack_into('<Q', hdr, 9, 1000000)
            lista_fmf._ler_indice(bytes(hdr))


if __name__ == '__main__':
    unittest.main()
