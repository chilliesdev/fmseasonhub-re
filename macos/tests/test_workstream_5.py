"""Workstream 5 End-to-End Integration, Memory Bridge, and API Test Suite."""

import os
import sys
import time
import json
import struct
import socket
import unittest
import threading
import subprocess
import tempfile
import urllib.request
import urllib.error

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
NATIVE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "native"))
DIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist"))

sys.path.insert(0, SRC_DIR)

import server
import uvicorn
import fm_memory
import fm_reader
import biblioteca
import acesso
import legal
import settings
import moneyball
import overall


class TestWorkstream5(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.port = 54322
        cls.host = "127.0.0.1"
        cls.config = uvicorn.Config(server.app, host=cls.host, port=cls.port, log_level="error")
        cls.srv = uvicorn.Server(cls.config)
        cls.srv_thread = threading.Thread(target=cls.srv.run, daemon=True)
        cls.srv_thread.start()
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        cls.srv.should_exit = True

    def _req(self, path, method="GET", body=None):
        url = f"http://{self.host}:{self.port}{path}"
        headers = {"Content-Type": "application/json"} if body is not None else {}
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as he:
            return he.code, he.read()

    def test_01_all_modules_import(self):
        """Verify all python modules in src import cleanly."""
        py_files = [f[:-3] for f in os.listdir(SRC_DIR) if f.endswith(".py")]
        self.assertGreaterEqual(len(py_files), 50)
        for mod in py_files:
            __import__(mod)

    def test_02_fastapi_endpoints(self):
        """Verify key endpoints respond with 200 OK and valid schemas."""
        # 1. SPA and Assets
        status, data = self._req("/")
        self.assertEqual(status, 200)
        self.assertIn(b"html", data.lower())

        status, data = self._req("/assets/index-Cvmv7E2F.js")
        self.assertEqual(status, 200)
        self.assertGreater(len(data), 1000000)

        # 2. Status & Settings
        status, data = self._req("/api/status")
        self.assertEqual(status, 200)

        status, data = self._req("/api/settings")
        self.assertEqual(status, 200)

        # 3. Acesso & Legal
        status, data = self._req("/api/acesso")
        self.assertEqual(status, 200)
        js = json.loads(data)
        self.assertEqual(js.get("nivel"), 4)

        status, data = self._req("/api/acesso/estado")
        self.assertEqual(status, 200)

        status, data = self._req("/api/legal")
        self.assertEqual(status, 200)
        js = json.loads(data)
        self.assertTrue(js.get("aceite"))

        status, data = self._req("/api/legal/aceitar", "POST", {"termos": True, "privacidade": True})
        self.assertEqual(status, 200)

        # 4. Idiomas
        status, data = self._req("/api/idiomas")
        self.assertEqual(status, 200)
        status, data = self._req("/api/idiomas/en")
        self.assertEqual(status, 200)
        status, data = self._req("/api/idiomas/pt")
        self.assertEqual(status, 200)

        # 5. Moneyball & Overall
        status, data = self._req("/api/moneyball/columns")
        self.assertEqual(status, 200)
        status, data = self._req("/api/moneyball/browse")
        self.assertEqual(status, 200)
        status, data = self._req("/api/overall/modos")
        self.assertEqual(status, 200)
        js = json.loads(data)
        self.assertIn("misto", js.get("modos", []))

        # 6. Biblioteca & Factory Presets
        status, data = self._req("/api/biblioteca/listar")
        self.assertEqual(status, 200)
        js = json.loads(data)
        presets = {item["arquivo"] for item in js.get("arquivos", []) if item.get("fabrica")}
        expected_presets = {
            "agentes-livres.fsh", "contrato-acabando.fsh",
            "jovens-promessas.fsh", "listados-para-transferencia.fsh"
        }
        for ep in expected_presets:
            self.assertIn(ep, presets)

        # 7. Favoritos
        status, data = self._req("/api/favoritos")
        self.assertEqual(status, 200)

        # 8. Connect & Capture
        status, data = self._req("/api/connect", "POST", {})
        self.assertEqual(status, 200)
        status, data = self._req("/api/simular-captura", "POST", {})
        self.assertEqual(status, 200)
        status, data = self._req("/api/disconnect", "POST", {})
        self.assertEqual(status, 200)
        status, data = self._req("/api/capture", "POST", {})
        self.assertEqual(status, 409)

    def test_03_memory_bridge_primitives(self):
        """Verify universal libfmsh_bridge.dylib memory read primitives."""
        sock_path = "/tmp/fmsh_mem_bridge.sock"
        if os.path.exists(sock_path):
            try:
                os.unlink(sock_path)
            except Exception:
                pass

        dylib_path = os.path.join(NATIVE_DIR, "libfmsh_bridge.dylib")
        self.assertTrue(os.path.isfile(dylib_path))

        target_bin = "/tmp/test_target"
        if not os.path.isfile(target_bin):
            subprocess.run(["clang", "-O2", "-o", target_bin, "-x", "c", "-"], input=b"#include <unistd.h>\nint main(){sleep(5);return 0;}")

        # Load a real named plugin; GET_BASE must not substitute the executable.
        plugin_dir = tempfile.TemporaryDirectory(prefix="fmsh-plugin-")
        self.addCleanup(plugin_dir.cleanup)
        plugin_path = os.path.join(plugin_dir.name, "game_plugin.dylib")
        subprocess.run(["clang", "-shared", "-o", plugin_path, "-x", "c", "-"],
                       input=b"int fmsh_test_plugin = 1;", check=True)
        env = dict(os.environ)
        env["DYLD_INSERT_LIBRARIES"] = dylib_path + ":" + plugin_path
        proc = subprocess.Popen([target_bin], env=env)

        try:
            t0 = time.time()
            while time.time() - t0 < 3.0:
                if os.path.exists(sock_path):
                    break
                time.sleep(0.05)
            self.assertTrue(os.path.exists(sock_path))

            # A missing named module must never receive a guessed base.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(2)
                probe.connect(sock_path)
                probe.sendall(b"GET_BASE fmsh_module_that_does_not_exist\n")
                self.assertEqual(probe.recv(64), b"OK 0\n")
            mem = fm_memory.FmMemory(proc.pid)
            self.assertTrue(mem.is_alive())
            self.assertGreater(mem.base, 0)

            magic = mem.u32(mem.base)
            self.assertEqual(magic, 0xFEEDFACF)

            b4 = mem.bytes(mem.base, 4)
            self.assertEqual(b4, b"\xcf\xfa\xed\xfe")

            u8_val = mem.u8(mem.base)
            self.assertEqual(u8_val, 0xCF)

            u16_val = mem.u16(mem.base)
            self.assertEqual(u16_val, 0xFACF)

            u64_val = mem.u64(mem.base)
            self.assertEqual(u64_val & 0xFFFFFFFF, 0xFEEDFACF)
            if mem._bridge_socket:
                mem._bridge_socket.close()
        finally:
            proc.kill()
            proc.wait()
            if os.path.exists(sock_path):
                try:
                    os.unlink(sock_path)
                except Exception:
                    pass

    def test_04_app_bundle_structure(self):
        """Verify built standalone FM Season Hub.app bundle structure."""
        app_path = os.path.join(DIST_DIR, "FM Season Hub.app")
        self.assertTrue(os.path.isdir(app_path))

        plist_path = os.path.join(app_path, "Contents", "Info.plist")
        self.assertTrue(os.path.isfile(plist_path))

        exec_path = os.path.join(app_path, "Contents", "MacOS", "FM Season Hub")
        self.assertTrue(os.path.isfile(exec_path))
        self.assertTrue(os.access(exec_path, os.X_OK))

        icon_path = os.path.join(app_path, "Contents", "Resources", "AppIcon.icns")
        self.assertTrue(os.path.isfile(icon_path))
        self.assertGreater(os.path.getsize(icon_path), 50000)

        dylib_bundle = os.path.join(app_path, "Contents", "Resources", "native", "libfmsh_bridge.dylib")
        self.assertTrue(os.path.isfile(dylib_bundle))
