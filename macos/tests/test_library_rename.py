"""Library rename contracts, using real HTTP and disposable macOS files."""

from concurrent.futures import ThreadPoolExecutor
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import server
import uvicorn


@unittest.skipUnless(sys.platform == "darwin", "Requires macOS exclusive rename")
class LibraryRenameTests(unittest.TestCase):
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
        library = patch.object(server, "_get_biblioteca_dir", return_value=self.root)
        library.start()
        self.addCleanup(library.stop)

    def rename(self, source, destination):
        request = urllib.request.Request(
            self.base + f"/api/biblioteca/{source}/nome",
            data=json.dumps({"nome": destination}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            with response:
                return response.code, json.load(response)

    def test_collision_preserves_both_names_and_exact_contents(self):
        source = self.root / "qa-one.fsh"
        target = self.root / "qa-two.fsh"
        source.write_bytes(b'{"qa":1}')
        target.write_bytes(b'{"qa":2}')
        status, response = self.rename(source.name, target.name)
        self.assertEqual(status, 409)
        self.assertTrue(response["detail"])
        self.assertEqual(source.read_bytes(), b'{"qa":1}')
        self.assertEqual(target.read_bytes(), b'{"qa":2}')

    def test_unused_name_moves_exact_contents_and_keeps_response_contract(self):
        source = self.root / "qa-one.fsh"
        target = self.root / "qa-new.fsh"
        source.write_bytes(b'{"qa":1}\n')
        self.assertEqual(self.rename(source.name, target.name), (200, {"ok": True, "novo": target.name}))
        self.assertFalse(source.exists())
        self.assertEqual(target.read_bytes(), b'{"qa":1}\n')

    def test_unchanged_name_is_a_successful_no_op(self):
        source = self.root / "qa-one.fsh"
        source.write_bytes(b'{"qa":1}')
        self.assertEqual(self.rename(source.name, source.name), (200, {"ok": True, "novo": source.name}))
        self.assertEqual(source.read_bytes(), b'{"qa":1}')

    def test_missing_source_does_not_change_existing_target(self):
        target = self.root / "qa-two.fsh"
        target.write_bytes(b'{"qa":2}')
        self.assertEqual(self.rename("missing.fsh", target.name)[0], 404)
        self.assertEqual(target.read_bytes(), b'{"qa":2}')
        self.assertEqual(self.rename("missing.fsh", "missing.fsh")[0], 404)

    def test_directory_symlink_and_hardlink_targets_are_not_replaced(self):
        source = self.root / "qa-one.fsh"
        source.write_bytes(b'{"qa":1}')
        other = self.root / "other.fsh"
        other.write_bytes(b'{"qa":2}')
        directory = self.root / "directory.fsh"
        directory.mkdir()
        marker = directory / "keep"
        marker.write_bytes(b"keep")
        link = self.root / "link.fsh"
        link.symlink_to(other)
        broken = self.root / "broken.fsh"
        broken.symlink_to(self.root / "absent.fsh")
        hardlink = self.root / "hardlink.fsh"
        os.link(source, hardlink)
        for target in (directory, link, broken, hardlink):
            with self.subTest(target=target.name):
                self.assertEqual(self.rename(source.name, target.name)[0], 409)
                self.assertEqual(source.read_bytes(), b'{"qa":1}')
        self.assertEqual(marker.read_bytes(), b"keep")
        self.assertTrue(link.is_symlink())
        self.assertTrue(broken.is_symlink())
        self.assertEqual(other.read_bytes(), b'{"qa":2}')
        self.assertEqual(hardlink.stat().st_ino, source.stat().st_ino)

    def test_target_created_at_native_operation_boundary_is_preserved(self):
        source = self.root / "qa-one.fsh"
        target = self.root / "qa-two.fsh"
        source.write_bytes(b'{"qa":1}')
        exclusive_rename = server._renomear_sem_substituir

        def create_then_rename(src, dst):
            dst.write_bytes(b'{"qa":2}')
            exclusive_rename(src, dst)

        with patch.object(server, "_renomear_sem_substituir", side_effect=create_then_rename):
            self.assertEqual(self.rename(source.name, target.name)[0], 409)
        self.assertEqual(source.read_bytes(), b'{"qa":1}')
        self.assertEqual(target.read_bytes(), b'{"qa":2}')

    def test_concurrent_renames_have_one_winner_and_preserve_loser(self):
        sources = [self.root / "qa-one.fsh", self.root / "qa-two.fsh"]
        for number, source in enumerate(sources, 1):
            source.write_bytes(json.dumps({"qa": number}).encode())
        target = self.root / "qa-target.fsh"
        barrier = threading.Barrier(2)
        exclusive_rename = server._renomear_sem_substituir

        def simultaneous_rename(src, dst):
            barrier.wait(timeout=5)
            exclusive_rename(src, dst)

        with patch.object(server, "_renomear_sem_substituir", side_effect=simultaneous_rename):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda source: self.rename(source.name, target.name), sources))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        winner = next(index for index, result in enumerate(results) if result[0] == 200)
        self.assertFalse(sources[winner].exists())
        self.assertEqual(json.loads(target.read_bytes()), {"qa": winner + 1})
        self.assertEqual(json.loads(sources[1 - winner].read_bytes()), {"qa": 2 - winner})

    def test_case_only_name_preserves_one_copy(self):
        source = self.root / "qa-one.fsh"
        target = self.root / "QA-ONE.fsh"
        source.write_bytes(b'{"qa":1}')
        status, _ = self.rename(source.name, target.name)
        self.assertIn(status, (200, 409))
        self.assertEqual(len(list(self.root.iterdir())), 1)
        self.assertEqual(next(self.root.iterdir()).read_bytes(), b'{"qa":1}')

    def test_native_failure_never_falls_back_to_overwriting_rename(self):
        source = self.root / "qa-one.fsh"
        target = self.root / "qa-two.fsh"
        source.write_bytes(b'{"qa":1}')
        target.write_bytes(b'{"qa":2}')
        for native_error in (OSError("unavailable"), AttributeError("renamex_np")):
            with self.subTest(error=type(native_error).__name__):
                with patch.object(server.ctypes, "CDLL", side_effect=native_error), patch.object(server.logger, "exception"):
                    self.assertEqual(self.rename(source.name, target.name)[0], 500)
                self.assertEqual(source.read_bytes(), b'{"qa":1}')
                self.assertEqual(target.read_bytes(), b'{"qa":2}')

    def test_source_removed_before_native_operation_returns_not_found(self):
        source = self.root / "qa-one.fsh"
        source.write_bytes(b'{"qa":1}')
        exclusive_rename = server._renomear_sem_substituir

        def remove_then_rename(src, dst):
            src.unlink()
            exclusive_rename(src, dst)

        with patch.object(server, "_renomear_sem_substituir", side_effect=remove_then_rename):
            self.assertEqual(self.rename(source.name, "qa-new.fsh")[0], 404)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_null_byte_cannot_truncate_native_destination(self):
        source = self.root / "qa-one.fsh"
        source.write_bytes(b'{"qa":1}')
        with patch.object(server.logger, "exception"):
            self.assertEqual(self.rename(source.name, "qa-new.fsh\0ignored")[0], 400)
        self.assertEqual(source.read_bytes(), b'{"qa":1}')
        self.assertEqual(list(self.root.iterdir()), [source])


if __name__ == "__main__":
    unittest.main()
