"""Library path containment through real HTTP with disposable files."""

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
import urllib.parse
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import server
import uvicorn


class LibraryPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listener = socket.socket()
        cls.listener.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.listener.getsockname()[1]}"
        cls.srv = uvicorn.Server(uvicorn.Config(server.app, log_level="error"))
        cls.thread = threading.Thread(target=cls.srv.run, kwargs={"sockets": [cls.listener]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 5
        while not cls.srv.started and cls.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not cls.srv.started:
            raise RuntimeError("Library test HTTP server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True
        cls.thread.join(5)
        cls.listener.close()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.library = self.root / "Biblioteca"
        self.library.mkdir()
        self.outside = self.root / "outside.fsh"
        self.outside.write_bytes(b"outside marker")
        library = patch.object(server, "_get_biblioteca_dir", return_value=self.library)
        library.start()
        self.addCleanup(library.stop)

    def request(self, route, body=None, raw=False):
        request = urllib.request.Request(self.base + route)
        if body is not None:
            request.data = json.dumps(body).encode()
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                content = response.read()
                if raw:
                    return response.status, content
                try:
                    return response.status, json.loads(content)
                except Exception:
                    return response.status, content
        except urllib.error.HTTPError as response:
            with response:
                content = response.read()
                try:
                    return response.code, json.loads(content)
                except Exception:
                    return response.code, content

    def read_file(self, name):
        encoded = urllib.parse.quote(name, safe="").replace(".", "%2E")
        return self.request(f"/api/biblioteca/{encoded}")

    def download_bruto(self, name):
        encoded = urllib.parse.quote(name, safe="").replace(".", "%2E")
        return self.request(f"/api/biblioteca/{encoded}/bruto", raw=True)

    def save(self, name, content):
        return self.request("/api/biblioteca", {"arquivo": name, "conteudo": content})

    def rename(self, source, destination):
        encoded = urllib.parse.quote(source, safe="").replace(".", "%2E")
        return self.request(f"/api/biblioteca/{encoded}/nome", {"nome": destination})

    def invalid_names(self):
        return (
            "../outside.fsh", "../escaped.fsh", str(self.outside),
            str(self.root / "escaped.fsh"), "nested/escaped.fsh",
            "nested\\escaped.fsh", "..\\escaped.fsh", "C:\\escaped.fsh",
            "C:/escaped.fsh", "C:escaped.fsh", "\\\\host\\share\\escaped.fsh",
            ".", "..", "", "   ", "bad\0name.fsh", "bad\ud800name.fsh",
        )

    def assert_original_files(self, source):
        self.assertEqual(self.outside.read_bytes(), b"outside marker")
        self.assertEqual(source.read_bytes(), b"source marker")
        self.assertEqual(set(self.root.iterdir()), {self.library, self.outside})
        self.assertEqual(list(self.library.iterdir()), [source])

    def test_save_rejects_paths_without_changing_any_files(self):
        source = self.library / "source.fsh"
        source.write_bytes(b"source marker")
        for name in self.invalid_names():
            with self.subTest(name=repr(name)):
                self.assertEqual(self.save(name, {"escaped": True})[0], 400)
                self.assert_original_files(source)

    def test_rename_rejects_unsafe_destinations_without_changing_any_files(self):
        source = self.library / "source.fsh"
        source.write_bytes(b"source marker")
        for name in self.invalid_names():
            with self.subTest(name=repr(name)):
                self.assertEqual(self.rename(source.name, name)[0], 400)
                self.assert_original_files(source)

    def test_rename_rejects_unsafe_sources_without_changing_any_files(self):
        source = self.library / "source.fsh"
        source.write_bytes(b"source marker")
        for name in self.invalid_names():
            if "\ud800" in name:
                continue  # Invalid UTF-8 cannot be encoded into an HTTP URL.
            with self.subTest(name=repr(name)):
                # Decoded slashes/empty names can fail routing before validation.
                self.assertIn(self.rename(name, "renamed.fsh")[0], (400, 404, 405))
                self.assert_original_files(source)

    def test_save_rejects_existing_and_dangling_symlinks(self):
        missing = self.root / "missing.fsh"
        for target in (self.outside, missing):
            with self.subTest(target=target.name):
                link = self.library / "linked.fsh"
                link.symlink_to(target)
                self.assertEqual(self.save(link.name, {"escaped": True})[0], 400)
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), str(target))
                self.assertEqual(self.outside.read_bytes(), b"outside marker")
                self.assertFalse(missing.exists())
                link.unlink()

    def test_save_rejects_symlink_created_at_open_boundary(self):
        target = self.library / "race.fsh"
        original_open = os.open

        def insert_link(path, flags, mode=0o777, **kwargs):
            if path == target:
                target.symlink_to(self.outside)
            return original_open(path, flags, mode, **kwargs)

        with patch.object(server.os, "open", side_effect=insert_link):
            self.assertEqual(self.save(target.name, "escaped")[0], 400)
        self.assertTrue(target.is_symlink())
        self.assertEqual(self.outside.read_bytes(), b"outside marker")

    def test_rename_rejects_symlink_sources(self):
        source = self.library / "linked.fsh"
        for target in (self.outside, self.root / "missing.fsh"):
            with self.subTest(target=target.name):
                source.symlink_to(target)
                self.assertEqual(self.rename(source.name, "renamed.fsh")[0], 400)
                self.assertEqual(self.rename(source.name, source.name)[0], 400)
                self.assertTrue(source.is_symlink())
                self.assertFalse((self.library / "renamed.fsh").exists())
                self.assertEqual(self.outside.read_bytes(), b"outside marker")
                source.unlink()

    @unittest.skipUnless(sys.platform == "darwin", "Requires macOS exclusive rename")
    def test_rename_preserves_symlink_destination_and_outside_file(self):
        source = self.library / "source.fsh"
        source.write_bytes(b"source marker")
        destination = self.library / "linked.fsh"
        for target in (self.outside, self.root / "missing.fsh"):
            with self.subTest(target=target.name):
                destination.symlink_to(target)
                self.assertEqual(self.rename(source.name, destination.name)[0], 409)
                self.assertTrue(destination.is_symlink())
                self.assertEqual(source.read_bytes(), b"source marker")
                self.assertEqual(self.outside.read_bytes(), b"outside marker")
                self.assertFalse((self.root / "missing.fsh").exists())
                destination.unlink()

    def test_valid_saves_keep_content_and_response_contract(self):
        name = "Équipe finale.fsh"
        for content in ({"qa": "saved"}, [1, 2], "plain text", None):
            with self.subTest(content=content):
                self.assertEqual(self.save(name, content), (200, {"ok": True, "arquivo": name}))
                target = self.library / name
                if isinstance(content, (dict, list)):
                    self.assertEqual(json.loads(target.read_text()), content)
                else:
                    self.assertEqual(target.read_text(), content or "")
        status, listing = self.request("/api/biblioteca")
        self.assertEqual(status, 200)
        self.assertIn(name, [entry["arquivo"] for entry in listing["arquivos"]])
        encoded = urllib.parse.quote(name, safe="")
        self.assertEqual(self.request(f"/api/biblioteca/{encoded}"), (200, {"texto": ""}))

    def test_omitted_and_null_names_keep_default_filename(self):
        for body in ({"conteudo": {"qa": 1}}, {"arquivo": None, "conteudo": {"qa": 2}}):
            with self.subTest(body=body):
                self.assertEqual(self.request("/api/biblioteca", body), (200, {"ok": True, "arquivo": "salvo.fsh"}))
                self.assertEqual(json.loads((self.library / "salvo.fsh").read_text()), body["conteudo"])

    def test_read_and_download_reject_unsafe_paths(self):
        source = self.library / "source.fsh"
        source.write_bytes(b"source marker")
        for name in self.invalid_names():
            if "\ud800" in name:
                continue
            with self.subTest(name=repr(name)):
                self.assertIn(self.read_file(name)[0], (400, 404, 405))
                self.assertIn(self.download_bruto(name)[0], (400, 404, 405))
                self.assert_original_files(source)

    def test_read_and_download_reject_symlinks_pointing_outside_and_dangling(self):
        source = self.library / "source.fsh"
        source.write_bytes(b"source marker")
        link = self.library / "linked.fsh"
        for target in (self.outside, self.root / "missing.fsh"):
            with self.subTest(target=target.name):
                link.symlink_to(target)
                try:
                    status_read, body_read = self.read_file(link.name)
                    self.assertIn(status_read, (400, 404))
                    if status_read == 400:
                        self.assertEqual(body_read.get("detail"), "Arquivo nao pode ser um link simbolico")

                    status_raw, body_raw = self.download_bruto(link.name)
                    self.assertIn(status_raw, (400, 404))
                    if status_raw == 400:
                        payload = json.loads(body_raw) if isinstance(body_raw, bytes) else body_raw
                        self.assertEqual(payload.get("detail"), "Arquivo nao pode ser um link simbolico")

                    self.assertTrue(link.is_symlink())
                finally:
                    if link.is_symlink() or link.exists():
                        link.unlink()
                self.assert_original_files(source)

    def test_read_and_download_allow_regular_files_and_presets_and_internal_symlinks(self):
        source = self.library / "source.fsh"
        source.write_text(json.dumps({"qa": "source"}))
        status, data = self.read_file(source.name)
        self.assertEqual(status, 200)
        self.assertEqual(data, {"qa": "source"})

        status, raw = self.download_bruto(source.name)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), {"qa": "source"})

        internal = self.library / "internal.fsh"
        internal.symlink_to(source)
        status, data = self.read_file(internal.name)
        self.assertEqual(status, 200)
        self.assertEqual(data, {"qa": "source"})

        status, raw = self.download_bruto(internal.name)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), {"qa": "source"})
        internal.unlink()

        preset_name = "agentes-livres.fsh"
        status, data = self.read_file(preset_name)
        self.assertEqual(status, 200)
        self.assertIsInstance(data, dict)

        status, raw = self.download_bruto(preset_name)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), data)


if __name__ == "__main__":
    unittest.main()
